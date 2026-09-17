#!/usr/bin/env python3
"""contact_sheet.py — 把 Bing 下载到的参考图拼成一张带标签的对照图，供视觉判断元件外观。

用法:
    contact_sheet.py --refs <refs_dir> [--out <png>] [--cell 320] [--cols 4]

读取 <refs_dir>/_index.json 的分组信息；没有 index 时按文件名前缀自动分组。
输出一张 PNG（浅色底、带组标题和文件名标注），Agent 可直接用图像识读能力判断
「PCB 颜色 / 外形比例 / 接口位置 / 丝印文字 / 引脚数」。
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BG = (245, 246, 248)
CARD = (255, 255, 255)
INK = (28, 32, 38)
SUB = (110, 118, 128)
LINE = (222, 226, 232)

FONT_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]


def load_font(size):
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def fit(im, box_w, box_h):
    im = im.convert("RGB")
    r = min(box_w / im.width, box_h / im.height, 1.0)
    return im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))), Image.LANCZOS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refs", required=True)
    ap.add_argument("--out")
    ap.add_argument("--cell", type=int, default=320)
    ap.add_argument("--cols", type=int, default=4)
    args = ap.parse_args()

    refs = Path(args.refs)
    if not refs.is_dir():
        sys.exit(f"目录不存在: {refs}")
    out = Path(args.out) if args.out else refs / "_contact_sheet.png"

    index = {}
    idx_path = refs / "_index.json"
    if idx_path.exists():
        index = json.loads(idx_path.read_text(encoding="utf8"))

    # 分组：优先用 index，其次按文件名前缀
    groups = {}
    for slug, info in index.items():
        files = [Path(i["file"]) for i in info.get("images", []) if Path(i["file"]).exists()]
        if files:
            groups[slug] = (info.get("name", slug), files)
    if not groups:
        for f in sorted(refs.iterdir()):
            if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") and not f.name.startswith("_"):
                slug = re.sub(r"_\d+$", "", f.stem)
                groups.setdefault(slug, (slug, []))[1].append(f)

    if not groups:
        sys.exit("没有可用参考图")

    cell = args.cell
    pad = 14
    label_h = 34
    cols = args.cols
    f_title = load_font(15)
    f_sub = load_font(12)

    rows = []
    for slug, (name, files) in groups.items():
        rows.append((slug, name, files[: cols * 2]))

    total_h = pad
    for _, _, files in rows:
        n_rows = (len(files) + cols - 1) // cols
        total_h += 30 + n_rows * (cell + label_h + pad) + pad
    total_w = pad + cols * (cell + pad)

    canvas = Image.new("RGB", (total_w, total_h), BG)
    d = ImageDraw.Draw(canvas)
    y = pad

    for slug, name, files in rows:
        d.text((pad + 2, y), f"{name}   ·   {slug}", font=f_title, fill=INK)
        y += 30
        for i, f in enumerate(files):
            r, c = divmod(i, cols)
            x = pad + c * (cell + pad)
            yy = y + r * (cell + label_h + pad)
            d.rectangle([x, yy, x + cell, yy + cell + label_h], fill=CARD, outline=LINE)
            try:
                im = fit(Image.open(f), cell - 12, cell - 12)
                canvas.paste(im, (x + (cell - im.width) // 2, yy + (cell - im.height) // 2))
            except Exception as e:
                d.text((x + 8, yy + 8), f"读取失败 {e}", font=f_sub, fill=(200, 60, 60))
            d.text((x + 8, yy + cell + 8), f.name[:44], font=f_sub, fill=SUB)
        n_rows = (len(files) + cols - 1) // cols
        y += n_rows * (cell + label_h + pad) + pad

    canvas.save(out)
    print(out)
    print(f"{len(rows)} 组 / {sum(len(f) for _, _, f in rows)} 张图 -> {canvas.size[0]}x{canvas.size[1]}")


if __name__ == "__main__":
    main()
