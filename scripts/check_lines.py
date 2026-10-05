# -*- coding: utf-8 -*-
# Rasterize a ruled-paper PDF and detect line gaps programmatically.
# Purpose: decide whether "broken lines" are real (PDF data) or viewer rendering jitter.
# 2026-10-05: old (0.78 gray/0.5pt) and new (0.5/0.75pt) both scanned clean -> rendering issue.
import argparse

import pymupdf

PAGE_W_MM = 210.0
PAGE_H_MM = 297.0


def check_lines(path, dpi, spacing, margin):
    doc = pymupdf.open(path)
    page = doc[0]
    pix = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72.0, dpi / 72.0))
    w, h, s = pix.width, pix.height, pix.samples
    stride = w * 3
    x1 = int(margin / PAGE_W_MM * w) + 5
    x2 = int((PAGE_W_MM - margin) / PAGE_W_MM * w) - 5
    problems = []
    n = 0
    y_mm = margin
    while y_mm <= PAGE_H_MM - margin + 0.01:
        n += 1
        py = int(round(y_mm / PAGE_H_MM * h))
        rows = [s[yy * stride + x1 * 3: yy * stride + x2 * 3][0::3]
                for yy in range(max(0, py - 2), min(h, py + 3))]
        if not rows:
            y_mm += spacing
            continue
        mins = [min(t) for t in zip(*rows)]  # per-x darkest across y band
        gaps, gap_start = [], None
        for i, v in enumerate(mins):
            if v >= 240:  # near-white = not a line pixel
                if gap_start is None:
                    gap_start = i
            else:
                if gap_start is not None and i - gap_start >= 4:
                    gaps.append((gap_start, i))
                gap_start = None
        if gap_start is not None and len(mins) - gap_start >= 4:
            gaps.append((gap_start, len(mins)))
        inner = [(a, b) for a, b in gaps if a > 8 and b < len(mins) - 8]
        if inner:
            problems.append((n, round(y_mm, 1), inner))
        y_mm += spacing
    doc.close()
    if problems:
        print(f"BREAKS: {len(problems)}/{n} lines have inner gaps:")
        for ln, ymm, g in problems:
            print(f"  line#{ln} y={ymm}mm gap_px={g}")
        return 1
    print(f"all {n} lines continuous - no gaps (if screen shows breaks: it's renderer jitter)")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Detect line gaps in a ruled-paper PDF")
    ap.add_argument("--pdf", required=True, help="PDF to scan")
    ap.add_argument("--dpi", type=int, default=150, help="rasterize DPI (default 150)")
    ap.add_argument("--spacing", type=float, default=8.0, help="expected line spacing mm")
    ap.add_argument("--margin", type=float, default=15.0, help="expected margin mm")
    args = ap.parse_args()
    raise SystemExit(check_lines(args.pdf, args.dpi, args.spacing, args.margin))


if __name__ == "__main__":
    main()
