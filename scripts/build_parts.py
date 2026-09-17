#!/usr/bin/env python3
"""
build_parts.py — 生成各元件/开发板的 Fritzing 风格 SVG，并导出引脚坐标表

用法:
    build_parts.py --out <dir> --parts geekble_nano_esp32s3,mpu6050_gy521,...
    build_parts.py --out <dir> --all                 # 生成库中全部元件
    build_parts.py --out <dir> --all --sheet         # 额外拼一张 parts_sheet.svg

输出:
    <dir>/parts/<id>.svg          单个元件（可直接拖进 Fritzing 参考，或用于文档）
    <dir>/parts/_pins.json        各元件引脚坐标（mm，相对元件左上角）+ 朝向
    <dir>/parts/parts_sheet.svg   所有元件排成一张总览图（可选）
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parts_library import REGISTRY, render_by_id  # noqa: E402
from fritzing_kit import Svg, C  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="输出根目录")
    ap.add_argument("--parts", help="逗号分隔的元件 id")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--sheet", action="store_true", help="额外输出总览图")
    ap.add_argument("--titles", action="store_true", help="在单个 SVG 内绘制标题")
    args = ap.parse_args()

    ids = list(REGISTRY) if args.all or not args.parts else [
        p.strip() for p in args.parts.split(",") if p.strip()
    ]
    partsdir = os.path.join(args.out, "parts")
    os.makedirs(partsdir, exist_ok=True)

    pins_out = {}
    rendered = []
    for pid in ids:
        part = render_by_id(pid)
        rendered.append(part)
        path = os.path.join(partsdir, f"{pid}.svg")
        with open(path, "w", encoding="utf8") as f:
            f.write(part.svg)
        pins_out[pid] = {
            "name": part.name,
            "size_mm": [part.w, part.h],
            "meta": part.meta,
            "pins": part.pins,
        }
        print(f"  ✓ {pid:26s} {part.w:5.1f}×{part.h:4.1f}mm  {len(part.pins):2d} pins  -> {path}")

    with open(os.path.join(partsdir, "_pins.json"), "w", encoding="utf8") as f:
        json.dump(pins_out, f, ensure_ascii=False, indent=2)

    if args.sheet:
        cols = 2
        gap_x, gap_y, title_h = 16.0, 12.0, 6.0
        col_w = max(p.w for p in rendered) + gap_x
        rows = (len(rendered) + cols - 1) // cols
        row_h = max(p.h for p in rendered) + gap_y + title_h
        sheet = Svg(cols * col_w, rows * row_h, pad_mm=6.0, bg="#F7F8FA")
        for i, p in enumerate(rendered):
            r, c = divmod(i, cols)
            ox = c * col_w + gap_x / 2
            oy = r * row_h + title_h + gap_y / 2
            inner = p.svg.split("<svg", 1)[1]
            inner = inner.split(">", 1)[1].rsplit("</svg>", 1)[0]
            sheet.add(f'<g transform="translate({ox*10:.1f},{oy*10:.1f})">{inner}</g>')
            sheet.rect(ox - 2, oy - 2, p.w + 4, p.h + 4, r=1.5, fill="none",
                       stroke="#D5DAE0", sw=0.25)
            sheet.text(ox + p.w / 2, oy - 3.0, p.name, size=2.0, fill="#2A2F36", weight="700")
            sheet.text(ox + p.w / 2, oy + p.h + 5.6, f"{p.w:.1f} × {p.h:.1f} mm",
                       size=1.5, fill="#8A9099", weight="600")
        sheetpath = os.path.join(partsdir, "parts_sheet.svg")
        with open(sheetpath, "w", encoding="utf8") as f:
            f.write(sheet.render(aria="元件总览"))
        print(f"  ✓ parts_sheet -> {sheetpath}")

    print(f"\n共 {len(ids)} 个元件，输出目录: {partsdir}")


if __name__ == "__main__":
    main()
