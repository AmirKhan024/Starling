"""scripts/explainer_to_pdf.py
-------------------------------
Print `review/explainer.html` to `review/explainer.pdf`.

Uses headless Chromium through Playwright, which is already a dependency of the
review harness, so this adds no new tooling. The page is rendered with the light
colour scheme forced: the document's dark mode follows the reader's OS setting,
which is right on screen and wrong on paper.

    python scripts/build_explainer.py
    python scripts/explainer_to_pdf.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "review" / "explainer.html"
OUT = REPO / "review" / "explainer.pdf"


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Render review/explainer.html to PDF")
    ap.add_argument("--src", default=str(SRC))
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)

    src, out = Path(args.src), Path(args.out)
    if not src.exists():
        print(f"{src} does not exist — run scripts/build_explainer.py first", file=sys.stderr)
        return 1

    from playwright.sync_api import sync_playwright

    url = "file:///" + str(src.resolve()).replace("\\", "/")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        # color_scheme="light" pins the theme; the print stylesheet does the rest.
        page = browser.new_context(color_scheme="light").new_page()
        page.goto(url, wait_until="load")
        # Every screenshot must have decoded before the PDF is taken, or images
        # land in the file as blank boxes.
        page.wait_for_function(
            "() => Array.from(document.images).every(i => i.complete && i.naturalWidth > 0)",
            timeout=60_000,
        )
        page.wait_for_timeout(1200)
        n_img = page.evaluate("document.images.length")
        page.pdf(
            path=str(out),
            format="A4",
            print_background=True,
            margin={"top": "14mm", "bottom": "16mm", "left": "13mm", "right": "13mm"},
            display_header_footer=True,
            header_template="<div></div>",
            footer_template=(
                '<div style="width:100%;font-size:8pt;color:#8a94a6;padding:0 13mm;'
                'font-family:system-ui,sans-serif;display:flex;justify-content:space-between">'
                "<span>Starling &mdash; reading the dashboard</span>"
                '<span><span class="pageNumber"></span> of <span class="totalPages"></span></span></div>'
            ),
        )
        browser.close()

    print(f"wrote {out} ({out.stat().st_size/1024/1024:.1f} MB, {n_img} screenshots embedded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
