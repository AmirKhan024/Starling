"""scripts/build_project_guide.py
---------------------------------
Builds a SELF-CONTAINED copy of docs/PROJECT_GUIDE.md: every screenshot and chart is embedded
(base64), so the file can be shared on its own.

    docs/PROJECT_GUIDE_standalone.html   open in any browser (diagrams need internet once)
    docs/PROJECT_GUIDE.pdf               printed from the HTML (diagrams rendered)

    python scripts/build_project_guide.py
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

import markdown

DOCS = Path(__file__).resolve().parents[1] / "docs"
MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"

CSS = """
body{font:16px/1.65 "Segoe UI",system-ui,sans-serif;color:#1b2430;max-width:980px;margin:0 auto;padding:32px 28px 80px}
h1{font-size:34px;letter-spacing:-.02em;border-bottom:3px solid #2f6fed;padding-bottom:10px}
h2{font-size:26px;margin-top:54px;border-bottom:1px solid #dde3ec;padding-bottom:6px}
h3{font-size:20px;margin-top:34px} h4{font-size:17px}
img{max-width:100%;height:auto;border:1px solid #dde3ec;border-radius:10px;margin:10px 0 6px;display:block;box-shadow:0 2px 10px rgba(20,30,50,.08)}
code{background:#eef2f8;padding:1px 6px;border-radius:5px;font-size:.92em}
pre{background:#0f1722;color:#e8eef6;padding:14px 16px;border-radius:10px;overflow:auto}
pre code{background:none;color:inherit;padding:0}
table{border-collapse:collapse;width:100%;margin:14px 0;font-size:14.5px}
th,td{border:1px solid #dde3ec;padding:8px 10px;text-align:left;vertical-align:top}
th{background:#f1f5fb} blockquote{border-left:4px solid #f2b45a;background:#fff8e8;margin:16px 0;padding:8px 16px;border-radius:0 8px 8px 0}
.mermaid{background:#f7f9fc;border:1px solid #dde3ec;border-radius:10px;padding:12px;margin:14px 0;text-align:center}
hr{border:0;border-top:1px solid #dde3ec;margin:30px 0}
@media print{body{max-width:none;padding:0;font-size:13.5px} img,table,.mermaid,pre{break-inside:avoid} h2{break-before:page}}
"""


def embed(match: re.Match) -> str:
    alt, rel = match.group(1), match.group(2)
    p = DOCS / rel
    if not p.exists():
        return match.group(0)
    mime = "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    return f'<img alt="{alt}" src="data:{mime};base64,{data}">'


def main() -> None:
    md = (DOCS / "PROJECT_GUIDE.md").read_text(encoding="utf-8")
    md = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", embed, md)
    # mermaid blocks become <div class="mermaid"> (kept out of the markdown code handling)
    blocks: list[str] = []

    def stash(m: re.Match) -> str:
        blocks.append(m.group(1))
        return f"\n\nMERMAIDBLOCK{len(blocks) - 1}\n\n"

    md = re.sub(r"```mermaid\n(.*?)```", stash, md, flags=re.S)
    html = markdown.markdown(md, extensions=["tables", "fenced_code", "toc"])
    for i, b in enumerate(blocks):
        html = html.replace(f"<p>MERMAIDBLOCK{i}</p>", f'<div class="mermaid">{b}</div>')
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Starling: the complete project guide</title><style>{CSS}</style></head><body>{html}"
        f'<script src="{MERMAID}"></script><script>mermaid.initialize({{startOnLoad:true,theme:"default"}});</script>'
        "</body></html>"
    )
    out = DOCS / "PROJECT_GUIDE_standalone.html"
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page()
        pg.goto(out.as_uri())
        pg.wait_for_timeout(4000)  # mermaid
        pdf = DOCS / "PROJECT_GUIDE.pdf"
        pg.pdf(path=str(pdf), format="A4", print_background=True, margin={"top": "14mm", "bottom": "14mm", "left": "12mm", "right": "12mm"})
        print(f"wrote {pdf} ({pdf.stat().st_size / 1e6:.1f} MB)")
        n = pg.evaluate("document.querySelectorAll('.mermaid svg').length")
        print("diagrams rendered:", n)
        b.close()


if __name__ == "__main__":
    main()
