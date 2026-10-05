# 打印任意 PDF 到本机打印机 — 单入口
# 流程: python 光栅化 PDF->PNG (print_pdf.py) -> .NET System.Drawing.PrintDocument 打印
# 为什么 .NET: win32ui 位图路线死于黑白激光 1bpp 打印 DC 不吃 24bpp 位图 (2026-10-05 实测)
param(
    [Parameter(Mandatory = $true)][string]$Pdf,
    # 不传则取系统默认打印机 (2026-10-05 审计后改, Brother DCP-7057 只是实测环境示例)
    [string]$Printer = "",
    [string]$Pages = "all",
    [int]$Copies = 1,
    [int]$Dpi = 300,
    # DotNet = 光栅化后 System.Drawing 打 (位图, 稳); Sumatra = 矢量直打 (质量更好, 需装 SumatraPDF)
    [ValidateSet("DotNet", "Sumatra")][string]$Engine = "DotNet",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$py = Join-Path $PSScriptRoot "print_pdf.py"
$SumatraExe = "$env:LOCALAPPDATA\SumatraPDF\SumatraPDF.exe"

# -Printer 不传 → 系统默认打印机
# 注意: pwsh7 的 [PrinterSettings]::Default 静态属性是 null (.NET Core 未实现), 别用 — 走 CIM
if (-not $Printer) {
    $Printer = (Get-CimInstance Win32_Printer -Filter "Default=TRUE" | Select-Object -First 1).Name
    if (-not $Printer) { throw "no system default printer; pass -Printer <name>" }
}
# 虚拟打印机照样能收 job 但不出纸, 提醒一句
if ($Printer -match 'Print to PDF|OneNote|XPS') {
    Write-Warning "selected printer looks virtual: $Printer (jobs will be captured to file/dialog, not paper)"
}

if (-not (Test-Path $Pdf)) { throw "no such file: $Pdf" }

# --- Sumatra 矢量引擎: 官方 CLI, 不经过光栅化 ---
if ($Engine -eq "Sumatra") {
    if (-not (Test-Path $SumatraExe)) { throw "SumatraPDF not found: $SumatraExe" }
    # 页范围: Sumatra 只认 -print-settings "1-3" (源码 Print.cpp %d-%d 解析), 不认单独的 pages= 前缀;
    # -silent 已在官方 flag 清单 (gen-flags.ts), 用于压制报错弹窗
    $sumatraArgs = @("-silent", "-print-to", $Printer)
    if ($Pages -ne "all") { $sumatraArgs += @("-print-settings", $Pages) }
    if ($DryRun) {
        "DRY-RUN engine=Sumatra exe=$SumatraExe args=[$($sumatraArgs -join ' ')] pdf=$Pdf copies=$Copies"
        exit 0
    }
    # 必须用 & 调用: Start-Process 的 ArgumentList 不给含空格参数加引号,
    # "Brother DCP-7057" 会被拆成 printer='Brother' + file='DCP-7057' (2026-10-05 实测踩坑)
    # & 对 GUI 进程不等待, $LASTEXITCODE 会是 null — 成功信号 = spooler 收到 job
    # 局限: Get-PrintJob 匹配该打印机上的任意 job (含别人排队的), 平时空队列下够用;
    # 按 DocumentName 反而有 Sumatra 作业名不匹配的风险, 故只加超时不按名匹配
    for ($i = 1; $i -le $Copies; $i++) {
        & $SumatraExe @sumatraArgs $Pdf
        $deadline = (Get-Date).AddSeconds(15)
        $got = $false
        while ((Get-Date) -lt $deadline) {
            if (Get-PrintJob -PrinterName $Printer -ErrorAction SilentlyContinue) { $got = $true; break }
            Start-Sleep -Milliseconds 500
        }
        if (-not $got) { throw "no spooler job within 15s (Sumatra likely popped an error dialog)" }
        # 让本 job 传完再打下一份, 避免轮询抓到上一份的残影; 卡住的队列不能无限等 — 180s 超时放行
        $drain = (Get-Date).AddSeconds(180)
        while (Get-PrintJob -PrinterName $Printer -ErrorAction SilentlyContinue) {
            if ((Get-Date) -gt $drain) { Write-Warning "print job still queued after 180s, continuing anyway"; break }
            Start-Sleep -Milliseconds 400
        }
    }
    "OK sumatra spooled x$Copies -> $Printer"
    exit 0
}

# stage 1: 光栅化 (dry-run 只看计划)
if ($DryRun) {
    & python $py --pdf $Pdf --out-dir (Join-Path $env:TEMP "unused") --pages $Pages --dpi $Dpi --dry-run
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Add-Type -AssemblyName System.Drawing.Common
    $probe = New-Object System.Drawing.Printing.PrintDocument
    $probe.PrinterSettings.PrinterName = $Printer
    "printer '$Printer' valid: $($probe.PrinterSettings.IsValid)"
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
    # 队列里显示 PDF 文件名, 便于人工核对 job
    $doc.DocumentName = [System.IO.Path]::GetFileNameWithoutExtension($Pdf)

    $script:pageIdx = 0
    $doc.add_PrintPage({
        param($src, $e)
        if ($script:pageIdx -ge $script:pageList.Count) { $e.HasMorePages = $false; return }
        $img = [System.Drawing.Image]::FromFile($script:pageList[$script:pageIdx].FullName)
        try {
            $b = $e.MarginBounds
            $scale = [Math]::Min($b.Width / $img.Width, $b.Height / $img.Height)
            $w = [int]($img.Width * $scale)
            $h = [int]($img.Height * $scale)
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
