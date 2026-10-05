# -*- coding: utf-8 -*-
# GDI direct print: draw ruled lines straight to printer DC via pywin32.
# Shortest path for line-type content (no PDF round-trip). PDF printing has its own
# dual engine in print_pdf.ps1 (DotNet raster + Sumatra vector, both verified 2026-10-05);
# Edge headless failed twice — see SKILL.md §7.
# 0.5 gray on a 1bpp laser = driver halftone dots; fine at 6px pen, look changes at thinner pens.
import argparse
import re
import sys

import win32con
import win32print
import win32serviceutil
import win32ui

PAGE_W = 210.0
PAGE_H = 297.0


def main():
    ap = argparse.ArgumentParser(description="Draw ruled lines directly to a printer (GDI)")
    ap.add_argument("--printer", default=None, help="printer name (default: system default printer)")
    ap.add_argument("--spacing", type=float, default=8.0, help="line spacing mm")
    ap.add_argument("--gray", type=float, default=0.5, help="line gray 0-1")
    ap.add_argument("--pt", type=float, default=0.75, help="pen width pt")
    ap.add_argument("--margin", type=float, default=15.0, help="page margin mm")
    ap.add_argument("--calibrate", action="store_true",
                    help="margin box + corner crosses instead of ruled lines (measure print margins)")
    ap.add_argument("--dry-run", action="store_true", help="print plan only, no job")
    args = ap.parse_args()

    if args.spacing <= 0:
        ap.error("--spacing must be > 0")
    # Spooler preflight: with it stopped, EnumPrinters returns empty and the script would
    # misleadingly claim the (correctly named) printer "not found"
    if win32serviceutil.QueryServiceStatus("Spooler")[1] != 4:  # 4 = SERVICE_RUNNING
        print("ERROR Spooler not running - see SKILL.md §1/§5", flush=True)
        sys.exit(1)

    if not args.printer:
        try:
            args.printer = win32print.GetDefaultPrinter()
        except Exception:
            print("ERROR no system default printer; pass --printer", flush=True)
            sys.exit(1)
        # mirror print_pdf.ps1: auto-resolved virtual printer -> error, explicit -> warn
        if re.search('Print to PDF|OneNote|XPS', args.printer):
            print(f"ERROR system default printer is virtual: '{args.printer}' - pass --printer <name>", flush=True)
            sys.exit(1)
    elif re.search('Print to PDF|OneNote|XPS', args.printer):
        print(f"WARNING printing to a virtual printer: {args.printer}", flush=True)

    # LOCAL alone misses network/shared printers -> also enumerate connections
    names = [p[2] for p in win32print.EnumPrinters(
        win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)]
    if args.printer not in names:
        print(f"ERROR printer not found: {args.printer}", flush=True)
        print("available:", names, flush=True)
        sys.exit(1)

    gray_val = max(0, min(255, int(round(args.gray * 255))))
    color = (gray_val << 16) | (gray_val << 8) | gray_val
    # dry-run can't query paper caps without a DC — estimate on A4, real print reports actual
    n_est = int((PAGE_H - 2 * args.margin) / args.spacing + 1e-4) + 1
    if args.dry_run and n_est < 1 and not args.calibrate:
        # A4 estimate is only valid in dry-run (no DC yet); real prints validate against
        # the ACTUAL paper size after CreatePrinterDC — don't kill e.g. margin 200 on A3
        ap.error(f"--margin {args.margin}mm leaves no room for a line on A4")
    what = "calibrate-box" if args.calibrate else f"lines~{n_est}(A4 est)"
    plan = (f"printer={args.printer} {what} spacing={args.spacing}mm "
            f"gray={gray_val} pen={args.pt}pt margins={args.margin}mm single-sided(driver)")
    if args.dry_run:
        print(f"DRY-RUN {plan}", flush=True)
        return

    dc = win32ui.CreateDC()
    try:
        dc.CreatePrinterDC(args.printer)  # single-arg; CreateDC() method does NOT exist
    except Exception as e:
        print(f"CreatePrinterDC failed: {e}", flush=True)
        sys.exit(1)

    try:
        dpi_x = dc.GetDeviceCaps(win32con.LOGPIXELSX)
        dpi_y = dc.GetDeviceCaps(win32con.LOGPIXELSY)
        # DC origin = printable-area top-left (dotnet DefaultPrintController translates
        # -PHYSICALOFFSET to reach the paper corner, proving the raw origin is NOT the
        # paper corner). Paper corner sits at (-off_x, -off_y) in DC coords.
        phys_w = dc.GetDeviceCaps(win32con.PHYSICALWIDTH)
        phys_h = dc.GetDeviceCaps(win32con.PHYSICALHEIGHT)
        off_x = dc.GetDeviceCaps(win32con.PHYSICALOFFSETX)
        off_y = dc.GetDeviceCaps(win32con.PHYSICALOFFSETY)
        paper_w_mm = phys_w / dpi_x * 25.4
        paper_h_mm = phys_h / dpi_y * 25.4
        pen_w = max(1, int(round(args.pt / 72.0 * dpi_x)))

        def mmx(v):  # v mm from paper edge -> DC x: subtract offset, NOT add (v+off = 2x hard margin)
            return int(round(v / 25.4 * dpi_x)) - off_x

        def mmy(v):
            return int(round(v / 25.4 * dpi_y)) - off_y

        # resolve paper size and validate margin BEFORE StartDoc — exiting after
        # StartDoc/StartPage would leave a half-open job in the spooler (blank feed).
        # sys.exit(1) so agents don't mistake the failure for success (return == rc 0);
        # SystemExit still runs the finally below.
        pw = paper_w_mm if paper_w_mm > 1 else PAGE_W
        ph = paper_h_mm if paper_h_mm > 1 else PAGE_H
        if ph - 2 * args.margin <= 0 or pw - 2 * args.margin <= 0:
            print(f"ERROR --margin {args.margin}mm too large for paper {pw:.0f}x{ph:.0f}mm", flush=True)
            sys.exit(1)

        started = False
        try:
            # StartDoc: string form first; tuple fallback (pywin32 docstrings are all None)
            for attempt in (lambda: dc.StartDoc("ruled-lines"),
                            lambda: dc.StartDoc(("ruled-lines", None, None))):
                try:
                    attempt()
                    started = True
                    break
                except TypeError:
                    pass
            if not started:
                print("StartDoc: no variant accepted", flush=True)
                sys.exit(1)

            dc.StartPage()
            # hold a python reference: a pen selected into the DC must not be GC'd mid-draw
            pen = win32ui.CreatePen(win32con.PS_SOLID, pen_w, color)
            old_pen = dc.SelectObject(pen)
            sent = 0
            if args.calibrate:
                # margin box + corner crosses — ruler each box edge to the paper edge
                x1, x2 = args.margin, pw - args.margin
                y1, y2 = args.margin, ph - args.margin
                for a, b in (((x1, y1), (x2, y1)), ((x2, y1), (x2, y2)),
                             ((x2, y2), (x1, y2)), ((x1, y2), (x1, y1))):
                    dc.MoveTo(mmx(a[0]), mmy(a[1]))
                    dc.LineTo(mmx(b[0]), mmy(b[1]))
                arm = 4.0
                for cx, cy in ((x1, y1), (x2, y1), (x1, y2), (x2, y2)):
                    dc.MoveTo(mmx(cx - arm), mmy(cy))
                    dc.LineTo(mmx(cx + arm), mmy(cy))
                    dc.MoveTo(mmx(cx), mmy(cy - arm))
                    dc.LineTo(mmx(cx), mmy(cy + arm))
                sent = 4  # 4 box edges
            else:
                # symmetric slack centering — same formula as ruled_paper.py / check_lines.py
                avail = ph - 2 * args.margin
                n = int(avail / args.spacing + 1e-4) + 1
                y = args.margin + (avail - (n - 1) * args.spacing) / 2.0
                for _ in range(n):
                    dc.MoveTo(mmx(args.margin), mmy(y))
                    dc.LineTo(mmx(pw - args.margin), mmy(y))
                    sent += 1
                    y += args.spacing
            dc.SelectObject(old_pen)  # restore pen; keep python ref till here (PyCPen has no DeleteObject)
            del pen
            dc.EndPage()
            dc.EndDoc()
            kind = "calibrate box" if args.calibrate else f"{sent} lines"
            print(f"OK sent {kind} (paper {pw:.0f}x{ph:.0f}mm off {off_x},{off_y}px) ({plan})", flush=True)
        except Exception:
            # without AbortDoc a crashed draw leaves a stuck job in the spooler
            if started:
                try:
                    dc.AbortDoc()
                except Exception:
                    pass
            raise
    finally:
        dc.DeleteDC()


if __name__ == "__main__":
    main()
