#!/usr/bin/env python3
"""
fritzing_kit.py — Fritzing Parts 风格的 SVG 绘图工具箱（无第三方依赖）

设计要点
--------
1. **用毫米作图**：所有坐标/尺寸都用真实物理尺寸（mm）书写，渲染时统一乘以 MM 系数，
   这样元件的比例天然正确，也便于把「实际尺寸」作为布局依据。
2. **风格对齐 Fritzing breadboard view**：正交俯视、纯平色块、比底色略深的描边、
   白色丝印文字、白色/金色安装孔、黑色排针塑料体 + 金色针脚。不加渐变与投影（参考
   Fritzing Parts 库的观感）。
3. **图元即零件**：pcb / header / chip / mic_can / trimpot / tactile / usb_c / led /
   passive / via / mount_hole 等，覆盖常见模块的构成要素。

单位约定：1mm = 10 用户单位（MM=10）。描边 0.15~0.25mm，丝印字高 1.2~1.8mm。
"""

from __future__ import annotations

import math

MM = 10.0  # 1mm = 10 SVG 用户单位

# ---------------------------------------------------------------- 调色板
C = {
    "silk": "#FFFFFF",
    "silk_dim": "#C9CDD2",
    "pcb_black": "#141618",
    "pcb_black_edge": "#08090A",
    "pcb_blue": "#1B5FA8",
    "pcb_blue_edge": "#123F70",
    "pcb_navy": "#123C6B",
    "pcb_navy_edge": "#0A2647",
    "pcb_green": "#12803C",
    "pcb_green_edge": "#0A5827",
    "pcb_red": "#C22B22",
    "pcb_red_edge": "#8A1A14",
    "pcb_purple": "#2A2430",
    "gold": "#D4A72C",
    "gold_dark": "#A97F1B",
    "silver": "#C6C9CC",
    "silver_dark": "#9BA0A5",
    "plastic": "#191B1D",
    "plastic_hi": "#2A2D30",
    "blue_trimpot": "#2B5CB8",
    "blue_trimpot_edge": "#1B3E82",
    "led_red": "#E23B2E",
    "led_green": "#33C24A",
    "led_off": "#EDEFF2",
    "hole": "#FFFFFF",
}

FONT = (
    "ui-sans-serif,-apple-system,BlinkMacSystemFont,'Helvetica Neue',"
    "'PingFang SC','Microsoft YaHei',Arial,sans-serif"
)


def _n(v: float) -> str:
    """数字格式化：去掉多余小数，减小文件体积"""
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return s if s not in ("-0", "") else "0"


def darken(hex_color: str, factor: float = 0.72) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    r, g, b = (max(0, min(255, int(c * factor))) for c in (r, g, b))
    return f"#{r:02X}{g:02X}{b:02X}"


def lighten(hex_color: str, factor: float = 0.25) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    r, g, b = (max(0, min(255, int(c + (255 - c) * factor))) for c in (r, g, b))
    return f"#{r:02X}{g:02X}{b:02X}"


