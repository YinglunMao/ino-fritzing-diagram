#!/usr/bin/env python3
"""
parse_ino.py — 从 Arduino sketch（.ino 及同目录 .h/.cpp）中提取元件清单与引脚定义

输出 JSON：
{
  "sketch": "...",
  "includes": [...],
  "defines": {"PIN_SDA": {"value": "8", "comment": "ADC1_CH3"}},
  "i2c_addresses": ["0x39", "0x68"],
  "i2c_pins": {"sda": 8, "scl": 9, "source": "Wire.begin(PIN_SDA, PIN_SCL)"},
  "analog_pins": [4, 5],
  "serial_baud": 115200,
  "components": [
     {"key":"as7341","name":"AS7341","confidence":"high",
      "evidence":["注释: AS7341 多光谱传感器","I2C 0x39","前缀 as7341_"],
      "query":"...","part_id":"as7341_module","bus":"i2c","pins":[...]}
  ],
  "needs_user_input": [{"reason":"...","options":[...]}],
  "net_hints": [{"from":"Pulse S","to":"GPIO4"}]
}

用法:
    parse_ino.py --ino <sketch.ino> [--catalog <component-catalog.json>] [--pretty]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

DEFAULT_CATALOG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "references", "component-catalog.json")

NON_COMPONENT_INCLUDE = re.compile(
    r"^(Wire|SPI|EEPROM|FS|SPIFFS|LittleFS|SD|WiFi|BLEDevice|Arduino|math|"
    r"esp_|driver/|nvs|Preferences|USB|HardwareSerial|Adafruit_Sensor|"
    r"Adafruit_Unified_Sensor|soc/|freertos/|esp32-hal)",
    re.I)


def read_sketch(path):
    base = os.path.dirname(os.path.abspath(path))
    texts = {}
    for fn in os.listdir(base):
        if fn.lower().endswith((".ino", ".h", ".hpp", ".cpp", ".c")):
            p = os.path.join(base, fn)
            try:
                texts[fn] = open(p, encoding="utf8", errors="replace").read()
            except Exception:
                pass
    if not texts:
        texts[os.path.basename(path)] = open(path, encoding="utf8", errors="replace").read()
    return texts


def strip_comments(code):
    code = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), code, flags=re.S)
    return re.sub(r"//[^\n]*", "", code)


def collect_includes(text):
    return re.findall(r"#\s*include\s*[<\"]([^>\"]+)[>\"]", text)


def collect_defines(text):
    out = {}
    for line in text.splitlines():
        m = re.match(r"\s*#\s*define\s+([A-Za-z_]\w*)\s+([^\s/][^/]*?)\s*(?://\s*(.*))?$", line)
        if m:
            out[m.group(1)] = {"value": m.group(2).strip().rstrip(";"),
                               "comment": (m.group(3) or "").strip()}
    return out


def resolve(token, defines, depth=0):
    token = token.strip()
    if depth > 6:
        return None
    if re.fullmatch(r"\d+", token):
        return int(token)
    if token in defines:
        return resolve(defines[token]["value"], defines, depth + 1)
    m = re.fullmatch(r"GPIO(\d+)", token, re.I)
    if m:
        return int(m.group(1))
    m = re.fullmatch(r"[AD](\d+)", token, re.I)
    if m:
        return None  # 丝印名交给 detect_board 解析
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ino", required=True)
    ap.add_argument("--catalog", default=DEFAULT_CATALOG)
    args = ap.parse_args()

    texts = read_sketch(args.ino)
    joined = "\n".join(f"/* {k} */\n{v}" for k, v in texts.items())
    code = strip_comments(joined)
    catalog = json.load(open(args.catalog, encoding="utf8"))
    entries = [c for c in catalog["components"] if c.get("kind") != "skip"]

    # ---- 基础信息
    includes = sorted(set(collect_includes(joined)))
    defines = collect_defines(joined)

    i2c_addrs = sorted(set(re.findall(r"0x[0-9A-Fa-f]{2}\b", joined)),
                       key=lambda x: int(x, 16))
    # 只保留看起来像从机地址的（出现在 addr/_ADDR 语境里的）
    addr_ctx = set()
    for m in re.finditer(r"([A-Za-z_]\w*(?:ADDR|Addr|addr)\w*)\s*[,=]?\s*(0x[0-9A-Fa-f]{2})",
                         joined):
        addr_ctx.add(m.group(2).upper())
    for m in re.finditer(r"begin\w*\(\s*(0x[0-9A-Fa-f]{2})", joined):
        addr_ctx.add(m.group(1).upper())
    for m in re.finditer(r"0x([0-9A-Fa-f]{2})", joined):
        pass
    i2c_like = sorted((a for a in i2c_addrs if a.upper() in addr_ctx),
                      key=lambda x: int(x, 16))

    i2c = {}
    m = re.search(r"Wire\.begin\(\s*([^,)]+)\s*,\s*([^,)]+)", code)
    if m:
        i2c = {"sda": resolve(m.group(1), defines), "scl": resolve(m.group(2), defines),
               "sda_expr": m.group(1).strip(), "scl_expr": m.group(2).strip(),
               "source": "Wire.begin(...)"}
    m = re.search(r"Wire\.begin\(\s*\)", code)
    if m and not i2c:
        i2c = {"sda": None, "scl": None, "source": "Wire.begin() 使用核心默认 I2C 引脚"}

    analog_pins = sorted({resolve(x, defines)
                          for x in re.findall(r"analog(?:Read|SetPinAttenuation)\(\s*([A-Za-z_0-9]+)",
                                              code)} - {None})
    m = re.search(r"Serial\.begin\(\s*(\d+)", code)
    baud = int(m.group(1)) if m else None

    # ---- 元件识别
    found, matched_lines = {}, {}
    for entry in entries:
        hits = []
        hit_pats = []
        for pat in entry.get("patterns", []):
            try:
                rx = re.compile(pat, re.I | re.M)
            except re.error:
                continue
            for lm in rx.finditer(joined):
                line = joined[lm.start(): joined.find("\n", lm.start())].strip()
                line = re.sub(r"^[\s*/]+", "", line)[:110]
                if line and line not in hits:
                    hits.append(line)
                if len(hits) >= 5:
                    break
            if hits:
                hit_pats.append(pat)
                break
        if not hits:
            continue
        ev = list(hits)
        conf = "medium"
        # 证据加权
        names = entry.get("names") or []
        if any(n and re.search(re.escape(n), joined, re.I) for n in names):
            conf = "high"
        if entry.get("i2c"):
            for a in entry["i2c"]:
                if a.upper() in {x.upper() for x in i2c_like}:
                    ev.append(f"I2C 地址 {a} 出现在代码中")
                    conf = "high"
        if any(re.search(re.escape(i.split(".")[0]), joined, re.I)
               for i in entry.get("includes", []) or []):
            conf = "high"
        if entry.get("generic_patterns") and all(
                any(g in pat for g in entry["generic_patterns"]) for pat in hit_pats):
            conf = "low"
        generic = entry.get("generic_patterns") or []
        only_generic = bool(hit_pats) and all(
            any(re.fullmatch(re.escape(g), pat.strip("\\b^$()")) or g in pat for g in generic)
            for pat in hit_pats) and bool(generic)
        found[entry["key"]] = {
            "key": entry["key"], "name": names[0] if names else entry["key"],
            "confidence": "low" if only_generic else conf,
            "matched_patterns": hit_pats,
            "only_generic_alias": only_generic,
            "evidence": ev,
            "query": entry.get("query"), "part_id": entry.get("part_id"),
            "bus": entry.get("bus"), "i2c": entry.get("i2c", []),
            "kind": entry.get("kind"), "pins": entry.get("pins", []),
            "note": entry.get("note", ""),
        }
        matched_lines[entry["key"]] = hits

    # ---- 未识别 include / 类名 -> 待用户确认
    needs = []
    unknown_libs = []
    for inc in includes:
        head = inc.split(".")[0]
        if NON_COMPONENT_INCLUDE.match(inc):
            continue
        if any(re.search(re.escape(k.split("_")[0]), inc, re.I) for k in found):
            continue
        if not any(re.search(re.escape(k.split("_")[0]), inc, re.I) for k in found):
            unknown_libs.append(inc)
    known_prefix = ("Adafruit_", "SparkFun_", "Seeed_", "DHT", "SparkFun")
    for inc in unknown_libs:
        if inc.split(".")[0] in ("Adafruit_MPU6050",):
            continue
        needs.append({"kind": "library", "item": inc,
                      "reason": f"库 {inc} 未在元件字典中命中，可能对应一个未收录的元件",
                      "suggest": "请确认该库驱动的具体器件型号"})

    # ---- 从注释里挖「XX 接法」提示
    net_hints = []
    for m in re.finditer(r"([\w\u4e00-\u9fa5/\-]{2,24}?)\s*(?:->|→|接|连到|to)\s*"
                         r"(GPIO\s*\d+|[AD]\d+|3V3|3\.3V|GND|VCC|5V)", joined, re.I):
        net_hints.append({"from": m.group(1).strip(), "to": m.group(2).strip()})

    # ---- 通用别名命中 => 型号不明确，必须问用户
    GENERIC_OPTIONS = {
        "lm2904_mic": ["LM2904 声音/麦克风模块（FC-04）", "MAX9814 带 AGC 麦克风模块",
                       "MAX4466 可调增益麦克风模块", "通用电容咪头放大模块"],
    }
    for k, c in list(found.items()):
        if c.get("only_generic_alias"):
            needs.append({
                "kind": "ambiguous_model", "item": c["name"], "key": k,
                "reason": f"代码只写了通用名称（命中 {c['matched_patterns']}），没有具体型号，"
                          f"无法确定实物外观",
                "options": GENERIC_OPTIONS.get(k, ["请用户提供具体型号", "按通用模块绘制"]),
            })

    # ---- 人工确认项：识别出的元件里 part_id 为空（无法直接画）
    for k, c in found.items():
        if not c["part_id"]:
            needs.append({"kind": "part", "item": c["name"],
                          "reason": "元件已识别但绘图库中暂无该元件的外形绘制器",
                          "suggest": "可现场按其外形绘制，或让用户选择具体模块形态"})

    out = {
        "sketch": os.path.basename(args.ino),
        "files": sorted(texts),
        "includes": includes,
        "defines": defines,
        "i2c_addresses": i2c_like,
        "i2c_pins": i2c,
        "analog_pins": analog_pins,
        "serial_baud": baud,
        "components": sorted(found.values(), key=lambda c: c["key"]),
        "needs_user_input": needs,
        "net_hints": net_hints[:40],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
