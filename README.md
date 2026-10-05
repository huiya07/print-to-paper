# print-to-paper

Claude Code (Agent) 打印 skill — 把"打印"这件事交给 agent: 任意 PDF 双引擎打印、横线纸生成、Spooler/队列/PnP 三层诊断、屏幕断线 vs 纸面断线定层。全链路真机实测沉淀 (Windows 11 + Brother DCP-7057 激光打印机, 2026-10)。

> A Claude Code printing skill: dual-engine PDF printing, ruled-paper generation, 3-layer print diagnosis (Spooler / queue / PnP), and screen-vs-paper line-break triage. All paths verified on real hardware: ruler calibration 2026-10-06 passed, all three engines print the margin box at 15mm on all four edges.

## 为什么 / Why

GitHub 上的 agent 打印 skill 几乎是空白 (2026-10-05 检索: 最大办公 skill 集合 [claude-office-skills/skills](https://github.com/claude-office-skills/skills) 的 137 个 SKILL.md 中 0 个与打印相关, 全网仓库关键词+语义检索亦未见同类; 2026-10-06 复核仍为 0)。而打印链路的坑极多 — 本 skill 的 10 条踩坑档案每条都有触发条件和结论:

- `Start-Process` 的 ArgumentList **不给含空格参数加引号** → 打印机名被拆, 报"该打印机不存在"
- Edge headless `--print-to-printer` 在用户开着浏览器时**静默吞参数**
- pwsh7 里程序集叫 `System.Drawing.Common`, `System.Drawing.Printing` 不是程序集名
- 黑白激光打印 DC 是 1bpp, **不吃 24bpp 位图** (位图打印必须走 .NET GDI+)
- pymupdf 不能存 BMP; GUI 进程 `$LASTEXITCODE` 为 null 会误判失败
- 屏幕上"断线"多半是阅读器渲染抖动, **先光栅化定层再改参数**

## 功能 / Features

| 能力 | 入口 |
|---|---|
| 任意 PDF 打印 (.NET 光栅引擎, 默认) | `scripts/print_pdf.ps1 -Pdf file.pdf` |
| 任意 PDF 矢量打印 (SumatraPDF 引擎) | `scripts/print_pdf.ps1 -Pdf file.pdf -Engine Sumatra` |
| 横线纸生成 (行距/灰度/线宽参数化) | `scripts/ruled_paper.py` |
| 横线直画 (GDI, 跳过 PDF 最短路径) | `scripts/print_lines_gdi.py` |
| 断线定层 (光栅化扫描) | `scripts/check_lines.py --pdf x.pdf` |
| 三层诊断 + 10 条踩坑档案 | [SKILL.md](SKILL.md) |

## 安装 / Install

```bash
git clone https://github.com/huiya07/print-to-paper.git ~/.claude/skills/print-to-paper
```

依赖: Python 3 (`pip install reportlab pymupdf pywin32`) · PowerShell 7+ · 可选 [SumatraPDF](https://www.sumatrapdfreader.org) (矢量引擎) · 打印机驱动正常 (Spooler 运行中)。

默认取系统默认打印机; 用 `--printer` / `-Printer` 指定其他打印机 (实测环境为 Brother DCP-7057)。

## 快速开始 / Quick start

```powershell
# 打印任意 PDF (默认 .NET 引擎, 先 dry-run 验参数)
pwsh -File $HOME\.claude\skills\print-to-paper\scripts\print_pdf.ps1 -Pdf doc.pdf -DryRun
pwsh -File $HOME\.claude\skills\print-to-paper\scripts\print_pdf.ps1 -Pdf doc.pdf

# 矢量质量
pwsh -File $HOME\.claude\skills\print-to-paper\scripts\print_pdf.ps1 -Pdf doc.pdf -Engine Sumatra

# 生成横线纸 (A4 8mm 行距)
python ~/.claude/skills/print-to-paper/scripts/ruled_paper.py --out ruled.pdf
```

打印不通? 先走 [SKILL.md](SKILL.md) §1 三层诊断 — 十有八九是 Spooler 停了、或插拔时 Spooler 不在导致队列没建。

## 协议 / License

MIT
