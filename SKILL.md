---
name: ino-fritzing-diagram
description: 从 Arduino/ESP32 sketch（.ino）识别所用电子元件与开发板型号，生成 Fritzing Parts 风格元件 SVG 与「无面包板」接线图。**有实拍照片时优先按照片识别**（照片不够清晰才用 Bing 图片搜索比对，最后才询问用户）。接线图元件均分在开发板两侧，供电/接地直接回到板上引脚（供电红、接地黑、其余每根线颜色不同）。
metadata:
  author: WorkBuddy
  agent_created: true
version: 1.1.0
display_name: "Arduino 元件识别与 Fritzing 接线图"
display_name_en: "Arduino Parts Detector & Fritzing Wiring Diagram"
---

# ino-fritzing-diagram

把一个 `.ino` sketch 变成一套硬件可视化物料：**元件清单 → 外观参考图 → Fritzing 风格元件 SVG → 接线图 SVG**。

## 何时使用

- 用户给了 Arduino / ESP32 sketch，想要接线图、元件图、Fritzing parts
- 用户给了**电路/元件实拍照片**，想还原成人能照着接的图
- 需要「这个代码用了哪些模块、怎么连」的可视化说明
- 需要把散乱的引脚 `#define` 整理成一张能照着焊的图

## 总流程

```
 ⓪ photo_probe.py    ── 【有照片就走这条】切片/放大/测色，先从照片认出元件与板子
 ① parse_ino.py      ── 解析 ino：元件清单 + 引脚定义 + I2C 地址 + 注释里的接法
 ② detect_board.py   ── arduino-cli + pins_arduino.h（**仅作旁证，不可单独采信**）
 ③ 【判定】照片/Bing 都对不上 → 才 AskUserQuestion 问用户
 ④ bing_images.mjs   ── Chrome CDP 搜 Bing 图片，用参考图**比对确认**型号
 ⑤ contact_sheet.py  ── 拼图，用图像识读能力判断 PCB 颜色/外形/接口/丝印
 ⑥ build_parts.py    ── 生成 Fritzing 风格元件 SVG + 引脚坐标表
 ⑦ build_wiring.py   ── 依据网络表生成接线图 SVG（两侧分布 / 无独立电源轨）
 ⑧ render 自检        ── cdp.mjs shot 把 SVG 光栅化，肉眼核对后再交付
```

**每一步产物都要落盘**，便于用户复核与二次修改。

### 识别证据的优先级（重要）

**照片 > Bing 参考图比对 > arduino-cli > ino 注释 > 问用户**

`arduino-cli` 的板名**不能单独采信**：ESP32-S3 的原生 USB 会把「上次编译时选的板卡」
写进 USB 描述符（`build.usb_mode=1`），arduino-cli 是按 VID/PID 反查板名的，
于是形成**自我印证的回路** —— 板子换个型号烧进去，它报的还是旧名字。
**必须拿照片核对一遍**再落笔。踩过的坑见文末「实战教训」。

## 目录约定

```
<sketch 目录>/fritzing/
├── refs/                    Bing 下载的外观参考图 + _index.json + _contact_sheet.png
├── parts/                   每个元件一张 SVG（Fritzing Parts 风格）+ _pins.json
├── wiring_spec.json         接线图布局规格（元件实例 + 网络表）
├── wiring.svg               接线图
└── report.md                元件识别与接线说明
```

## 环境依赖

| 依赖 | 检查方式 | 缺失怎么办 |
|------|---------|-----------|
| Node 22+ | `node -v`（需原生 WebSocket） | 用 `install_binary` 装 |
| Chrome / Chromium / Edge | 任一路径在 `cdp.mjs` 的 `CHROME_CANDIDATES` 中 | 自启 headless；也可用 `CHROME_PATH` 环境变量指定 |
| arduino-cli | `arduino-cli version` | `brew install arduino-cli`（Linux 见官方 apt 源）；仅作旁证，缺了也能跑 |
| Python + Pillow | `python -c "import PIL"` | 装到隔离 venv（`pip install pillow`） |

脚本一律用绝对路径调用托管运行时。**Node 版本目录名会变（`22.22.2-2` → `22.22.2-3` …），
不要写死**，用下面这段自动取最新版：

