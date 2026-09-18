---
name: ino-fritzing-diagram
description: 从 Arduino/ESP32 sketch（.ino）识别所用电子元件与开发板型号，生成 Fritzing Parts 风格元件 SVG 与「无面包板」接线图。**有实拍照片时优先按照片识别**（照片不够清晰才用 Bing 图片搜索比对，最后才询问用户）。接线图元件均分在开发板两侧，供电/接地直接回到板上引脚（供电红、接地黑、其余每根线颜色不同）。
metadata:
  author: YinglunMao
  agent_created: true
version: 1.3.0
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
 ③ 【判定】照片/Bing 都对不上 → 才停下来问用户
 ④ bing_images.mjs   ── Chrome CDP 搜 Bing 图片，用参考图**比对确认**型号
 ⑤ contact_sheet.py  ── 拼图，用图像识读能力判断 PCB 颜色/外形/接口/丝印
 ⑥ build_parts.py    ── 生成 Fritzing 风格元件 SVG + 引脚坐标表
 ⑦ build_wiring.py   ── 依据网络表生成接线图 SVG（两侧分布 / 无独立电源轨）
 ⑧ check_wiring.py   ── 几何自检：重叠 / 贴线 / 穿体 / 落图错位，**不开浏览器**
 ⑨ render 自检        ── cdp.mjs shot 把 SVG 光栅化，肉眼核对外观后再交付
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
| Node 22+ | `node -v`（需原生 WebSocket） | 装一个 22+（nvm / 官网 / 包管理器均可） |
| Chrome / Chromium / Edge | 任一路径在 `cdp.mjs` 的 `CHROME_CANDIDATES` 中 | 自启 headless；也可用 `CHROME_PATH` 环境变量指定 |
| arduino-cli | `arduino-cli version` | `brew install arduino-cli`（Linux 见官方 apt 源）；仅作旁证，缺了也能跑 |
| Python + Pillow | `python -c "import PIL"` | 装到隔离 venv（`pip install pillow`） |

脚本一律用绝对路径调用。运行时**不要写死路径**（Node 的托管版本目录名会带版本后缀变动），
按下面这段定位，能跑通就行：

```bash
# 本 skill 所在目录（改成你实际放它的位置）
SKILL="${SKILL_DIR:-$HOME/skills/ino-fritzing-diagram}"
# Node 22+：需要原生 WebSocket，取不到或版本过低就装一个 22+
NODE=$(command -v node || true)
# Python：要能 import PIL；缺 Pillow 就建隔离 venv 装一个
PY=$(command -v python3 || true)
# 若已用 venv / 版本管理器管运行时，直接取它的绝对路径，别写死某个产品的安装目录
# 若 $NODE 为空：装 Node 22+（nvm / 官网 / 包管理器任选）
# 若 $PY 缺 Pillow："$PY" -m pip install pillow
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
- 布线器自动分侧扇出：同侧「锚点 → 板外通道 → 各分支」；**跨侧**的线沿板子**短边外侧**绕行，绝不穿过板体。
- **上半区元件必须 `"rot": 180`**，否则引脚朝上、背离板子（`Instance.pin()` 会翻转 `dir`）。

### 布线为什么要「独占坐标」（踩过的坑）

早期版本里**所有跨侧网络共用同一个拐点 y 和同一条竖直车道 x**，结果 4 条网络从 y=478 到 y=787
完全重叠在 x=363 上，看上去就是一根混色的粗线。现在的规则是：

| 对象 | 保证 |
|------|------|
| 水平通道 y | 每个「网络 × 有落点的一侧」**独占**一条，间距恒定 `LANE_GAP` |
| 绕行拐点 y | 每条跨侧网络**独占**一个（板边「颈区」内），间距 `NECK_GAP` |
| 绕行车道 x | 每条跨侧网络**独占**一条（板子短边外侧），间距 `WRAP_GAP`；车道越靠外，拐点离板越远 |
| 空间 | 不够就把元件推远、画布加高（`_need()` 算净空），**绝不压缩间距硬塞** |
| 干线 vs 落线 | 「板引脚竖线」与「元件焊盘竖线」横向近于 `SEP_X` 时，把干线所属网络**挪到更靠板**的位置，让两条竖线的 y 区间不再相交 |

**B. `rails`（早期布局，会拉出红/黑两条总线轨）** —— 仅在用户明确要「电源轨」画法时使用。
`check_wiring.py` 对它同样有效，但它的通道是 spec 写死的（`lane` / `lane_x`），
密度高时更容易挤，**优先用 `two_sided`**。
它现在会做两件补救：落轨竖线若正好落在开发板横向范围内（模块的电源脚正好在板子正下方），
先横挪到板子短边外再落到轨上，不再从板体里穿过；短竖线还会小幅横挪躲开附近的板引脚走线。
顺序上**先画信号线、再画电源线**，这样绕板时才知道信号走线在哪。

`layout` 不写时自动判断：有 `groups` + `board_id` 走 `two_sided`，否则退回 `rails`。

### 自动布局要点

- 上半区在 `y` 小的一侧，下半区在 `y` 大的一侧，开发板居中；两侧元件数量尽量相等
- **不用自己算通道间距**：`_plan_fans()` 会按网络数算净空并自动撑开画布
- 模块**引脚朝向**要对着开发板：上区 `rot:180`、下区不旋转
- 元件标题默认**朝外**（上区在上、下区在下），避免被走线带的竖线穿过；
  想手动指定用 `caption_pos` / `caption_xy`

## 步骤 ⑧ 自检（必做）

**先跑几何自检 —— 不需要开浏览器，能直接判定「线有没有叠在一起」：**

```bash
$PY $SKILL/scripts/build_wiring.py --spec "<sketch>/fritzing/wiring_spec.json" \
    --out "<sketch>/fritzing/wiring.svg" --debug-json /tmp/wiring.debug.json
