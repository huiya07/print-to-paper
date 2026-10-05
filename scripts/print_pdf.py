# -*- coding: utf-8 -*-
# PDF -> PNG rasterizer (stage 1 of print pipeline; stage 2 = print_pdf.ps1 PrintDocument).
# pymupdf cannot save BMP and win32ui bitmap route is a dead end (1bpp printer DC),
# so PNG + .NET System.Drawing is the verified-friendly pair.
import argparse
import os
import sys

import pymupdf


def main():
    ap = argparse.ArgumentParser(description="Rasterize PDF pages to PNG for printing")
    ap.add_argument("--pdf", required=True, help="PDF file")
    ap.add_argument("--out-dir", required=True, help="output directory for page PNGs")
    ap.add_argument("--pages", default="all", help='page range "1-3" or "all" (default)')
    ap.add_argument("--dpi", type=int, default=300, help="rasterize DPI (default 300)")
    ap.add_argument("--dry-run", action="store_true", help="plan only, no PNG written")
    args = ap.parse_args()

    if not os.path.isfile(args.pdf):
        print(f"ERROR no such file: {args.pdf}", file=sys.stderr, flush=True)
        sys.exit(1)

    doc = pymupdf.open(args.pdf)
    if args.pages == "all":
        page_list = list(range(doc.page_count))
    else:
        a, b = (args.pages.split("-") + [args.pages])[:2]
        page_list = list(range(int(a) - 1, int(b)))

    if args.dry_run:
        p0 = doc[0]
        print(f"DRY-RUN pdf={args.pdf} pages={len(page_list)}/{doc.page_count} "
              f"page0={p0.rect.width:.0f}x{p0.rect.height:.0f}pt dpi={args.dpi}")
        doc.close()
        return

    os.makedirs(args.out_dir, exist_ok=True)
    for idx in page_list:
        pix = doc[idx].get_pixmap(dpi=args.dpi)
        out = os.path.join(args.out_dir, f"page-{idx + 1:03d}.png")
        pix.save(out)
        print(out, flush=True)
    doc.close()
    print(f"OK rasterized {len(page_list)} page(s) @ {args.dpi}dpi", flush=True)


if __name__ == "__main__":
    main()
