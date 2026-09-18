#!/usr/bin/env python3
"""
check_wiring.py —— 接线图几何自检（不开浏览器）

读 `build_wiring.py --debug-json` 导出的布线日志，用几何计算找三类问题：

  ① 重叠：两条**不同网络**的线画在同一根线上（共线且区间相交）      —— 严重
  ② 贴线：两条不同网络的平行线横向距离过近（中间留不出空隙）        —— 严重
  ③ 穿体：导线从元件本体或开发板内部穿过（进出焊盘的那一小段除外）  —— 严重
  ④ 错位：SVG 里 **实际画上去**的元件位置 ≠ 布线按以走的坐标          —— 严重
          （元件在落图之后又被移动，线头就会悬空。靠 SVG 上的 data-box 比对抓。）

退出码 0 = 通过，1 = 有问题，可以直接当流水线的闸门。

用法:
    python3 check_wiring.py --debug-json <wiring.debug.json>
    python3 check_wiring.py --debug-json <...> --sep 16 --overlap-min 4
默认会从 debug-json 的文件名推出同名 .svg 做第 ④ 项比对，也可用 --svg 指定。
"""
import argparse
import json
import os
import re
import sys

AXIS_EPS = 0.8      # 判定「水平/竖直」的容差
INSIDE_MIN = 14.0   # 穿体的最小侵入长度（px），短于此视为进出焊盘的正常引线
PIN_TOL = 14.0      # 端点离焊盘这么近，就认为它是在接焊盘，不算穿体


def axis_seg(a, b):
    """线段 -> ('v'|'h', 固定坐标, lo, hi)；斜线返回 None"""
    if abs(a[0] - b[0]) < AXIS_EPS and abs(a[1] - b[1]) < AXIS_EPS:
        return None
    if abs(a[0] - b[0]) < AXIS_EPS:
        return ("v", a[0], min(a[1], b[1]), max(a[1], b[1]), a, b)
    if abs(a[1] - b[1]) < AXIS_EPS:
        return ("h", a[1], min(a[0], b[0]), max(a[0], b[0]), a, b)
    return None


def collect(wires):
    flat = []
    for w in wires:
        for a, b in zip(w["pts"], w["pts"][1:]):
            s = axis_seg(a, b)
            if s:
                flat.append({"net": w["net"], "color": w["color"], "ax": s[0],
                             "f": s[1], "lo": s[2], "hi": s[3],
                             "p0": tuple(a), "p1": tuple(b)})
    return flat


def check_overlap(flat, min_ov):
    bad = []
    for i in range(len(flat)):
        s1 = flat[i]
        for j in range(i + 1, len(flat)):
            s2 = flat[j]
            if s1["ax"] != s2["ax"] or s1["net"] == s2["net"]:
                continue
            if abs(s1["f"] - s2["f"]) > AXIS_EPS:
                continue
            ov = min(s1["hi"], s2["hi"]) - max(s1["lo"], s2["lo"])
            if ov > min_ov:
                bad.append((s1["net"], s2["net"], s1["ax"], round(s1["f"], 1), round(ov, 1)))
    return bad


def check_near(flat, sep, min_ov):
    bad = []
    for i in range(len(flat)):
        s1 = flat[i]
        for j in range(i + 1, len(flat)):
            s2 = flat[j]
            if s1["ax"] != s2["ax"] or s1["net"] == s2["net"]:
                continue
            d = abs(s1["f"] - s2["f"])
            if not (AXIS_EPS < d < sep):
                continue
            if min(s1["hi"], s2["hi"]) - max(s1["lo"], s2["lo"]) > min_ov:
                bad.append((s1["net"], s2["net"], s1["ax"],
                            round(s1["f"], 1), round(s2["f"], 1), round(d, 1)))
    return bad


def check_through(flat, boxes):
    """导线从元件本体 / 开发板内部穿过（端点即该元件焊盘的算正常引线）"""
    bad = []
    for iid, box in boxes.items():
        x0, y0, x1, y1 = box["box"]
        x0, y0, x1, y1 = x0 + 3, y0 + 3, x1 - 3, y1 - 3
        pin_xy = [(p[0], p[1]) for p in box["pins"].values()]
        for s in flat:
            touch = any(
                (s["p0"][0] - px) ** 2 + (s["p0"][1] - py) ** 2 < PIN_TOL ** 2
                or (s["p1"][0] - px) ** 2 + (s["p1"][1] - py) ** 2 < PIN_TOL ** 2
                for px, py in pin_xy)
            if touch:
                continue
            if s["ax"] == "v":
                if not (x0 < s["f"] < x1):
                    continue
                ov = min(s["hi"], y1) - max(s["lo"], y0)
            else:
                if not (y0 < s["f"] < y1):
                    continue
                ov = min(s["hi"], x1) - max(s["lo"], x0)
            if ov > INSIDE_MIN:
                bad.append((s["net"], iid, s["ax"], round(s["f"], 1), round(ov, 1)))
    return bad