$PY $SKILL/scripts/check_wiring.py --debug-json /tmp/wiring.debug.json   # 退出码 0 = 通过
```

它按坐标算出四类问题（都是「线看起来糊成一团」的真凶）：

1. **重叠** —— 两条不同网络的线画在同一根线上（共线且区间相交）
2. **贴线** —— 两条不同网络的平行线横向距离小于 `--sep`，中间留不出空隙
3. **穿体** —— 导线从元件本体或开发板内部穿过
4. **错位** —— SVG 里**实际画上去**的元件位置 ≠ 布线按以走的坐标。

第 ④ 条是给 `build_wiring.py` 自己上的保险。踩过的坑：`_plan_fans()` 为了腾出通道会把元件
整体下移，如果**先 `embed()` 落图、后规划**，元件就画在旧坐标上，而导线按新坐标走 ——
线头会整整齐齐地悬在元件外面一整个通道带的距离，`①`～`③` 全都查不出来（因为大家都用新坐标）。
所以 `build()` 里必须先 `_plan_fans()` 再 `embed()`；`Instance.embed()` 会把自己**落图那一刻**
的坐标写成 `data-box`，`check_wiring.py` 拿它跟 `--debug-json` 的外框对照，谁在落图后动过元件立刻露馅。

过不了就回头查 `_plan_fans()` 的通道分配或元件的 `x/y`，**不要靠肉眼硬看**。

**再渲染一张做人工核对**（自检只能查几何，查不了文字压盖与外形是否像实物）：

```bash
$NODE $SKILL/scripts/cdp.mjs shot --url "file://<abs>/wiring.svg" \
      --file /tmp/check.png --width 1460 --height 1560 --scale 1.2 --full true
```

- [ ] 红线只接 VCC，黑线只接 GND，其余线颜色两两不同
- [ ] 汇流点只在真正并联处出现；交叉处没有误加圆点
- [ ] 文字不互相压盖（必要时用 `halo` 白描边，或调 `caption_xy`）
- [ ] 元件比例正常（对照 `_pins.json` 里的 `size_mm`）
- [ ] 可选/未使用的引脚（如代码里没读的 INT）用虚线并在图例注明
- [ ] **板子外形与照片一致**（底色、按钮、USB 位置、指示灯丝印）
- [ ] 图例与注释紧贴内容下方，没有大块空白、也没压到元件

不合格就改 `parts_library.py` / `wiring_spec.json` 后重跑，**不要交付没自检过的 SVG**。

## 复用与扩展

| 想做的事 | 怎么做 |
|---------|--------|
| 支持新元件 | 往 `references/component-catalog.json` 加一条 + 在 `parts_library.py` 加 `render_*()`，并登记进 `REGISTRY` |
| 换开发板 | 往 `references/boards.json` 加一条（尺寸/配色/孔位/排针/装饰件），**不用写代码**；查询用 `boards.py --list` / `--match` |
| 目录外的板 | 自动走 `boards.py` 的 `generic_board()`：引脚名真实、外形示意，并在 `meta.warnings` 里告知 |
| 换配色 | 改 `fritzing_kit.py` 的 `C` 调色板 |
| 线还是挤在一起 | 跑 `check_wiring.py` 看是哪一类（重叠/贴线/穿体/错位），再调 `_plan_fans()` 的间距常量或元件的 `x/y` |
| 线头悬在元件外面 | 说明落图顺序被改了：`build()` 里必须 `_plan_fans()` → `embed()`，跑 `check_wiring.py` 的第 ④ 条能直接指认 |
| 想加一条新的避让规则 | 在 `build_wiring.py` 里加一个几何测试（照 `_seg_clash` 写），让规划阶段反复试探直到满足；不要再靠调大间距常量硬顶 |
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
