#Requires -Version 7.0
# 打印任意 PDF 到本机打印机 — 单入口
# 流程: python 光栅化 PDF->PNG (print_pdf.py) -> .NET System.Drawing.PrintDocument 打印
# 为什么 .NET: win32ui 位图路线死于黑白激光 1bpp 打印 DC 不吃 24bpp 位图 (2026-10-05 实测)
param(
    [Parameter(Mandatory = $true)][string]$Pdf,
    # 不传则取系统默认打印机 (2026-10-05 审计后改, Brother DCP-7057 只是实测环境示例)
    [string]$Printer = "",
    [ValidatePattern('^(all|\d+(-\d+)?)$')][string]$Pages = "all",
    [ValidateRange(1, 99)][int]$Copies = 1,
    [ValidateRange(72, 1200)][int]$Dpi = 300,
    # DotNet = 光栅化后 System.Drawing 打 (位图, 稳); Sumatra = 矢量直打 (质量更好, 需装 SumatraPDF)
    [ValidateSet("DotNet", "Sumatra")][string]$Engine = "DotNet",
    # Sumatra 缩放模式; 默认 none=1:1 (Sumatra 自身默认是 shrink, 会把 A4 缩到 ~96%)
    [ValidateSet("none", "shrink", "fit", "stretch")][string]$Scale = "none",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$py = Join-Path $PSScriptRoot "print_pdf.py"
# 查找顺序: PATH 上的 SumatraPDF -> 默认安装位 -> Program Files
$SumatraExe = $null
foreach ($cand in @((Get-Command SumatraPDF -ErrorAction SilentlyContinue).Source,
                    "$env:LOCALAPPDATA\SumatraPDF\SumatraPDF.exe",
                    "$env:ProgramFiles\SumatraPDF\SumatraPDF.exe")) {
    if ($cand -and (Test-Path $cand)) { $SumatraExe = $cand; break }
}
# 参数互斥提醒: -Scale 只作用于 Sumatra, -Dpi 只作用于 DotNet
if ($Engine -eq "DotNet" -and $Scale -ne "none") { Write-Warning "-Scale only applies to -Engine Sumatra (ignored for DotNet)" }
if ($Engine -eq "Sumatra" -and $PSBoundParameters.ContainsKey('Dpi')) { Write-Warning "-Dpi only applies to -Engine DotNet (Sumatra rasterizes at driver resolution)" }

# Spooler 预检 — 它停着时 Get-Printer/CIM/Sumatra 全给误导性错误 ("printer not found"/
# "no system default printer"/15s 超时), 而这是本 skill 的第一类故障, 必须最先拦
if ((Get-Service Spooler -ErrorAction SilentlyContinue).Status -ne 'Running') {
    throw "Spooler not running - see SKILL.md §1/§5"
}

# -Printer 不传 → 系统默认打印机
# 注意: pwsh7 的 [PrinterSettings]::Default 静态属性是 null (.NET Core 未实现), 别用 — 走 CIM
if (-not $Printer) {
    $Printer = (Get-CimInstance Win32_Printer -Filter "Default=TRUE" | Select-Object -First 1).Name
    if (-not $Printer) { throw "no system default printer; pass -Printer <name>" }
    # 自动解析撞上虚拟打印机会卡在保存对话框/静默入文件 — 直接拦; 显式传参的尊重用户只警告
    if ($Printer -match 'Print to PDF|OneNote|XPS') {
        throw "system default printer is virtual: '$Printer' - pass -Printer <name> to print on paper"
    }
} elseif ($Printer -match 'Print to PDF|OneNote|XPS') {
    Write-Warning "printing to a virtual printer: $Printer (jobs go to file/dialog, not paper)"
}

# -LiteralPath: Test-Path treats [ ] in filenames as wildcards ("report[1].pdf" would not match)
if (-not (Test-Path -LiteralPath $Pdf)) { throw "no such file: $Pdf" }

# --- Sumatra 矢量引擎: 官方 CLI, 不经过光栅化 ---
if ($Engine -eq "Sumatra") {
    # $SumatraExe is $null when the lookup chain found nothing; Test-Path $null dies under
    # Stop preference with a binding error instead of our message — check null first
    if (-not $SumatraExe) { throw "SumatraPDF not found (searched PATH, %LOCALAPPDATA%, %ProgramFiles%)" }
    # 页范围: Sumatra 只认 -print-settings "1-3" (源码 Print.cpp %d-%d 解析), 不认单独的 pages= 前缀;
    # -silent 已在官方 flag 清单 (gen-flags.ts), 用于压制报错弹窗;
    # 缩放: Sumatra 默认 shrink (源码 defaultScaleAdv=Shrink, A4→~96%), 显式 noscale 保证 1:1 与 DotNet 引擎一致
    $sumatraArgs = @("-silent", "-print-to", $Printer)
    $settings = @()
    if ($Pages -ne "all") { $settings += $Pages }
    if ($Scale -ne "none") { $settings += $Scale } else { $settings += "noscale" }
    $sumatraArgs += @("-print-settings", ($settings -join ","))
    if ($DryRun) {
        # parity with the DotNet dry-run: verify the printer exists too
        if (-not (Get-Printer -Name $Printer -ErrorAction SilentlyContinue)) {
            throw "printer not found: $Printer"
        }
        "DRY-RUN engine=Sumatra exe=$SumatraExe args=[$($sumatraArgs -join ' ')] pdf=$Pdf copies=$Copies"
        exit 0
    }
    # 必须用 & 调用: Start-Process 的 ArgumentList 不给含空格参数加引号,
    # "Brother DCP-7057" 会被拆成 printer='Brother' + file='DCP-7057' (2026-10-05 实测踩坑)
    # & 对 GUI 进程不等待, $LASTEXITCODE 会是 null — 成功信号 = spooler 收到 job
    # job 归属: 只认 Id > 启动前最大 Id 的新作业 — 避开别人排队的/卡住的作业造成误判
    for ($i = 1; $i -le $Copies; $i++) {
        $before = @(Get-PrintJob -PrinterName $Printer -ErrorAction SilentlyContinue)
        $maxId = if ($before) { ($before | Measure-Object -Property Id -Maximum).Maximum } else { 0 }
        & $SumatraExe @sumatraArgs $Pdf
        $deadline = (Get-Date).AddSeconds(15)
        $myJob = $null
        while ((Get-Date) -lt $deadline) {
            $myJob = Get-PrintJob -PrinterName $Printer -ErrorAction SilentlyContinue |
                Where-Object { $_.Id -gt $maxId } | Select-Object -First 1
            if ($myJob) { break }
            Start-Sleep -Milliseconds 500
        }
        if (-not $myJob) { throw "no new spooler job within 15s (printer invalid / file unreadable / silent failure)" }
        # 只等自己那个 job 传完再打下一份; 别人的卡 job 不拖累, 自己的超 180s 放行
        $drain = (Get-Date).AddSeconds(180)
        while (Get-PrintJob -PrinterName $Printer -ErrorAction SilentlyContinue |
                Where-Object { $_.Id -eq $myJob.Id }) {
            if ((Get-Date) -gt $drain) { Write-Warning "job $($myJob.Id) still queued after 180s, continuing anyway"; break }
            Start-Sleep -Milliseconds 400
        }
    }
    "OK sumatra spooled x$Copies -> $Printer"
    exit 0
}

# stage 1: 光栅化 (dry-run 只看计划)
if ($DryRun) {
    $dry = & python $py --pdf $Pdf --out-dir (Join-Path $env:TEMP "unused") --pages $Pages --dpi $Dpi --dry-run
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $dry
    Add-Type -AssemblyName System.Drawing.Common
    $probe = New-Object System.Drawing.Printing.PrintDocument
    $probe.PrinterSettings.PrinterName = $Printer
    $valid = $probe.PrinterSettings.IsValid
    # PaperSize reads the device context and throws InvalidPrinterException on an
    # invalid printer — bail out before touching it so "valid=False" actually prints
    if (-not $valid) {
        "printer '$Printer' valid=False (unknown printer - check -Printer name)"
        $probe.Dispose()
        exit 1
    }
    $paper = $probe.DefaultPageSettings.PaperSize
    # 拿不到就跳过 — 输出 PaperSize + 推算 scale, 驱动纸张和 PDF 不一致时提醒
    $paperPtW = [math]::Round($paper.Width * 72 / 100)
    $paperPtH = [math]::Round($paper.Height * 72 / 100)
    $scaleWarn = ""
    # "$dry" stringify: an array -match would NOT populate $Matches if python ever prints >1 line
    if ("$dry" -match 'page0=(\d+)x(\d+)pt') {
        $pdfW = [int]$Matches[1]; $pdfH = [int]$Matches[2]
        $fitScale = [math]::Min($paperPtW / $pdfW, $paperPtH / $pdfH)
        if ([math]::Abs($fitScale - 1.0) -gt 0.02) {
            $scaleWarn = "  <- paper ${paperPtW}x${paperPtH}pt != pdf ${pdfW}x${pdfH}pt, scale=$([math]::Round($fitScale,3)) (content will be shrunk)"
        }
    }
    "printer '$Printer' valid=$valid paper=$($paper.Kind) ${paperPtW}x${paperPtH}pt copies=$Copies$scaleWarn"
    $probe.Dispose()
    exit 0
}

$tmp = Join-Path $env:TEMP ("print_pdf_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
try {
    & python $py --pdf $Pdf --out-dir $tmp --pages $Pages --dpi $Dpi
    if ($LASTEXITCODE -ne 0) { throw "rasterize failed (exit $LASTEXITCODE)" }
    $script:pageList = @(Get-ChildItem $tmp -Filter *.png | Sort-Object Name)
    if ($script:pageList.Count -eq 0) { throw "no pages rasterized" }

    # stage 2: .NET 打印 (GDI+ 自动处理位图到驱动格式转换)
    # pwsh7 注意: 程序集叫 System.Drawing.Common, System.Drawing.Printing 不是程序集名
    Add-Type -AssemblyName System.Drawing
    Add-Type -AssemblyName System.Drawing.Common
    $doc = New-Object System.Drawing.Printing.PrintDocument
    $doc.PrinterSettings.PrinterName = $Printer
    if (-not $doc.PrinterSettings.IsValid) { throw "invalid printer: $Printer" }
    $doc.PrinterSettings.Copies = $Copies
    # 页边距清零: .NET 默认 1 英寸 (100 = 1/100 inch) 四边 → MarginBounds 把整页缩到 75.8%,
    # 8mm 行距打出 6.1mm (2026-10-06 审计发现)。置 0 后 MarginBounds == PageBounds, PDF 按原尺寸铺满。
    # 内容自带页边距 (ruled_paper 15mm), 大于打印机硬边距, 不会被裁。
    $doc.DefaultPageSettings.Margins = [System.Drawing.Printing.Margins]::new(0, 0, 0, 0)
    # OriginAtMargins=true: DefaultPrintController 才会 TranslateTransform(-HardMargin) 把原点
    # 从可打印区左上挪回纸张角 (源码 if (document.OriginAtMargins) 分支); 默认 false 时内容整体
    # 右下偏 ~4mm 硬边距、右下边缘被裁 (2026-10-06 第四轮审计发现)
    $doc.OriginAtMargins = $true
    # 队列里显示 PDF 文件名, 便于人工核对 job
    $doc.DocumentName = [System.IO.Path]::GetFileNameWithoutExtension($Pdf)

    $script:pageIdx = 0
    $doc.add_PrintPage({
        param($src, $e)
        if ($script:pageIdx -ge $script:pageList.Count) { $e.HasMorePages = $false; return }
        $img = [System.Drawing.Image]::FromFile($script:pageList[$script:pageIdx].FullName)
        try {
            $b = $e.MarginBounds
            $fitScale = [Math]::Min($b.Width / $img.Width, $b.Height / $img.Height)
            # 驱动默认纸张 != PDF 页尺寸时静默缩放 — 首页警告一次。
            # $fitScale 混合了单位换算 (px→1/100in = 100/$Dpi), 只跟 unitScale 比才是真实纸张缩放
            $unitScale = 100.0 / $Dpi
            if (-not $script:scaleWarned -and [Math]::Abs($fitScale - $unitScale) -gt 0.02 * $unitScale) {
                Write-Warning "content scaled $([Math]::Round($fitScale / $unitScale, 3))x - printer paper size differs from PDF page size"
                $script:scaleWarned = $true
            }
            $w = [int]($img.Width * $fitScale)
            $h = [int]($img.Height * $fitScale)
            $x = $b.X + [int](($b.Width - $w) / 2)
            $y = $b.Y + [int](($b.Height - $h) / 2)
            $e.Graphics.DrawImage($img, $x, $y, $w, $h)
        } finally {
            $img.Dispose()
        }
        $script:pageIdx++
        $e.HasMorePages = $script:pageIdx -lt $script:pageList.Count
    })

    $doc.Print()
    $doc.Dispose()
    # Print() 返回只代表交给 spooler, 不代表出纸完成
    "OK spooled $($script:pageList.Count) page(s) x$Copies -> $Printer"
} finally {
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }
}
