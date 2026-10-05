# -*- coding: utf-8 -*-
# Ruled notebook paper PDF generator (A4, parameterized)
# Tested defaults: --spacing 8 --gray 0.5 --pt 0.75  (2026-10-05)
import argparse

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm


def main():
    ap = argparse.ArgumentParser(description="Generate ruled notebook paper PDF (A4)")
    ap.add_argument("--out", default="ruled.pdf", help="output PDF path")
    ap.add_argument("--spacing", type=float, default=8.0, help="line spacing mm (default 8)")
    ap.add_argument("--gray", type=float, default=0.5,
                    help="line gray 0-1, 1=white (default 0.5; 0.78 too light on paper)")
    ap.add_argument("--pt", type=float, default=0.75, help="line width in pt (default 0.75)")
    ap.add_argument("--margin", type=float, default=15.0, help="page margin mm (default 15)")
    ap.add_argument("--rgb", default=None,
                    help="override color as R,G,B 0-1 e.g. 0.6,0.7,0.85 (light blue)")
    args = ap.parse_args()

    W, H = A4
    c = canvas.Canvas(args.out, pagesize=A4)
    if args.rgb:
        r, g, b = (float(x) for x in args.rgb.split(","))
        c.setStrokeColorRGB(r, g, b)
    else:
        c.setStrokeColorRGB(args.gray, args.gray, args.gray)
    c.setLineWidth(args.pt)

    x1, x2 = args.margin * mm, W - args.margin * mm
    y = H - args.margin * mm
    n = 0
    while y >= args.margin * mm - 0.01:
        c.line(x1, y, x2, y)
        n += 1
        y -= args.spacing * mm
    c.showPage()
    c.save()
    print(f"OK {args.out} lines={n} spacing={args.spacing}mm gray={args.gray} pt={args.pt}")


if __name__ == "__main__":
    main()
