# -*- coding: utf-8 -*-
# GDI direct print: draw ruled lines straight to printer DC via pywin32.
# Shortest path for line-type content (no PDF round-trip). PDF printing has its own
# dual engine in print_pdf.ps1 (DotNet raster + Sumatra vector, both verified 2026-10-05);
# Edge headless failed twice — see SKILL.md §7.
# 0.5 gray on a 1bpp laser = driver halftone dots; fine at 6px pen, look changes at thinner pens.
import argparse
import sys

import win32con
import win32print
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
    ap.add_argument("--dry-run", action="store_true", help="print plan only, no job")
    args = ap.parse_args()

    if not args.printer:
        try:
            args.printer = win32print.GetDefaultPrinter()
        except Exception:
            print("ERROR no system default printer; pass --printer", flush=True)
            sys.exit(1)

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
    n_est = int((PAGE_H - 2 * args.margin) // args.spacing) + 1
    plan = (f"printer={args.printer} lines~{n_est}(A4 est) spacing={args.spacing}mm "
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
        # actual paper in device px + hard-printable-area offset: DC origin is the
        # printable-area top-left, NOT the paper corner — add offsets to lay out from paper edge
        phys_w = dc.GetDeviceCaps(win32con.PHYSICALWIDTH)
        phys_h = dc.GetDeviceCaps(win32con.PHYSICALHEIGHT)
        off_x = dc.GetDeviceCaps(win32con.PHYSICALOFFSETX)
        off_y = dc.GetDeviceCaps(win32con.PHYSICALOFFSETY)
        paper_w_mm = phys_w / dpi_x * 25.4
        paper_h_mm = phys_h / dpi_y * 25.4
        pen_w = max(1, int(round(args.pt / 72.0 * dpi_x)))

        def mmx(v):  # v mm from paper edge -> DC x
            return off_x + int(round(v / 25.4 * dpi_x))

        def mmy(v):
            return off_y + int(round(v / 25.4 * dpi_y))

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
            old_pen = dc.SelectObject(win32ui.CreatePen(win32con.PS_SOLID, pen_w, color))
            sent = 0
            # lay out on actual paper size (driver default), fall back to A4 if caps are 0
            pw = paper_w_mm if paper_w_mm > 1 else PAGE_W
            ph = paper_h_mm if paper_h_mm > 1 else PAGE_H
            y = args.margin
            while y <= ph - args.margin + 0.01:
                dc.MoveTo(mmx(args.margin), mmy(y))
                dc.LineTo(mmx(pw - args.margin), mmy(y))
                sent += 1
                y += args.spacing
            dc.SelectObject(old_pen)  # restore pen
            dc.EndPage()
            dc.EndDoc()
            print(f"OK sent {sent} lines (paper {pw:.0f}x{ph:.0f}mm off {off_x},{off_y}px) ({plan})", flush=True)
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
