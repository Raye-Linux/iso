# SPDX-License-Identifier: GPL-3.0-or-later
"""Folder pages for dl.rayelinux.com and the GitHub Pages mirror.

Every folder of the apt tree gets an index.html that lists what is in it,
so a visitor sees a folder browser instead of a 404. Only links between
folders of the tree are relative, so the same pages work on R2 (under
/apt/) and on GitHub Pages (under /packages/). No script, no outside
resource: the Raye eye is inlined as a data: image.

The pages are written AFTER the Release is generated and signed: they are
not apt indexes and are not named in Release, so apt never fetches them.
"""
from __future__ import annotations

import base64
import datetime
import html
import pathlib
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
EYE = HERE.parents[1] / "website/site/assets/raye-eye.svg"
INDEX = "index.html"
DOCTYPE = "<!DOCTYPE html>"
PAGE_LIMIT = 1000 * 1000

STYLE = """
:root{color-scheme:dark;--bg:#130E1F;--card:rgba(255,255,255,.05);--line:rgba(255,255,255,.08);
--text:#F3EAFF;--muted:#B9A8D6;--dim:#9889B1;--accent:#7B3CFF;--link:#B48CFF}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.5 system-ui,-apple-system,"Segoe UI","Noto Sans",Roboto,sans-serif}
main{max-width:880px;margin:0 auto;padding:40px 20px 64px}
header{display:flex;align-items:center;gap:14px;margin-bottom:28px}
header img{height:30px;width:auto}
header span{color:var(--muted);font-size:14px}
h1{font-size:22px;font-weight:600;margin:0 0 6px;word-break:break-all}
h1 a{color:var(--link);text-decoration:none}h1 a:hover{text-decoration:underline}
p{color:var(--muted);margin:0 0 18px}
a{color:var(--link)}
table{width:100%;border-collapse:collapse;background:var(--card);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:9px 14px;border-bottom:1px solid var(--line)}
th{color:var(--dim);font-weight:500;font-size:13px}
td.n{word-break:break-all}td.s,td.d,th.s,th.d{white-space:nowrap;color:var(--dim)}
td.s,th.s{text-align:right}
tr:last-child td{border-bottom:0}
td a{text-decoration:none}td a:hover{text-decoration:underline}
footer{margin-top:28px;color:var(--dim);font-size:13px}
footer a{color:var(--muted)}
"""


def _eye(eye=EYE):
    try:
        data = pathlib.Path(eye).read_bytes()
    except OSError:
        return ""
    src = "data:image/svg+xml;base64," + base64.b64encode(data).decode()
    return f'<img src="{src}" alt="Raye">'


def size_text(size):
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def _date(path):
    t = datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.timezone.utc)
    return t.strftime("%Y-%m-%d %H:%M UTC")


def release_label(release=None, conf=None):
    """RELEASE of release.conf the way people say it: 0.2-beta -> 0.2 Beta."""
    if release is None:
        import raye_publish
        release = raye_publish.settings(**({"path": conf} if conf else {}))["RELEASE"]
    number, _, stage = release.partition("-")
    stage = stage.upper() if len(stage) <= 2 else stage.capitalize()
    return f"{number} {stage}".strip()


def _page(title, body, eye):
    name = f"Raye Linux {release_label()}"
    return (f"{DOCTYPE}\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<title>{html.escape(name)} &middot; {html.escape(title)}</title>\n<style>{STYLE}</style>\n</head>\n<body>\n<main>\n"
            f"<header>{eye}<span>{html.escape(name)} downloads</span></header>\n{body}\n"
            "<footer>Raye Linux &middot; <a href=\"https://rayelinux.com/\">rayelinux.com</a></footer>\n"
            "</main>\n</body>\n</html>\n")


def folder_page(tree, folder, root_name="apt", eye=None):
    """The index.html text of one folder of the tree."""
    tree, folder = pathlib.Path(tree), pathlib.Path(folder)
    eye = _eye() if eye is None else eye
    parts = folder.relative_to(tree).parts
    depth = len(parts)
    crumbs = [f'<a href="{"../" * depth or "./"}">{html.escape(root_name)}</a>']
    for i, name in enumerate(parts):
        up = "../" * (depth - i - 1) or "./"
        crumbs.append(f'<a href="{up}">{html.escape(name)}</a>')
    rows = []
    if depth:
        rows.append('<tr><td class="n"><a href="../">../</a></td>'
                    '<td class="s">&ndash;</td><td class="d">&ndash;</td></tr>')
    entries = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name))
    for p in entries:
        if p.name == INDEX or p.is_symlink():
            continue
        name = html.escape(p.name)
        href = urllib.parse.quote(p.name)
        if p.is_dir():
            rows.append(f'<tr><td class="n"><a href="{href}/">{name}/</a></td>'
                        f'<td class="s">&ndash;</td><td class="d">{_date(p)}</td></tr>')
        elif p.is_file():
            rows.append(f'<tr><td class="n"><a href="{href}">{name}</a></td>'
                        f'<td class="s">{size_text(p.stat().st_size)}</td>'
                        f'<td class="d">{_date(p)}</td></tr>')
    path = "/".join((root_name, *parts)) + "/"
    intro = ("<p>The Raye Linux package archive. Raye systems already use it; "
             "nothing needs to be set up by hand.</p>\n") if not depth else ""
    body = (f"<h1>{' / '.join(crumbs)} /</h1>\n{intro}<table>\n"
            '<thead><tr><th>Name</th><th class="s">Size</th><th class="d">Modified</th></tr></thead>\n'
            "<tbody>\n" + "\n".join(rows) + "\n</tbody>\n</table>")
    return _page(f"Index of {path}", body, eye)


def write_folder_pages(tree, root_name="apt"):
    """Writes an index.html in every folder of the tree; returns how many."""
    tree = pathlib.Path(tree)
    eye = _eye()
    folders = [tree, *sorted(p for p in tree.rglob("*") if p.is_dir() and not p.is_symlink())]
    for folder in folders:
        (folder / INDEX).write_text(folder_page(tree, folder, root_name, eye))
        (folder / INDEX).chmod(0o644)
    return len(folders)


def root_page():
    """The page at the top of the dl.rayelinux.com bucket."""
    body = ("<h1>dl.rayelinux.com</h1>\n"
            "<p>This is where Raye Linux is downloaded from. It holds the Raye package "
            "archive, which every Raye system reads its updates from.</p>\n"
            "<table>\n<thead><tr><th>Name</th><th class=\"d\">What</th></tr></thead>\n<tbody>\n"
            '<tr><td class="n"><a href="apt/">apt/</a></td>'
            '<td class="d">the signed package archive</td></tr>\n'
            "</tbody>\n</table>\n"
            "<p style=\"margin-top:18px\">The installation image will be published here "
            "at launch.</p>")
    return _page("Downloads", body, _eye())


def is_folder_page(path):
    """True for an index.html these tools could have written."""
    path = pathlib.Path(path)
    if path.name != INDEX or path.stat().st_size >= PAGE_LIMIT:
        return False
    with open(path, "rb") as f:
        return f.read(len(DOCTYPE)) == DOCTYPE.encode()
