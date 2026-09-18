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

# two_sided 模式的间距常量。**任何两条不同网络的线都不允许共用同一坐标**，
# 空间不够时由 _plan_fans 自动把元件推远、把画布加高，而不是压缩这些间距。
LANE_GAP = 26.0    # 相邻水平通道的间距
NECK_HEAD = 18.0   # 板边颈区里第一个绕行拐点距板边的距离
NECK_GAP = 17.0    # 颈区里相邻绕行拐点的间距
CHAN_HEAD = 30.0   # 颈区之外，第一条水平通道再让出的距离
WRAP_GAP = 19.0    # 跨侧绕行时相邻竖直车道（板子短边外侧）的间距
SIDE_MARGIN = 42.0 # 最内侧绕行车道距板子短边的余量
CLEARANCE = 26.0   # 最外侧通道/拐点与元件外框之间保留的安全距离
SEP_X = 16.0       # 两条竖线横向近于此值就视为「会并线」，必须错开

# rails（旧版总线轨）模式：落轨的竖线若正好落在开发板横向范围内，直上直下会从板体
# 里穿过去。这时先横挪到板子短边外侧，再竖直落到轨上。
RAIL_MARGIN = 46.0 # 绕板落轨车道距板子短边的余量
RAIL_GAP = 24.0    # 相邻绕板落轨车道的间距
ROW_STEP = 6.0     # 绕板时逐行试探横挪位置的步长（细一点才躲得开信号走线）


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
        self.caption_pos_explicit = "caption_pos" in spec
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
        # data-box 记下「这一刻真正画上去的坐标」。check_wiring.py 会拿它跟
        # --debug-json 里的外框对照 —— 只要谁在落图之后又动了元件，立刻就露馅。
        x0, y0, x1, y1 = self.box
        tag = (f'data-inst="{esc(self.id)}" '
               f'data-box="{x0:.2f},{y0:.2f},{x1:.2f},{y1:.2f}"')
        if self.rot:
            cx, cy = self.x + self.w_px / 2, self.y + self.h_px / 2
            return (f'<g {tag} transform="translate({tx:.1f},{ty:.1f}) rotate({self.rot:.1f} '
                    f'{cx - tx:.1f} {cy - ty:.1f})">{inner}</g>')
        return f'<g {tag} transform="translate({tx:.1f},{ty:.1f})">{inner}</g>'


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
        self.wire_log = []          # 每条导线的折线，供 check_wiring.py 做数值自检
        # spec 里写死的竖直信号车道（wrap_top 的 lane_x），绕板落轨时不许占用
        self._reserved_x = [float(n["lane_x"]) for n in spec.get("nets", [])
                            if n.get("lane_x")]
        self.debug = spec.get("debug", False)
        # 布局自动判断：给了分组与开发板就走 two_sided（通道规划更完善），否则退回 rails
        self.layout = spec.get("layout") or (
            "two_sided" if (spec.get("board_id") or spec.get("groups")) else "rails")
        # two_sided：元件分组与开发板实例
        self.groups = spec.get("groups", {})
        self.side_of = {}
        for side, lst in self.groups.items():
            for isp in lst:
                self.side_of[isp["id"]] = side
        bid = spec.get("board_id")
        self.board = self.instances[bid] if bid in self.instances else None
        if self.board is None:
            # 没写 board_id 时把开发板认出来：板引脚带 row 字段（"A"/"B" 排），模块没有
            for inst in self.instances.values():
                if any(p.get("row") for p in inst.part.pins.values()):
                    self.board = inst
                    break

    # ---------- 元素
    def _wire(self, pts, color, dash=None, width=WIRE_W, net=None):
        pts = clean(pts)
        if len(pts) < 2:
            return
        self.wire_log.append({"net": net, "color": color, "w": width,
                              "dash": bool(dash), "pts": [[round(p[0], 2), round(p[1], 2)]
                                                          for p in pts]})
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
        if self.layout == "two_sided":
            # 先规划、再落图：_plan_fans() 会为了腾出通道把元件整体下移、把画布加高，
            # 必须在这之后再 embed()，否则元件画在旧坐标、导线却按新坐标走，
            # 线头会悬在元件外面（竖直方向整整差出一个通道带的距离）。
            self._plan_fans()
        for inst in self.instances.values():
            self.s.add(inst.embed())
        if self.layout == "two_sided":
            for net in spec["nets"]:
                self._route_fan_net(net)
        else:
            self._draw_rails()
            # 先画信号线、再画电源线：绕板落轨时要躲开信号走线，得先知道它们在哪
            for net in spec["nets"]:
                if not net.get("rail"):
                    self._route_signal_net(net)
            for net in spec["nets"]:
                if net.get("rail"):
                    self._route_rail_net(net)
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
        """把图例与注释紧接在内容下方排好，画布高度按实际内容收紧。

        规则（自上而下）：内容底边 → 图例标题 → 图例各行 → 注释各行 → 画布底。
        页脚**跟着内容走**，而不是钉在画布底部 —— 否则元件被推远后下面会空一大块，
        或者 `legend_y` 写死时图例直接压到元件上。
        """
        self.legend_items = self._dedup_legend()
        notes = self.spec.get("notes", [])
        rows = math.ceil(len(self.legend_items) / 2) if self.legend_items else 0
        pad = 24

        bottom = max([self._eff_box(i)[3] for i in self.instances.values()] or [0.0])
        self.legend_y0 = bottom + 56 + 26                     # 首行（标题另占 26）
        last_legend = self.legend_y0 + (rows - 1) * 30 if rows else self.legend_y0 - 26
        self.notes_y0 = last_legend + (40 if notes else 0)
        tail = self.notes_y0 + (len(notes) - 1) * 20 if notes else last_legend
        self.H = math.ceil(tail + pad)
        self.s.h = self.H

    # =====================================================================
    # two_sided 布局：元件均分在开发板两侧，供电/接地直接回到板上引脚
    # =====================================================================
    def _eff_box(self, inst):
        """含 SVG 留白的实际占位盒（px）"""
        pad = inst.pad * MM
        return (inst.x - pad, inst.y - pad,
                inst.x + inst.w_px + pad, inst.y + inst.h_px + pad)

    def _plan_fans(self):
        """规划「空间 + 水平通道 + 跨侧绕行车道」。

        三条硬约束，保证任意两条**不同网络**的线都不重合、不贴身：
        ① 每个「网络 × 有落点的那一侧」独占一条水平通道 y；
        ② 跨侧绕行时，每条网络**独占**一个拐点 y（板边颈区）与一条竖直车道 x
           —— 旧版所有跨侧网络共用同一个 x / y，线必然叠在一起；
        ③ 空间不够就把元件推远、画布加高，绝不压缩间距硬塞。
        """
        if self.board is None:
            raise KeyError("two_sided 布局需要 board_id 指向开发板实例")

        self._survey_nets()

        # ---- ① 先把空间撑到够用 ----
        for _ in range(4):
            self._compute_bands()
            d_top = self._need("top") - (self.board_box[1] - self.band_top_lo)
            d_bot = self._need("bottom") - (self.band_bot_hi - self.board_box[3])
            if d_top < 1 and d_bot < 1:
                break
            if d_top >= 1:
                # 上组元件不动，其余整体下移，画布同步加高 —— 上方净空净增 d
                d = math.ceil(d_top)
                for iid, inst in self.instances.items():
                    if self.side_of.get(iid) != "top":
                        inst.y += d
                self.H += d
                self.s.h = self.H
            if d_bot >= 1:
                # 下组元件继续往下推
                d = math.ceil(d_bot)
                for iid, s in self.side_of.items():
                    if s == "bottom":
                        self.instances[iid].y += d
                self.H += d
                self.s.h = self.H
        self._compute_bands()
        bx0, by0, bx1, by1 = self.board_box

        # ---- ② 跨侧绕行：每条网络独占拐点 y 与竖直车道 x ----
        self.neck_y, self.wrap_x = {}, {}
        plan = {"left": [], "right": []}
        for net in self.spec["nets"]:
            nid = net["id"]
            if nid not in self.home_of:
                continue
            home = self.home_of[nid]
            ax = self.instances[net["nodes"][0][0]].pin(net["nodes"][0][1])[0]
            for side in sorted(self.sides_of[nid] - {home}):
                g = "left" if abs(ax - bx0) <= abs(ax - bx1) else "right"
                plan[g].append((side, nid, ax, home))

        for gside, lst in plan.items():
            edge_x = bx0 if gside == "left" else bx1
            sign = -1 if gside == "left" else 1
            lst.sort(key=lambda t: abs(t[2] - edge_x))     # 锚点越靠板边 → 车道越靠内
            used = {}                                      # home 侧 -> 颈区档位
            for k, (side, nid, _ax, home) in enumerate(lst):
                self.wrap_x[(nid, side)] = edge_x + sign * (SIDE_MARGIN + k * WRAP_GAP)
                idx = used.get(home, 0)
                used[home] = idx + 1
                # 车道越靠外，拐点离板越远 —— 否则外层车道会切到内层的水平段
                self.neck_y[(nid, side)] = (
                    by0 - NECK_HEAD - idx * NECK_GAP if home == "top"
                    else by1 + NECK_HEAD + idx * NECK_GAP)

        # ---- ③ 水平通道：跨度大的靠板，并消解「干线压落线」的贴线冲突 ----
        spans = {"top": [], "bottom": []}
        for net in self.spec["nets"]:
            nid = net["id"]
            if nid not in self.home_of:
                continue
            ax = self.instances[net["nodes"][0][0]].pin(net["nodes"][0][1])[0]
            for side in ("top", "bottom"):
                if side not in self.sides_of[nid]:
                    continue
                ds = [self.instances[i].pin(p)[0]
                      for i, p in net["nodes"][1:] if self.side_of.get(i) == side]
                spans[side].append((nid, max([ax] + ds) - min([ax] + ds)))

        self.lane_of, self.lane_y = {"top": {}, "bottom": {}}, {"top": {}, "bottom": {}}
        for side in ("top", "bottom"):
            sign = -1 if side == "top" else 1
            edge = by0 if side == "top" else by1
            neck_h = (NECK_HEAD + max(0, self.n_neck[side] - 1) * NECK_GAP) \
                if self.n_neck[side] else 0.0
            base = edge + sign * (neck_h + CHAN_HEAD)      # 通道让开颈区
            for k, nid in enumerate(self._order_lanes(side, spans[side], base, sign)):
                self.lane_of[side][nid] = k
                self.lane_y[side][nid] = base + sign * k * LANE_GAP

    # ---------- 通道排序与贴线消解
    def _order_lanes(self, side, items, base, sign):
        """先按「跨度大靠板」初排，再把「干线压到别家落线」的网络往前挪。

        几何由来：干线竖线画在板引脚（或绕行车道）的 x 上，落线竖线画在元件焊盘的 x 上。
        两者横向一旦过近、y 区间又相交，就会并成一根双色线。
        而干线的 y 区间是 [通道…板引脚]、落线是 [焊盘…通道]，
        两者相交**当且仅当干线所属网络排在更外侧** —— 所以消解办法就是把它挪到更靠板的位置。
        """
        order = [nid for nid, _ in sorted(items, key=lambda t: -t[1])]
        for _ in range(30):
            lane_y = {nid: base + sign * k * LANE_GAP for k, nid in enumerate(order)}
            clash = self._first_lane_clash(side, order, lane_y)
            if not clash:
                break
            a, b = clash
            i, j = order.index(a), order.index(b)
            order[i], order[j] = order[j], order[i]
        return order

    def _trunk_iv(self, side, nid, lane_y):
        """该网络在这一侧的干线竖线（x, y0, y1）"""
        if self.home_of.get(nid) == side:
            a_id, a_pin = self._nets[nid]["nodes"][0]
            x, y, _, _ = self.instances[a_id].pin(a_pin)
        else:
            key = (nid, side)
            if key not in self.wrap_x:
                return None
            x, y = self.wrap_x[key], self.neck_y[key]
        ly = lane_y[nid]
        return (x, min(y, ly), max(y, ly))

    def _drop_ivs(self, side, nid, lane_y):
        """该网络在这一侧各落点竖线（焊盘 x, y0, y1）"""
        ly = lane_y[nid]
        out = []
        for i, p in self._nets[nid]["nodes"][1:]:
            if self.side_of.get(i) != side:
                continue
            x, y, _, _ = self.instances[i].pin(p)
            out.append((x, min(y, ly), max(y, ly)))
        return out

    def _first_lane_clash(self, side, order, lane_y):
        """找出第一处「干线竖线压到别家落线竖线」的冲突 (A, B)；无则 None"""
        for a in order:
            t = self._trunk_iv(side, a, lane_y)
            if t is None:
                continue
            tx, ty0, ty1 = t
            for b in order:
                if b == a:
                    continue
                a_closer = (lane_y[a] > lane_y[b]) if side == "top" else (lane_y[a] < lane_y[b])
                if a_closer:
                    continue                      # 干线已在内侧，y 区间不会相交
                for dx, dy0, dy1 in self._drop_ivs(side, b, lane_y):
                    if abs(tx - dx) >= SEP_X:
                        continue
                    if min(ty1, dy1) - max(ty0, dy0) > 4.0:
                        return (a, b)
        return None

    # ---------- 空间测算
    def _compute_bands(self):
        """板子外框与上下两组元件的边界"""
        self.board_box = self._eff_box(self.board)
        by0, by1 = self.board_box[1], self.board_box[3]
        tops = [i for i, s in self.side_of.items() if s == "top"]
        bots = [i for i, s in self.side_of.items() if s == "bottom"]
        self.band_top_lo = max((self._eff_box(self.instances[i])[3] for i in tops),
                               default=by0 - 240)          # 上组下沿
        self.band_bot_hi = min((self._eff_box(self.instances[i])[1] for i in bots),
                               default=by1 + 240)          # 下组上沿

    def _survey_nets(self):
        """统计每条网络的 home 侧与落点侧，以及两侧各需要多少条通道 / 颈位"""
        self.home_of, self.sides_of = {}, {}
        self._nets = {n["id"]: n for n in self.spec["nets"]}
        for net in self.spec["nets"]:
            nodes = net["nodes"]
            if len(nodes) < 2:
                continue
            a_id, a_pin = nodes[0]
            home = "top" if self.instances[a_id].pin(a_pin)[2] == "up" else "bottom"
            self.home_of[net["id"]] = home
            self.sides_of[net["id"]] = {self.side_of.get(i, home) for i, _ in nodes[1:]}
        self.n_chan = {s: sum(1 for v in self.sides_of.values() if s in v)
                       for s in ("top", "bottom")}
        self.n_neck = {s: sum(1 for nid, hm in self.home_of.items()
                              if hm == s and (self.sides_of[nid] - {s}))
                       for s in ("top", "bottom")}

    def _need(self, side):
        """该侧从板边到元件之间所需的竖直净空（颈区 + 通道 + 安全距离）"""
        h = 0.0
        if self.n_neck[side]:
            h += NECK_HEAD + (self.n_neck[side] - 1) * NECK_GAP
        if self.n_chan[side]:
            h += CHAN_HEAD + (self.n_chan[side] - 1) * LANE_GAP
        return h + CLEARANCE

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
                # 绕过板子短边：走本网络独占的拐点 y 与竖直车道 x
                ny = self.neck_y[(net["id"], side)]
                sx = self.wrap_x[(net["id"], side)]
                trunk = [(bx, by), b1, (bx, ny), (sx, ny), (sx, lane_y)]
            self._wire(trunk, color, dash=dash, net=net["id"])
            branches += 1

            ordered = sorted(dests, key=lambda t: self.instances[t[0]].pin(t[1])[0])
            for k, (iid, pname) in enumerate(ordered):
                inst = self.instances[iid]
                x, y, d, pin = inst.pin(pname)
                # 从干线与通道的交点出发 → 水平到分支 x → 竖向进入焊盘
                pts = [trunk[-1], (x, lane_y), step((x, y), d, STUB), (x, y)]
                self._wire(pts, color, dash=dash, net=net["id"])
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

    def _lane_free(self, x, y0, y1):
        """这条竖直车道 (x, y0→y1) 能不能用：不并到已画的竖线上，也不从别的元件身上过"""
        lo, hi = min(y0, y1), max(y0, y1)
        if any(abs(x - rx) < SEP_X for rx in self._reserved_x):
            return False                                  # spec 里写死的信号车道，先占住
        for w in self.wire_log:
            for a, b in zip(w["pts"], w["pts"][1:]):
                if abs(a[0] - b[0]) > 0.8:            # 只看竖直段
                    continue
                if abs(a[0] - x) >= SEP_X:
                    continue
                if min(hi, max(a[1], b[1])) - max(lo, min(a[1], b[1])) > 4.0:
                    return False
        for inst in self.instances.values():
            x0, by0, x1, by1 = self._eff_box(inst)
            if x0 + 4 < x < x1 - 4 and min(hi, by1) - max(lo, by0) > 20.0:
                return False
        return True

    def _seg_clash(self, f, lo, hi, kind, skip_net=None):
        """已画的线里有没有跟 [lo,hi] 这段「平行且过近」的：kind='v' 比 x，'h' 比 y"""
        for w in self.wire_log:
            if skip_net is not None and w["net"] == skip_net:
                continue
            for a, b in zip(w["pts"], w["pts"][1:]):
                if kind == "v":
                    if abs(a[0] - b[0]) > 0.8:
                        continue
                    v, s_lo, s_hi = a[0], min(a[1], b[1]), max(a[1], b[1])
                else:
                    if abs(a[1] - b[1]) > 0.8:
                        continue
                    v, s_lo, s_hi = a[1], min(a[0], b[0]), max(a[0], b[0])
                if abs(v - f) >= SEP_X:
                    continue
                if min(hi, s_hi) - max(lo, s_lo) > 4.0:
                    return True
        return False

    def _rail_lane_cands(self, box):
        """板外的绕行车道候选 x（左右两侧交替，由近及远）"""
        bx0, _, bx1, _ = box
        out = []
        for k in range(24):
            out.append((bx0 - RAIL_MARGIN - k * RAIL_GAP, bx1 + RAIL_MARGIN + k * RAIL_GAP))
        return [v for pair in out for v in pair]

    def _detour_rail(self, x, sy, ry, box, net_id):
        """让落轨线绕开板体：在板外的空当里挑一行横挪，再沿板边竖直落到轨上。

        逐步放宽着试，一找到就走：
          ① 短竖线的 x 先按焊盘原位置试，不行再小幅横挪（躲开正好压在附近的板引脚走线）；
          ② 横挪那一行从最靠近焊盘的一行开始，逐行往里试；
          ③ 绕行车道左右都试，离得近的优先，且不许走回头路。
        全部试不出干净路径时才退回直落（并会被 check_wiring.py 报出来）。
        """
        below = sy > box[3]
        limit = box[3] + CLEARANCE if below else box[1] - CLEARANCE
        sgn = -1 if below else 1
        n_row = max(int(abs(sy - limit) / ROW_STEP), 0)
        for xs in [x, x - 9, x + 9, x - 18, x + 18]:
            jog = abs(xs - x) > 0.5
            if jog and self._seg_clash(sy, min(x, xs), max(x, xs), "h", net_id):
                continue
            for k in range(n_row + 1):
                row = sy + sgn * k * ROW_STEP
                if self._seg_clash(xs, min(row, sy), max(row, sy), "v", net_id):
                    continue
                for dx in sorted(self._rail_lane_cands(box), key=lambda v: abs(v - xs)):
                    if jog and (dx - xs) * (x - xs) > 0:
                        continue                      # 横挪之后别又拐回去
                    if not self._lane_free(dx, min(row, ry), max(row, ry)):
                        continue
                    if self._seg_clash(row, min(xs, dx), max(xs, dx), "h", net_id):
                        continue
                    pts = [(x, sy)]
                    if jog:
                        pts.append((xs, sy))
                    return pts + [(xs, row), (dx, row), (dx, ry)]
        return [(x, ry)]

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
                box = self._eff_box(self.board) if (
                    self.board is not None and iid != self.board.id) else None
                sy = pts[-1][1]
                y_lo, y_hi = min(ry, sy), max(ry, sy)
                cross = (box and box[0] < x < box[2]
                         and min(y_hi, box[3]) - max(y_lo, box[1]) > 0)
                pts += (self._detour_rail(x, sy, ry, box, net["id"]) if cross
                        else [(x, ry)])
            self._wire(pts, color, net=net.get("id"))
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
            self._wire([(ax, ay), a1, (ax, lane)], color, net=net.get("id"))
            self._pin_tag(ax, ay, ad, apin, self._tag(a, anchor_pin, apin))
            dests = []
            for iid, pname in nodes[1:]:
                inst = self.instances[iid]
                x, y, d, pin = inst.pin(pname)
                dests.append((abs(x - ax), x, y, d, pin, inst, pname))
            dests.sort()
            for k, (_, x, y, d, pin, inst, pname) in enumerate(dests):
                self._wire([(ax, lane), (x, lane), step((x, y), d, STUB), (x, y)], color,
                           net=net.get("id"))
                if k < len(dests) - 1:            # 不是最后一个分支 => 需要汇流点
                    self._dot(x, lane, color)
                self._pin_tag(x, y, d, pin, self._tag(inst, pname, pin))
            self._dot(ax, lane, color) if len(dests) > 0 else None

        elif template == "wrap_top":
            # 锚点在开发板「上排」，需绕到板外车道再下行
            lane_x = net["lane_x"]
            top_y = net.get("top_y", 250)
            self._wire([(ax, ay), a1, (ax, top_y), (lane_x, top_y), (lane_x, lane)],
                       color, dash=net.get("dash"), net=net.get("id"))
            self._pin_tag(ax, ay, ad, apin, self._tag(a, anchor_pin, apin))
            dests = []
            for iid, pname in nodes[1:]:
                inst = self.instances[iid]
                x, y, d, pin = inst.pin(pname)
                dests.append((abs(x - lane_x), x, y, d, pin, inst, pname))
            dests.sort()
            for k, (_, x, y, d, pin, inst, pname) in enumerate(dests):
                pts = [(lane_x, lane), (x, lane), step((x, y), d, STUB), (x, y)]
                self._wire(pts, color, dash=net.get("dash"), net=net.get("id"))
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
                self._wire(pts, color, dash=net.get("dash"), net=net.get("id"))
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
            pos = inst.caption_pos
            if self.layout == "two_sided" and not inst.caption_pos_explicit:
                # 标题一律朝外：走线带在板与元件之间，标题留在外面才不会被竖线穿过
                pos = "above" if self.side_of.get(inst.id) == "top" else "below"
            if inst.caption_xy:
                self.s.text(inst.caption_xy[0], inst.caption_xy[1], inst.caption,
                            size=13, fill="#20262E", anchor=inst.caption_anchor,
                            weight="800", halo="#FFFFFF")
            elif pos == "above":
                self.s.text((x0 + x1) / 2, y0 - 14, inst.caption, size=13,
                            fill="#20262E", anchor="middle", weight="800", halo="#FFFFFF")
            else:
                self.s.text((x0 + x1) / 2, y1 + 24, inst.caption, size=12.5,
                            fill="#20262E", anchor="middle", weight="700", halo="#FFFFFF")

    def _draw_legend(self):
        items = self.legend_items
        if not items:
            return
        # 自动排好的位置是下界：spec 里的 legend_y 只能把图例再往下推，不能压到元件上
        y0 = max(self.legend_y0, float(self.spec.get("legend_y") or 0.0))
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
    ap.add_argument("--debug-json", help="把布线折线与元件外框导出成 JSON，供 check_wiring.py 自检")
    args = ap.parse_args()

    with open(args.spec, encoding="utf8") as f:
        spec = json.load(f)
    b = WiringBuilder(spec)
    svg = b.build().render(aria=spec.get("title", "接线图"))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf8") as f:
        f.write(svg)

    if args.debug_json:
        boxes = {}
        for iid, inst in b.instances.items():
            boxes[iid] = {"part": inst.part.pid, "box": [round(v, 2) for v in inst.box],
                          "side": b.side_of.get(iid, "board"),
                          "pins": {k: [round(v[0], 2), round(v[1], 2), v[2]]
                                   for k, v in ((n, inst.pin(n)) for n in inst.part.pins)}}
        with open(args.debug_json, "w", encoding="utf8") as f:
            json.dump({"canvas": [b.W, b.H], "boxes": boxes, "wires": b.wire_log},
                      f, ensure_ascii=False, indent=1)
        print(f"  布线日志 -> {args.debug_json}  ({len(b.wire_log)} 段折线)")

    print(f"✓ 接线图 -> {args.out}  ({b.W}×{b.H} 单位)")
    n_inst = len(spec.get("instances", [])) + sum(
        len(v) for v in spec.get("groups", {}).values())
    print(f"  元件 {n_inst} 个 / 网络 {len(spec['nets'])} 条")


if __name__ == "__main__":
    main()