# ---------------------------------------------------------------- SVG 画布
class Svg:
    """以毫米为单位的 SVG 画布。调用 render() 得到完整 <svg> 字符串。

    若整张图改用像素/自定义坐标作图，传入 unit=1.0 即可关闭 mm→unit 的换算。
    """

    def __init__(self, w_mm: float, h_mm: float, pad_mm: float = 1.0, bg: str | None = None,
                 unit: float = MM):
        self.w = w_mm
        self.h = h_mm
        self.pad = pad_mm
        self.bg = bg
        self.u = unit
        self._body: list[str] = []

    # ---- 基础
    def add(self, s: str):
        self._body.append(s)
        return self

    def group(self, content: list[str] | str, cls: str = "", transform: str = ""):
        inner = content if isinstance(content, str) else "\n".join(content)
        attrs = ""
        if cls:
            attrs += f' class="{cls}"'
        if transform:
            attrs += f' transform="{transform}"'
        self._body.append(f"<g{attrs}>\n{inner}\n</g>")
        return self

    def _common(self, fill, stroke, sw, opacity):
        a = f'fill="{fill}"' if fill else 'fill="none"'
        if stroke:
            a += f' stroke="{stroke}" stroke-width="{_n(sw * self.u)}" stroke-linejoin="round"'
        if opacity is not None:
            a += f' opacity="{_n(opacity)}"'
        return a

    # ---- 形状
    def rect(self, x, y, w, h, r=0.0, fill="#000", stroke=None, sw=0.18, opacity=None, extra=""):
        self._body.append(
            f'<rect x="{_n(x*self.u)}" y="{_n(y*self.u)}" width="{_n(w*self.u)}" height="{_n(h*self.u)}"'
            f' rx="{_n(r*self.u)}" ry="{_n(r*self.u)}" {self._common(fill, stroke, sw, opacity)} {extra}/>'
        )
        return self

    def circle(self, cx, cy, r, fill="#000", stroke=None, sw=0.18, opacity=None):
        self._body.append(
            f'<circle cx="{_n(cx*self.u)}" cy="{_n(cy*self.u)}" r="{_n(r*self.u)}" '
            f'{self._common(fill, stroke, sw, opacity)}/>'
        )
        return self

    def ellipse(self, cx, cy, rx, ry, fill="#000", stroke=None, sw=0.18, opacity=None):
        self._body.append(
            f'<ellipse cx="{_n(cx*self.u)}" cy="{_n(cy*self.u)}" rx="{_n(rx*self.u)}" ry="{_n(ry*self.u)}" '
            f'{self._common(fill, stroke, sw, opacity)}/>'
        )
        return self

    def path(self, d_mm: str, fill="#000", stroke=None, sw=0.18, opacity=None, extra=""):
        self._body.append(
            f'<path d="{d_mm}" {self._common(fill, stroke, sw, opacity)} {extra}/>'
        )
        return self

    def path_pts(self, pts, fill="#000", stroke=None, sw=0.18, close=True, opacity=None):
        d = "M " + " L ".join(f"{_n(x*self.u)},{_n(y*self.u)}" for x, y in pts) + (" Z" if close else "")
        return self.path(d, fill, stroke, sw, opacity)

    def line(self, x1, y1, x2, y2, stroke="#fff", sw=0.18, dash=None, cap="round",
             opacity=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        o = f' opacity="{_n(opacity)}"' if opacity is not None else ""
        self._body.append(
            f'<line x1="{_n(x1*self.u)}" y1="{_n(y1*self.u)}" x2="{_n(x2*self.u)}" y2="{_n(y2*self.u)}" '
            f'stroke="{stroke}" stroke-width="{_n(sw*self.u)}" stroke-linecap="{cap}"{d}{o}/>'
        )
        return self

    def text(self, x, y, s, size=1.5, fill=None, anchor="middle", rot=0, weight="600",
             family=None, opacity=None, spacing=None, halo=None):
        fill = fill or C["silk"]
        t = f' transform="rotate({_n(rot)} {_n(x*self.u)} {_n(y*self.u)})"' if rot else ""
        o = f' opacity="{_n(opacity)}"' if opacity is not None else ""
        sp = f' letter-spacing="{_n(spacing*self.u)}"' if spacing else ""
        h = (f' paint-order="stroke" stroke="{halo}" stroke-width="{_n(size*0.34*self.u)}" '
             f'stroke-linejoin="round"') if halo else ""
        self._body.append(
            f'<text x="{_n(x*self.u)}" y="{_n(y*self.u)}" font-family="{family or FONT}" '
            f'font-size="{_n(size*self.u)}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}"{t}{o}{sp}{h}>{esc(s)}</text>'
        )
        return self

    def arc_text(self, cx, cy, r, text, size=1.2, fill=None, start_deg=200, end_deg=340, flip=False):
        """沿圆弧排布的文字（用于 PulseSensor 那种环形丝印）"""
        n = max(1, len(text) - 1)
        for i, ch in enumerate(text):
            a = math.radians(start_deg + (end_deg - start_deg) * i / n)
            x = cx + r * math.cos(a)
            y = cy + r * math.sin(a)
            rot = math.degrees(a) + (90 if not flip else -90)
            self.text(x, y, ch, size=size, fill=fill, anchor="middle", rot=rot)
        return self

    def render(self, extra_defs: str = "", aria: str = "") -> str:
        w = (self.w + self.pad * 2) * self.u
        h = (self.h + self.pad * 2) * self.u
        bg = f'<rect width="{_n(w)}" height="{_n(h)}" fill="{self.bg}"/>' if self.bg else ""
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_n(w)} {_n(h)}" '
            f'width="{_n(w)}" height="{_n(h)}" role="img" aria-label="{esc(aria)}">\n'
            f"<defs>{extra_defs}</defs>\n{bg}\n"
            f'<g transform="translate({_n(self.pad*self.u)},{_n(self.pad*self.u)})">\n'
            + "\n".join(self._body)
            + "\n</g>\n</svg>\n"
        )


def esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ---------------------------------------------------------------- 图元


def pcb(s: Svg, x, y, w, h, fill=None, edge=None, r=1.0, holes=None, hole_r=1.05,
        plated=False, inner_rim=False):
    """PCB 板体：圆角矩形 + 深色描边（可带四角安装孔）。"""
    fill = fill or C["pcb_black"]
    edge = edge or darken(fill, 0.55)
    s.rect(x, y, w, h, r=r, fill=fill, stroke=edge, sw=0.22)
    if inner_rim:
        s.rect(x + 0.45, y + 0.45, w - 0.9, h - 0.9, r=max(0, r - 0.3), fill="none",
               stroke=lighten(fill, 0.16), sw=0.14, opacity=0.7)
    for hx, hy in holes or []:
        mount_hole(s, x + hx, y + hy, hole_r, plated=plated)
    return s


def mount_hole(s: Svg, cx, cy, r=1.05, plated=False):
    """安装孔：未镀 = 白孔 + 深色圈；镀金 = 金色环 + 白孔。"""
    if plated:
        s.circle(cx, cy, r + 0.45, fill=C["gold"], stroke=C["gold_dark"], sw=0.16)
    s.circle(cx, cy, r, fill=C["hole"], stroke="#5A5F66", sw=0.18)
    return s


def via(s: Svg, cx, cy, r=0.42):
    s.circle(cx, cy, r + 0.22, fill=C["gold"], stroke=C["gold_dark"], sw=0.1)
    s.circle(cx, cy, r * 0.5, fill="#1B1D1F")
    return s


def pad(s: Svg, cx, cy, r=0.95, hole_r=0.45):
    """通孔焊盘（圆形）"""
    s.circle(cx, cy, r, fill=C["gold"], stroke=C["gold_dark"], sw=0.14)
    s.circle(cx, cy, r * 0.42, fill="#0F1113")
    return s


def header(s: Svg, x, y, n, orient="h", pitch=2.54, body_w=2.54, pins=True,
           body=None, pin_fill=None, square_first=False, pin_len=1.2, socket=False):
    """
    排针 / 排母。
      orient='h'：沿 X 方向排列；'v'：沿 Y 方向。
      socket=True 画成母座（黑体 + 圆孔）；False 画成公针（黑体 + 金方针脚）。
    返回 (第一个针中心坐标, 针间距)。
    """
    body = body or C["plastic"]
    pin_fill = pin_fill or C["gold"]
    total = (n - 1) * pitch + body_w
    if orient == "h":
        s.rect(x, y, total, body_w, r=0.25, fill=body, stroke=darken(body, 0.5), sw=0.16)
        c0 = (x + body_w / 2, y + body_w / 2)
    else:
        s.rect(x, y, body_w, total, r=0.25, fill=body, stroke=darken(body, 0.5), sw=0.16)
        c0 = (x + body_w / 2, y + body_w / 2)

    for i in range(n):
        if orient == "h":
            cx, cy = x + body_w / 2 + i * pitch, y + body_w / 2
        else:
            cx, cy = x + body_w / 2, y + body_w / 2 + i * pitch
        if pins:
            ps = 0.62 if not (square_first and i == 0) else 0.7
            if socket:
                s.circle(cx, cy, 0.62, fill="#0B0C0D", stroke=pin_fill, sw=0.14)
            else:
                s.rect(cx - ps / 2, cy - ps / 2, ps, ps, r=0.08,
                       fill=pin_fill, stroke=darken(pin_fill, 0.6), sw=0.12)
    return c0, pitch


