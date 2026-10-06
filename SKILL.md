---
name: print-to-paper
description: "Windows 11 打印交付 (需 PowerShell 7 + Python + 本地打印机)。何时用: 用户要打印 PDF/打印这个文件、打印不通/打印不了/打印机不认/后台打印程序 Spooler 问题、要生成横线纸/笔记本纸/分隔线、打印出来断线缺线时。涵盖 Spooler/队列/PnP 三层诊断、横线纸生成(reportlab)、任意 PDF 双引擎打印(.NET 光栅/Sumatra 矢量)、GDI 直画(pywin32)、屏幕断线 vs 纸面断线的光栅化定层"
---

# 打印交付 (print-to-paper)

2026-10-05~06 实测沉淀 + 8 轮交叉审计收敛: 横线纸生成→吐纸、任意 PDF 双引擎打印、Spooler 拉起、三层识别、渲染断线排查、三引擎边距标定 (四边 15mm 实测)。

---

## 1. 打印不通 → 三层诊断 (从上往下)

```powershell
# 层1 服务: Spooler 必须 Running (打印的命根子, 停了 Get-Printer 直接报错)
Get-Service Spooler | Select-Object Status, StartType
# 手动停的用 Start-Service; 需提权走三防线(见§5)

# 层2 队列: 有队列才能打
Get-Printer | Select-Object Name, DriverName, PortName, PrinterStatus

# 层3 PnP/驱动: USB 认了 ≠ 队列存在
Get-PnpDevice | Where-Object InstanceId -match 'VID_04F9'   # 换目标 VID
pnputil /enum-drivers                                          # 搜 Printer 类驱动
```

**三层状态矩阵 (10-05 实测)**:

| 现象 | 根因 | 解法 |
|---|---|---|
| 队列在 + PnP OK | 正常 | 直接打 |
| USB OK + 扫描(Image类) OK + **无队列** | **插拔时 Spooler 是停的** (Win11 + 类驱动实测; 机理: 插入瞬间无 Spooler → 建队列步骤静默跳过, WIA 扫描通道不依赖 Spooler 所以扫描认了) | 拉起 Spooler → **拔插一次 USB** → 队列自动重建 (Win11 类驱动兜底, 不用 Windows Update; 其他驱动/系统未验) |
| Get-Printer 报"无法访问后台打印程序服务" | Spooler 停 | §5 拉起 |

## 2. 生成横线纸 PDF (reportlab)

已装: `reportlab 4.4.9`。**固定 A4 页面** (要非 A4 横线纸走 §4 GDI 路径, 它读驱动实际纸张; check_lines 按 PDF 实际页尺扫描, 与生成器无关)。参数速查 (实测调优, 打印观感验证过):

| 参数 | 实测值 | 说明 |
|---|---|---|
| 行距 | **8mm** | 常规横线本密度, A4 34 条 |
| 颜色 | **0.5 灰** | 0.78 太浅 (打印几乎看不见), 0.5 扎实 |
| 线宽 | **0.75pt** | 0.5pt 屏幕渲染易抖 |
| 边距 | 15mm 四边 | |

```bash
python ~/.claude/skills/print-to-paper/scripts/ruled_paper.py --out out.pdf --spacing 8 --gray 0.5 --pt 0.75
```

## 3. 打印任意 PDF → print_pdf.ps1 双引擎 (单入口)

```powershell
# 引擎1 DotNet (默认): python 光栅化 300dpi PNG → System.Drawing.PrintDocument
# 路径写法: pwsh -File 不展开 ~; 反斜杠在 bash 工具里会被当转义吞 — 用带引号正斜杠 (两个 shell 都认), 裸文件名依赖 cwd 别照抄
pwsh -File "$HOME/.claude/skills/print-to-paper/scripts/print_pdf.ps1" -Pdf "file.pdf"                        # 全部页
pwsh -File "$HOME/.claude/skills/print-to-paper/scripts/print_pdf.ps1" -Pdf "file.pdf" -Pages 1-3 -Copies 2
pwsh -File "$HOME/.claude/skills/print-to-paper/scripts/print_pdf.ps1" -Pdf "file.pdf" -DryRun                # 只验参数+打印机

# 引擎2 Sumatra (矢量, 质量更好): 官方 CLI 直打, 不光栅化
pwsh -File "$HOME/.claude/skills/print-to-paper/scripts/print_pdf.ps1" -Pdf "file.pdf" -Engine Sumatra
```

选型: 日常/批量用默认 **DotNet** (稳, 无外部依赖); 线条图/小字要矢量质量用 **Sumatra**。两引擎均实测出纸 (DotNet 含 **2 页多页** @300dpi 光栅化 2s 静默出纸, 10-06); 10-06 边距/缩放改动经标定页量尺确认 (四边 15mm)。

