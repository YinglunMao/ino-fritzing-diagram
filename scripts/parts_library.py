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

from dataclasses import dataclass, field

from fritzing_kit import (C, Svg, chip_dip, chip_qfn, chip_soic, header, heart, led,
                          male_pins_out, mic_can, mount_hole, pad, passive, pcb,
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
# 6) ESP32-S3 Nano 开发板（白色 PCB 版，52.8 × 20.5 mm，1×20 针 × 2 排）
#    依据「用户实拍照片」识别：白底 + 黑丝印、裸 ESP32-S3 QFN、BOOT/RST 轻触键、
#    短边 USB、PWR + G48 双指示灯；丝印直接标 GPIO 号（非 D0/A0 别名）。
# ===========================================================================
# 板上丝印顺序（照片可辨部分：3V3 … 07 08 09 10 11 12 13 14 / 5V GND BOOT 48 47 38 39 40 21）
# 本电路用到的 GPIO 按「上排接下侧元件友好、下排接上侧元件友好」排布，
# **实际针位请以实物丝印为准**（此板丝印直接印 GPIO 号）。
NANO_ROW_A = ["3V3", "5", "8", "9", "11", "1", "2", "3", "6", "7",
              "15", "16", "17", "43", "46", "12", "13", "14", "47", "48"]
NANO_ROW_B = ["5V", "GND_B", "RST", "4", "10", "38", "39", "40", "21", "20",
              "45", "0", "35", "36", "37", "41", "42", "44", "GND_C", "GND_D"]


def render_esp32s3_nano_white() -> Part:
    W, H = 52.8, 20.5
    PITCH = 2.54
    X0 = (W - 19 * PITCH) / 2.0
    YA, YB = 2.1, H - 2.1
    WHITE = "#EDEFF2"
    WHITE_E = "#C6CBD2"
    INK = "#15181C"          # 黑丝印

    s = Svg(W, H, pad_mm=2.2)
    pcb(s, 0, 0, W, H, fill=WHITE, edge=WHITE_E, r=1.0,
        holes=[(1.7, 2.1), (W - 1.7, 2.1), (1.7, H - 2.1), (W - 1.7, H - 2.1)],
        hole_r=0.72, plated=True)

    # 两排焊盘 + GPIO 号丝印
    pins = {}
    for i, nm in enumerate(NANO_ROW_A):
        x = X0 + i * PITCH
        pad(s, x, YA, r=0.92, hole_r=0.4)
        s.text(x, 3.7, nm, size=0.95, fill=INK, rot=-90, anchor="end", weight="700")
        key = "3V3" if nm == "3V3" else "G" + nm
        pins[key] = {"x": x, "y": YA, "dir": "up", "label": nm, "row": "A",
                     "gpio": int(nm) if nm.isdigit() and nm != "3V3" else None}
    # 3V3 不是 GPIO，去掉伪造的 gpio
    pins["3V3"]["gpio"] = None
    for i, nm in enumerate(NANO_ROW_B):
        x = X0 + i * PITCH
        pad(s, x, YB, r=0.92, hole_r=0.4)
        shown = "GND" if nm.startswith("GND") else nm
        s.text(x, H - 3.7, shown, size=0.95, fill=INK, rot=-90, anchor="start",
               weight="700")
        if nm.startswith("GND"):
            key = nm
        elif nm in ("5V", "RST"):
            key = nm
        else:
            key = "G" + nm
        pins[key] = {"x": x, "y": YB, "dir": "down", "label": shown, "row": "B",
                     "gpio": int(nm) if nm.isdigit() else None}

    # 主控：裸 ESP32-S3 QFN（照片中无屏蔽罩）
    chip_qfn(s, 16.0, H / 2, size=6.0, label="ESP32-S3")
    # 排针旁的去耦电容阵列
    for i in range(5):
        passive(s, 21.5 + i * 1.05, H / 2 - 4.2, 0.85, 0.5)
        passive(s, 21.5 + i * 1.05, H / 2 + 3.8, 0.85, 0.5)
    # U1：USB 转串口 / LDO（SOT-23-5，照片中位于 USB 左侧）
    chip_soic(s, 42.1, H / 2 - 1.5, 1.9, 2.4, label="U1", legs=3)

    # BOOT / RST 轻触按键（照片中位于板中偏右，并排）
    tactile(s, 35.0, H / 2, w=3.2, h=3.2)
    tactile(s, 38.8, H / 2, w=3.2, h=3.2)
    s.text(35.0, H / 2 - 3.1, "BOOT", size=0.8, fill=INK, weight="700")
    s.text(38.8, H / 2 - 3.1, "RST", size=0.8, fill=INK, weight="700")

    # PWR / G48 双指示灯（照片右侧可见 "PWR" 与 "G48" 丝印）
    led(s, 30.2, H / 2 - 5.0, 1.5, 0.9, color=C["led_red"])
    s.text(28.6, H / 2 - 3.7, "PWR", size=0.7, fill=INK, weight="700", anchor="start")
    led(s, 30.2, H / 2 + 3.6, 1.5, 0.9, color=C["led_green"])
    s.text(28.6, H / 2 + 5.5, "G48", size=0.7, fill=INK, weight="700", anchor="start")

    # 短边 USB 座（照片中为板右端，横跨板宽）
    usb_c(s, W - 8.8, H / 2 - 3.9, 8.8, 7.8, orient="h")
    s.text(47.0, H / 2 + 6.4, "USB", size=0.75, fill=INK, weight="700")

    # 板名丝印（照片中为黑丝印）
    s.text(9.4, H / 2 + 0.4, "ESP32-S3", size=1.5, fill=INK, weight="800",
           anchor="middle", rot=-90)

    return _mk("esp32s3_nano_white", "ESP32-S3 Nano（白色 PCB）", W, H, s, pins,
               {"note": "依据用户实拍照片识别：白底黑丝印 · 裸 ESP32-S3 · BOOT/RST · "
                        "PWR+G48 指示灯 · 短边 USB。丝印直接标 GPIO 号。"
                        "未在照片中读到的针位为占位，请以实物丝印为准。"})


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
# 注册表
#
# 模块（传感器/执行器）用本文件里的手工渲染器，逐个按实物资料精修。
# 开发板则来自 `references/boards.json` —— **数据驱动，加板子不用改这里的代码**：
#   * 目录里标了 `hand_tuned` 的板（已按实拍照片精修）→ 转交本文件同名渲染器；
#   * 其余板 → 交给 `boards.render_board()` 按 JSON 里的外形/排针/丝印生成。
# ===========================================================================
REGISTRY = {
    "geekble_nano_esp32s3": render_geekble_nano,
    "esp32s3_nano_white": render_esp32s3_nano_white,
    "mpu6050_gy521": render_mpu6050,
    "as7341_module": render_as7341,
    "as7341_black6": render_as7341_black6,
    "pulse_sensor": render_pulse_sensor,
    "mic_lm2904_module": render_mic_lm2904,
    "mic_sound_blue": render_mic_sound_blue,
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
