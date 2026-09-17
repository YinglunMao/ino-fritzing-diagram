#!/usr/bin/env python3
"""
boards.py — 数据驱动的开发板渲染器

设计目标
--------
**换板子不用改代码。** 板卡的外形、配色、排针分组、引脚丝印名、GPIO 映射
全部写在 `references/boards.json` 里；本模块只负责把它「翻译」成 SVG + 引脚坐标表。

加一块新板只需在 `boards.json` 的 `boards[]` 里追加一条：
    { "id": "my_board", "size_mm": [w,h], "connectors": [...], "gpio": {...} }
若某块板要按实拍照片精修外观，给该条加 `"hand_tuned": "<id>"`，
渲染时就会转交给 `parts_library.py` 里同名的手工渲染器。

坐标约定
--------
* 与 `parts_library` 一致：引脚坐标是**毫米**、相对板子左上角，`dir` 表示引线朝外方向。
* 丝印文字一律**垂直于排针方向**朝板内延伸 —— 这是实物排针板的印字方式，
  也让字号不受 2.54mm 针距限制（长标签如 `ADC_VREF` 才放得下）。

用法
----
    python boards.py --list                       # 列出全部板卡
    python boards.py --match esp32:esp32:esp32    # 用 FQBN 匹配
    python boards.py --render esp32_devkitc --out /tmp/b.svg
    python boards.py --json                       # 输出目录 JSON
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fritzing_kit import (C, Svg, chip_qfn, esc, mount_hole, pcb, pad,  # noqa: E402
                          shield_can, tactile, usb_c, led as led_prim)

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CATALOG = os.path.join(os.path.dirname(HERE), "references", "boards.json")

# 每字符宽度 ≈ size * CHAR_K，用于自动收缩字号
CHAR_K = 0.62
MIN_LABEL_SIZE = 0.5


# --------------------------------------------------------------------- 载入


def catalog_path() -> str:
    return os.environ.get("INO_FRITZING_BOARDS", DEFAULT_CATALOG)


def load(path: str | None = None) -> dict[str, dict]:
    """读板卡目录，返回 {id: spec}。"""
    p = path or catalog_path()
    with open(p, encoding="utf8") as f:
        doc = json.load(f)
    return {b["id"]: b for b in doc.get("boards", [])}


_CACHE: dict[str, dict] | None = None


def specs(refresh: bool = False) -> dict[str, dict]:
    global _CACHE
    if _CACHE is None or refresh:
        try:
            _CACHE = load()
        except Exception:
            _CACHE = {}
    return _CACHE


def list_boards() -> list[tuple[str, str, list, str]]:
    """[(id, name, size_mm, kind)]，kind 为 hand_tuned / generated。"""
    out = []
    for bid, sp in specs().items():
        kind = "hand_tuned" if sp.get("hand_tuned") else "generated"
        out.append((bid, sp.get("name", bid), sp.get("size_mm") or [0, 0], kind))
    return out


# --------------------------------------------------------------------- 匹配


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def match(fqbn: str | None = None, variant: str | None = None,
          name: str | None = None) -> dict | None:
    """
    按证据强度依次匹配：FQBN 精确 → FQBN 归一化 → variant → 显示名/关键词。
    返回 spec 或 None。
    """
    all_specs = specs()
    if fqbn:
        for sp in all_specs.values():
            if sp.get("fqbn") and sp["fqbn"].lower() == fqbn.lower():
                return sp
        nf = _norm(fqbn)
        for sp in all_specs.values():
            if sp.get("fqbn") and _norm(sp["fqbn"]) == nf:
                return sp
    if variant:
        nv = _norm(variant)
        for sp in all_specs.values():
            for v in sp.get("variants") or []:
                if _norm(v) == nv:
                    return sp
    for probe in (name, fqbn, variant):
        if not probe:
            continue
        np_ = _norm(probe)
        if not np_:
            continue
        # 关键词包含匹配（长关键词优先，避免 "nano" 抢走 "geekble nano"）
        best = None
        for sp in all_specs.values():
            keys = list(sp.get("match") or []) + [sp.get("name", ""), sp["id"]]
            for k in keys:
                nk = _norm(k)
                if nk and (nk in np_ or np_ in nk):
                    if best is None or len(nk) > best[0]:
                        best = (len(nk), sp)
        if best:
            return best[1]
    return None


# --------------------------------------------------------------------- 渲染


def _fit_size(label: str, base: float, room_mm: float) -> float:
    """按可用长度收缩字号，长标签（ADC_VREF）自动变小以免压到邻针。"""
    if not label:
        return base
    return max(MIN_LABEL_SIZE, min(base, room_mm / len(label) / CHAR_K))


def _decor(s: Svg, spec: dict, silk: str):
    """绘制装饰件（芯片 / USB / 按键 / 灯 / 文字）。只影响外观，不产生引脚。"""
    for d in spec.get("decor") or []:
        t = d.get("type")
        x, y = d.get("x", 0), d.get("y", 0)
        w, h = d.get("w", 0), d.get("h", 0)
        label = d.get("label", "")
        if t == "text":
            s.text(x, y, d.get("s", ""), size=d.get("size", 2.0), fill=d.get("fill", silk),
                   rot=d.get("rot", 0), weight=d.get("weight", "700"),
                   anchor=d.get("anchor", "middle"), opacity=d.get("opacity"))
        elif t == "chip":
            body = d.get("body", "#191B1E")
            legs = int(d.get("legs", 0))
            lc = C["silver"]
            if legs and w >= h:          # 横向：引脚在上下两条长边
                pitch = w / legs
                for i in range(legs):
                    lx = x + pitch * (i + 0.5)
                    s.rect(lx - 0.18, y - 0.7, 0.36, 0.75, r=0.05, fill=lc, stroke=C["silver_dark"], sw=0.08)
                    s.rect(lx - 0.18, y + h - 0.05, 0.36, 0.75, r=0.05, fill=lc, stroke=C["silver_dark"], sw=0.08)
            elif legs:                    # 纵向：引脚在左右两条长边
                pitch = h / legs
                for i in range(legs):
                    ly = y + pitch * (i + 0.5)
                    s.rect(x - 0.7, ly - 0.18, 0.75, 0.36, r=0.05, fill=lc, stroke=C["silver_dark"], sw=0.08)
                    s.rect(x + w - 0.05, ly - 0.18, 0.75, 0.36, r=0.05, fill=lc, stroke=C["silver_dark"], sw=0.08)
            s.rect(x, y, w, h, r=0.2, fill=body, stroke="#0B0C0D", sw=0.15)
            s.circle(x + 0.6, y + 0.6, 0.22, fill="#3A3E44")
            if label:
                s.text(x + w / 2, y + h / 2 + 0.3, label, size=d.get("label_size", 0.8),
                       fill="#B9BEC4", weight="700")
        elif t == "shield":
            shield_can(s, x, y, w, h)
        elif t == "usb":
            kind = d.get("kind", "micro")
            if kind == "c":
                usb_c(s, x, y, w, h)
            else:
                s.rect(x, y, w, h, r=0.5, fill=C["silver"], stroke=C["silver_dark"], sw=0.2)
                inset = 1.0 if kind == "b" else 0.7
                s.rect(x + inset, y + inset * 1.2, w - inset * 2, h - inset * 2.4, r=0.35,
                       fill="#8C9196", stroke="#7A7F85", sw=0.12)
                if kind == "b":
                    s.rect(x + inset * 1.6, y + inset * 1.9, w - inset * 3.2, h - inset * 3.8,
                           r=0.3, fill="#E9EBED", stroke="#B9BEC3", sw=0.1)
                else:
                    s.rect(x + inset * 1.3, y + inset * 1.7, w - inset * 2.6, h - inset * 3.4,
                           r=0.3, fill="#1B1D1F", stroke="#3A3E44", sw=0.1)
        elif t == "barrel":
            s.rect(x, y, w, h, r=0.6, fill="#1A1C1E", stroke="#0A0B0C", sw=0.2)
            s.circle(x + w * 0.72, y + h / 2, min(w, h) * 0.34, fill="#3A3D41", stroke="#151719", sw=0.16)
            s.circle(x + w * 0.72, y + h / 2, min(w, h) * 0.1, fill="#0A0B0C")
        elif t == "button":
            tactile(s, x, y, w=d.get("w", 3.6), h=d.get("h", 3.6))
            if label:
                s.text(x, y + d.get("h", 3.6) / 2 + 1.25, label, size=0.75, fill=silk, weight="700")
        elif t == "led":
            lw, lh = d.get("w", 1.7), d.get("h", 1.0)
            led_prim(s, x, y, lw, lh, color=d.get("color", C["led_red"]))
            lab = label or d.get("silk", "")
            if lab:
                s.text(x + lw + 0.5, y + lh / 2 + 0.45, lab, size=0.72, fill=silk,
                       weight="700", anchor="start")
        elif t == "crystal":
            s.rect(x, y, w, h, r=0.5, fill=C["silver"], stroke=C["silver_dark"], sw=0.2)
            s.rect(x + 0.6, y + 0.55, w - 1.2, h - 1.1, r=0.35, fill="#AEB3B8", stroke="#8E9398", sw=0.12)
        elif t == "qfn":
            chip_qfn(s, x, y, size=d.get("size", 4.0), label=label or None)


def render_board(bid_or_spec) -> "object":
    """渲染一块开发板，返回 Part（含引脚坐标表）。"""
    from parts_library import _mk, render_by_id   # 延迟导入，避免循环依赖

    spec = specs()[bid_or_spec] if isinstance(bid_or_spec, str) else bid_or_spec
    if not isinstance(spec, dict):
        raise KeyError(f"未知开发板: {bid_or_spec}")

    # 手工精修板：转交给 parts_library 里同名渲染器
    if spec.get("hand_tuned"):
        return render_by_id(spec["hand_tuned"])

    W, H = spec["size_mm"]
    pcb_c = spec.get("pcb") or {}
    silk = spec.get("silk", "#FFFFFF")
    s = Svg(W, H, pad_mm=1.6, bg=None)
    pcb(s, 0, 0, W, H, fill=pcb_c.get("fill", C["pcb_black"]),
        edge=pcb_c.get("edge"), r=pcb_c.get("corner_r", 1.2))
    _decor(s, spec, silk)

    # -- 排针 ---------------------------------------------------------------
    pins: dict[str, dict] = {}
    pad_xy: list[tuple[float, float]] = []
    warn: list[str] = []
    gpio_of = spec.get("gpio") or {}

    for ci, conn in enumerate(spec.get("connectors") or []):
        side = conn.get("side", "top")
        names = conn.get("pins") or []
        pitch = float(conn.get("pitch", 2.54))
        hide = set(conn.get("hide_pins") or [])
        base_size = float(conn.get("label_size", 0.95))
        pad_r = float(conn.get("pad_r", 0.95))
        hole_r = float(conn.get("hole_r", 0.45))
        at = float(conn.get("at", 0))

        for i, nm in enumerate(names):
            if side in ("top", "bottom"):
                px = at + i * pitch
                py = float(conn.get("y", 2.4 if side == "top" else H - 2.4))
                direc = "down" if side == "bottom" else "up"
            else:
                py = at + i * pitch
                px = float(conn.get("x", 2.4 if side == "left" else W - 2.4))
                direc = "right" if side == "right" else "left"

            pad(s, px, py, r=pad_r, hole_r=hole_r)
            pad_xy.append((px, py))

            # 丝印：垂直于排针方向、朝板内延伸
            size = _fit_size(nm, base_size, pitch * 2.2)
            if side == "top":
                s.text(px, py + 1.5, nm, size=size, fill=silk, rot=-90, anchor="end", weight="700")
            elif side == "bottom":
                s.text(px, py - 1.5, nm, size=size, fill=silk, rot=-90, anchor="start", weight="700")
            elif side == "left":
                s.text(px + 1.5, py, nm, size=size, fill=silk, rot=0, anchor="start", weight="700")
            else:
                s.text(px - 1.5, py, nm, size=size, fill=silk, rot=0, anchor="end", weight="700")

            if nm in hide:
                continue
            key = re.sub(r"[^0-9A-Za-z]+", "_", nm).strip("_") or f"P{ci}_{i}"
            if key in pins:
                n = 2
                while f"{key}_{n}" in pins:
                    n += 1
                warn.append(f"引脚名 '{nm}' 重复，第 {n} 个记为 {key}_{n}")
                key = f"{key}_{n}"
            pins[key] = {"x": px, "y": py, "dir": direc, "label": nm,
                         "gpio": gpio_of.get(nm), "row": side}

    # -- 安装孔（自动避让焊盘，避免压在一起） -------------------------------
    hole_r_default = spec.get("mount_hole_r", 1.35)
    for hx, hy, hr in spec.get("holes") or []:
        r = hr if hr is not None else hole_r_default
        hit = any((hx - px) ** 2 + (hy - py) ** 2 < (r + 0.95 + 0.12) ** 2 for px, py in pad_xy)
        if hit:
            warn.append(f"安装孔 ({hx},{hy}) 与焊盘冲突，已跳过")
            continue
        mount_hole(s, hx, hy, r)

    meta = {"fqbn": spec.get("fqbn"), "source": spec.get("source"),
            "catalog": spec["id"], "kind": "generated"}
    if warn:
        meta["warnings"] = warn
    return _mk(spec["id"], spec.get("name", spec["id"]), W, H, s, pins, meta)


# --------------------------------------------------------- 未知板卡的兜底渲染


def generic_board(names: list[str], title: str = "Unknown board",
                  gpio: dict | None = None, fqbn: str | None = None,
                  columns: int = 2) -> "object":
    """
    目录里没有的板子：用 `detect_board` 解析出的**真实引脚名**生成一块外形示意的板。

    电气连接仍然正确（引脚名来自核心包 pins_arduino.h），只有「焊盘在板上的物理位置」
    是示意排列 —— 成图时应在 report 里注明，并建议用户拍一张实物照片以便精修。
    """
    from parts_library import _mk

    names = [str(n) for n in names if n]
    if not names:
        names = [f"P{i}" for i in range(20)]
    per = max(1, (len(names) + columns - 1) // columns)
    W, H = 25.4, max(52.0, per * 2.54 + 10.0)
    s = Svg(W, H, pad_mm=1.6, bg=None)
    pcb(s, 0, 0, W, H, fill=C["pcb_black"], edge=C["pcb_black_edge"], r=1.4)
    shield_can(s, 4.4, 5.0, W - 8.8, min(20.0, H * 0.42))
    s.text(W / 2, H - 3.2, title[:18], size=1.5, fill="#C9CDD2", weight="700")

    pins: dict[str, dict] = {}
    for i, nm in enumerate(names[:per * columns]):
        col = 0 if i < per else 1
        row = i if col == 0 else i - per
        px = 2.4 if col == 0 else W - 2.4
        py = 3.6 + row * 2.54
        pad(s, px, py, r=0.95, hole_r=0.45)
        size = _fit_size(nm, 0.68, 2.54 * 2.2)
        if col == 0:
            s.text(px + 1.5, py, nm, size=size, fill="#E4E7EA", anchor="start", weight="700")
        else:
            s.text(px - 1.5, py, nm, size=size, fill="#E4E7EA", anchor="end", weight="700")
        key = re.sub(r"[^0-9A-Za-z]+", "_", nm).strip("_") or f"P{i}"
        if key in pins:
            n = 2
            while f"{key}_{n}" in pins:
                n += 1
            key = f"{key}_{n}"
        pins[key] = {"x": px, "y": py, "dir": "left" if col == 0 else "right",
                     "label": nm, "gpio": (gpio or {}).get(nm),
                     "row": "left" if col == 0 else "right"}

    meta = {"fqbn": fqbn, "catalog": None, "kind": "generic_fallback",
            "note": "目录中无此板卡，排针位置为示意排列；引脚名来自核心包 pins_arduino.h"}
    return _mk(f"generic_{re.sub(r'[^a-z0-9]+', '_', (fqbn or title).lower())}",
               title, W, H, s, pins, meta)


# --------------------------------------------------------------------- CLI


def main():
    ap = argparse.ArgumentParser(description="开发板目录 / 渲染器")
    ap.add_argument("--list", action="store_true", help="列出全部板卡")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出目录")
    ap.add_argument("--match", help="按 FQBN / variant / 名称匹配")
    ap.add_argument("--variant", help="按核心包 variant 名匹配")
    ap.add_argument("--render", help="渲染指定板卡 id")
    ap.add_argument("--out", help="输出 SVG 路径（配合 --render）")
    ap.add_argument("--catalog", help="指定板卡目录 JSON")
    args = ap.parse_args()

    if args.catalog:
        global _CACHE
        _CACHE = load(args.catalog)

    if args.json:
        print(json.dumps({k: v for k, v in specs().items()},
                         ensure_ascii=False, indent=2))
        return

    if args.match or args.variant:
        sp = match(fqbn=args.match, variant=args.variant, name=args.match)
        if not sp:
            print("未匹配到板卡（可用 --list 查看已有板卡；"
                  "未知板卡建议走 generic_board 兜底渲染）")
            sys.exit(2)
        print(json.dumps({"id": sp["id"], "name": sp.get("name"),
                          "size_mm": sp.get("size_mm"), "fqbn": sp.get("fqbn"),
                          "hand_tuned": sp.get("hand_tuned"),
                          "source": sp.get("source")}, ensure_ascii=False, indent=2))
        return

    if args.render:
        part = render_board(args.render)
        print(f"✓ {part.pid}  {part.name}  {part.w}×{part.h} mm  {len(part.pins)} 引脚")
        for k, v in list(part.pins.items())[:4]:
            g = f" · GPIO{v['gpio']}" if v.get("gpio") is not None else ""
            print(f"    {k:10s} ({v['x']:6.2f},{v['y']:6.2f}) {v['dir']:5s} {v['label']}{g}")
        if part.meta.get("warnings"):
            for w in part.meta["warnings"]:
                print("    ! " + w)
        if args.out:
            with open(args.out, "w", encoding="utf8") as f:
                f.write(part.svg)
            print(f"→ {args.out}")
        return

    # 默认：列表
    rows = list_boards()
    print(f"共 {len(rows)} 块板卡（{catalog_path()}）\n")
    print(f"{'id':26s} {'尺寸(mm)':16s} {'类型':11s} 名称")
    print("-" * 78)
    for bid, name, size, kind in rows:
        dim = f"{size[0]}×{size[1]}"
        print(f"{bid:26s} {dim:16s} {kind:11s} {name}")


if __name__ == "__main__":
    main()
