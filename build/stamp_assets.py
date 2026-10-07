"""Stamp a content version onto the site's own JS and CSS URLs.

Why this exists. `index.html` and `docs/data/*.json` are revalidated on every
load (the JSON is fetched with `cache: 'no-cache'`), but the six ES modules are
ordinary subresources and a browser will happily keep serving a cached copy for
as long as its heuristics allow. After a push that changes both the summary
schema and the code that reads it, that produces the worst possible failure
mode: NEW html + NEW json + OLD javascript, which does not error — it silently
renders an empty chart. That is exactly what happened once, and the symptom
("no species rows with detections above zero") pointed at the data rather than
at the cache, which is the expensive kind of wrong.

The fix is to make the URL change whenever the content does. Every import
specifier between our own modules, and the two references in `index.html`, get
a `?v=<token>` where the token is a hash of all of that code. A stale module
is then simply a URL the browser has never seen.

One token covers the whole set rather than one per file. Any change busts all
six, which costs a few tens of kilobytes on the next load and removes the
possibility of a half-updated module graph — modules that import each other
are not independently versionable in any useful sense.

Vendored libraries (Leaflet, Plotly) are deliberately NOT stamped: they are
large, they never change, and letting them stay cached is the point of
vendoring them.

Idempotent: existing stamps are stripped before hashing, so re-running without
a code change is a no-op and the token is a function of the code alone.

Run it last, after the summary and media steps:

    python build/stamp_assets.py
"""
import hashlib
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(REPO, "docs")
JS_DIR = os.path.join(DOCS, "assets", "js")
CSS = os.path.join(DOCS, "assets", "css", "dashboard.css")
HTML = os.path.join(DOCS, "index.html")

# `from './data.js'` / `from "./map.js"`, with or without an existing stamp.
IMPORT_RE = re.compile(
    r"""(?P<head>\bfrom\s+['"])(?P<path>\./[A-Za-z0-9_\-/]+\.js)"""
    r"""(?:\?v=[0-9a-f]+)?(?P<tail>['"])""")

# The two references in index.html that point at our own code.
HTML_RE = re.compile(
    r"""(?P<head>(?:src|href)=")(?P<path>\./assets/(?:js/main\.js|css/dashboard\.css))"""
    r"""(?:\?v=[0-9a-f]+)?(?P<tail>")""")


def strip_js(text):
    return IMPORT_RE.sub(lambda m: m.group("head") + m.group("path") + m.group("tail"),
                         text)


def strip_html(text):
    return HTML_RE.sub(lambda m: m.group("head") + m.group("path") + m.group("tail"),
                       text)


def main():
    js_files = sorted(f for f in os.listdir(JS_DIR) if f.endswith(".js"))
    if not js_files:
        raise SystemExit(f"no ES modules found in {JS_DIR}")

    sources = {}
    for name in js_files:
        path = os.path.join(JS_DIR, name)
        sources[path] = strip_js(open(path).read())
    sources[CSS] = open(CSS).read()

    # Token over the UNSTAMPED content, so it depends on the code and not on
    # the previous run's token.
    h = hashlib.sha256()
    for path in sorted(sources):
        h.update(os.path.basename(path).encode())
        h.update(sources[path].encode())
    token = h.hexdigest()[:10]

    changed = []
    for path, clean in sources.items():
        if path == CSS:
            new = clean
        else:
            new = IMPORT_RE.sub(
                lambda m: (m.group("head") + m.group("path") + f"?v={token}"
                           + m.group("tail")), clean)
        if new != open(path).read():
            with open(path, "w") as fh:
                fh.write(new)
            changed.append(os.path.relpath(path, REPO))

    html = open(HTML).read()
    new_html = HTML_RE.sub(
        lambda m: (m.group("head") + m.group("path") + f"?v={token}"
                   + m.group("tail")), strip_html(html))
    if new_html != html:
        with open(HTML, "w") as fh:
            fh.write(new_html)
        changed.append(os.path.relpath(HTML, REPO))

    n_imports = sum(len(IMPORT_RE.findall(v)) for k, v in sources.items()
                    if k != CSS)
    n_html = len(HTML_RE.findall(new_html))
    print(f"  asset version {token}: stamped {n_imports} module imports and "
          f"{n_html} references in index.html")
    if changed:
        print("  rewrote " + ", ".join(sorted(changed)))
    else:
        print("  no change (already stamped at this version)")

    if n_html != 2:
        print("  WARNING index.html should carry exactly 2 stamped references "
              f"(main.js, dashboard.css); found {n_html}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
