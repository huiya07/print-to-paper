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

if (-not (Test-Path $Pdf)) { throw "no such file: $Pdf" }

# --- Sumatra 矢量引擎: 官方 CLI, 不经过光栅化 ---
if ($Engine -eq "Sumatra") {
    if (-not (Test-Path $SumatraExe)) { throw "SumatraPDF not found: $SumatraExe" }
    if ($DryRun) {
        "DRY-RUN engine=Sumatra exe=$SumatraExe printer='$Printer' pdf=$Pdf"
        exit 0
    }
    # 必须用 & 调用: Start-Process 的 ArgumentList 不给含空格参数加引号,
    # "Brother DCP-7057" 会被拆成 printer='Brother' + file='DCP-7057' (2026-10-05 实测踩坑)
    # & 对 GUI 进程不等待, $LASTEXITCODE 会是 null — 成功信号 = spooler 收到 job
    for ($i = 1; $i -le $Copies; $i++) {
        & $SumatraExe -print-to $Printer $Pdf
        $deadline = (Get-Date).AddSeconds(15)
        $got = $false
        while ((Get-Date) -lt $deadline) {
            if (Get-PrintJob -PrinterName $Printer -ErrorAction SilentlyContinue) { $got = $true; break }
            Start-Sleep -Milliseconds 500
        }
        if (-not $got) { throw "no spooler job within 15s (Sumatra likely popped an error dialog)" }
        # 让本 job 传完再打下一份, 避免轮询抓到上一份的残影
        while (Get-PrintJob -PrinterName $Printer -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 400 }
    }
    "OK sumatra printed x$Copies -> $Printer"
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
    "OK printed $($script:pageList.Count) page(s) x$Copies -> $Printer"
} finally {
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }
}
