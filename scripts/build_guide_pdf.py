"""Render stuff/docs/PROJECT_GUIDE.md to a styled HTML page and print it to PDF with headless Chrome.

Usage: venv/Scripts/python.exe scripts/build_guide_pdf.py <repo root> <build dir>   (build dir: any scratch folder)
"""
import shutil
import subprocess
import sys
from pathlib import Path

from markdown_it import MarkdownIt

root, build = Path(sys.argv[1]), Path(sys.argv[2])
build.mkdir(parents=True, exist_ok=True)
fonts = build / "fonts"
fonts.mkdir(exist_ok=True)
for f in (root / "app" / "web" / "static" / "fonts").glob("*.woff2"):
    shutil.copy(f, fonts / f.name)

md = MarkdownIt("commonmark", {"html": False, "typographer": False}).enable("table").enable("strikethrough")
body = md.render((root / "stuff" / "docs" / "PROJECT_GUIDE.md").read_text(encoding="utf-8"))

css = """
@font-face{font-family:Plex;src:url(fonts/IBMPlexSans-400.woff2);font-weight:400}
@font-face{font-family:Plex;src:url(fonts/IBMPlexSans-400i.woff2);font-weight:400;font-style:italic}
@font-face{font-family:Plex;src:url(fonts/IBMPlexSans-600.woff2);font-weight:600}
@font-face{font-family:Plex;src:url(fonts/IBMPlexSans-600.woff2);font-weight:700}
@font-face{font-family:Mono;src:url(fonts/IBMPlexMono-400.woff2)}
@font-face{font-family:Spectral;src:url(fonts/Spectral-600.woff2);font-weight:600}
@font-face{font-family:Spectral;src:url(fonts/Spectral-500.woff2);font-weight:500}
@font-face{font-family:Spectral;src:url(fonts/Spectral-500i.woff2);font-weight:500;font-style:italic}
@page{size:A4;margin:18mm 16mm 18mm 16mm}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{font-family:Plex,'Segoe UI',sans-serif;font-size:9.6pt;line-height:1.5;color:#1c1a17;max-width:none}
h1,h2,h3{font-family:Spectral,Georgia,serif;color:#1c1a17;line-height:1.2}
h1{font-size:21pt;font-weight:600;border-bottom:2px solid #7a1f1f;padding-bottom:4pt;margin:0 0 10pt;break-before:page}
h1:first-of-type{break-before:avoid;font-size:26pt}
h2{font-size:14pt;font-weight:600;margin:16pt 0 6pt;color:#7a1f1f;break-after:avoid}
h3{font-size:11.5pt;font-weight:600;margin:12pt 0 4pt;break-after:avoid}
p{margin:0 0 6pt}
ul,ol{margin:0 0 6pt;padding-left:18pt}
li{margin:1.5pt 0}
code{font-family:Mono,Consolas,monospace;font-size:8.6pt;background:#f2eee6;padding:0 2pt;border-radius:2pt}
pre{background:#f6f3ec;border-left:3px solid #7a1f1f;padding:6pt 8pt;font-size:7.2pt;line-height:1.3;white-space:pre;overflow:hidden;break-inside:avoid}
pre code{background:none;padding:0;font-family:Consolas,'Cascadia Mono',monospace;font-size:inherit}
table{border-collapse:collapse;width:100%;margin:4pt 0 9pt;font-size:8.4pt;break-inside:auto}
th{background:#ece6da;text-align:left;font-weight:600}
th,td{border:1px solid #cfc6b6;padding:2.5pt 5pt;vertical-align:top}
tr{break-inside:avoid}
blockquote{margin:6pt 0;padding:5pt 9pt;background:#fbf3e3;border-left:3px solid #b07a1c}
hr{border:none;border-top:1px solid #cfc6b6;margin:10pt 0}
strong{font-weight:600}
em{font-style:italic}
"""
html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Pramana - Project Guide</title><style>{css}</style></head><body>{body}</body></html>"""
page = build / "guide.html"
page.write_text(html, encoding="utf-8")

out = (root / "stuff" / "docs" / "PROJECT_GUIDE.pdf").resolve()  # Chrome does not resolve a relative path against our cwd
chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
profile = build / "chrome-profile"
subprocess.run([chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={profile}",
                "--no-pdf-header-footer", f"--print-to-pdf={out}", page.resolve().as_uri()],
               check=True, timeout=180)
print("wrote", out)