def check_misplaced(svg_text, boxes, tol=1.0):
    """SVG 上真的画在哪 vs 布线以为它画在哪。

    build_wiring.py 会在每个元件组上打 data-inst / data-box 标记，记录**落图那一刻**
    的坐标；--debug-json 里的 boxes 则是收尾时读到的坐标。两者不一致，就说明元件在
    落图之后被挪动过 —— 元件的引脚位置只剩导线知道，人眼看到的是线头悬在板子外面。
    """
    drawn = {}
    for m in re.finditer(r'<g data-inst="([^"]+)" data-box="([^"]+)"', svg_text):
        try:
            drawn[m.group(1)] = [float(v) for v in m.group(2).split(",")]
        except ValueError:
            continue
    bad = []
    for iid, box in boxes.items():
        if iid not in drawn:
            bad.append((iid, "SVG 里找不到该元件（没打 data-box 标记）", None))
            continue
        a, b = drawn[iid], box["box"]
        if max(abs(a[i] - b[i]) for i in range(4)) > tol:
            dy = round(b[1] - a[1], 1)
            dx = round(b[0] - a[0], 1)
            bad.append((iid, f"画在 y={a[1]:.1f}，布线却按 y={b[1]:.1f} 走", (dx, dy)))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--debug-json", required=True)
    ap.add_argument("--svg", help="对应的接线图 SVG；默认由 debug-json 文件名推出")
    ap.add_argument("--sep", type=float, default=16.0, help="平行线最小间距（px）")
    ap.add_argument("--overlap-min", type=float, default=4.0, help="重叠多少 px 才算问题")
    args = ap.parse_args()

    with open(args.debug_json, encoding="utf8") as f:
        d = json.load(f)
    flat = collect(d["wires"])
    nets = sorted({w["net"] for w in d["wires"]})
    print(f"网络 {len(nets)} 条 / 折线 {len(d['wires'])} 段 / 线段 {len(flat)} 条\n")

    bad = False

    ov = check_overlap(flat, args.overlap_min)
    print(f"① 不同网络重叠: {len(ov)} 处")
    for a, b, ax, f, n in ov[:20]:
        print(f"   ✗ {a} ↔ {b}   同为{'竖' if ax == 'v' else '横'}线 @{f}   重叠 {n}px")
    bad |= bool(ov)

    near = check_near(flat, args.sep, args.overlap_min)
    print(f"② 不同网络贴线（间距 < {args.sep:g}px）: {len(near)} 处")
    for a, b, ax, f1, f2, dd in near[:20]:
        print(f"   ✗ {a} ↔ {b}   同为{'竖' if ax == 'v' else '横'}线 @{f1} / {f2}   间距 {dd}px")
    bad |= bool(near)

    th = check_through(flat, d["boxes"])
    print(f"③ 导线穿过元件 / 板体: {len(th)} 处")
    for net, iid, ax, f, n in th[:20]:
        print(f"   ✗ {net} 穿过 {iid}   {'竖线' if ax == 'v' else '横线'}@{f}   侵入 {n}px")
    bad |= bool(th)

    svg_path = args.svg or os.path.splitext(args.debug_json)[0].replace(".debug", "") + ".svg"
    if os.path.exists(svg_path):
        with open(svg_path, encoding="utf8") as f:
            mis = check_misplaced(f.read(), d["boxes"])
        print(f"④ 元件「画的位置」与「布线用的坐标」不符: {len(mis)} 处")
        for iid, why, _ in mis[:20]:
            print(f"   ✗ {iid}: {why}")
        bad |= bool(mis)
    else:
        print(f"④ 元件位置一致性: 跳过（没找到 {os.path.basename(svg_path)}）")

    print("\n" + ("✗ 未通过：上面这些问题正是「线看起来叠在一起」的原因"
                  if bad else "✓ 通过：无重叠、无贴线、无穿体、元件位置一致"))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