def male_pins_out(s: Svg, x, y, n, orient="h", pitch=2.54, length=1.6, fill=None):
    """在板边外侧画一排「伸出的金属针脚」（breadboard 视角的关键特征）。"""
    fill = fill or C["silver"]
    for i in range(n):
        if orient == "h":
            cx = x + i * pitch
            s.rect(cx - 0.28, y, 0.56, length, r=0.12, fill=fill,
                   stroke=C["silver_dark"], sw=0.12)
        else:
            cy = y + i * pitch
            s.rect(x, cy - 0.28, length, 0.56, r=0.12, fill=fill,
                   stroke=C["silver_dark"], sw=0.12)
    return s


def chip_soic(s: Svg, x, y, w, h, label=None, legs=4, leg_color=None, body="#191B1E",
              label_size=0.72, label_color="#9AA0A6"):
    """SOIC/SOP 贴片芯片：黑色本体 + 两侧银色引脚 + 一脚标记点。"""
    leg_color = leg_color or C["silver"]
    pitch = h / legs
    for i in range(legs):
        ly = y + pitch * (i + 0.5)
        s.rect(x - 0.65, ly - 0.18, 0.75, 0.36, r=0.05, fill=leg_color,
               stroke=C["silver_dark"], sw=0.08)
        s.rect(x + w - 0.1, ly - 0.18, 0.75, 0.36, r=0.05, fill=leg_color,
               stroke=C["silver_dark"], sw=0.08)
    s.rect(x, y, w, h, r=0.18, fill=body, stroke="#0B0C0D", sw=0.14)
    s.circle(x + 0.55, y + 0.55, 0.22, fill="#3A3E44")
    if label:
        s.text(x + w / 2, y + h / 2 + label_size * 0.35, label, size=label_size,
               fill=label_color, weight="700")
    return s


def chip_dip(s: Svg, x, y, w, h, label=None, legs=4, body="#191B1E"):
    """DIP 直插芯片"""
    pitch = h / legs
    for i in range(legs):
        ly = y + pitch * (i + 0.5)
        for dx in (-1.0, 1.0):
            px = x - 1.0 if dx < 0 else x + w
            s.rect(px, ly - 0.2, 1.0, 0.4, r=0.06, fill=C["silver"],
                   stroke=C["silver_dark"], sw=0.1)
    s.rect(x, y, w, h, r=0.3, fill=body, stroke="#0B0C0D", sw=0.16)
    s.path_pts([(x + 1.1, y + 0.75), (x + 2.0, y + 0.75), (x + 1.55, y + 1.5)],
               fill="#0B0C0D", stroke=None, sw=0)
    if label:
        s.text(x + w / 2, y + h / 2 + 0.28, label, size=0.72, fill="#9AA0A6",
               rot=-90, weight="700")
    return s


def chip_qfn(s: Svg, cx, cy, size=4.0, body="#2C2F33", pads=True, label=None,
             exposed=True):
    """QFN/BGA 芯片：方形本体 + 四周引脚 + 中央散热焊盘"""
    if pads:
        for i in range(5):
            off = -size / 2 + size * (i + 0.5) / 5
            for dx, dy, w, h in (
                (off, -size / 2 - 0.42, size / 7, 0.5),
                (off, size / 2 - 0.08, size / 7, 0.5),
                (-size / 2 - 0.42, off, 0.5, size / 7),
                (size / 2 - 0.08, off, 0.5, size / 7),
            ):
                s.rect(cx + dx, cy + dy, w, h, r=0.04, fill=C["silver"],
                       stroke=C["silver_dark"], sw=0.07)
    s.rect(cx - size / 2, cy - size / 2, size, size, r=0.15, fill=body,
           stroke="#101214", sw=0.16)
    if exposed:
        s.rect(cx - size / 4, cy - size / 4, size / 2, size / 2, r=0.1,
               fill="#4A4F55", opacity=0.85)
    if label:
        s.text(cx, cy + 0.5, label, size=0.62, fill="#B9BEC4", weight="700")
    return s


