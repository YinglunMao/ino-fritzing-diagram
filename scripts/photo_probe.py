#!/usr/bin/env python3
"""
photo_probe.py — 实拍照片「取证」工具：先看清照片，再决定元件型号

用途
----
当用户提供了电路/元件实拍照片时，**优先从照片识别元件与开发板**。
但手机照片往往分辨率不足、丝印看不清，直接肉眼看容易误判。
本脚本把照片切成可读的图块 / 指定区域放大增强，让「看图」这一步可复现、
可复核，而不是靠猜。

三个子功能
----------
1. `--tiles R C`  把整张照片切成 R×C 块，逐块放大 —— **先全局扫一遍找元件**
2. `--crop`       对指定区域裁剪 + 放大 + 增强 —— **再逐个读丝印/认外形**
   （`--rotate 180` 用于丝印倒置的板子；`--contrast` 用于白底黑丝印的低反差板）
3. `--color`      采样区域平均色 —— **客观判定 PCB 底色**（别用肉眼猜「白板/黑板」）

用法
----
    # 0) 看尺寸
    photo_probe.py --photo P.jpg

    # 1) 全局切片（3 行 4 列），先找元件在哪
    photo_probe.py --photo P.jpg --out out --tiles 3 4

    # 2) 区域放大：读开发板丝印（丝印倒置 → 旋转 180；白底低反差 → 加对比）
    photo_probe.py --photo P.jpg --out out \
        --crop 250,805,545,845 --scale 10 --rotate 180 --contrast 2.5 --tag dev_silk

    # 3) 客观测 PCB 底色
    photo_probe.py --photo P.jpg --color pcbA=430,890,460,905 --color ref_wood=900,1400,930,1415
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys

try:
    from PIL import Image, ImageEnhance
except ImportError:
    sys.exit("需要 Pillow： pip install Pillow")


def _parse_box(s: str):
    parts = [p for p in s.replace(" ", "").split(",") if p]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(f"区域格式应为 x0,y0,x1,y1，收到: {s}")
    return tuple(int(float(p)) for p in parts)


def _enhance(img, contrast, sharpness):
    if contrast and contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)
    if sharpness and sharpness != 1.0:
        img = ImageEnhance.Sharpness(img).enhance(sharpness)
    return img


def do_tiles(im, out, rows, cols, scale, contrast):
    W, H = im.size
    tw, th = W / cols, H / rows
    made = []
    for r in range(rows):
        for c in range(cols):
            box = (int(c * tw), int(r * th), int((c + 1) * tw), int((r + 1) * th))
            tile = im.crop(box)
            tile = tile.resize((tile.width * scale, tile.height * scale), Image.LANCZOS)
            tile = _enhance(tile, contrast, 1.4)
            p = os.path.join(out, f"tile_r{r+1}c{c+1}.png")
            tile.save(p)
            made.append(p)
    return made


def do_crops(im, out, crops, scale, rotate, contrast):
    made = []
    for box, tag in crops:
        c = im.crop(box)
        if rotate:
            c = c.rotate(rotate, expand=True)
        c = c.resize((c.width * scale, c.height * scale), Image.LANCZOS)
        c = _enhance(c, contrast, 1.4)
        p = os.path.join(out, f"{tag}.png")
        c.save(p)
        made.append(p)
    return made


def do_colors(im, specs):
    out = []
    for name, box in specs:
        reg = im.crop(box).convert("RGB")
        px = list(reg.getdata())
        r = statistics.mean(p[0] for p in px)
        g = statistics.mean(p[1] for p in px)
        b = statistics.mean(p[2] for p in px)
        out.append((name, r, g, b))
    return out


def main():
    ap = argparse.ArgumentParser(description="实拍照片取证：切片 / 放大 / 测色")
    ap.add_argument("--photo", required=True)
    ap.add_argument("--out", default="photo_probe")
    ap.add_argument("--tiles", nargs=2, type=int, metavar=("ROWS", "COLS"))
    ap.add_argument("--tile-scale", type=int, default=2)
    ap.add_argument("--crop", action="append", type=_parse_box, default=[],
                    metavar="x0,y0,x1,y1")
    ap.add_argument("--tag", action="append", default=[], help="与 --crop 一一对应的文件名")
    ap.add_argument("--scale", type=int, default=4)
    ap.add_argument("--rotate", type=int, default=0, choices=[0, 90, 180, 270])
    ap.add_argument("--contrast", type=float, default=1.0)
    ap.add_argument("--color", action="append", default=[], metavar="name=x0,y0,x1,y1")
    args = ap.parse_args()

    im = Image.open(args.photo)
    print(f"照片: {args.photo}")
    print(f"尺寸: {im.size[0]}×{im.size[1]} px  模式: {im.mode}")

    if not (args.tiles or args.crop or args.color):
        print("\n（只读了尺寸。加 --tiles / --crop / --color 才会产出分析图）")
        return

    os.makedirs(args.out, exist_ok=True)

    if args.tiles:
        made = do_tiles(im, args.out, args.tiles[0], args.tiles[1],
                        args.tile_scale, args.contrast)
        print(f"\n切片 {args.tiles[0]}×{args.tiles[1]} → {len(made)} 张")
        for p in made:
            print("  " + p)

    if args.crop:
        tags = list(args.tag) + [f"crop{i+1}" for i in range(len(args.crop))]
        crops = list(zip(args.crop, tags))
        made = do_crops(im, args.out, crops, args.scale, args.rotate, args.contrast)
        print(f"\n区域放大 → {len(made)} 张")
        for p in made:
            print("  " + p)

    if args.color:
        specs = []
        for s in args.color:
            if "=" not in s:
                sys.exit(f"--color 需要 name=x0,y0,x1,y1 形式，收到: {s}")
            nm, box = s.split("=", 1)
            specs.append((nm, _parse_box(box)))
        print("\n区域平均色（用于客观判定 PCB 底色）:")
        for nm, r, g, b in do_colors(im, specs):
            tone = "亮白" if min(r, g, b) > 170 else (
                "深色" if max(r, g, b) < 90 else "中等")
            print(f"  {nm:16s} R={r:6.1f} G={g:6.1f} B={b:6.1f}  "
                  f"#{int(r):02X}{int(g):02X}{int(b):02X}  → {tone}")


if __name__ == "__main__":
    main()
