# -*- coding: utf-8 -*-
# GDI direct print: draw ruled lines straight to printer DC via pywin32.
# The ONLY print path verified on this machine (Edge headless failed twice, see SKILL.md #6).
# Tested: Brother DCP-7057, 600dpi, 0.75pt -> 6px, A4 simplex via driver defaults.
import argparse
import sys

import win32con
import win32print
import win32ui

DEFAULT_PRINTER = "Brother DCP-7057"
PAGE_W = 210.0
PAGE_H = 297.0


def main():
    ap = argparse.ArgumentParser(description="Draw ruled lines directly to a printer (GDI)")
    ap.add_argument("--printer", default=DEFAULT_PRINTER, help="printer name")
    ap.add_argument("--spacing", type=float, default=8.0, help="line spacing mm")
    ap.add_argument("--gray", type=float, default=0.5, help="line gray 0-1")
    ap.add_argument("--pt", type=float, default=0.75, help="pen width pt")
    ap.add_argument("--margin", type=float, default=15.0, help="page margin mm")
    ap.add_argument("--dry-run", action="store_true", help="print plan only, no job")
    args = ap.parse_args()

    names = [p[2] for p in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL)]
    if args.printer not in names:
        print(f"ERROR printer not found: {args.printer}", flush=True)
        print("available:", names, flush=True)
        sys.exit(1)

    n = int((PAGE_H - 2 * args.margin) // args.spacing) + 1
    gray_val = max(0, min(255, int(round(args.gray * 255))))
    color = (gray_val << 16) | (gray_val << 8) | gray_val
    plan = (f"printer={args.printer} lines={n} spacing={args.spacing}mm "
            f"gray={gray_val} pen={args.pt}pt margins={args.margin}mm A4-single-sided(driver)")
    if args.dry_run:
        print(f"DRY-RUN {plan}", flush=True)
        return

    dc = win32ui.CreateDC()
    try:
        dc.CreatePrinterDC(args.printer)  # single-arg; CreateDC() method does NOT exist
    except Exception as e:
        print(f"CreatePrinterDC failed: {e}", flush=True)
        sys.exit(1)

    dpi_x = dc.GetDeviceCaps(win32con.LOGPIXELSX)
    dpi_y = dc.GetDeviceCaps(win32con.LOGPIXELSY)
    pen_w = max(1, int(round(args.pt / 72.0 * dpi_x)))

    def mmx(v):
        return int(round(v / 25.4 * dpi_x))

    def mmy(v):
        return int(round(v / 25.4 * dpi_y))

    # StartDoc: string form first; tuple fallback (pywin32 docstrings are all None)
    started = False
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
    dc.SelectObject(win32ui.CreatePen(win32con.PS_SOLID, pen_w, color))
    sent = 0
    y = args.margin
    while y <= PAGE_H - args.margin + 0.01:
        dc.MoveTo(mmx(args.margin), mmy(y))
        dc.LineTo(mmx(PAGE_W - args.margin), mmy(y))
        sent += 1
        y += args.spacing
    dc.EndPage()
    dc.EndDoc()
    dc.DeleteDC()
    print(f"OK sent {sent} lines ({plan})", flush=True)


if __name__ == "__main__":
    main()