def mic_can(s: Svg, cx, cy, r=4.5, facing="down"):
    """驻极体麦克风（电容咪头）：金属圆柱罐 + 前置黑色毡面"""
    s.circle(cx, cy, r, fill=C["silver"], stroke=C["silver_dark"], sw=0.2)
    s.circle(cx, cy, r * 0.86, fill="#E4E7EA", stroke=C["silver_dark"], sw=0.14)
    s.circle(cx, cy, r * 0.52, fill="#26282B", stroke="#3A3D40", sw=0.12)
    for i in range(12):
        a = math.radians(i * 30)
        s.circle(cx + r * 0.68 * math.cos(a), cy + r * 0.68 * math.sin(a), 0.16,
                 fill="#8E9398")
    return s


def trimpot(s: Svg, x, y, size=5.0, body=None):
    """3296W 蓝色可调电位器：蓝方块 + 十字螺丝槽"""
    body = body or C["blue_trimpot"]
    s.rect(x, y, size, size, r=0.5, fill=body, stroke=C["blue_trimpot_edge"], sw=0.2)
    s.rect(x + 0.35, y + 0.35, size - 0.7, size - 0.7, r=0.4, fill="none",
           stroke=lighten(body, 0.3), sw=0.12, opacity=0.55)
    cx, cy = x + size / 2, y + size / 2
    s.circle(cx, cy, size * 0.22, fill="#DDE3EA", stroke="#8E97A2", sw=0.12)
    s.line(cx - size * 0.16, cy, cx + size * 0.16, cy, stroke="#6B7480", sw=0.22)
    s.line(cx, cy - size * 0.16, cx, cy + size * 0.16, stroke="#6B7480", sw=0.22)
    return s


def tactile(s: Svg, cx, cy, w=4.6, h=3.6, label=None):
    """轻触按键（俯视）：白色/银色胶帽 + 黑色本体"""
    s.rect(cx - w / 2, cy - h / 2, w, h, r=0.35, fill="#0E1012", stroke="#050607", sw=0.16)
    s.circle(cx, cy, min(w, h) * 0.33, fill="#EDEFF1", stroke="#A8AEB4", sw=0.16)
    if label:
        s.text(cx, cy + h / 2 + 1.35, label, size=0.95, fill=C["silk"], weight="700")
    return s


def usb_c(s: Svg, x, y, w=7.4, h=9.0, orient="h"):
    """USB-C 母座（俯视）：银色外壳 + 内腔"""
    s.rect(x, y, w, h, r=0.7, fill=C["silver"], stroke=C["silver_dark"], sw=0.2)
    s.rect(x + 0.7, y + 1.1, w - 1.4, h - 2.2, r=0.45, fill="#8C9196",
           stroke="#7A7F85", sw=0.12)
    s.rect(x + 1.15, y + 1.6, w - 2.3, h - 3.2, r=0.35, fill="#E9EBED",
           stroke="#B9BEC3", sw=0.1)
    return s


def led(s: Svg, x, y, w=1.6, h=0.9, color=None, glow=False):
    color = color or C["led_red"]
    s.rect(x, y, w, h, r=0.14, fill=color, stroke=darken(color, 0.6), sw=0.1)
    s.rect(x + 0.2, y + 0.16, w - 0.4, 0.22, r=0.08, fill=lighten(color, 0.55),
           opacity=0.85)
    return s


def passive(s: Svg, x, y, w=1.6, h=0.8, kind="res", rot=0):
    """贴片阻容（0805/0603 观感）"""
    body = "#D9C9A8" if kind == "res" else "#8B6E4A"
    if rot:
        w, h = h, w
    s.rect(x, y, w, h, r=0.1, fill=body, stroke="#8A7A5C", sw=0.1)
    s.rect(x - 0.28, y, 0.3, h, r=0.06, fill=C["silver"], stroke=C["silver_dark"], sw=0.07)
    s.rect(x + w - 0.02, y, 0.3, h, r=0.06, fill=C["silver"], stroke=C["silver_dark"], sw=0.07)
    if kind == "res":
        s.rect(x + w * 0.3, y + h * 0.28, w * 0.4, h * 0.44, r=0.05, fill="#1F2226")
    return s


