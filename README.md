# ino-fritzing-diagram

**把一份 Arduino / ESP32 / RP2040 的 `.ino` sketch，变成一套能照着接线的硬件物料。**

输入 `.ino` 代码（可再加一张电路实拍照片），输出：元件清单 → 外观参考图 → Fritzing Parts 风格元件 SVG → 一张**无面包板**的接线图。

这是一个 **skill** —— 一份写给 Agent 的流程说明（`SKILL.md`）加一组独立的命令行脚本。任何能读文档、能跑命令的 Agent 工具都可以用，不绑定特定厂商或框架。

## 安装

### 1. 依赖

| 依赖 | 要求 | 用途 |
|------|------|------|
| Python | 3.9+，含 Pillow | 图像处理与 SVG 生成 |
| Node.js | 22 或更高（需要原生 `WebSocket`） | 图片搜索、SVG 光栅化 |
| Chrome / Chromium / Edge | 任意近期版本，可用 `CHROME_PATH` 指定 | 同上 |
| arduino-cli | 可选 | 辅助识别开发板型号 |

```bash
python3 -m pip install pillow
```

### 2. 放进你的 Agent 技能目录

**方式一：让 Agent 自己装。** 把下面这段原样发给你的 Agent，它会自己完成克隆与依赖检查：

```text
请从 GitHub 安装 skill：https://github.com/YinglunMao/ino-fritzing-diagram

要求：
1. 克隆到你的技能目录，目录名保持 ino-fritzing-diagram；如果你的框架没有技能机制，就放到一个固定目录，
   并把该目录下的 SKILL.md 作为后续使用该 skill 的指令来源。
2. 按仓库 README 核对依赖：Python 3.9+（含 Pillow）、Node.js 22+、Chrome/Chromium，缺什么就装什么。
3. 跑一遍 README「验证」一节里的命令，把结果告诉我。
```

**B. 手动克隆。**

```bash
git clone https://github.com/YinglunMao/ino-fritzing-diagram.git \
  <你的技能目录>/ino-fritzing-diagram
```

技能目录的位置因工具而异。若你用的框架没有技能机制，把仓库放在任意目录同样可用：把 `SKILL.md` 作为指令交给 Agent，脚本按下文方式手动调用即可。

### 3. 验证

```bash
python3 <技能目录>/scripts/parse_ino.py --help
node   <技能目录>/scripts/cdp.mjs check      # 应输出 ok: true 与一个 ws:// 地址
```

## 使用

**方式一：交给 Agent。** 把 `.ino`（建议同时附上电路实拍照片）发给它，说明需要接线图。Agent 会按 `SKILL.md` 走完整流程，中间产物全部落在 `<sketch 目录>/fritzing/` 下。

**方式二：手动调脚本。** 全部脚本都是独立的命令行工具：

| 脚本 | 作用 |
|------|------|
| `photo_probe.py` | 照片切片 / 放大 / 旋转 / 测色 |
| `parse_ino.py` | 解析 sketch，列出元件 |
| `detect_board.py` | 识别开发板与引脚映射 |
| `bing_images.mjs` | 搜索并下载外观参考图 |
| `contact_sheet.py` | 参考图拼版 |
| `build_parts.py` | 生成元件与开发板 SVG |
| `build_wiring.py` | 生成接线图 SVG（`--debug-json` 可导出几何数据） |
| `check_wiring.py` | 接线图几何自检（重叠 / 贴线 / 穿体 / 落图错位） |
| `boards.py` | 板卡目录查询（`--list` / `--match` / `--render`） |
| `cdp.mjs` | Chrome DevTools Protocol 客户端（`check` / `shot` / `eval`） |

各脚本的完整参数用 `--help` 查看；执行顺序与每一步的注意事项见 `SKILL.md`。

## 目录

```
ino-fritzing-diagram/
├── SKILL.md                      流程说明
├── scripts/                      命令行脚本
└── references/
    ├── component-catalog.json    元件识别词典
    ├── boards.json               板卡目录
    └── fritzing-style.md         绘制规范
```

## License

[MIT](LICENSE)