```bash
SKILL="$HOME/.workbuddy/skills/ino-fritzing-diagram"
# Node：托管版本目录名带版本后缀，取最新那个；取不到就退回系统 node
NODE=$(ls -d "$HOME"/.workbuddy/binaries/node/versions/*/bin/node 2>/dev/null | sort -V | tail -1)
[ -x "$NODE" ] || NODE=$(command -v node || true)
# Python：优先托管 venv（保证有 Pillow），否则退回系统 python3
PY="$HOME/.workbuddy/binaries/python/envs/default/bin/python"
[ -x "$PY" ] || PY=$(command -v python3 || true)
# 若 $NODE 为空 → 用 install_binary 装 Node 22+（需要原生 WebSocket）
# 若 $PY 缺 Pillow → "$PY" -m pip install pillow
```

## 步骤 ⓪ 先看照片（有照片就走这一步，优先于一切）

用户给了实拍照片时，**照片是第一证据**。但手机照片常常看不清丝印，
所以先用 `photo_probe.py` 把它变成「看得清的一组图」再看：

```bash
# 0) 看尺寸
$PY $SKILL/scripts/photo_probe.py --photo "<照片>.jpg"

# 1) 全局切片，先找元件在哪（3 行 4 列）
$PY $SKILL/scripts/photo_probe.py --photo "<照片>.jpg" --out probe --tiles 3 4

# 2) 逐个区域放大读丝印
#    · 丝印倒置（板子横躺）→ --rotate 180
#    · 白底黑丝印反差低   → --contrast 2.5
#    · 丝印极细           → --scale 8~10
$PY $SKILL/scripts/photo_probe.py --photo "<照片>.jpg" --out probe \
    --crop 250,805,545,845 --scale 10 --rotate 180 --contrast 2.5 --tag dev_silk

# 3) 客观测 PCB 底色（别用肉眼猜「白板/黑板」——照片会骗人）
$PY $SKILL/scripts/photo_probe.py --photo "<照片>.jpg" \
    --color pcbA=430,890,460,905 --color 木桌=900,1400,930,1415
```

然后**逐个区域读图**，对每个元件记录四件事（这是后面画 SVG 的依据）：

| 记什么 | 为什么 |
|--------|--------|
| **PCB 底色**（白/黑/蓝/深蓝/紫） | 决定 SVG 的 `fill`，是最强的区分特征 |
| **外形指纹** | 圆形板？圆柱咪头？金色采光窗？屏蔽罩？——「一眼认得出」靠它 |
| **引脚数与丝印引脚名** | 直接决定网络表能不能对上（例：`GPIO INT SDA SCL GND VIN`） |
| **安装孔 / 连接器位置** | 影响布局与走线 |

**照片能读清 → 直接按照片画，不用搜图、不用问用户。**
**照片读不清 → 进入步骤 ④，拿 Bing 参考图与照片并排比对，取最像的那个。**
**只有「压根没有照片」时，才走步骤 ③ 问用户。**

> 读丝印时注意：板子横躺在桌面上时丝印往往是倒的，`--rotate 180` 后再读。
> 白底黑丝印的板子对比度低，`--contrast 2.5~3` 才看得清。
> 照片分辨率不够时**不要硬猜**——记下「丝印不可读」，改走 Bing 比对。

## 步骤 ① 解析 sketch

```bash
$PY $SKILL/scripts/parse_ino.py --ino "<path>/xxx.ino"
```

输出要点：
- `components[]`：元件 + `confidence` + `evidence`（**必须把 evidence 给用户看**，让判定可追溯）
- `only_generic_alias: true` 的条目 = 代码只写了通用名（如「咪头模块」），**型号不可推断**
- `i2c_addresses` / `i2c_pins` / `analog_pins` / `defines`
- `net_hints[]`：从注释里挖出的 `X -> GPIOn` 接法线索

识别词典在 `references/component-catalog.json`，未收录的元件按同样结构补一条即可。

## 步骤 ② 识别开发板

```bash
$PY $SKILL/scripts/detect_board.py --ino "<path>/xxx.ino"
```

三级证据链（越靠前越权威）：

1. **照片**（步骤 ⓪，最权威）—— 用户拍了就以此为准
2. `arduino-cli board list --format json` → 实机 FQBN（**旁证**，见下方警告）
3. 核心包 `variants/<variant>/pins_arduino.h` → `D5=8 / A3=4` 这类**丝印名↔GPIO 映射**
4. ino 头部注释 → 兜底（置信度低）

