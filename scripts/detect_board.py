#!/usr/bin/env python3
"""
detect_board.py — 识别 sketch 对应的开发板型号，并解析「丝印名 ↔ GPIO 号」映射

三级证据链（越靠前越权威）：
  1. arduino-cli board list  —— 实机连接信息（FQBN）
  2. arduino-cli board details + 核心包 variants/<variant>/pins_arduino.h
     —— 官方引脚定义，直接给出 D0..D13 / A0..A7 对应的 GPIO
  3. ino 文件头部注释 / boards.txt 名称  —— 兜底线索

输出 JSON：
{
  "board": {"fqbn": "...", "name": "...", "variant": "...", "source": "arduino-cli"},
  "pins": {"D5": 8, "A3": 4, "SDA": 11, ...},
  "gpio": {"8": ["D5"], "4": ["A3"], ...},
  "alias": {"SDA": "A4", "SCL": "A5", "TX": "D1", "RX": "D0"},
  "variant_file": "/path/to/pins_arduino.h",
  "notes": [...]
}

用法:
    detect_board.py --ino <sketch.ino> [--fqbn <fqbn>] [--json]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys

ARDUINO_CLI = os.environ.get("ARDUINO_CLI", "arduino-cli")


def sh(cmd, timeout=25):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


# ------------------------------------------------------------------ 1) 实机
def from_cli():
    out = sh([ARDUINO_CLI, "board", "list", "--format", "json"])
    if not out.strip():
        return None
    try:
        data = json.loads(out)
    except Exception:
        return None
    ports = data if isinstance(data, list) else data.get("detected_ports", [])
    cand = []
    for p in ports:
        m = p.get("matching_boards") or []
        for b in m:
            fqbn = b.get("fqbn")
            if fqbn:
                cand.append({"fqbn": fqbn, "name": b.get("name", ""),
                             "port": (p.get("port") or {}).get("address", "")})
    for p in ports:
        for b in (p.get("boards") or []):
            if b.get("fqbn"):
                cand.append({"fqbn": b["fqbn"], "name": b.get("name", ""),
                             "port": (p.get("port") or {}).get("address", "")})
    return cand or None


def board_details(fqbn):
    out = sh([ARDUINO_CLI, "board", "details", "-b", fqbn, "--format", "json"], timeout=40)
    try:
        return json.loads(out)
    except Exception:
        return {}


def _props(details):
    """arduino-cli 的 build_properties 是 ["k=v", ...] 形式"""
    out = {}
    bp = details.get("build_properties") or []
    if isinstance(bp, list):
        for item in bp:
            if isinstance(item, str) and "=" in item:
                k, v = item.split("=", 1)
                out[k] = v
    elif isinstance(bp, dict):
        out.update(bp)
    return out


def variant_of(fqbn, details):
    props = _props(details)
    if props.get("build.variant"):
        return props["build.variant"]
    return fqbn.split(":")[-1] if fqbn else None


def find_pins_header(variant, details=None):
    """优先用 core 包的 platform path 直接定位，其次全局 glob 兜底"""
    if details:
        props = _props(details)
        for key in ("build.core.platform.path", "build.board.platform.path"):
            base = props.get(key)
            if base and variant:
                p = os.path.join(base, "variants", variant, "pins_arduino.h")
                if os.path.exists(p):
                    return p
    roots = [
        os.path.expanduser("~/Library/Arduino15/packages"),
        os.path.expanduser("~/.arduino15/packages"),
        os.path.expanduser("~/Arduino"),
        "/usr/local/share/arduino/packages",
        os.path.expanduser("~/Documents/Arduino"),
    ]
    for r in roots:
        for pat in (os.path.join(r, "**", "variants", variant, "pins_arduino.h"),
                    os.path.join(r, "**", "variants", variant, "**", "pins_arduino.h")):
            hits = glob.glob(pat, recursive=True)
            if hits:
                return sorted(hits, key=len)[0]
    return None


# ------------------------------------------------------------------ 2) 引脚定义
PIN_RE = re.compile(
    r"(?:static\s+const\s+uint8_t|#define|constexpr\s+uint8_t|static\s+constexpr\s+uint8_t)\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:=\s*)?\(?\s*([A-Za-z_][A-Za-z0-9_]*|\d+)\s*\)?\s*;"
)


def parse_pins_header(path):
    """解析 pins_arduino.h，返回 {名字: GPIO号} 与 #define 别名"""
    consts, defines = {}, {}
    src = open(path, encoding="utf8", errors="replace").read()
    for line in src.splitlines():
        line = line.split("//")[0]
        m = PIN_RE.search(line)
        if m:
            name, val = m.group(1), m.group(2)
            if val.isdigit():
                consts[name] = int(val)
            elif val in consts:
                consts[name] = consts[val]
        m2 = re.match(r"\s*#define\s+([A-Za-z_][A-Za-z0-9_]*)\s+([A-Za-z_][A-Za-z0-9_]*)\s*$",
                      line)
        if m2:
            defines[m2.group(1)] = m2.group(2)
    return consts, defines