**流程 (烧纸不可逆, 强制)**: 真打前**必须先 `-DryRun`** — 确认页数/份数/打印机解析无误后再去掉跑真打; 带 `-Copies` 时尤其必跑。`-Printer` 不传时取**系统默认打印机**, 默认是虚拟打印机 (Print to PDF/OneNote/XPS) 时直接报错, 显式传的只警告。

**边距标定**: `ruled_paper.py --calibrate` (或 `print_lines_gdi.py --calibrate`) 出"距边 margin 的矩形框+四角十字"页 — 三个引擎各打一张, 量四边到框线距离应全等于 margin (默认 15mm), 一次验证全部边距/偏移/缩放链路。**2026-10-06 三引擎标定实测: 框四边距纸边均 = 15mm ✓** (DotNet/Sumatra/GDI 各一张, Margins=0、OriginAtMargins、GDI v-off、Sumatra noscale 全链路通过)。

**工程细节 (都是踩出来的)**:
- pwsh7 程序集名是 `System.Drawing.Common` — `System.Drawing.Printing` 不是程序集名, Add-Type 会报"找不到路径"
- 成功信号: DotNet 引擎同步返回; Sumatra 是 GUI 进程 `&` 不等待、`$LASTEXITCODE` 为 null — **以 spooler 收到新 job 为准**: 启动前记下当前最大 job Id, 15s 内出现 **Id 更大** 的 job = 成功, 该 job 消失 = 该份传完 (按 Id 归属, 别人排队/卡住的作业不误判)
- DotNet 引擎每页 `DrawImage` 等比缩放进 MarginBounds, 纸张/单双面用驱动首选项 (A4/Duplex=False)。**Margins 已显式置 0** — .NET 默认四边 1 英寸会把内容缩到 75.8% (8mm 行距打出 6.1mm, 2026-10-06 审计发现), 别改回去
- **`OriginAtMargins = $true` 也必须保留**: 默认 false 时 Graphics 原点在可打印区左上而非纸张角, 内容整体右下偏 ~4mm 硬边距、右下边缘被裁 (源码 DefaultPrintController 只在 OriginAtMargins 时 TranslateTransform(-HardMargin))
- Sumatra 引擎脚本默认追加 `noscale` — Sumatra 自身默认 shrink 会把 A4 缩到 ~96% (8mm→7.7mm), 加 noscale 才与 DotNet 的 1:1 一致; 要缩放用 `-Scale shrink|fit|stretch`
- 局限: Margins=0 后满版无边距 PDF 的最外 ~4mm (打印机硬边距) 会被裁 — 横线纸自带 15mm 边距不受影响; 真满版内容先自己内缩再打
- 横向 PDF: DotNet 引擎不自动切纸方向, 横页会被压扁 — 横版用 `-Engine Sumatra` 打 (Sumatra 默认 auto-rotate)
- `-Copies` 已实测 (10-06 ×2): .NET 把份数交打印机驱动层 (DEVMODE), PrintPage 只按文档页调用 — 两份都出图, **不会**出现"第二份因页码游标打空而白页"的担忧

## 4. GDI 直画 (生成式内容直打, 不经 PDF)

**画线类内容** (横线纸/格线) 可跳过 PDF 直接往打印机 DC 画 — 最短路径:

```bash
python ~/.claude/skills/print-to-paper/scripts/print_lines_gdi.py --dry-run
python ~/.claude/skills/print-to-paper/scripts/print_lines_gdi.py   # 真打
```

pywin32 签名实况 (docstring 全 None 别猜): `dc.CreatePrinterDC(printer)` 单参数 (无 `CreateDC` 方法), printer 不传时取系统默认打印机 (虚拟默认同样直接报错, 显式 `--printer` 只警告 — 与 §3 同规则); `dc.StartDoc("name")` 字符串即可; 笔宽 `pt/72*dpi` px (600dpi 下 0.75pt→6px)。
⚠️ **GDI 只适合画线/矢量图元** — 位图路线死于黑白激光 1bpp 打印 DC 不吃 24bpp 位图 (`SelectObject` 报 "Select bitmap object failed"), 打图走 §3。

## 5. Spooler 拉起 (需 Admin, 三防线)

令牌没提权 (`IsInRole(Administrator)`) 别硬跑 `Start-Service` — 报"无法打开服务"。流程: 验令牌 → 写 BOM 脚本 (`[Parser]::ParseFile` 预检) → `Start-Process pwsh -Verb RunAs` 弹 UAC → **每 2s 查一次执行日志, 最长等 60s** → 见日志才删脚本。

## 6. 断线排查: 屏幕断 ≠ 纸上断

屏幕上线断 = PDF 数据真断 或 阅读器渲染抖 (细浅线缩放被抗锯齿吃掉)。先定层:

```bash
python ~/.claude/skills/print-to-paper/scripts/check_lines.py --pdf target.pdf
# "all N lines present and continuous" → PDF 数据完整, 断线更可能来自渲染, 别急着改 PDF
# "BREAKS: ..." → 线中间真断, 查生成代码
# "MISSING: ..." → 整条线缺失, 查生成代码
# "SHORT: ..." → 线两端没画到边距 (被截短), 查生成代码
```

reportlab 单线段生成层不会断; 150dpi 光栅化逐线扫像素: 亮值 ≥240 且内段 ≥4px 判断口, 带内 >80% 空白判整线缺失, 首尾 >10px 白判截短 (三类均已用故意造断的负例 PDF 验证能报出)。10-05 两版全绿 + 纸面完整 → 坐实渲染锅。**适用范围**: 只查第 1 页; 线需深于约 0.9 灰 (白阈值 240, 更浅的线与纸面无法区分, 会全报 MISSING); **`--spacing/--margin` 必须与生成时的参数一致** — 拿错会整版错位误报 (实测: 默认 8mm 扫 10mm 的纸 → MISSING 28/34)。

## 7. ⚠️ 踩坑档案 (别重复踩)

| 坑 | 结论 |
|---|---|
| **Start-Process ArgumentList 引号** | **不给含空格元素加引号!** `-print-to Brother DCP-7057 file.pdf` 被拆成 printer='Brother' + file='DCP-7057' → "该打印机不存在"。用 `&` 调用 (自动引用) 或手动包 `"`"$x`"" |
| **GUI 进程的 $LASTEXITCODE** | `& gui.exe` 不等待, $LASTEXITCODE 为 null — `$null -ne 0` 为 True 会误判失败。以 spooler job/进程退出为信号 |
| **Edge headless `--print-to-printer`** | 两连败: ① 用户开着 Edge 时单实例路由吞参数; ② 独立 profile 依旧无 job 且不退。**别再试** |
| **pymupdf 不能存 BMP** | 只有 png/jpg/pnm 系; GDI 的 LoadBitmapFile 又只认 BMP — 这条缝别再钻, 位图打印走 .NET |
| **屏幕渲染断线** | 越细越浅越抖; 纸面走打印驱动独立光栅化不受影响 — 用 §6 定层, 别凭屏幕改参数 |
| **Out-Printer** | 只打文本, 图/PDF 别用 |
| **Sumatra `-log`** | 要 `-log -log-to-file <path>` 两参数连用; 单 `-log <path>` 时路径掉进位置参数槽 — 被当**待打印文件**报 "Couldn't open file 'xxx.log' for printing" |
| **Sumatra `-list-printers`** | 3.6.1 不认这 flag (master 新增), 会当文件路径打开 |
| **.NET 默认 1 英寸页边距** | `MarginBounds` 默认四边缩 25.4mm → 整页 75.8%, 8mm 行距打出 6.1mm — 脚本已 `Margins=0` 修死, 别改回 (10-06 标定实测: 框四边 15mm ✓) |
| **.NET 打印原点 OriginAtMargins** | 默认 false → Graphics 原点在**可打印区**左上非纸角, 内容右下偏 ~4mm 且右下被裁 — 脚本已设 `$true` (源码只在 true 时 Translate(-HardMargin)), 别改回 (10-06 标定实测: 框四边 15mm ✓) |
| **reportlab 排中文豆腐** | emoji (`⚠️` 的 U+FE0F 变体) 和拉丁字体 (consolas 等) 无中文字形 → PDF 里画成 .notdef 方框; 中文段落用 msyh `<font>` 混排, 生成后**断言文本层无 `\x00`** 再交付 (10-06 打印概览实测踩到) |
| **屏幕配色打黑白丢层次** | 靠色相区分的填充色转灰阶可能直接归零 — #eef3f9 斑马纹实测灰度 242 vs 纸 255, 黑白下等同消失; 填充灰阶压在 **180~210** (`gray=0.2126R+0.7152G+0.0722B`), 浅于 235 ≈ 纸色; 生成后用 `pymupdf.csGRAY` 渲一页预览先看层次再打 (10-06 真打实测) |

## 8. 依赖清单 (10-05 实测环境)

`reportlab 4.4.9` (生成) · `pywin32` (GDI 直画) · `pymupdf 1.28.2` (光栅化+断线扫描) · `SumatraPDF 3.6.1` @ `%LOCALAPPDATA%\SumatraPDF\SumatraPDF.exe` (矢量引擎) · System.Drawing.Common (pwsh7 内置) · Edge (**别用来打印**) · Brother DCP-7057 @ USB001, 600dpi, 类驱动 `Brother Laser Type1 Class Driver`