> ⚠️ **不要只凭 arduino-cli 的板名就下结论。**
> ESP32-S3 走原生 USB（`build.usb_mode=1`）时，USB 描述符里的厂商/型号是**上次编译时
> 选的板卡定义烧进去的**。arduino-cli 按 VID/PID 反查板名 → **自己印证自己**，
> 板子换了、固件没换，它照样报旧名字。
> 实战：`pins_arduino.h` 里写着 `USB_PRODUCT "Geekble nano ESP32-S3"`、
> `PID 0x82C5`，arduino-cli 就报 Geekble —— 而实拍照片里是一块**白色 PCB** 的板子。
> **落到 SVG 之前，必须用照片核对一遍外形。**

> **为什么必须做「丝印名↔GPIO」这一步**：代码里写的是 `GPIO8`，而板子上可能印 `D5`，
> 也可能**直接印 `8`**（本 skill 实测过这种板）。接线图必须同时标注，
> 否则用户拿着图找不到焊盘。

多块板同时连接时，输出 `board.candidates`，让用户选。

## 步骤 ③ 照片与 Bing 都对不上，才问用户

**询问是最后手段**，只在下面两种情况才用：

- **完全没有照片**，且代码里只写了通用名/低置信度
- 照片与 Bing 结果**互相矛盾**且无法裁定时（把候选照片一并给用户看）

其他情况一律自己定：照片能看清就按照片，看不清就搜 Bing 比对。

问题要给出**可选项 + 推荐项 + 每项对图的影响**，例如：

| 选项 | 影响 |
|------|------|
| MAX9814 麦克风模块（推荐） | 带 AGC，模拟输出 |
| MAX4466 麦克风模块 | 电位器调增益 |
| 通用电容咪头模块 | 无型号 PCB |

## 步骤 ④ Chrome CDP + Bing 找外观参考图

```bash
$NODE $SKILL/scripts/bing_images.mjs --out "<sketch>/fritzing/refs" --limit 4 \
  --q "AS7341 spectral color sensor module breakout board" \
  --q "MPU6050 GY-521 module"
```

- 自研零依赖 CDP 客户端（`scripts/cdp.mjs`），入口探测顺序：`--ws` 显式指定 → 本机 9222/9229/9333/9334
  的 `/json/version` 或 `/devtools/browser`（**多端口并行探测取最快**）→ 都不通则自启 headless Chrome
  （独立 `user-data-dir`，绝不碰用户浏览器）
- 只创建**后台标签**（`Target.createTarget{background:true}`），用完 `/close`，不动用户已开的页面
- 图片下载走 `curl`（自动继承 `HTTPS_PROXY`），按域名多样性择优、过滤 favicon/占位图
- 结果写 `refs/_index.json`（含来源页 `purl`，便于溯源）

**实测坑位**：
- 本机 Chrome 的 devtools WebSocket 握手可能耗时 **~5s**，探测超时不要小于 9s
- 端口 9222 不提供 HTTP `/json/version` 时仍可直接连 `ws://127.0.0.1:9222/devtools/browser`
- 沙箱内的后台进程可能访问不到本机 CDP，**脚本要在前台跑**

## 步骤 ⑤ 看参考图，定外形

```bash
$PY $SKILL/scripts/contact_sheet.py --refs "<sketch>/fritzing/refs" --cell 300 --cols 4
```

然后用图像识读能力读 `_contact_sheet.png`，确定并用一句话记录每个元件的：

- **PCB 颜色**（蓝/绿/黑/红/紫）+ 尺寸比例
- **接口形态**：排针在长边还是短边、几针、针距 2.54、是否有 STEMMA/JST
- **主要器件**：主芯片封装、电容咪头/屏蔽罩/电位器/LED 的数量与位置
- **丝印文字**：型号名、引脚名（**引脚名决定了接线图能否自解释**）

搜不到合适参考图时（Bing 返回噪声），直接访问厂商官网/立创开源硬件等一手来源；仍不确定就在报告里声明「外形为示意」。

## 步骤 ⑥ 生成 Fritzing 风格元件 SVG

```bash
$PY $SKILL/scripts/build_parts.py --out "<sketch>/fritzing" --all --sheet
```

- 渲染器在 `scripts/parts_library.py`，**每个 `render_*()` 同时返回 SVG 与引脚坐标表**
  —— 引脚坐标与绘图同源，接线图端点必然落在焊盘上，不会出现「图上的焊盘」和「连线的落点」不一致
- 未收录的元件：用 `fritzing_kit.py` 的图元（`pcb / header / chip_qfn / mic_can / trimpot /
  usb_c / tactile / shield_can / mount_hole / led / passive / via / heart`）组合一个新 `render_*()`，
  照抄实物测量尺寸（mm）。**同时把新元件登记进 `REGISTRY`**，下次可复用