SILK_ORDER = (
    [f"D{i}" for i in range(0, 40)] + [f"A{i}" for i in range(0, 16)]
    + ["SDA", "SCL", "TX", "RX", "SS", "MOSI", "MISO", "SCK", "LED_BUILTIN",
       "SW_BUILTIN", "RTS", "CTS", "DTR", "DSR", "T1", "T2", "T3", "T4", "T5", "T6", "T7"]
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ino")
    ap.add_argument("--fqbn")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    notes = []
    board = {}

    if args.fqbn:
        board = {"fqbn": args.fqbn, "name": "", "source": "用户指定"}
    else:
        cand = from_cli()
        if cand:
            # 若同时插了多块板，取第一块并记录其余，供上层询问用户
            board = {"fqbn": cand[0]["fqbn"], "name": cand[0]["name"],
                     "port": cand[0].get("port"), "source": "arduino-cli board list"}
            if len(cand) > 1:
                notes.append(f"检测到 {len(cand)} 块开发板，已取第一个；全部候选: "
                             + ", ".join(f"{c['name']}({c['fqbn']})" for c in cand))
                board["candidates"] = cand

    if not board:
        notes.append("arduino-cli 未找到已连接开发板，改用 ino 注释线索")
        if args.ino:
            head = open(args.ino, encoding="utf8", errors="replace").read()[:2500]
            m = re.findall(r"(ESP32-S3|ESP32-C3|ESP32|Arduino\s+\w+|RP2040|XIAO[\w\s-]*)", head)
            if m:
                board = {"fqbn": None, "name": m[0], "source": "ino 注释（需人工确认）"}
                notes.append("开发板型号来自代码注释，置信度较低，建议向用户确认")

    details = board_details(board["fqbn"]) if board.get("fqbn") else {}
    if details.get("name"):
        board["name"] = details["name"]
    variant = variant_of(board["fqbn"], details) if board.get("fqbn") else None
    header = find_pins_header(variant, details) if variant else None

    pins, alias = {}, {}
    if header:
        consts, defines = parse_pins_header(header)
        for k, v in consts.items():
            pins[k] = v
        for k, v in defines.items():
            if v in consts:
                alias[k] = v
                pins.setdefault(k, consts[v])
        board["variant"] = variant
        board["core_header"] = header
    elif board:
        notes.append("未找到核心包 pins_arduino.h（可能未安装对应核心），"
                     "无法自动建立丝印名↔GPIO 映射")

    # 反向表：GPIO -> 丝印名
    rev = {}
    for name in SILK_ORDER:
        if name in pins:
            rev.setdefault(str(pins[name]), []).append(name)
    for name in pins:
        if name not in SILK_ORDER:
            rev.setdefault(str(pins[name]), []).append(name)

    out = {
        "board": board,
        "pins": pins,
        "gpio": rev,
        "alias": alias,
        "notes": notes,
    }

    # 关键别名优先（SDA/SCL 指向的丝印名）
    for k in ("SDA", "SCL", "TX", "RX", "SS", "MOSI", "MISO", "SCK"):
        if k in pins:
            same = [n for n, v in pins.items()
                    if v == pins[k] and n != k and re.fullmatch(r"[AD]\d+", n)]
            if same:
                out.setdefault("alias_to_silk", {})[k] = sorted(same)[0]

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
