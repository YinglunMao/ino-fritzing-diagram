#!/usr/bin/env python3
"""
parts_library.py — 每个元件的 Fritzing 风格 SVG 渲染器

关键约定
--------
`render_*()` 同时返回 **SVG 字符串** 和 **引脚坐标表**。
引脚坐标与绘图出自同一份代码，因此接线图里的导线端点天然与元件焊盘重合，
不会出现「图上画的焊盘」和「实际连线的位置」对不上的问题。

引脚表结构：{pin_name: {"x": mm, "y": mm, "dir": "up|down|left|right", "label": 丝印名,
                        "note": 说明}}
`dir` 表示引线应该从元件**朝哪个方向**引出，供布线器决定导线第一段的方向。

尺寸来自实物资料（模块规格/参考图测量），已尽量贴近真实比例。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from fritzing_kit import (C, MM, Svg, _n, chip_dip, chip_qfn, chip_soic, header, heart,
                          led, male_pins_out, mic_can, mount_hole, pad, passive, pcb,
                          shield_can, tactile, trimpot, usb_c, via, darken, lighten)


@dataclass
class Part:
    pid: str
    name: str
    w: float
    h: float
    svg: str
    pins: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    @property
    def bbox(self):
        return (self.w, self.h)


def _mk(pid, name, w, h, s: Svg, pins, meta=None):
    return Part(pid, name, w, h, s.render(aria=name), pins, meta or {})


# ===========================================================================
# 1) Geekble nano ESP32-S3 开发板（Nano 外形 43.2 × 17.8 mm，15 针 × 2 排）
#    引脚排列依据 Geekble 官方 PinMap（Geekble-nano-ESP32S3 仓库）
# ===========================================================================
ROW_A = ["VIN", "GND", "B1", "5V", "A7", "A6", "A5", "A4", "A3", "A2", "A1", "A0", "B0", "3V3", "D13"]
ROW_B = ["GND", "TX", "RX", "RST", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10", "D11", "D12"]
GPIO_OF = {
    "B1": 0, "A0": 1, "A1": 2, "A2": 3, "A3": 4, "D2": 5, "D3": 6, "D4": 7, "D5": 8,
    "D6": 9, "D7": 10, "A4": 11, "A5": 12, "A6": 13, "A7": 14, "D8": 17, "D9": 18,
    "D10": 21, "D11": 38, "TX": 43, "RX": 44, "B0": 46, "D12": 47, "D13": 48,
}


def render_geekble_nano() -> Part:
    W, H = 43.2, 17.8
    X0, PITCH = 3.8, 2.54
    YA, YB = 2.0, H - 2.0      # 两排焊盘中心线
    s = Svg(W, H, pad_mm=2.0, bg=None)

    pcb(s, 0, 0, W, H, fill=C["pcb_black"], edge=C["pcb_black_edge"], r=0.9,
        holes=[(1.55, 2.0), (W - 1.55, 2.0), (1.55, H - 2.0), (W - 1.55, H - 2.0)],
        hole_r=0.62)
    # 板边镀金半孔（castellated）观感：沿两条长边画深色条 + 少量过孔
    for i in range(26):
        via(s, 2.2 + i * 1.55, H / 2, 0.24)

    # 两排焊盘
    pins = {}
    for i, nm in enumerate(ROW_A):
        x = X0 + i * PITCH
        pad(s, x, YA, r=0.92, hole_r=0.4)
        key = "GND_A" if nm == "GND" else nm
        pins[key] = {"x": x, "y": YA, "dir": "up", "label": nm, "gpio": GPIO_OF.get(nm),
                     "row": "A"}
    for i, nm in enumerate(ROW_B):
        x = X0 + i * PITCH
        pad(s, x, YB, r=0.92, hole_r=0.4)
        key = "GND_B" if nm == "GND" else nm
        pins[key] = {"x": x, "y": YB, "dir": "down", "label": nm, "gpio": GPIO_OF.get(nm),
                     "row": "B"}

    # 丝印引脚名（沿板长方向竖排，与实物一致）
    for key, p in pins.items():
        if p["row"] == "A":
            s.text(p["x"], 3.55, p["label"], size=1.05, fill="#E4E7EA", weight="700",
                   rot=-90, anchor="end", opacity=0.92)
        else:
            s.text(p["x"], H - 3.55, p["label"], size=1.05, fill="#E4E7EA", weight="700",
                   rot=-90, anchor="start", opacity=0.92)

    # ESP32-S3 主控（QFN，位于天线区之后）
    chip_qfn(s, 10.8, H / 2, size=5.4, label="ESP32-S3")
    for i in range(5):
        passive(s, 13.9 + i * 1.0, H / 2 - 3.3, 0.85, 0.5)
        passive(s, 13.9 + i * 1.0, H / 2 + 2.9, 0.85, 0.5)
    # 板端天线净空区（无铜）
    s.rect(0.75, 2.6, 2.6, H - 5.2, r=0.25, fill="#0B0C0E", stroke="#2B2E33", sw=0.12)
    s.rect(1.15, 3.1, 1.8, H - 6.2, r=0.2, fill="none", stroke="#3A3E44", sw=0.1,
           opacity=0.8)

    # USB-C（板右端，开口朝右）
    s.rect(W - 6.4, H / 2 - 5.0, 6.4, 10.0, r=0.6, fill="#0E1012",
           stroke=C["silver_dark"], sw=0.2)
    s.rect(W - 5.5, H / 2 - 4.1, 5.0, 8.2, r=0.45, fill=C["silver"],
           stroke=C["silver_dark"], sw=0.18)
    s.rect(W - 4.1, H / 2 - 2.4, 3.6, 4.8, r=0.35, fill="#5C6167")
    s.rect(W - 3.5, H / 2 - 1.9, 3.0, 3.8, r=0.3, fill="#E9EBED")

    # BOOT / RST 轻触按键
    tactile(s, 30.6, H / 2, w=3.3, h=3.3)
    tactile(s, 33.6, H / 2, w=3.3, h=3.3)
    s.text(30.6, H / 2 - 3.2, "BOOT", size=0.85, fill="#E4E7EA", weight="700")
    s.text(33.6, H / 2 - 3.2, "RST", size=0.85, fill="#E4E7EA", weight="700")
    # 电源指示 + RGB LED
    led(s, 4.4, H / 2 - 0.45, 1.5, 0.9, color=C["led_red"])
    led(s, 6.6, H / 2 - 0.45, 1.5, 0.9, color="#E8E9EC")
    s.text(5.5, H / 2 + 2.4, "PWR", size=0.8, fill="#D8DCE0", weight="700")

    # 板名丝印
    s.text(21.5, H / 2 - 0.6, "Geekble", size=1.5, fill=C["silk"], weight="700",
           anchor="middle")
    s.text(21.5, H / 2 + 1.7, "nano ESP32-S3", size=1.1, fill="#D8DCE0", weight="600",
           anchor="middle")

    return _mk("geekble_nano_esp32s3", "Geekble nano ESP32-S3", W, H, s, pins,
               {"fqbn": "esp32:esp32:Geekble_Nano_ESP32S3",
                "note": "引脚排列依据 Geekble 官方 PinMap"})


# ===========================================================================
# 2) MPU6050 六轴模块（GY-521，21.0 × 15.7 mm，8 针单排）
# ===========================================================================
def render_mpu6050() -> Part:
    W, H = 21.0, 15.7
    s = Svg(W, H, pad_mm=2.0)
    pcb(s, 0, 0, W, H, fill=C["pcb_blue"], edge=C["pcb_blue_edge"], r=0.9,
        holes=[(1.7, 1.7), (W - 1.7, 1.7), (1.7, H - 1.7), (W - 1.7, H - 1.7)],
        hole_r=0.95)

    names = ["VCC", "GND", "SCL", "SDA", "XDA", "XCL", "AD0", "INT"]
    X0, PITCH, PADY = 1.35, 2.54, 1.9
    pins = {}
    for i, nm in enumerate(names):
        x = X0 + i * PITCH
        pad(s, x, PADY, r=0.95, hole_r=0.42)
        s.text(x, 3.3, nm, size=0.86, fill=C["silk"], rot=-90, anchor="end", weight="700")
        pins[nm] = {"x": x, "y": PADY, "dir": "up", "label": nm}
    male_pins_out(s, X0, -1.6, len(names), orient="h", pitch=PITCH, length=1.6)

    # MPU-6050 主芯片
    chip_qfn(s, 10.6, 8.8, size=4.0, label="MPU-6050")
    # 3.3V LDO + 阻容
    chip_soic(s, 4.4, 5.4, 2.4, 2.8, label=None, legs=3)
    s.text(5.6, 9.1, "KB33", size=0.6, fill="#DCE2E8", weight="700")
    for i in range(3):
        passive(s, 15.2 + i * 1.0, 4.6, 0.85, 0.5)
        passive(s, 15.2 + i * 1.0, 12.6, 0.85, 0.5)
    trimpot(s, 15.6, 6.9, size=3.4)

    s.text(8.6, 12.6, "GY-521", size=1.05, fill=C["silk"], weight="700", anchor="middle")
    return _mk("mpu6050_gy521", "MPU6050 (GY-521)", W, H, s, pins,
               {"i2c": 0x68, "note": "AD0 接 GND ⇒ 地址 0x68"})


# ===========================================================================
# 3) AS7341 11 通道光谱传感器模块（国产分线板，26 × 18 mm，6 针单排）
# ===========================================================================
def render_as7341() -> Part:
    W, H = 26.0, 18.0
    s = Svg(W, H, pad_mm=2.0)
    pcb(s, 0, 0, W, H, fill=C["pcb_blue"], edge=C["pcb_blue_edge"], r=0.9,
        holes=[(1.8, 1.8), (W - 1.8, 1.8), (1.8, H - 1.8), (W - 1.8, H - 1.8)],
        hole_r=0.95, plated=True)

    names = ["VCC", "GND", "SDA", "SCL", "INT", "GPIO"]
    X0, PITCH, PADY = 5.6, 2.54, 1.9
    pins = {}
    for i, nm in enumerate(names):
        x = X0 + i * PITCH
        pad(s, x, PADY, r=0.95, hole_r=0.42)
        s.text(x, 3.5, nm, size=0.86, fill=C["silk"], rot=-90, anchor="end", weight="700")
        pins[nm] = {"x": x, "y": PADY, "dir": "up", "label": nm}
    male_pins_out(s, X0, -1.6, len(names), orient="h", pitch=PITCH, length=1.6)

    chip_qfn(s, 11.6, 11.4, size=3.6, label="AS7341")
    # 光谱芯片的采光窗（白色扩散片）
    s.circle(11.6, 11.4, 0.95, fill="#F2F4F6", stroke="#C9CED3", sw=0.16)
    s.text(11.6, 14.4, "AS7341", size=0.9, fill="#DCE2E8", weight="700")
    for i in range(4):
        passive(s, 4.0 + i * 1.05, 7.4, 0.85, 0.5)
    for i in range(3):
        passive(s, 17.6 + i * 1.05, 7.4, 0.85, 0.5)
    led(s, 17.9, 13.4, 1.5, 0.9, color="#E8E9EC")
    led(s, 17.9, 15.0, 1.5, 0.9, color="#E8E9EC")

    s.text(18.0, 9.9, "Spectral", size=1.0, fill=C["silk"], weight="700")
    s.text(18.0, 11.3, "Color", size=1.0, fill=C["silk"], weight="700")
    s.text(18.0, 12.7, "Sensor", size=1.0, fill=C["silk"], weight="700")
    return _mk("as7341_module", "AS7341 光谱传感器模块", W, H, s, pins,
               {"i2c": 0x39, "note": "国产 AS7341 分线板形态；尺寸按参考图估算"})


# ===========================================================================
# 4) Pulse Sensor Amped 脉搏传感器（Ø15.8 mm 圆形板）
# ===========================================================================
def render_pulse_sensor() -> Part:
    """圆形板；接线凸台置于顶端朝上，便于接线图中引线朝向开发板。"""
    D = 15.8
    H = D + 3.4
    s = Svg(D, H, pad_mm=2.4)
    cx, cy = D / 2, 1.6 + D / 2
    r = D / 2
    s.circle(cx, cy, r, fill=C["pcb_black"], stroke=C["pcb_black_edge"], sw=0.25)

    # 顶部接线凸台
    s.path_pts([(cx - 5.4, cy - r + 1.6), (cx + 5.4, cy - r + 1.6),
                (cx + 5.1, cy - r - 1.9), (cx - 5.1, cy - r - 1.9)],
               fill=C["pcb_black"], stroke=C["pcb_black_edge"], sw=0.2)

    # 心形丝印
    heart(s, cx, cy + 1.1, size=9.2, fill="#FFFFFF")
    s.circle(cx, cy + 1.1, 1.28, fill="#B9BEC4", stroke="#8E9398", sw=0.18)
    s.circle(cx, cy + 1.1, 0.46, fill="#E9EBED")
    chip_soic(s, cx - 0.9, cy - 3.2, 1.8, 1.7, legs=3)

    import math
    # 安装孔：只放在下方两侧，把底部弧线让给丝印文字
    for a in (25, 155):
        rr = r - 1.3
        s.circle(cx + rr * math.cos(math.radians(a)), cy + rr * math.sin(math.radians(a)),
                 0.4, fill="#FFFFFF", stroke="#5A5F66", sw=0.14)

    # 环形丝印沿下方弧线（上方弧线被接线凸台与引脚名占用，放上去会叠字）
    # 下方弧线要「从右往左」布线 + flip，字才是正的（arc_text 的 rot = angle-90）
    s.arc_text(cx, cy, r - 1.2, "pulsesensor.com", size=0.82, fill="#FFFFFF",
               start_deg=122, end_deg=58, flip=True)

    # 顶部 3 个接线焊盘（GND / VCC / SIG）
    names = [("GND", -3.6), ("VCC", 0.0), ("SIG", 3.6)]
    pins = {}
    for nm, dx in names:
        px = cx + dx
        py = cy - r - 1.05
        pad(s, px, py, r=0.98, hole_r=0.46)
        s.text(px, cy - r + 2.5, nm, size=0.78, fill=C["silk"], weight="700")
        pins[nm] = {"x": px, "y": py, "dir": "up", "label": nm,
                    "wire": {"SIG": "#8E44AD", "VCC": "#E53935", "GND": "#212121"}[nm]}
    return _mk("pulse_sensor", "Pulse Sensor Amped 脉搏传感器", D, H, s, pins,
               {"note": "经典 Pulse Sensor Amped；原厂线序 紫=SIG 红=VCC 黑=GND；"
                        "图中接线凸台朝上，与实物方向相反"})


# ===========================================================================
# 5) LM2904 声音/咪头模块（FC-04，35 × 16 mm，4 针单排）
# ===========================================================================
def render_mic_lm2904() -> Part:
    W, H = 35.0, 16.0
    s = Svg(W, H, pad_mm=2.2)
    pcb(s, 0, 0, W, H, fill=C["pcb_navy"], edge=C["pcb_navy_edge"], r=0.9,
        holes=[(1.8, 2.0), (W - 1.8, 2.0), (1.8, H - 2.0), (W - 1.8, H - 2.0)],
        hole_r=0.9)

    # 驻极体咪头（伸出板左边）
    mic_can(s, 0.6, H / 2, r=4.4)

    # 4 针排针（板右上）：VCC GND DO AO
    names = ["VCC", "GND", "DO", "AO"]
    X0, PITCH, PADY = W - 12.2, 2.54, 1.9
    pins = {}
    for i, nm in enumerate(names):
        x = X0 + i * PITCH
        pad(s, x, PADY, r=0.95, hole_r=0.42)
        s.text(x, 3.4, nm, size=0.86, fill=C["silk"], rot=-90, anchor="end", weight="700")
        pins[nm] = {"x": x, "y": PADY, "dir": "up", "label": nm}
    male_pins_out(s, X0, -1.6, len(names), orient="h", pitch=PITCH, length=1.6)

    # LM2904 双运放
    chip_soic(s, 17.2, 5.9, 4.4, 5.4, label="LM2904", legs=4)
    # 增益电位器 + 指示灯
    trimpot(s, 11.2, 5.6, size=5.0)
    led(s, 25.6, 5.8, 1.6, 0.95, color=C["led_red"])
    led(s, 25.6, 8.0, 1.6, 0.95, color=C["led_green"])
    s.text(26.6, 6.4, "PWR", size=0.72, fill="#D8DCE0", weight="700", anchor="start")
    s.text(26.6, 8.6, "SIG", size=0.72, fill="#D8DCE0", weight="700", anchor="start")
    for i in range(4):
        passive(s, 6.6 + i * 1.0, 11.2, 0.85, 0.5)
        passive(s, 11.4 + i * 1.0, 11.2, 0.85, 0.5)
    s.text(17.5, 14.4, "FC-04 声音传感器模块", size=1.0, fill=C["silk"], weight="700")
    return _mk("mic_lm2904_module", "LM2904 声音传感器模块 (FC-04)", W, H, s, pins,
               {"note": "咪头模块经用户确认为 LM2904 型；AO 输出模拟波形"})


# ===========================================================================
# 6) ESP32-S3 Nano 开发板（浅蓝 PCB，52.8 × 20.5 mm，半孔焊盘 1×20 针 × 2 排）
#    丝印逐个字对照用户实拍照片（2026-09-24 那张 6/9 的板子特写）：
#      · 浅蓝阻焊 + 深色丝印，丝印**直接印 GPIO 号**（不是 D0/A0 别名）
#      · 半孔（castellated）焊盘贴着板的长边，两排各 20 个
#      · 靠近 USB 的那一端是 1 号针，两排都以 GND 起头
#      · 每排第 2、4 个针位印的是「角标」而非文字（把 5V / 3V3 框起来）
# ===========================================================================
NANO_BLUE = "#BCD7F0"        # 板面（照片取色 #CBE0F7，压一点饱和度更像实物）
NANO_BLUE_EDGE = "#8FB2D4"
NANO_INK = "#22303A"         # 丝印墨色（照片实测 #222D35）

# 渲染时 USB 座在板的**右端** → 数组按「远离 USB → 靠近 USB」书写（与照片读序相反）。
#   top = 照片里印 5V / BAT 的那一列；bot = 印 3V3 / RST 的那一列。
#   "TK" = 照片里那个角标丝印（不是针名，无法确认为字符，按原样复刻）。
NANO_ROWS = {
    "top": ["46", "45", "42", "41", "15", "16", "17", "18", "GND", "21",
            "40", "39", "38", "47", "48", "BAT", "TK", "5V", "TK", "GND"],
    "bot": ["01", "02", "03", "04", "05", "06", "GND", "07", "08", "09",
            "10", "11", "12", "13", "14", "RST", "TK", "3V3", "TK", "GND"],
}


def _half_disc(s: Svg, cx, cy, r, inward, fill, stroke=None, sw=0.14):
    """以板边为直径、朝板内鼓出的半圆（半孔焊盘用）。

    用折线逼近而不是 SVG 圆弧 —— 圆弧的 sweep 方向在 y 轴向下的画布里很容易搞反，
    这里直接按解析式采样，inward=+1 一定朝下、-1 一定朝上。
    """
    n = 24
    pts = [(cx + r * math.cos(math.pi * i / n), cy + inward * r * math.sin(math.pi * i / n))
           for i in range(n + 1)]
    s.path_pts(pts, fill=fill, stroke=stroke, sw=sw)
    return s


def _castellated_pad(s: Svg, cx, cy, inward, r=0.95, hole_r=0.45):
    """半孔焊盘：金属半环 + 亮孔，都落在板内（板边把外半圈切掉）。"""
    _half_disc(s, cx, cy, r, inward, fill=C["silver"], stroke=C["silver_dark"])
    _half_disc(s, cx, cy, hole_r, inward, fill=C["hole"])
    return s


def _nano_tick(s: Svg, cx, y, up, tick_at=1):
    """照片里 5V / 3V3 两侧那对「角标」丝印（不是文字，按原样复刻）。

    形状＝一根沿排方向的短横线 + 一端的短竖线。up=True 时竖线朝上（板边方向）。
    同一排的两枚左右镜像，竖线都落在靠中间那个针名的一侧，合起来像把针名括住。
    """
    bar, tick = 1.6, 0.9
    x1, x2 = cx - bar / 2, cx + bar / 2
    s.line(x1, y, x2, y, stroke=NANO_INK, sw=0.2, cap="butt")
    tx = x2 if tick_at > 0 else x1
    s.line(tx, y, tx, y - tick if up else y + tick, stroke=NANO_INK, sw=0.2, cap="butt")
    return s


def render_esp32s3_nano() -> Part:
    W, H = 52.8, 20.5
    PITCH = 2.54
    X0 = (W - 19 * PITCH) / 2.0          # 2.27mm，与照片里焊盘距板端的余量一致

    s = Svg(W, H, pad_mm=2.2)
    pcb(s, 0, 0, W, H, fill=NANO_BLUE, edge=NANO_BLUE_EDGE, r=1.1, inner_rim=True)

    # ---- 两排半孔焊盘 + 丝印 ----
    pins = {}
    gnd_n = {"top": 0, "bot": 0}
    for row, names in (("top", NANO_ROWS["top"]), ("bot", NANO_ROWS["bot"])):
        y = 0.0 if row == "top" else H
        inward = 1 if row == "top" else -1              # 由板边指向板内
        dirn = "up" if row == "top" else "down"          # 导线离开板的方向
        base = 2.15 if row == "top" else H - 1.15        # 丝印基线
        tk_n = 0
        for i, nm in enumerate(names):
            x = X0 + i * PITCH
            _castellated_pad(s, x, y, inward)
            if nm == "TK":
                tk_n += 1
                _nano_tick(s, x, base - 0.35, up=(row == "top"),
                           tick_at=(1 if tk_n == 1 else -1))
                continue
            s.text(x, base, nm, size=1.0, fill=NANO_INK, weight="800")
            if nm == "GND":
                gnd_n[row] += 1
                key = "GND_%s%s" % ("A" if row == "top" else "B",
                                    "" if gnd_n[row] == 1 else gnd_n[row])
            elif nm in ("3V3", "5V", "BAT", "RST"):
                key = nm
            else:
                key = "G" + nm
            pins[key] = {"x": x, "y": y, "dir": dirn, "label": nm,
                         "row": "A" if row == "top" else "B",
                         "gpio": int(nm) if nm.isdigit() else None}

    # ---- 板载元件（位置按照片；USB 在右端） ----
    # 主控：裸 ESP32-S3 QFN（照片中无屏蔽罩，QFN 偏远离 USB 的一端）
    chip_qfn(s, 16.2, 13.0, size=6.2, label="")
    # 板载 Flash / 电源 SOIC-8
    chip_soic(s, 21.6, 12.0, 4.2, 3.4)
    # 40MHz 晶振
    s.rect(11.0, 8.9, 2.2, 1.6, r=0.18, fill=C["silver"], stroke=C["silver_dark"], sw=0.14)
    s.text(12.1, 10.0, "040J", size=0.55, fill="#6C7378", weight="700")
    # 远离 USB 的那一端：IPEX 天线座 + 电池连接器
    s.rect(6.0, 13.6, 3.2, 2.8, r=0.25, fill="#B9BDC1", stroke="#8A9095", sw=0.18)
    s.circle(7.6, 15.0, 0.85, fill="#6E7378", stroke="#4E5257", sw=0.16)
    s.circle(7.6, 15.0, 0.3, fill="#2A2D30")
    s.rect(5.9, 10.4, 3.0, 2.2, r=0.2, fill="#2E6FC4", stroke="#1E4E8F", sw=0.18)
    # BOOT / RST 轻触键：照片里两键纵向叠放在板宽中段、以板中线对称，
    # BOOT 靠 46/45 那一排、RST 靠 01 那一排，丝印都印在按键左侧（字头朝上读）
    tactile(s, 35.0, 6.9, w=3.4, h=3.4)
    tactile(s, 35.0, 14.0, w=3.4, h=3.4)
    s.text(31.6, 6.9, "BOOT", size=0.85, fill=NANO_INK, weight="800", anchor="middle", rot=-90)
    s.text(31.6, 14.0, "RST", size=0.85, fill=NANO_INK, weight="800", anchor="middle", rot=-90)
    # U1：USB 转串口 / LDO（SOT-23-5，紧邻 USB）
    chip_soic(s, 41.4, 4.2, 1.9, 2.4, label="U1", legs=3)
    # PWR / G48 指示灯（照片里紧挨 USB 座两侧）
    led(s, 41.6, 7.6, 1.5, 0.9, color=C["led_green"])
    s.text(41.6, 6.4, "G48", size=0.68, fill=NANO_INK, weight="800")
    led(s, 41.6, 12.4, 1.5, 0.9, color=C["led_red"])
    s.text(41.6, 13.6, "PWR", size=0.68, fill=NANO_INK, weight="800")
    # 零星阻容，让板面不那么空
    for i in range(4):
        passive(s, 26.0 + i * 1.4, 5.6, 0.9, 0.55)
        passive(s, 26.0 + i * 1.4, 17.0, 0.9, 0.55)
    # 短边 USB-C 座（照片里占满板端中间，两排针从其两侧绕过）
    usb_c(s, W - 9.2, (H - 7.6) / 2, 9.2, 7.6, orient="h")

    return _mk("esp32s3_nano_blue", "ESP32-S3 Nano（浅蓝 PCB）", W, H, s, pins,
               {"note": "丝印逐个字对照用户实拍照片：浅蓝阻焊 + 深色丝印、半孔焊盘，"
                        "两排各 20 针。照片里 USB 座在一端，两排的编号（01…14、46…15）"
                        "都从**无 USB 的那一端**起算。丝印直接印 GPIO 号。"
                        "每排第 2、4 位是照片里那对角标丝印（把 5V / 3V3 括起来），"
                        "不是文字，故未登记为可接针位。"})


def render_esp32s3_nano_white() -> Part:
    """旧 id 别名（早年按「白板」画的版本），保持向下兼容。"""
    return render_esp32s3_nano()


# ===========================================================================
# 7) AS734x 光谱模块（黑色 PCB，6 针，照片版）
#    照片丝印：AS734x / GPIO INT SDA SCL GND VIN，中央金色光谱窗口，两个安装孔
# ===========================================================================
def render_as7341_black6() -> Part:
    W, H = 25.4, 15.2
    s = Svg(W, H, pad_mm=2.2)
    pcb(s, 0, 0, W, H, fill=C["pcb_black"], edge=C["pcb_black_edge"], r=0.9,
        holes=[(2.1, H / 2), (W - 2.1, H / 2)], hole_r=1.5, plated=True)

    # 6 针单排（照片从上到下：GPIO INT SDA SCL GND VIN）
    names = ["GPIO", "INT", "SDA", "SCL", "GND", "VIN"]
    X0, PITCH, PADY = 5.2, 2.54, 1.9
    pins = {}
    for i, nm in enumerate(names):
        x = X0 + i * PITCH
        pad(s, x, PADY, r=0.92, hole_r=0.4)
        s.text(x, 3.6, nm, size=0.82, fill=C["silk"], rot=-90, anchor="end", weight="700")
        pins[nm] = {"x": x, "y": PADY, "dir": "up", "label": nm}
    male_pins_out(s, X0, -1.6, len(names), orient="h", pitch=PITCH, length=1.6)

    # 中央金色光谱窗口（照片中最醒目的识别锚点）
    s.rect(15.4, 6.0, 4.4, 4.4, r=0.3, fill=C["gold"], stroke=C["gold_dark"], sw=0.2)
    s.rect(16.0, 6.6, 3.2, 3.2, r=0.2, fill="#F2D06B", stroke="none", sw=0)
    # 窗口左侧的 AS7341 主芯片
    chip_qfn(s, 10.6, 8.2, size=2.6, label=None)
    s.text(17.6, 13.4, "AS734x", size=1.1, fill=C["silk"], weight="800")
    return _mk("as7341_black6", "AS734x 光谱传感器模块（黑色 6 针）", W, H, s, pins,
               {"i2c": 0x39, "note": "依据用户实拍照片：黑色 PCB、6 针 "
                                     "GPIO/INT/SDA/SCL/GND/VIN、中央金色光谱窗口"})


# ===========================================================================
# 8) 电容咪头声音模块（亮蓝 PCB，照片版）
#    照片：横长蓝板 + 左侧圆柱电容咪头 + 右侧 4 针（VCC/GND/S/A）
# ===========================================================================
def render_mic_sound_blue() -> Part:
    W, H = 28.0, 15.0
    s = Svg(W, H, pad_mm=2.4)
    pcb(s, 0, 0, W, H, fill=C["pcb_blue"], edge=C["pcb_blue_edge"], r=0.9,
        holes=[(2.0, H / 2), (W - 2.0, H / 2)], hole_r=1.35, plated=True)

    # 驻极体电容咪头（左端圆柱）
    mic_can(s, 2.4, H / 2, r=4.2)

    # 4 针排针（照片右端白色连接器）
    names = ["VCC", "GND", "S", "A"]
    X0, PITCH, PADY = 13.4, 2.54, 1.9
    pins = {}
    for i, nm in enumerate(names):
        x = X0 + i * PITCH
        pad(s, x, PADY, r=0.92, hole_r=0.4)
        s.text(x, 3.6, nm, size=0.84, fill=C["silk"], rot=-90, anchor="end", weight="700")
        key = {"VCC": "VCC", "GND": "GND", "S": "DO", "A": "AO"}[nm]
        pins[key] = {"x": x, "y": PADY, "dir": "up", "label": nm}
    male_pins_out(s, X0, -1.6, len(names), orient="h", pitch=PITCH, length=1.6)

    # 放大 / 运放芯片 + 增益电阻（照片：中央 8 脚 IC，丝印 10K/15K/17K/2K/470）
    chip_soic(s, 9.4, 6.4, 3.0, 3.6, label=None, legs=4)
    for i, (dx, val) in enumerate([(6.6, "15K"), (10.2, "10K"), (13.0, "470")]):
        passive(s, dx, 11.6 + (i % 2) * 1.5, 0.85, 0.5)
        s.text(dx + 1.2, 12.0 + (i % 2) * 1.5, val, size=0.6, fill=C["silk"], weight="700")
    s.text(4.0, 13.2, "MIC AMP", size=0.85, fill=C["silk"], weight="700")
    return _mk("mic_sound_blue", "电容咪头声音模块（蓝色）", W, H, s, pins,
               {"note": "依据用户实拍照片：亮蓝 PCB、左端圆柱电容咪头、"
                        "4 针 VCC/GND/S/A。型号丝印不可读，按通用咪头放大电路绘制。"})


# ===========================================================================
# 9) 微型潜水泵模块（奶白泵体 + 白色 PCB 驱动板，3 针 G-V-S，照片版）
#    照片：奶白圆柱泵体（端面中心出水孔 + 底部斜出水嘴）+ 白色驱动板
#    （G-V-S 白色 JST 连接器、两颗 SOT-23 + 0603 电阻、两个沉金安装孔、
#      水泵叶轮丝印图标、D 字 logo、板边走线槽 + 黑色热缩管应力释放）
# ===========================================================================
def render_pump_module_gvs() -> Part:
    W, H = 88.0, 40.0
    IVORY = "#F1ECDC"        # 泵体奶白塑料
    IVORY_E = "#AFA68E"
    IVORY_DK = "#DFD8C2"
    WHITE = "#EDEFF2"        # 白色 PCB
    WHITE_E = "#C6CBD2"
    INK = "#3A3E44"          # 深灰丝印（白底板）

    s = Svg(W, H, pad_mm=2.4)

    # ---- 潜水泵（正交俯视：横躺圆柱 → 圆端盖 + 长圆机身 + 斜出水嘴）
    cx, cy, r_cap = 13.5, 20.0, 10.0
    bx1, bx2 = 13.5, 45.0    # 机身 x 范围
    # 机身
    s.rect(bx1, cy - r_cap, bx2 - bx1, r_cap * 2, r=4.0, fill=IVORY,
           stroke=IVORY_E, sw=0.25)
    # 机身纵向棱线（同色系略深）
    for dy in (-5.2, 5.2):
        s.line(bx1 + 4.5, cy + dy, bx2 - 4.5, cy + dy, stroke=IVORY_DK, sw=0.5)
    # 端盖（同心圆）
    s.circle(cx, cy, r_cap, fill=IVORY, stroke=IVORY_E, sw=0.25)
    s.circle(cx, cy, 7.6, fill="none", stroke=IVORY_DK, sw=0.4)
    # 端面中心出水孔
    s.circle(cx, cy, 2.9, fill="#8A8268", stroke="#6E674F", sw=0.2)
    s.circle(cx, cy, 1.8, fill="#3E3A2C")
    # 斜出水嘴（底部朝下）
    import math as _m
    ang = _m.radians(52)
    d = (_m.cos(ang), _m.sin(ang))
    p = (19.8, 29.6)
    perp = (d[1] * 2.2, -d[0] * 2.2)
    ln = 7.6
    e = (p[0] + d[0] * ln, p[1] + d[1] * ln)
    s.path_pts([(p[0] + perp[0], p[1] + perp[1]), (e[0] + perp[0], e[1] + perp[1]),
                (e[0] - perp[0], e[1] - perp[1]), (p[0] - perp[0], p[1] - perp[1])],
               fill=IVORY, stroke=IVORY_E, sw=0.22)
    s.line(e[0] + perp[0], e[1] + perp[1], e[0] - perp[0], e[1] - perp[1],
           stroke=IVORY_E, sw=0.22)
    # 出水嘴根部法兰环
    s.line(p[0] + perp[0] * 1.35, p[1] + perp[1] * 1.35,
           p[0] - perp[0] * 1.35, p[1] - perp[1] * 1.35, stroke=IVORY_E, sw=0.5)
    # 端盖定位小凸柱（照片中两颗）
    s.circle(cx + 4.6, cy - 8.4, 0.55, fill=IVORY_DK, stroke=IVORY_E, sw=0.14)

    # ---- 泵 → 驱动板 的黑色导线（画在板之下，端头被热缩管盖住）
    # 注意：s.path() 的 d 数据需要自行乘 unit（mm→px）
    u = s.u
    s.path(f"M {43.0*u} {11.8*u} C {51.0*u} {5.5*u}, {56.0*u} {7.0*u}, {62.2*u} {11.6*u}",
           fill="none", stroke="#1F2226", sw=1.8, extra='stroke-linecap="round"')

    # ---- 驱动板（白色 PCB，30 × 24 mm，圆角）
    BX, BY, BW, BH = 55.0, 12.0, 30.0, 24.0
    pcb(s, BX, BY, BW, BH, fill=WHITE, edge=WHITE_E, r=1.8,
        holes=[(3.5, 3.5), (27.4, 17.6)], hole_r=1.45, plated=True)
    # 板边走线槽示意（热缩管两侧的槽口刻线）
    s.line(60.2, BY, 60.2, BY + 2.6, stroke=WHITE_E, sw=0.3)
    s.line(66.6, BY, 66.6, BY + 2.6, stroke=WHITE_E, sw=0.3)

    # ---- 3 针白色 JST 连接器（G-V-S）+ 焊盘
    X0, PITCH, PADY = 58.6, 2.54, 34.2
    names = [("GND", "G", "#212121"), ("VCC", "V", "#E53935"), ("SIG", "S", "#1565C0")]
    pins = {}
    for i, (key, lab, wc) in enumerate(names):
        x = X0 + i * PITCH
        pad(s, x, PADY, r=0.92, hole_r=0.4)
        s.text(x, 32.5, lab, size=0.95, fill=INK, rot=-90, anchor="middle", weight="700")
        pins[key] = {"x": x, "y": PADY, "dir": "down", "label": lab, "full": key,
                     "wire": wc}
    # 连接器本体（白色，三插槽）
    s.rect(56.8, 26.2, 8.6, 5.4, r=0.6, fill="#F4F2EC", stroke="#B9B4A6", sw=0.2)
    for i in range(3):
        s.rect(58.0 + i * PITCH, 27.6, 1.15, 2.7, r=0.25, fill="#6B665A")
    # 两侧固定翼
    s.rect(55.6, 27.4, 1.1, 3.0, r=0.3, fill="#E7E4DB", stroke="#B9B4A6", sw=0.16)
    s.rect(65.5, 27.4, 1.1, 3.0, r=0.3, fill="#E7E4DB", stroke="#B9B4A6", sw=0.16)

    # ---- 驱动电路：两颗 SOT-23（MOSFET / 肖特基）+ 0603 阻容
    chip_soic(s, 64.3, 16.6, 1.8, 2.3, label=None, legs=3)
    chip_soic(s, 67.9, 17.6, 1.8, 2.3, label=None, legs=3)
    passive(s, 71.8, 17.2, 1.5, 0.8)
    passive(s, 70.2, 15.4, 1.5, 0.8)
    via(s, 62.5, 22.5, 0.42)
    via(s, 74.5, 21.0, 0.42)
    via(s, 68.5, 24.0, 0.42)

    # ---- 丝印：水泵叶轮图标（板左缘）
    icx, icy, icr = 57.9, 21.6, 1.75
    s.circle(icx, icy, icr, fill="none", stroke=INK, sw=0.22)
    s.circle(icx, icy, 0.35, fill=INK)
    for a in (90, 210, 330):
        ax = icx + icr * 0.72 * _m.cos(_m.radians(a))
        ay = icy + icr * 0.72 * _m.sin(_m.radians(a))
        s.line(icx + 0.5 * _m.cos(_m.radians(a)), icy + 0.5 * _m.sin(_m.radians(a)),
               ax, ay, stroke=INK, sw=0.22)

    # ---- 丝印：D 字 logo（板右下角）
    s.rect(76.2, 31.4, 3.1, 3.1, r=0.25, fill="none", stroke=INK, sw=0.26)
    s.text(77.75, 33.9, "D", size=2.1, fill=INK, weight="800")

    # ---- 黑色热缩管应力释放（压在板顶走线槽上，最上层）
    s.rect(60.4, 9.6, 6.2, 4.6, r=1.9, fill="#23262B", stroke="#0F1113", sw=0.2)
    s.rect(61.6, 8.8, 3.8, 2.2, r=1.0, fill="#1A1D21", stroke="#0F1113", sw=0.18)

    return _mk("pump_module_gvs", "微型潜水泵模块（G-V-S 驱动板）", W, H, s, pins,
               {"note": "依据实拍照片：奶白圆柱泵体（端面中心出水 + 底部斜嘴）+ "
                        "白色 PCB 驱动板，3 针 G-V-S（GND/VCC/SIG），MOSFET 低边驱动。"
                        "泵 Ø20×31.5mm、板 30×24mm 为按照片比例估算。"})


# ===========================================================================
# 注册表
#
# 模块（传感器/执行器）用本文件里的手工渲染器，逐个按实物资料精修。
# 开发板则来自 `references/boards.json` —— **数据驱动，加板子不用改这里的代码**：
#   * 目录里标了 `hand_tuned` 的板（已按实拍照片精修）→ 转交本文件同名渲染器；
#   * 其余板 → 交给 `boards.render_board()` 按 JSON 里的外形/排针/丝印生成。
# ===========================================================================
REGISTRY = {
    "geekble_nano_esp32s3": render_geekble_nano,
    "esp32s3_nano_blue": render_esp32s3_nano,
    "esp32s3_nano_white": render_esp32s3_nano_white,   # 旧 id，别名
    "mpu6050_gy521": render_mpu6050,
    "as7341_module": render_as7341,
    "as7341_black6": render_as7341_black6,
    "pulse_sensor": render_pulse_sensor,
    "mic_lm2904_module": render_mic_lm2904,
    "mic_sound_blue": render_mic_sound_blue,
    "pump_module_gvs": render_pump_module_gvs,
}


def _render_catalog_board(bid: str) -> Part:
    import boards
    return boards.render_board(bid)


def _extend_with_boards(reg: dict) -> None:
    """把 boards.json 里的板卡并进注册表（失败不影响模块渲染）。"""
    try:
        import boards
        for bid in boards.specs():
            if bid in reg:
                continue
            reg[bid] = (lambda b=bid: _render_catalog_board(b))
    except Exception:
        pass


_extend_with_boards(REGISTRY)


def render_by_id(pid: str) -> Part:
    if pid not in REGISTRY:
        raise KeyError(f"未收录的元件: {pid}（可选: {', '.join(REGISTRY)}）")
    return REGISTRY[pid]()