- 风格规范见 `references/fritzing-style.md`（务必先读）

## 步骤 ⑦ 生成接线图

```bash
$PY $SKILL/scripts/build_wiring.py --spec "<sketch>/fritzing/wiring_spec.json" \
                                   --out  "<sketch>/fritzing/wiring.svg"
```

### 硬性绘制规则（用户明确要求）

| 规则 | 实现 |
|------|------|
| 不出现面包板 | 开发板与模块直连 |
| **元件均分在开发板两侧** | `layout: "two_sided"` + `groups.top` / `groups.bottom` 各放一半 |
| **不单独拉电源轨** | 每个模块的 VCC/GND **直接连回板上的供电/接地引脚**，不画横贯全图的总线 |
| 供电红、接地黑 | `color: "#E53935"` / `"#212121"` |
| 其余每根线颜色都不同 | 每个信号网络一个独立色值 |
| 引脚依据代码定义 | 端点坐标来自 `parts_library` 的引脚表；网络表来自 `parse_ino` + 照片/板卡定义 |

### 两种布局模式

**A. `two_sided`（推荐，即上面参考图的画法）**

```jsonc
{
  "layout": "two_sided",
  "board_id": "board",
  "groups": {
    "top":    [ /* 上半区元件：pins 朝下 → 用 "rot": 180 */ ],
    "bottom": [ /* 下半区元件：pins 朝上 → 不旋转 */ ]
  },
  "nets": [
    { "id": "3V3", "color": "#E53935",
      "nodes": [["board","3V3"], ["mpu","VCC"], ["as7341","VIN"]] }
  ]
}
```

- `nodes[0]` 是**板上锚点引脚**；其余是各元件引脚。一个网络可同时含上下两侧的元件。
- 布线器自动分侧扇出：同侧直接「锚点 → 板外通道 → 各分支」；**跨侧**的线沿板子
  **短边外侧**绕行，绝不穿过板体。
- 通道按「跨度大的靠板、跨度小的靠外」自动排序，避免交叉。
- **上半区元件必须 `"rot": 180`**，否则引脚朝上、背离板子（`Instance.pin()` 会翻转 `dir`）。

**B. `rails`（旧版，会拉出红/黑两条总线轨）** —— 只有在用户明确要「电源轨」画法时才用。

### 自动布局要点

- 上半区在 `y` 小的一侧，下半区在 `y` 大的一侧，开发板居中；两侧元件数量尽量相等
- 上下两区之间要给通道留够空间（每条通道约 26px，通道数 = 该侧参与的网络数）
- 模块**引脚朝向**要对着开发板：上区 `rot:180`、下区不旋转

## 步骤 ⑧ 自检（必做）

```bash
$NODE $SKILL/scripts/cdp.mjs shot --url "file://<abs>/wiring.svg" \
      --file /tmp/check.png --width 1460 --height 1420 --scale 1.2 --full true
```

读这张 PNG，逐项核对：

- [ ] 每根导线**两端都落在焊盘/丝印位置上**，没有悬空
- [ ] **没有导线穿过开发板板体**（跨侧的线应绕板子短边外侧走）
- [ ] 红线只接 VCC，黑线只接 GND，其余线颜色两两不同
- [ ] 汇流点只在真正并联处出现；交叉处没有误加圆点
- [ ] 文字不互相压盖（必要时用 `halo` 白描边，或调 `caption_xy`）
- [ ] 元件比例正常（对照 `_pins.json` 里的 `size_mm`）
- [ ] 可选/未使用的引脚（如代码里没读的 INT）用虚线并在图例注明
- [ ] **板子外形与照片一致**（底色、按钮、USB 位置、指示灯丝印）

不合格就改 `parts_library.py` / `wiring_spec.json` 后重跑，**不要交付没看过的 SVG**。

## 复用与扩展

| 想做的事 | 怎么做 |
|---------|--------|
| 支持新元件 | 往 `references/component-catalog.json` 加一条 + 在 `parts_library.py` 加 `render_*()`，并登记进 `REGISTRY` |
| 换开发板 | 往 `references/boards.json` 加一条（尺寸/配色/孔位/排针/装饰件），**不用写代码**；查询用 `boards.py --list` / `--match` |
| 目录外的板 | 自动走 `boards.py` 的 `generic_board()`：引脚名真实、外形示意，并在 `meta.warnings` 里告知 |
| 换配色 | 改 `fritzing_kit.py` 的 `C` 调色板 |
| 出一份 PDF/长图 | 用 `cdp.mjs shot` 加大 `--scale` 光栅化，或直接把 SVG 交给用户（矢量可无损缩放） |
| 照片看不清 | `photo_probe.py --tiles` 切片 → `--crop ... --rotate 180 --contrast 2.5` 逐块读 |

