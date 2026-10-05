# -*- coding: utf-8 -*-
# Rasterize a ruled-paper PDF and detect line gaps programmatically.
# Purpose: decide whether "broken lines" are real (PDF data) or viewer rendering jitter.
# 2026-10-05: old (0.78 gray/0.5pt) and new (0.5/0.75pt) both scanned clean -> rendering issue.
# 2026-10-06 audit: fully-missing line used to pass (gap (0,w) filtered by inner) -> now flagged.
# Single-page tool: only checks page 1 (ruled paper is generated single-page).
import argparse
import sys

try:
    import pymupdf  # PyMuPDF >= 1.24.3
except ImportError:  # legacy package name
    import fitz as pymupdf

MM_PER_PT = 25.4 / 72.0


def check_lines(path, dpi, spacing, margin):
    if spacing <= 0:
        print("ERROR --spacing must be > 0", file=sys.stderr, flush=True)
        return 1
    try:
        doc = pymupdf.open(path)
    except Exception as e:
        print(f"ERROR cannot open PDF: {path} ({e})", file=sys.stderr, flush=True)
        return 1
    if doc.needs_pass:
        print(f"ERROR encrypted PDF (password required): {path}", file=sys.stderr, flush=True)
        doc.close()
        return 1
    page = doc[0]
    pix = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72.0, dpi / 72.0))
    w, h, s, stride, n = pix.width, pix.height, pix.samples, pix.stride, pix.n
    pw_mm = page.rect.width * MM_PER_PT
    ph_mm = page.rect.height * MM_PER_PT
    x1 = int(margin / pw_mm * w) + 5
    x2 = int((pw_mm - margin) / pw_mm * w) - 5
    # same symmetric-slack formula as ruled_paper.py (mm domain + epsilon, so boundary
    # parameter combos can't drift apart by one line and false-positive MISSING)
    avail = ph_mm - 2 * margin
    if avail <= 0:
        print(f"ERROR --margin {margin}mm too large for page {ph_mm:.0f}mm", file=sys.stderr, flush=True)
        doc.close()
        return 1
    n_expected = int(avail / spacing + 1e-4) + 1
    slack = avail - (n_expected - 1) * spacing
    y_start = margin + slack / 2.0
    problems = []  # (kind, line_no, y_mm, detail)
    n_lines = 0
    y_mm = y_start
    while n_lines < n_expected:
        n_lines += 1
        py = int(round(y_mm / ph_mm * h))
        rows = [s[yy * stride + x1 * n: yy * stride + x2 * n][0::n]
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
        total = len(mins)
        missing = [g for g in gaps if g[1] - g[0] > 0.8 * total]  # whole line (nearly) gone
        inner = [(a, b) for a, b in gaps if a > 8 and b < total - 8 and (b - a) <= 0.8 * total]
        if missing:
            problems.append(("MISSING", n_lines, round(y_mm, 1), missing))
        else:
            if inner:
                problems.append(("GAP", n_lines, round(y_mm, 1), inner))
            # ends: the line must reach both scan edges — inner-gap filter intentionally
            # ignores <8px edge gaps, so trimmed ends need their own check (10px tol)
            lit = [i for i, v in enumerate(mins) if v < 240]
            if lit:
                if lit[0] > 10:
                    problems.append(("SHORT-L", n_lines, round(y_mm, 1), lit[0]))
                if lit[-1] < total - 11:
                    problems.append(("SHORT-R", n_lines, round(y_mm, 1), total - 1 - lit[-1]))
        y_mm += spacing
    doc.close()
    if problems:
        miss = [p for p in problems if p[0] == "MISSING"]
        gaps_p = [p for p in problems if p[0] == "GAP"]
        shorts = [p for p in problems if p[0].startswith("SHORT")]
        if gaps_p:
            print(f"BREAKS: {len(gaps_p)}/{n_lines} lines have inner gaps:")
            for _, ln, ymm, g in gaps_p:
                print(f"  line#{ln} y={ymm}mm gap_px={g}")
        if miss:
            print(f"MISSING: {len(miss)}/{n_lines} lines absent (scan band >80% blank):")
            for _, ln, ymm, g in miss:
                print(f"  line#{ln} y={ymm}mm white_px={g}")
        if shorts:
            print(f"SHORT: {len(shorts)} line end(s) do not reach the margin:")
            for kind, ln, ymm, g in shorts:
                side = "left" if kind.endswith("L") else "right"
                print(f"  line#{ln} y={ymm}mm {side} end short by {g}px")
        return 1
    print(f"all {n_lines} lines present and continuous - PDF data intact "
          f"(if screen shows breaks, they come from rendering, not this file)")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Detect line gaps in a ruled-paper PDF (page 1 only)")
    ap.add_argument("--pdf", required=True, help="PDF to scan")
    ap.add_argument("--dpi", type=int, default=150, help="rasterize DPI (default 150)")
    ap.add_argument("--spacing", type=float, default=8.0, help="expected line spacing mm")
    ap.add_argument("--margin", type=float, default=15.0, help="expected margin mm")
    args = ap.parse_args()
    raise SystemExit(check_lines(args.pdf, args.dpi, args.spacing, args.margin))


if __name__ == "__main__":
    main()
