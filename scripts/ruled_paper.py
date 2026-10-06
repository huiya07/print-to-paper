# -*- coding: utf-8 -*-
# Ruled notebook paper PDF generator (A4, parameterized)
# Tested defaults: --spacing 8 --gray 0.5 --pt 0.75  (2026-10-05)
import argparse
import os

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

H_MM = A4[1] / mm  # page height in mm (297)


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
    ap.add_argument("--calibrate", action="store_true",
                    help="margin box + corner crosses instead of ruled lines (measure print margins with a ruler)")
    args = ap.parse_args()

    if args.spacing <= 0:
        ap.error("--spacing must be > 0")
    if 2 * args.margin >= H_MM - args.spacing:
        ap.error(f"--margin {args.margin}mm too large for A4 {H_MM}mm with spacing {args.spacing}mm")

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
    # create the output directory if needed (print_pdf.py already does makedirs)
    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    c = canvas.Canvas(args.out, pagesize=A4)
    if args.rgb:
        c.setStrokeColorRGB(*rgb)
    else:
        c.setStrokeColorRGB(gray, gray, gray)
    c.setLineWidth(args.pt)

    x1, x2 = args.margin * mm, W - args.margin * mm
    if args.calibrate:
        # margin box + corner crosses: ruler the box edge to paper edge -> should be --margin
        m = args.margin * mm
        # reportlab rect(x, y, width, height) — NOT corner coords (passing corners made
        # right/top edges land exactly on the paper edge, unmeasurable)
        c.rect(m, m, W - 2 * m, H - 2 * m)
        arm = 4 * mm  # cross arm length
        for cx, cy in ((m, m), (W - m, m), (m, H - m), (W - m, H - m)):
            c.line(cx - arm, cy, cx + arm, cy)
            c.line(cx, cy - arm, cx, cy + arm)
        c.showPage()
        c.save()
        print(f"OK {args.out} calibrate-box margin={args.margin}mm (all 4 edges; corners = crosses) "
              f"gray={gray} pt={args.pt}")
        return
    # top/bottom symmetric — compute in the mm domain with an epsilon so the generator
    # and check_lines.py always agree on the line count (pt-division could drift by 1
    # on boundary parameter combos, e.g. margin 13.5 / spacing 10)
    avail = H_MM - 2 * args.margin
    n = int(avail / args.spacing + 1e-4) + 1
    slack = avail - (n - 1) * args.spacing
    top = args.margin + slack / 2.0  # distance of first line from top edge (mm)
    y = H - top * mm
    for _ in range(n):
        c.line(x1, y, x2, y)
        y -= args.spacing * mm
    c.showPage()
    c.save()
    print(f"OK {args.out} lines={n} spacing={args.spacing}mm gray={gray} pt={args.pt} "
          f"top={top:.1f}mm bottom={args.margin + slack / 2:.1f}mm (symmetric)")


if __name__ == "__main__":
    main()