### 已收录的元件（`REGISTRY`）

`geekble_nano_esp32s3` · `esp32s3_nano_white`（白色 PCB 版）· `mpu6050_gy521` ·
`as7341_module`（蓝板）· `as7341_black6`（黑板 6 针，照片版）· `pulse_sensor` ·
`mic_lm2904_module`（深蓝 FC-04）· `mic_sound_blue`（亮蓝咪头，照片版）

### 已收录的板卡（`references/boards.json`）

| id | 板子 | 尺寸 | 排针 |
|----|------|------|------|
| `arduino_uno` | Arduino Uno R3 | 68.6×53.4 | 上 18 / 下 14 |
| `arduino_nano` | Arduino Nano | 45.0×17.8 | 左右各 15 |
| `esp32_devkitc` | ESP32 DevKitC v4 | 25.4×52.4 | 左右各 19 |
| `esp8266_nodemcu` | NodeMCU v3 (LoLin) | 25.4×48.0 | 左右各 15 |
| `rp_pico` | Raspberry Pi Pico (RP2040) | 21.0×51.0 | 左右各 20 |
| `esp32s3_nano_white` | ESP32-S3 Nano（白 PCB） | 52.8×20.5 | 上下各 20 |
| `geekble_nano_esp32s3` | Geekble nano ESP32-S3 | 43.2×17.8 | 上下各 15 |

板卡不在这张表里也能跑 —— `generic_board()` 会用真实引脚名兜底渲染。

## 实战教训（踩过的坑，别再踩）

1. **arduino-cli 的板名可能是自己印证自己** —— ESP32-S3 原生 USB 会把上次编译时的
   `USB_PRODUCT` 写进描述符，arduino-cli 按 VID/PID 反查就报那块板。
   实测：报 `Geekble nano ESP32-S3`，照片里却是**白色 PCB** 的另一块板。
   → **落笔前必须用照片核对外形。**
2. **丝印可能是倒的、可能是白底黑字** —— 不 `--rotate 180` / `--contrast 2.5`
   就读不出来；`photo_probe.py --color` 可以客观测底色，别凭肉眼猜。
3. **别把「通用名」当型号** —— 代码写「咪头模块」只是类别，不是型号；
   照片里若能看到圆柱咪头 + 增益电阻，就按通用咪头放大模块画，别硬套 LM2904。
4. **上半区元件必须 `rot: 180`** —— 否则引脚背对开发板，布线器会绕远。
5. **单目的地网络不要漏掉水平段** —— `build_wiring.py::_route_fan_net` 里
   每个目的地都要从「干线与通道的交点」连过去；只画竖线会让导线悬空。
6. Node 版本目录名会变，`NODE=` 别写死（见「环境依赖」的 glob 写法）。
7. 本机 Chrome 的 devtools WebSocket 握手约 **5s**，探测超时不要小于 9s；
   端口 9222 可能没有 HTTP `/json/version`，要直连 `ws://`。
8. CDP 脚本**必须前台运行** —— 沙箱内的后台进程访问不到本机浏览器。
9. **图例与注释要自上而下算好位置** —— 注释超过一行时，若仍按 `H - 30 + i*20`
   递增绘制会直接**画到画布外面**。`_layout_footer()` 现在会自动加高画布并让图例
   压在注释上方；改图例/注释排版时别绕开它。
10. **`arc_text()` 画下方弧线要反向 + flip** —— 默认 `rot = angle + 90` 是给**上方**
    弧线用的；画在圆的下半部必须 `start_deg > end_deg` 且 `flip=True`，
    否则整串字会镜像倒置。
11. **元件上的丝印别和引脚名抢同一条带** —— 圆形板（如 PulseSensor）的顶部被接线
    凸台和引脚名占满，环形丝印要挪到下方弧线，并让开安装孔。

## 交付

用 `present_files` 呈现：`wiring.svg`（主）、`parts/parts_sheet.svg`、各元件 SVG、
`refs/_contact_sheet.png`（照片/Bing 比对依据）、`report.md`。
所有路径都在 `<sketch 目录>/fritzing/` 下。
