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

    try:
        gray = float(args.gray)
        if not 0.0 <= gray <= 1.0:
            raise ValueError
    except ValueError:
        ap.error("--gray must be a float 0-1 (e.g. 0.5)")
    if args.rgb:
        try:
            rgb = tuple(float(x) for x in args.rgb.split(","))
            if len(rgb) != 3 or not all(0.0 <= v <= 1.0 for v in rgb):
                raise ValueError
        except ValueError:
            ap.error("--rgb must be 'R,G,B' floats 0-1 (e.g. 0.6,0.7,0.85)")

    W, H = A4
    c = canvas.Canvas(args.out, pagesize=A4)
    if args.rgb:
        c.setStrokeColorRGB(*rgb)
    else:
        c.setStrokeColorRGB(gray, gray, gray)
    c.setLineWidth(args.pt)

    x1, x2 = args.margin * mm, W - args.margin * mm
    # top/bottom symmetric: page height between margins is rarely an exact multiple of
    # spacing (A4/15mm/8mm -> 267mm = 33*8 + 3) — center the slack instead of dropping
    # it all at the bottom (previously top 15mm / bottom 18mm)
    avail = H - 2 * args.margin * mm
    n = int(avail // (args.spacing * mm)) + 1
    slack = avail - (n - 1) * args.spacing * mm
    top = args.margin * mm + slack / 2.0  # distance of first line from top edge
    y = H - top
    for _ in range(n):
        c.line(x1, y, x2, y)
        y -= args.spacing * mm
    c.showPage()
    c.save()
    print(f"OK {args.out} lines={n} spacing={args.spacing}mm gray={gray} pt={args.pt} "
          f"top={top / mm:.1f}mm bottom={slack / 2 / mm + args.margin:.1f}mm (symmetric)")


if __name__ == "__main__":
    main()