def shield_can(s: Svg, x, y, w, h, r=0.5, etch=True):
    """金属屏蔽罩（ESP32 模组等）"""
    s.rect(x, y, w, h, r=r, fill="#C9CCD0", stroke="#8E9398", sw=0.22)
    s.rect(x + 0.4, y + 0.4, w - 0.8, h - 0.8, r=max(0, r - 0.2), fill="none",
           stroke="#E6E8EA", sw=0.14, opacity=0.75)
    if etch:
        for i in range(3):
            s.line(x + 1.0, y + h * (0.25 + i * 0.25), x + w - 1.0,
                   y + h * (0.25 + i * 0.25), stroke="#AEB3B8", sw=0.08, opacity=0.6)
    return s


def screw_terminal(s: Svg, x, y, w, h, poles=2, color="#1E9E4A"):
    """绿色螺钉端子"""
    s.rect(x, y, w, h, r=0.4, fill=color, stroke=darken(color, 0.6), sw=0.2)
    step = h / poles if h > w else w / poles
    for i in range(poles):
        if h > w:
            cx, cy = x + w / 2, y + step * (i + 0.5)
            s.rect(x + w / 2 - 0.55, cy - 0.55, 1.1, 1.1, r=0.12, fill="#0F1113")
        else:
            cx, cy = x + step * (i + 0.5), y + h / 2
            s.rect(cx - 0.55, cy - 0.55, 1.1, 1.1, r=0.12, fill="#0F1113")
    return s


def heart(s: Svg, cx, cy, size=8.0, fill="#FFFFFF", stroke=None, sw=0.2):
    """心形（Pulse Sensor 丝印）"""
    k = size / 10.0
    d = (
        f"M {_n((cx)*MM)} {_n((cy + 3.2*k)*MM)} "
        f"C {_n((cx-5.2*k)*MM)} {_n((cy-1.2*k)*MM)} {_n((cx-3.4*k)*MM)} {_n((cy-5.4*k)*MM)} "
        f"{_n((cx)*MM)} {_n((cy-2.2*k)*MM)} "
        f"C {_n((cx+3.4*k)*MM)} {_n((cy-5.4*k)*MM)} {_n((cx+5.2*k)*MM)} {_n((cy-1.2*k)*MM)} "
        f"{_n((cx)*MM)} {_n((cy + 3.2*k)*MM)} Z"
    )
    s.path(d, fill=fill, stroke=stroke, sw=sw)
    return s


def wire(s: Svg, pts, color="#E53935", width=0.9, dash=None, r=1.2, cap="round"):
    """折线导线（圆角拐弯）。坐标单位 mm。"""
    if len(pts) < 2:
        return s
    d = f"M {_n(pts[0][0]*MM)} {_n(pts[0][1]*MM)}"
    for i in range(1, len(pts)):
        x0, y0 = pts[i - 1]
        x1, y1 = pts[i]
        if r > 0 and i < len(pts) - 1:
            # 圆角：在拐点处用二次贝塞尔
            nx, ny = pts[i + 1]
            dx1, dy1 = x1 - x0, y1 - y0
            dx2, dy2 = nx - x1, ny - y1
            l1 = math.hypot(dx1, dy1) or 1
            l2 = math.hypot(dx2, dy2) or 1
            rr = min(r, l1 / 2, l2 / 2)
            ax, ay = x1 - dx1 / l1 * rr, y1 - dy1 / l1 * rr
            bx, by = x1 + dx2 / l2 * rr, y1 + dy2 / l2 * rr
            d += f" L {_n(ax*MM)} {_n(ay*MM)} Q {_n(x1*MM)} {_n(y1*MM)} {_n(bx*MM)} {_n(by*MM)}"
        else:
            d += f" L {_n(x1*MM)} {_n(y1*MM)}"
    da = f' stroke-dasharray="{dash}"' if dash else ""
    s.add(
        f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{_n(width*MM)}" '
        f'stroke-linecap="{cap}" stroke-linejoin="round"{da}/>'
    )
    return s


def junction(s: Svg, cx, cy, r=0.55, color="#1565C0"):
    """导线连接点（实心圆点）"""
    s.circle(cx, cy, r, fill=color, stroke="#FFFFFF", sw=0.22)
    return s
