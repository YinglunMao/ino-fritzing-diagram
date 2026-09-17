# ino-fritzing-diagram

**把一份 Arduino / ESP32 / RP2040 的 `.ino` sketch，变成一套能照着接线的硬件物料。**

输入 `.ino` 代码（可选再加一张电路实拍照片），输出：元件清单 → 外观参考图 → Fritzing Parts 风格元件 SVG → 一张**无面包板**的接线图。

这是一个 **skill** —— 一份写给 Agent 的流程说明（`SKILL.md`）加一组独立的命令行脚本。任何能读文档、能跑命令的 Agent 工具都可以用，不绑定特定厂商：Claude Code、Codex、Hermes、OpenClaw，或你自建的 Agent 框架。

## 功能简介

- **元件识别** —— 解析 `.ino` 里的 `#include` / `#define` / I²C 地址 / 注释，列出所用元件，每条附**置信度与判定依据**。
- **照片优先** —— 有实拍照片就先认照片（切片定位、区域放大、旋转读取倒置丝印、采样测量 PCB 底色），照片看不清才去比对网图，询问用户是最后手段。
- **开发板识别** —— 解析板卡定义，得到**丝印名 ↔ GPIO 号**的映射（例如 `D5 ↔ 8`）。已收录 Arduino Uno / Nano、ESP32-DevKitC、NodeMCU、Raspberry Pi Pico 等常见板卡；**未收录的板子也能出图**。
- **外观参考图** —— 用 Chrome DevTools Protocol 搜索并下载元件图片，拼成对照表用于确认型号。
- **元件 SVG** —— 按实物尺寸绘制的 Fritzing Parts 风格矢量图，可无损缩放。
- **接线图** —— 依据代码里的引脚定义绘制：**不出现面包板**，元件均分在开发板两侧，**供电红、接地黑**，其余每根线颜色互不相同，导线绕行板外、不穿板体。
- **产物可复核** —— 每一步的结果都落盘为文件（识别依据、参考图、引脚坐标表、布局规格），错了能改，不必重跑对话。

## 安装

### 1. 依赖

| 依赖 | 要求 | 用途 |
|------|------|------|
| Node.js | 22 或更高（需要原生 `WebSocket`） | 图片搜索、SVG 光栅化 |
| Chrome / Chromium / Edge | 任意近期版本 | 同上；可用 `CHROME_PATH` 环境变量指定 |
| Python | 3.9+ ，含 Pillow | 图像处理与 SVG 生成 |
| arduino-cli | 可选 | 识别开发板型号 |

```bash
python3 -m pip install pillow
```

### 2. 放进你的 Agent 技能目录

```bash
git clone https://github.com/YinglunMao/ino-fritzing-diagram.git \
  <你的技能目录>/ino-fritzing-diagram
```

技能目录的位置因工具而异（如 `~/.claude/skills/`）。若你用的框架没有技能机制，放在任意目录同样可用 —— 把 `SKILL.md` 作为指令交给 Agent，脚本按下面的方式手动调用即可。

### 3. 验证

```bash
python3 <技能目录>/scripts/parse_ino.py --help
node   <技能目录>/scripts/cdp.mjs check      # 应输出 ok: true 与一个 ws:// 地址
```

## 使用

**方式一：交给 Agent。** 把 `.ino`（建议同时附上电路实拍照片）发给它，说明需要接线图。Agent 会按 `SKILL.md` 走完整流程，中间产物全部落在 `<sketch 目录>/fritzing/` 下，最终交付接线图、元件图与说明。

**方式二：手动调脚本。** 全部脚本都是独立的命令行工具，互不依赖框架：

| 脚本 | 作用 |
|------|------|
| `photo_probe.py` | 照片切片 / 放大 / 旋转 / 测色 |
| `parse_ino.py` | 解析 sketch，列出元件 |
| `detect_board.py` | 识别开发板与引脚映射 |
| `bing_images.mjs` | 搜索并下载外观参考图 |
| `contact_sheet.py` | 参考图拼版 |
| `build_parts.py` | 生成元件与开发板 SVG |
| `build_wiring.py` | 生成接线图 SVG |
| `boards.py` | 板卡目录查询（`--list` / `--match` / `--render`） |
| `cdp.mjs` | CDP 客户端（`check` / `shot` / `eval`） |

各脚本的完整参数用 `--help` 查看；执行顺序与每一步的注意事项见 `SKILL.md`。

## 扩展

- **新增元件** —— 在 `references/component-catalog.json` 补一条识别规则，并在 `scripts/parts_library.py` 增加对应渲染器。
- **新增开发板** —— 在 `references/boards.json` 补一条记录即可，无需改代码。

## 目录

```
ino-fritzing-diagram/
├── SKILL.md                  Agent 读的流程说明
├── scripts/                  全部脚本
└── references/
    ├── component-catalog.json  元件识别词典
    ├── boards.json             板卡目录
    └── fritzing-style.md       Fritzing Parts 绘制规范
```

## License

[MIT](LICENSE)
