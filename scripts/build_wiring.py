#!/usr/bin/env python3
"""
build_wiring.py — 依据「元件实例布局 + 网络表」生成 Fritzing 风格接线图 SVG

核心约定
--------
* 不使用面包板：开发板与各模块直接连线。
* **供电(VCC/3V3)用红线、地(GND)用黑线**；其余每根信号线颜色互不相同。
* 导线端点一律取自元件的引脚坐标表（parts_library 输出），保证图与元件严格对齐。

两种布局模式（`layout` 字段）
-----------------------------
**A. `rails`（默认，旧版）** —— 供电/接地各自汇成一条总线轨
    所有 VCC 连到同一根红轨，所有 GND 连到同一根黑轨；信号线走水平通道。

**B. `two_sided`（推荐）** —— 元件均分在开发板两侧，供电/接地各自回到板子的引脚
    元件按 `groups.top` / `groups.bottom` 分成两组，分列开发板上、下两侧；
    **不再拉横贯全图的总线轨**：每个元件的 VCC/GND 都直接连到开发板上真正的
    供电/接地引脚（这正是参考图里的画法）。同一根板引脚上的多条线在引脚汇合处
    画实心汇流点。跨侧的网络（如板上 3V3 要给下侧模块供电）沿板子**短边外侧**
    绕行，不穿过板体。

two_sided 布局规格 JSON
----------------------
{
  "layout": "two_sided",
  "canvas": [W, H], "title": "...", "subtitle": "...", "badge": "...",
  "board_id": "board",
  "groups": {
     "top":    [ {"id":"mpu","part":"mpu6050_gy521","x":300,"y":150,"caption":"..."} ],
     "bottom": [ {"id":"as7341","part":"as7341_black6","x":300,"y":700,"caption":"..."} ]
  },
  "nets": [
     {"id":"3V3","color":"#E53935","label":"3V3 供电",
      "nodes":[["board","3V3"],["mpu","VCC"],["as7341","VIN"],["pulse","VCC"]]},
     {"id":"SDA","color":"#1565C0","label":"SDA",
      "desc":"I2C 数据 · GPIO8",
      "nodes":[["board","G8"],["as7341","SDA"],["mpu","SDA"]]}
  ],
  "notes": ["..."]
}

网络规则：`nodes[0]` 必须落在开发板上（作为该网络的锚点引脚），其余为元件引脚。
一个网络可以同时含上、下两侧的元件，布线器会自动分侧扇出。

布局规格 JSON
-------------
{
  "canvas": [w, h],
  "title": "...", "subtitle": "...",
  "rails": [{"net":"GND","y":140,"x0":70,"x1":1290,"color":"#212121","label":"GND 地轨"}, ...],
  "instances": [
     {"id":"board","part":"geekble_nano_esp32s3","x":434,"y":280,
      "power_lane":{"x":890,"y":520}},          # 可选：供电线借道路径
     ...
  ],
  "nets": [
     {"id":"3V3","color":"#E53935","rail":true,"nodes":[["board","3V3"],["mpu","VCC"]]},
     {"id":"SDA","color":"#1565C0","nodes":[["board","D5"],["as7341","SDA"],["mpu","SDA"]],
      "lane":580},                              # 可选：水平走线通道
     {"id":"PULSE","color":"#2E9E4F","nodes":[["board","A3"],["pulse","SIG"]],
      "template":"wrap_top","lane_x":900,"lane":620}
  ],
  "legend": [...]
}

用法:
    build_wiring.py --spec <layout.json> --out <dir>/wiring.svg [--pins <_pins.json>]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fritzing_kit import MM, Svg, esc, lighten, darken  # noqa: E402
from parts_library import render_by_id  # noqa: E402

STUB = 16.0        # 从焊盘引出的第一段短线（px）
WIRE_W = 5.4       # 导线宽度
HALO_W = 8.0       # 导线描边（让交叉处层次分明）
LANE_GAP = 26.0    # two_sided 模式下相邻水平通道的间距
SIDE_MARGIN = 46.0 # 跨侧绕行时，绕过板子短边所用的外侧车道余量


# --------------------------------------------------------------- 元件实例
class Instance:
    def __init__(self, spec):
        self.id = spec["id"]
        self.part = render_by_id(spec["part"])
        self.x = float(spec["x"])
        self.y = float(spec["y"])
        self.rot = float(spec.get("rot", 0))
        self.power_lane = spec.get("power_lane")
        self.caption = spec.get("caption", self.part.name)
        self.caption_pos = spec.get("caption_pos", "below")
        self.caption_xy = spec.get("caption_xy")
        self.caption_anchor = spec.get("caption_anchor", "start")
        # 从 viewBox 反推内部留白
        m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', self.part.svg)
        self.svg_w = float(m.group(1)) / MM
        self.svg_h = float(m.group(2)) / MM
        self.pad = (self.svg_w - self.part.w) / 2.0

    @property
    def w_px(self):
        return self.part.w * MM

    @property
    def h_px(self):
        return self.part.h * MM

    @property
    def box(self):
        return (self.x, self.y, self.x + self.w_px, self.y + self.h_px)

    def pin(self, name):
        if name not in self.part.pins:
            raise KeyError(f"{self.id} 没有引脚 {name}；可用: {list(self.part.pins)}")
        p = self.part.pins[name]
        x, y = p["x"] * MM, p["y"] * MM
        d = p["dir"]
        if self.rot == 180:
            x, y = self.w_px - x, self.h_px - y
            d = {"up": "down", "down": "up", "left": "right", "right": "left"}[d]
        return (self.x + x, self.y + y, d, p)

    def embed(self):
        inner = self.part.svg.split("<svg", 1)[1]
        inner = inner.split(">", 1)[1].rsplit("</svg>", 1)[0]
        tx, ty = self.x - self.pad * MM, self.y - self.pad * MM
        if self.rot:
            cx, cy = self.x + self.w_px / 2, self.y + self.h_px / 2
            return (f'<g transform="translate({tx:.1f},{ty:.1f}) rotate({self.rot:.1f} '
                    f'{cx - tx:.1f} {cy - ty:.1f})">{inner}</g>')
        return f'<g transform="translate({tx:.1f},{ty:.1f})">{inner}</g>'


# --------------------------------------------------------------- 折线工具
def clean(pts, eps=0.01):
    """去掉重复点与共线冗余点"""
    out = []
    for p in pts:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > eps:
            out.append(p)
    i = 1
    while i < len(out) - 1:
        a, b, c = out[i - 1], out[i], out[i + 1]
        if (abs(a[0] - b[0]) < eps and abs(b[0] - c[0]) < eps) or (
            abs(a[1] - b[1]) < eps and abs(b[1] - c[1]) < eps
        ):
            out.pop(i)
        else:
            i += 1
    return out


def step(p, d, n):
    return {
        "up": (p[0], p[1] - n), "down": (p[0], p[1] + n),
        "left": (p[0] - n, p[1]), "right": (p[0] + n, p[1]),
    }[d]


def hoverlaps(a, b, skip_x=6.0):
    """水平段 a→b 是否跨越 x 且与 x 相距足够"""
    lo, hi = sorted((a[0], b[0]))
    return lo + skip_x < 0 < hi - skip_x or True


# --------------------------------------------------------------- 主生成器
class WiringBuilder:
    def __init__(self, spec):
        self.spec = spec
        self.W, self.H = spec.get("canvas", [1360, 1100])
        self.s = Svg(self.W, self.H, pad_mm=0.0, bg="#FFFFFF", unit=1.0)
        self.instances = {}
        all_specs = list(spec.get("instances", []))
        for lst in spec.get("groups", {}).values():
            all_specs += list(lst)
        for isp in all_specs:
            inst = Instance(isp)
            inst.caption = isp.get("caption", inst.caption)
            inst.caption_pos = isp.get("caption_pos", inst.caption_pos)
            inst.caption_xy = isp.get("caption_xy", inst.caption_xy)
            inst.caption_anchor = isp.get("caption_anchor", inst.caption_anchor)
            self.instances[inst.id] = inst
        self.rails = spec.get("rails", [])
        self.rail_of = {r["net"]: r for r in self.rails}
        self.legend_items = []
        self._tags = []
        self.debug = spec.get("debug", False)
        self.layout = spec.get("layout", "rails")
        # two_sided：元件分组与开发板实例
        self.groups = spec.get("groups", {})
        self.side_of = {}
        for side, lst in self.groups.items():
            for isp in lst:
                self.side_of[isp["id"]] = side
        bid = spec.get("board_id")
        self.board = self.instances[bid] if bid in self.instances else None

    # ---------- 元素
    def _wire(self, pts, color, dash=None, width=WIRE_W):
        pts = clean(pts)
        if len(pts) < 2:
            return
        # 描边 + 主体，两遍绘制，交叉处层次清晰
        self.s.add(
            f'<path d="{self._d(pts)}" fill="none" stroke="#0E1013" stroke-opacity="0.22" '
            f'stroke-width="{HALO_W:.1f}" stroke-linecap="round" stroke-linejoin="round"/>'
        )
        da = f' stroke-dasharray="{dash}"' if dash else ""
        self.s.add(
            f'<path d="{self._d(pts)}" fill="none" stroke="{color}" stroke-width="{width:.1f}" '
            f'stroke-linecap="round" stroke-linejoin="round"{da}/>'
        )

    @staticmethod
    def _d(pts, r=9.0):
        d = f"M {pts[0][0]:.1f} {pts[0][1]:.1f}"
        for i in range(1, len(pts) - 1):
            x0, y0 = pts[i - 1]
            x1, y1 = pts[i]
            nx, ny = pts[i + 1]
            dx1, dy1 = x1 - x0, y1 - y0
            dx2, dy2 = nx - x1, ny - y1
            l1 = math.hypot(dx1, dy1) or 1
            l2 = math.hypot(dx2, dy2) or 1
            rr = min(r, l1 / 2, l2 / 2)
            ax, ay = x1 - dx1 / l1 * rr, y1 - dy1 / l1 * rr
            bx, by = x1 + dx2 / l2 * rr, y1 + dy2 / l2 * rr
            d += f" L {ax:.1f} {ay:.1f} Q {x1:.1f} {y1:.1f} {bx:.1f} {by:.1f}"
        x1, y1 = pts[-1]
        d += f" L {x1:.1f} {y1:.1f}"
        return d

    def _dot(self, x, y, color):
        self.s.circle(x, y, 6.0, fill=color, stroke="#FFFFFF", sw=0.22)

    def _chip(self, x, y, text, color="#FFFFFF", size=11, bold=True, pad=5.0, op=1.0):
        """带底色的标签胶囊"""
        w = len(text) * size * 0.62 + pad * 2
        h = size + pad * 1.2
        self.s.rect(x, y - h / 2, w, h, r=h / 2, fill=color, stroke="none", sw=0,
                    opacity=op)
        self.s.text(x + w / 2, y + size * 0.36, text, size=size, fill="#FFFFFF",
                    weight="700" if bold else "600")
        return w

    # ---------- 布线
    def build(self):
        spec = self.spec
        self._draw_header()
        for inst in self.instances.values():
            self.s.add(inst.embed())
        if self.layout == "two_sided":
            self._plan_fans()
            for net in spec["nets"]:
                self._route_fan_net(net)
        else:
            self._draw_rails()
            for net in spec["nets"]:
                if net.get("rail"):
                    self._route_rail_net(net)
            for net in spec["nets"]:
                if not net.get("rail"):
                    self._route_signal_net(net)
        self._draw_captions()
        self._flush_tags()
        self._layout_footer()
        self._draw_legend()
        if spec.get("notes"):
            self._draw_notes()
        return self.s

    # =====================================================================
    # 页脚：图例 + 注释
    # =====================================================================
    def _dedup_legend(self):
        items, seen = [], set()
        for c, lab, desc in self.legend_items:
            if lab in seen:
                continue
            seen.add(lab)
            items.append((c, lab, desc))
        return items

    def _layout_footer(self):
        """把图例与注释排到内容下方；空间不够就自动加高画布。

        规则（自上而下）：内容底边 → 图例标题 → 图例各行 → 注释各行 → 画布底。
        不在这一步算好，长注释会直接画到画布外面去。
        """
        self.legend_items = self._dedup_legend()
        notes = self.spec.get("notes", [])
        rows = math.ceil(len(self.legend_items) / 2) if self.legend_items else 0
        legend_h = 26 + rows * 30 if rows else 0      # 标题 + 各行
        notes_h = 20 * len(notes)
        pad = 24

        bottom = max([self._eff_box(i)[3] for i in self.instances.values()] or [0.0])
        need = bottom + 56 + legend_h + (notes_h + 18 if notes else 0) + pad
        if need > self.H:
            self.H = math.ceil(need)
            self.s.h = self.H

        # 自下而上定位：注释贴底，图例压在注释上方
        self.notes_y0 = self.H - pad - (len(notes) - 1) * 20
        legend_bottom = self.notes_y0 - 34 if notes else self.H - pad
        self.legend_y0 = legend_bottom - (rows - 1) * 30 if rows else legend_bottom

    # =====================================================================
    # two_sided 布局：元件均分在开发板两侧，供电/接地直接回到板上引脚
    # =====================================================================
    def _eff_box(self, inst):
        """含 SVG 留白的实际占位盒（px）"""
        pad = inst.pad * MM
        return (inst.x - pad, inst.y - pad,
                inst.x + inst.w_px + pad, inst.y + inst.h_px + pad)

    def _plan_fans(self):
        """为每个「网络 × 侧」分配一条水平走线通道，避免互相压线。"""
        if self.board is None:
            raise KeyError("two_sided 布局需要 board_id 指向开发板实例")
        bx0, by0, bx1, by1 = self._eff_box(self.board)
        self.board_box = (bx0, by0, bx1, by1)

        tops = [i for i, s in self.side_of.items() if s == "top"]
        bots = [i for i, s in self.side_of.items() if s == "bottom"]
        self.band_top_lo = max((self._eff_box(self.instances[i])[3] for i in tops),
                               default=by0 - 120)          # 上组下沿
        self.band_bot_hi = min((self._eff_box(self.instances[i])[1] for i in bots),
                               default=by1 + 120)          # 下组上沿

        # 每个网络在每个侧上的水平跨度 -> 跨度大的通道靠板（避免交叉）
        spans = {"top": [], "bottom": []}
        for net in self.spec["nets"]:
            if len(net["nodes"]) < 2:
                continue
            a_id, a_pin = net["nodes"][0]
            ax = self.instances[a_id].pin(a_pin)[0]
            for side in ("top", "bottom"):
                ds = [self.instances[i].pin(p)[0]
                      for i, p in net["nodes"][1:] if self.side_of.get(i) == side]
                if ds:
                    lo, hi = min([ax] + ds), max([ax] + ds)
                    spans[side].append((net["id"], hi - lo))
        self.lane_of = {"top": {}, "bottom": {}}
        for side in ("top", "bottom"):
            spans[side].sort(key=lambda t: -t[1])          # 跨度大 -> 先排（靠板）
            for k, (nid, _) in enumerate(spans[side]):
                self.lane_of[side][nid] = k
        # 通道 y：top 侧自板顶向上排；bottom 侧自板底向下排
        self.lane_y = {"top": {}, "bottom": {}}
        n_top = max(1, len(self.lane_of["top"]))
        room_top = max(60.0, (by0 - self.band_top_lo))
        gap_top = min(LANE_GAP, room_top / (n_top + 1))
        for nid, k in self.lane_of["top"].items():
            self.lane_y["top"][nid] = by0 - 18 - (k + 1) * gap_top
        n_bot = max(1, len(self.lane_of["bottom"]))
        room_bot = max(60.0, (self.band_bot_hi - by1))
        gap_bot = min(LANE_GAP, room_bot / (n_bot + 1))
        for nid, k in self.lane_of["bottom"].items():
            self.lane_y["bottom"][nid] = by1 + 18 + (k + 1) * gap_bot

    def _wrap_side_x(self, bx):
        """跨侧绕行的外侧车道 x：取板子两端中较近的一侧"""
        bx0, _, bx1, _ = self.board_box
        left, right = bx0 - SIDE_MARGIN, bx1 + SIDE_MARGIN
        return left if abs(bx - left) <= abs(bx - right) else right

    def _route_fan_net(self, net):
        """一个网络 = 板上锚点引脚 + 各元件引脚；按侧扇出，不拉总线轨。"""
        color = net["color"]
        nodes = net["nodes"]
        dash = net.get("dash")
        a_id, a_pin = nodes[0]
        board = self.instances[a_id]
        bx, by, bdir, bpin = board.pin(a_pin)
        home = "top" if bdir == "up" else "bottom"

        by_side = {"top": [], "bottom": []}
        for i, p in nodes[1:]:
            by_side[self.side_of.get(i, home)].append((i, p))

        # 锚点引出的第一段
        b1 = step((bx, by), bdir, STUB)
        self._pin_tag(bx, by, bdir, bpin, self._tag(board, a_pin, bpin))

        branches = 0
        for side in ("top", "bottom"):
            dests = by_side[side]
            if not dests:
                continue
            lane_y = self.lane_y[side][net["id"]]
            if side == home:
                trunk = [(bx, by), b1, (bx, lane_y)]
            else:
                # 绕过板子短边，落到另一侧的通道
                wrap_y = (self.board_box[1] - 30.0) if side == "bottom" \
                    else (self.board_box[3] + 30.0)
                sx = self._wrap_side_x(bx)
                trunk = [(bx, by), b1, (bx, wrap_y), (sx, wrap_y), (sx, lane_y)]
            self._wire(trunk, color, dash=dash)
            branches += 1

            ordered = sorted(dests, key=lambda t: self.instances[t[0]].pin(t[1])[0])
            for k, (iid, pname) in enumerate(ordered):
                inst = self.instances[iid]
                x, y, d, pin = inst.pin(pname)
                # 从干线与通道的交点出发 → 水平到分支 x → 竖向进入焊盘
                pts = [trunk[-1], (x, lane_y), step((x, y), d, STUB), (x, y)]
                self._wire(pts, color, dash=dash)
                if k < len(ordered) - 1:
                    self._dot(x, lane_y, color)
                self._pin_tag(x, y, d, pin, self._tag(inst, pname, pin))

        # 锚点处若分出多条支路（含跨侧），画汇流点
        if branches >= 1 and (len(by_side["top"]) + len(by_side["bottom"])) > 1:
            self._dot(b1[0], b1[1], color)

        self.legend_items.append(
            (color, net.get("label", net["id"]),
             net.get("desc", " + ".join(f"{i}.{p}" for i, p in nodes)))
        )

    def _flush_tags(self):
        """引脚标注最后绘制，保证不被导线压住；同向相邻标注自动错开行高"""
        groups = {}
        for x, y, d, text in self._tags:
            groups.setdefault(d, []).append((x, y, text))
        for d, items in groups.items():
            items.sort()
            used = []
            for x, y, text in items:
                k = 0
                while any(abs(x - ux) < 72 and k == uk for ux, uk in used):
                    k += 1
                used.append((x, k))
                base = {"up": (0, -42), "down": (0, 32), "left": (-9, 4), "right": (9, 4)}[d]
                anchor = {"up": "middle", "down": "middle", "left": "end", "right": "start"}[d]
                dy = base[1] + (k * 15 if d in ("up", "down") else 0)
                self.s.text(x + base[0], y + dy, text, size=10.5, fill="#2E3641",
                            anchor=anchor, weight="700", halo="#FFFFFF")

    def _draw_header(self):
        spec = self.spec
        self.s.text(40, 46, spec.get("title", ""), size=25, fill="#14181D",
                    anchor="start", weight="800")
        self.s.text(40, 74, spec.get("subtitle", ""), size=13, fill="#6C757F",
                    anchor="start", weight="600")
        if spec.get("badge"):
            self.s.text(self.W - 40, 46, spec["badge"], size=13, fill="#6C757F",
                        anchor="end", weight="700")

    def _draw_rails(self):
        for r in self.rails:
            y = r["y"]
            x0, x1 = r["x0"], r["x1"]
            self.s.add(
                f'<path d="M {x0} {y} H {x1}" fill="none" stroke="#0E1013" '
                f'stroke-opacity="0.22" stroke-width="{WIRE_W+4:.1f}" stroke-linecap="round"/>'
            )
            self.s.add(
                f'<path d="M {x0} {y} H {x1}" fill="none" stroke="{r["color"]}" '
                f'stroke-width="{WIRE_W+2:.1f}" stroke-linecap="round"/>'
            )
            # 轨标（画在轨的左端，避免出画布）
            self._chip(x0 - 100, y, r["label"], color=r["color"], size=12, pad=6)
            self.legend_items.append((r["color"], r["label"], r.get("desc", "")))

    def _route_rail_net(self, net):
        rail = self.rail_of.get(net["id"])
        if not rail:
            raise KeyError(f"网络 {net['id']} 标了 rail 但 rails 里没有对应轨")
        ry = rail["y"]
        nodes = net["nodes"]
        color = net["color"]
        for i, (iid, pname) in enumerate(nodes):
            inst = self.instances[iid]
            x, y, d, pin = inst.pin(pname)
            lane = inst.power_lane
            pts = [(x, y), step((x, y), d, STUB)]
            if lane:
                pts += [(x, lane["y"]), (lane["x"], lane["y"]), (lane["x"], ry)]
            else:
                pts += [(x, ry)]
            self._wire(pts, color)
            self._dot(pts[-1][0], pts[-1][1], color)
            label = inst.part.pins[pname].get("label", pname)
            gpio = pin.get("gpio")
            txt = f"{label} · GPIO{gpio}" if gpio is not None else label
            self._pin_tag(x, y, d, pin, txt)

    def _route_signal_net(self, net):
        color = net["color"]
        nodes = net["nodes"]
        lane = net.get("lane")
        template = net.get("template", "z")
        anchor_id, anchor_pin = nodes[0]
        a = self.instances[anchor_id]
        ax, ay, ad, apin = a.pin(anchor_pin)
        a1 = step((ax, ay), ad, STUB)

        # I2C 总线：锚点 -> 干线 -> 各分支
        if template == "z":
            assert lane is not None, f"网络 {net['id']} 需要 lane"
            # 干线
            self._wire([(ax, ay), a1, (ax, lane)], color)
            self._pin_tag(ax, ay, ad, apin, self._tag(a, anchor_pin, apin))
            dests = []
            for iid, pname in nodes[1:]:
                inst = self.instances[iid]
                x, y, d, pin = inst.pin(pname)
                dests.append((abs(x - ax), x, y, d, pin, inst, pname))
            dests.sort()
            for k, (_, x, y, d, pin, inst, pname) in enumerate(dests):
                self._wire([(ax, lane), (x, lane), step((x, y), d, STUB), (x, y)], color)
                if k < len(dests) - 1:            # 不是最后一个分支 => 需要汇流点
                    self._dot(x, lane, color)
                self._pin_tag(x, y, d, pin, self._tag(inst, pname, pin))
            self._dot(ax, lane, color) if len(dests) > 0 else None

        elif template == "wrap_top":
            # 锚点在开发板「上排」，需绕到板外车道再下行
            lane_x = net["lane_x"]
            top_y = net.get("top_y", 250)
            self._wire([(ax, ay), a1, (ax, top_y), (lane_x, top_y), (lane_x, lane)],
                       color, dash=net.get("dash"))
            self._pin_tag(ax, ay, ad, apin, self._tag(a, anchor_pin, apin))
            dests = []
            for iid, pname in nodes[1:]:
                inst = self.instances[iid]
                x, y, d, pin = inst.pin(pname)
                dests.append((abs(x - lane_x), x, y, d, pin, inst, pname))
            dests.sort()
            for k, (_, x, y, d, pin, inst, pname) in enumerate(dests):
                pts = [(lane_x, lane), (x, lane), step((x, y), d, STUB), (x, y)]
                self._wire(pts, color, dash=net.get("dash"))
                if k < len(dests) - 1:
                    self._dot(x, lane, color)
                self._pin_tag(x, y, d, pin, self._tag(inst, pname, pin))

        elif template == "direct":
            for iid, pname in nodes[1:]:
                inst = self.instances[iid]
                x, y, d, pin = inst.pin(pname)
                b1 = step((x, y), d, STUB)
                if ad in ("up", "down") and d in ("up", "down"):
                    pts = [(ax, ay), a1, (ax, lane), (x, lane), b1, (x, y)]
                else:
                    pts = [(ax, ay), a1, (x, a1[1]), b1, (x, y)]
                self._wire(pts, color, dash=net.get("dash"))
                self._pin_tag(x, y, d, pin, self._tag(inst, pname, pin))
            self._pin_tag(ax, ay, ad, apin, self._tag(a, anchor_pin, apin))
        else:
            raise ValueError(f"未知布线模板: {template}")

        self.legend_items.append(
            (color, net.get("label", net["id"]),
             net.get("desc", " + ".join(f"{i}.{p}" for i, p in nodes)))
        )

    def _tag(self, inst, pname, pin):
        """板上引脚的标注：丝印名与 GPIO 号不同则并列显示，相同则只显示 GPIO 号。"""
        label = pin.get("label", pname)
        gpio = pin.get("gpio")
        if gpio is None:
            return label
        return f"GPIO{gpio}" if label == str(gpio) else f"{label} · GPIO{gpio}"

    def _pin_tag(self, x, y, d, pin, text):
        """只在开发板引脚处标注「丝印名 · GPIO号」——模块侧已有板上丝印，不重复标注"""
        if pin.get("row") is None and pin.get("gpio") is None:
            return
        self._tags.append((x, y, d, text))

    def _draw_captions(self):
        for inst in self.instances.values():
            x0, y0, x1, y1 = inst.box
            if not inst.caption:
                continue
            if inst.caption_xy:
                self.s.text(inst.caption_xy[0], inst.caption_xy[1], inst.caption,
                            size=13, fill="#20262E", anchor=inst.caption_anchor,
                            weight="800", halo="#FFFFFF")
            elif inst.caption_pos == "above":
                cx = x0 + (x1 - x0) * 0.32
                self.s.text(cx, y0 - 14, inst.caption, size=13, fill="#20262E",
                            anchor="middle", weight="800", halo="#FFFFFF")
            else:
                self.s.text((x0 + x1) / 2, y1 + 24, inst.caption, size=12.5,
                            fill="#20262E", anchor="middle", weight="700", halo="#FFFFFF")

    def _draw_legend(self):
        items = self.legend_items
        if not items:
            return
        y0 = self.spec.get("legend_y", self.legend_y0)
        self.s.text(40, y0 - 28, "导线颜色对照表", size=15, fill="#14181D",
                    anchor="start", weight="800")
        col_w = (self.W - 80) / 2
        for i, (c, lab, desc) in enumerate(items):
            col, row = divmod(i, math.ceil(len(items) / 2))
            x = 40 + col * col_w
            y = y0 + row * 30
            self.s.add(f'<path d="M {x} {y} H {x+34}" fill="none" stroke="{c}" '
                       f'stroke-width="7" stroke-linecap="round"/>')
            self.s.text(x + 46, y + 5, lab, size=12.5, fill="#1F252C", anchor="start",
                        weight="700")
            if desc:
                self.s.text(x + 46 + len(lab) * 8.4 + 12, y + 5, desc, size=11,
                            fill="#78828C", anchor="start", weight="500")

    def _draw_notes(self):
        y = getattr(self, "notes_y0", self.H - 30)
        for i, n in enumerate(self.spec["notes"]):
            self.s.text(40, y + i * 20, "· " + n, size=11, fill="#78828C",
                        anchor="start", weight="500")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.spec, encoding="utf8") as f:
        spec = json.load(f)
    b = WiringBuilder(spec)
    svg = b.build().render(aria=spec.get("title", "接线图"))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf8") as f:
        f.write(svg)
    print(f"✓ 接线图 -> {args.out}  ({spec['canvas'][0]}×{spec['canvas'][1]} 单位)")
    n_inst = len(spec.get("instances", [])) + sum(
        len(v) for v in spec.get("groups", {}).values())
    print(f"  元件 {n_inst} 个 / 网络 {len(spec['nets'])} 条")


if __name__ == "__main__":
    main()
