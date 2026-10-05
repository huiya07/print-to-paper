---
name: print-to-paper
description: "Windows 11 打印交付 (需 PowerShell 7 + Python + 本地打印机)。何时用: 用户要打印 PDF/打印这个文件、打印不通/打印不了/打印机不认/后台打印程序 Spooler 问题、要生成横线纸/笔记本纸/分隔线、打印出来断线缺线时。涵盖 Spooler/队列/PnP 三层诊断、横线纸生成(reportlab)、任意 PDF 双引擎打印(.NET 光栅/Sumatra 矢量)、GDI 直画(pywin32)、屏幕断线 vs 纸面断线的光栅化定层"
---

# 打印交付 (print-to-paper)

2026-10-05 实测沉淀: 横线纸生成→吐纸、任意 PDF 双引擎打印、Spooler 拉起、三层识别、渲染断线排查。

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

已装: `reportlab 4.4.9`。参数速查 (实测调优, 打印观感验证过):

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
pwsh -File print_pdf.ps1 -Pdf "file.pdf"                        # 全部页
pwsh -File print_pdf.ps1 -Pdf "file.pdf" -Pages 1-3 -Copies 2
pwsh -File print_pdf.ps1 -Pdf "file.pdf" -DryRun                # 只验参数+打印机

# 引擎2 Sumatra (矢量, 质量更好): 官方 CLI 直打, 不光栅化
pwsh -File print_pdf.ps1 -Pdf "file.pdf" -Engine Sumatra
```

选型: 日常/批量用默认 **DotNet** (稳, 无外部依赖); 线条图/小字要矢量质量用 **Sumatra**。两引擎均 10-05 实测出纸。

**流程 (烧纸不可逆, 强制)**: 真打前**必须先 `-DryRun`** — 确认页数/份数/打印机解析无误后再去掉跑真打; 带 `-Copies` 时尤其必跑。`-Printer` 不传时取**系统默认打印机**。

**工程细节 (都是踩出来的)**:
- pwsh7 程序集名是 `System.Drawing.Common` — `System.Drawing.Printing` 不是程序集名, Add-Type 会报"找不到路径"
- 成功信号: DotNet 引擎同步返回; Sumatra 是 GUI 进程 `&` 不等待、`$LASTEXITCODE` 为 null — **以 spooler 收到 job 为准**: `Get-PrintJob -PrinterName <名>` 15s 内出现 job = 成功, job 消失 = 该份传完 (脚本内已按此轮询, 手动调 Sumatra 时照此判断)
- DotNet 引擎每页 `DrawImage` 等比缩放进 MarginBounds, 纸张/单双面用驱动首选项 (A4/Duplex=False)。**Margins 已显式置 0** — .NET 默认四边 1 英寸会把内容缩到 75.8% (8mm 行距打出 6.1mm, 2026-10-06 审计发现), 别改回去
- 横向 PDF: DotNet 引擎不自动切纸方向, 横页会被压扁 — 横版用 `-Engine Sumatra` 打

## 4. GDI 直画 (生成式内容直打, 不经 PDF)

**画线类内容** (横线纸/格线) 可跳过 PDF 直接往打印机 DC 画 — 最短路径:

```bash
python ~/.claude/skills/print-to-paper/scripts/print_lines_gdi.py --dry-run
python ~/.claude/skills/print-to-paper/scripts/print_lines_gdi.py   # 真打
```

pywin32 签名实况 (docstring 全 None 别猜): `dc.CreatePrinterDC(printer)` 单参数 (无 `CreateDC` 方法), printer 不传时取系统默认打印机; `dc.StartDoc("name")` 字符串即可; 笔宽 `pt/72*dpi` px (600dpi 下 0.75pt→6px)。
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
```

reportlab 单线段生成层不会断; 150dpi 光栅化逐线扫像素, 亮值 ≥240 且内段 ≥4px 判断。10-05 两版全绿 + 纸面完整 → 坐实渲染锅。

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
| **.NET 默认 1 英寸页边距** | `MarginBounds` 默认四边缩 25.4mm → 整页 75.8%, 8mm 行距打出 6.1mm — 脚本已 `Margins=0` 修死, 别改回 (2026-10-06 审计发现) |

## 8. 依赖清单 (10-05 实测环境)

`reportlab 4.4.9` (生成) · `pywin32` (GDI 直画) · `pymupdf 1.28.2` (光栅化+断线扫描) · `SumatraPDF 3.6.1` @ `%LOCALAPPDATA%\SumatraPDF\SumatraPDF.exe` (矢量引擎) · System.Drawing.Common (pwsh7 内置) · Edge (**别用来打印**) · Brother DCP-7057 @ USB001, 600dpi, 类驱动 `Brother Laser Type1 Class Driver`
