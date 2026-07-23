#!/usr/bin/env python3
"""Assemble docs/ into the field hub that gets deployed to GitHub Pages.

    python scripts/build_site.py            # build + verify
    python scripts/build_site.py --verify   # verify an already built docs/

Produces:
    docs/index.html        the hub (generated from scripts/hub_template.html)
    docs/guide-sergey.html rendered from MESHCORE_TESTING.md
    docs/guide-mark.html   rendered from MESHCORE_MARK.md
    docs/meshlog.py        copied verbatim from the repo root
    docs/app.webmanifest   PWA manifest
    docs/sw.js             service worker - guides and logger only, never the flasher

The guide sources and meshlog.py are supplied by the user. Whatever is missing
is reported and its hub card renders as "не готово" rather than as a dead link,
so the site is never broken by a file that has not landed yet.
"""

import argparse
import hashlib
import html
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_guide  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
HUB_TEMPLATE = ROOT / "scripts" / "hub_template.html"

GUIDES = [
    {
        "source": "MESHCORE_TESTING.md",
        "output": "guide-sergey.html",
        "title": "Инструкция: Сергей",
        "subtitle": "Полевое тестирование MeshCore — полный протокол",
        "card": "Инструкция: Сергей",
        "blurb": "Полный протокол тестирования: роли нод, критерии приёмки, грабли.",
    },
    {
        "source": "MESHCORE_MARK.md",
        "output": "guide-mark.html",
        "title": "Инструкция: Марк",
        "subtitle": "Что делать в поле — коротко и по шагам",
        "card": "Инструкция: Марк",
        "blurb": "Пошагово: что нажать, что смотреть, что делать если не так.",
    },
]

LOGGER_SOURCE = "meshlog.py"
LOGGER_RUN_CMD = "python meshlog.py --tcp 192.168.4.1:5000"

# Cached for offline use. The flasher needs Web Serial and a CDN, so it is
# deliberately absent - caching it would promise something it cannot deliver.
SW_CACHE = [
    "./",
    "index.html",
    "guide-sergey.html",
    "guide-mark.html",
    "meshlog.py",
    "app.webmanifest",
    "icon.svg",
]
CACHE_PREFIX = "meshcore-field-kit"


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #

def build_guides() -> list[dict]:
    results = []
    for g in GUIDES:
        src, out = ROOT / g["source"], DOCS / g["output"]
        if src.is_file():
            page, stats = render_guide.render(src, g["title"], g["subtitle"])
            out.write_text(page, encoding="utf-8")
            print(f"  + {g['output']:<20} from {g['source']}  {stats}")
            results.append({**g, "present": True, "stats": stats})
        else:
            out.write_text(placeholder_page(g), encoding="utf-8")
            print(f"  ! {g['output']:<20} PLACEHOLDER - {g['source']} not in the repo yet")
            results.append({**g, "present": False, "stats": None})
    return results


def placeholder_page(g: dict) -> str:
    body = (
        "<h2>Инструкция ещё не загружена</h2>"
        f"<p>Эта страница собирается из <code>{html.escape(g['source'])}</code> в корне "
        "репозитория. Файла там пока нет, поэтому рендерить нечего.</p>"
        "<p>Как только он будет закоммичен, страница пересоберётся автоматически "
        "при следующем пуше — здесь появится полный текст инструкции.</p>"
        '<p><a href="./">← вернуться в хаб</a></p>'
    )
    page = render_guide.TEMPLATE.read_text(encoding="utf-8")
    return (
        page.replace("{{TITLE}}", html.escape(g["title"]))
        .replace("{{SUBTITLE}}", "источник ещё не закоммичен")
        .replace("{{TOC}}", "")
        .replace("{{BODY}}", body)
        .replace("{{SOURCE_NAME}}", html.escape(g["source"]))
    )


def copy_logger() -> bool:
    src = ROOT / LOGGER_SOURCE
    if src.is_file():
        # Copied byte for byte: this is a field script debugged against real
        # failures, not something to tidy up.
        shutil.copyfile(src, DOCS / LOGGER_SOURCE)
        print(f"  + {LOGGER_SOURCE:<20} copied verbatim ({src.stat().st_size} bytes)")
        return True
    print(f"  ! {LOGGER_SOURCE:<20} not in the repo yet - card will show as not ready")
    return False


def card_html(href: str, icon: str, title: str, blurb: str, ready: bool, note: str = "") -> str:
    if not ready:
        return (
            '<div class="card card-off">'
            f'<div class="card-icon">{icon}</div>'
            f"<h2>{html.escape(title)}</h2>"
            f"<p>{html.escape(blurb)}</p>"
            '<p class="card-note">Ещё не загружено в репозиторий</p>'
            "</div>"
        )
    return (
        f'<a class="card" href="{href}">'
        f'<div class="card-icon">{icon}</div>'
        f"<h2>{html.escape(title)}</h2>"
        f"<p>{html.escape(blurb)}</p>"
        + (f'<p class="card-note">{note}</p>' if note else "")
        + '<span class="card-go">открыть →</span>'
        "</a>"
    )


def build_hub(guides: list[dict], logger_ok: bool) -> None:
    cards = [
        card_html("flash.html", "⚡", "Прошить ноду",
                  "Heltec V4 — кликом в браузере. T114 — файл .uf2.", True,
                  "нужен интернет"),
    ]
    if logger_ok:
        cards.append(
            '<a class="card" href="meshlog.py" download>'
            '<div class="card-icon">📡</div>'
            "<h2>Скачать логгер</h2>"
            "<p>meshlog.py — пишет лог с ноды.</p>"
            '<span class="card-go">скачать →</span>'
            "</a>"
        )
    else:
        cards.append(card_html("meshlog.py", "📡", "Скачать логгер",
                               "meshlog.py — пишет лог с ноды.", False))

    for g in guides:
        cards.append(card_html(g["output"], "📖", g["card"], g["blurb"], True,
                               "" if g["present"] else "черновик"))

    run_cmd = html.escape(LOGGER_RUN_CMD)
    logger_block = (
        '<div class="runbox">'
        "<p class=\"runbox-label\">Запуск логгера</p>"
        '<div class="code-wrap">'
        '<button class="copy-btn" type="button" aria-label="Скопировать команду">копировать</button>'
        f"<pre><code>{run_cmd}</code></pre>"
        "</div></div>"
    )

    page = HUB_TEMPLATE.read_text(encoding="utf-8")
    page = page.replace("{{CARDS}}", "".join(cards))
    page = page.replace("{{LOGGER_BLOCK}}", logger_block)
    (DOCS / "index.html").write_text(page, encoding="utf-8")
    print(f"  + index.html          hub with {len(cards)} cards")


def build_pwa() -> None:
    manifest = {
        "name": "MeshCore Field Kit",
        "short_name": "MeshCore",
        "start_url": "./",
        "scope": "./",
        "display": "standalone",
        "background_color": "#0b0d10",
        "theme_color": "#0b0d10",
        "description": "Прошивка нод, логгер и полевые инструкции MeshCore",
        "icons": [
            {
                # Inline SVG icon keeps the manifest self-contained - no binary
                # asset to keep in sync, and nothing extra to fetch.
                "src": "icon.svg",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any maskable",
            }
        ],
    }
    (DOCS / "app.webmanifest").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    icon = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192">'
        '<rect width="192" height="192" rx="38" fill="#0b0d10"/>'
        '<circle cx="96" cy="96" r="16" fill="#4ade80"/>'
        '<g fill="none" stroke="#4ade80" stroke-width="8" stroke-linecap="round" opacity=".75">'
        '<path d="M60 60a51 51 0 0 0 0 72"/><path d="M132 60a51 51 0 0 1 0 72"/>'
        '</g>'
        '<g fill="none" stroke="#38bdf8" stroke-width="7" stroke-linecap="round" opacity=".55">'
        '<path d="M38 38a82 82 0 0 0 0 116"/><path d="M154 38a82 82 0 0 1 0 116"/>'
        "</g></svg>\n"
    )
    (DOCS / "icon.svg").write_text(icon, encoding="utf-8")

    # Cache name is a content hash of the cached assets, so it changes exactly
    # when they do. Python's hash() is salted per process and would mint a new
    # cache name on every build, throwing away the users' cache each deploy.
    digest = hashlib.sha256()
    for name in SW_CACHE:
        f = DOCS / name
        if f.is_file():
            digest.update(name.encode())
            digest.update(f.read_bytes())
    version = digest.hexdigest()[:12]
    sw = f"""// Caches the offline half of the field kit: guides and the logger.
// The flasher (flash.html, firmware images, ESP Web Tools) is deliberately NOT
// cached - it needs Web Serial and a CDN, so pretending it works offline would
// be a lie in the field.
const CACHE = '{CACHE_PREFIX}-{version}';
const ASSETS = {json.dumps(SW_CACHE, ensure_ascii=False)};

self.addEventListener('install', (e) => {{
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
}});

self.addEventListener('activate', (e) => {{
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
}});

self.addEventListener('fetch', (e) => {{
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  // Never serve the flasher or firmware from cache.
  if (/flash\\.html|\\.bin$|\\.uf2$|manifest\\.json$/.test(url.pathname)) return;
  e.respondWith(
    caches.match(e.request).then((hit) => hit || fetch(e.request).then((res) => {{
      if (res.ok) {{
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
      }}
      return res;
    }}).catch(() => caches.match('index.html')))
  );
}});
"""
    (DOCS / "sw.js").write_text(sw, encoding="utf-8")
    print("  + app.webmanifest / icon.svg / sw.js")


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #

def count_source(md: str) -> dict:
    fences = len(re.findall(r"^```", md, flags=re.M)) // 2
    return {
        "headings": len(re.findall(r"^#{2,3} ", md, flags=re.M)),
        "tables": len(re.findall(r"^\|.*\|\s*$\n^\|[\s:|-]+\|\s*$", md, flags=re.M)),
        "code_blocks": fences,
    }


def verify() -> int:
    problems: list[str] = []
    print("\n=== VERIFY ===")

    # 1. guides: nothing lost in conversion
    for g in GUIDES:
        src, out = ROOT / g["source"], DOCS / g["output"]
        if not out.is_file():
            problems.append(f"{g['output']} was not produced")
            continue
        page = out.read_text(encoding="utf-8")
        if not src.is_file():
            print(f"  ~ {g['output']}: placeholder ({g['source']} not committed yet) - skipping content check")
            continue
        want = count_source(src.read_text(encoding="utf-8"))
        got = {
            "headings": len(re.findall(r'<h[23] id=', page)),
            "tables": len(re.findall(r"<table\b", page)),
            "code_blocks": len(re.findall(r'<div class="code-wrap">', page)),
        }
        line = f"  {g['output']}: source {want} -> output {got}"
        for k in want:
            if got[k] < want[k]:
                problems.append(f"{g['output']}: {k} lost in conversion ({want[k]} -> {got[k]})")
        print(line + ("  OK" if all(got[k] >= want[k] for k in want) else "  MISMATCH"))

    # 2. every code block has a copy button
    for name in [g["output"] for g in GUIDES] + ["index.html"]:
        p = DOCS / name
        if not p.is_file():
            continue
        page = p.read_text(encoding="utf-8")
        pres = len(re.findall(r"<pre\b", page))
        btns = len(re.findall(r'class="copy-btn"', page))
        if pres != btns:
            problems.append(f"{name}: {pres} code blocks but {btns} copy buttons")
        print(f"  {name}: {pres} code blocks / {btns} copy buttons" + ("  OK" if pres == btns else "  MISMATCH"))
        if pres and "navigator.clipboard" not in page:
            problems.append(f"{name}: has code blocks but no clipboard handler")

    # 3. guides fetch nothing when opened.
    # Only sub-resources matter here. A plain <a href="https://..."> costs
    # nothing until someone taps it, and the real guides legitimately link out -
    # flagging those would fail the build on correct content.
    subresource = re.compile(
        r"""(?:<script[^>]+\bsrc|<link[^>]+\bhref|<img[^>]+\bsrc|<iframe[^>]+\bsrc"""
        r"""|<source[^>]+\bsrc|<video[^>]+\bsrc|<audio[^>]+\bsrc)\s*=\s*["'](?:https?:)?//""",
        re.I,
    )
    css_remote = re.compile(r"""(?:@import\s+|url\()\s*["']?(?:https?:)?//""", re.I)
    for g in GUIDES:
        p = DOCS / g["output"]
        if not p.is_file():
            continue
        page = p.read_text(encoding="utf-8")
        hits = subresource.findall(page) + css_remote.findall(page)
        links = len(re.findall(r'<a [^>]*href\s*=\s*["\']https?://', page, re.I))
        if hits:
            problems.append(f"{g['output']}: {len(hits)} external sub-resource(s) - breaks offline use")
        print(
            f"  {g['output']}: external sub-resources = {len(hits)}"
            f" (plain links out: {links}, harmless)" + ("  OK" if not hits else "  FAIL")
        )

    # 4. hub links resolve
    hub = DOCS / "index.html"
    if hub.is_file():
        page = hub.read_text(encoding="utf-8")
        targets = set(re.findall(r'<a class="card" href="([^"#]+)"', page))
        missing = [t for t in targets if not (DOCS / t).exists()]
        print(f"  index.html: {len(targets)} card link(s), broken = {len(missing)}"
              + ("  OK" if not missing else f"  FAIL {missing}"))
        if missing:
            problems.append(f"index.html: broken card links {missing}")
        for must in ("flash.html", "guide-sergey.html", "guide-mark.html"):
            if must not in page:
                problems.append(f"index.html: does not link {must}")
    else:
        problems.append("index.html missing")

    # 5. flasher must not be cached offline
    sw = DOCS / "sw.js"
    if sw.is_file():
        body = sw.read_text(encoding="utf-8")
        bad = [a for a in ("flash.html", ".bin", ".uf2") if f'"{a}"' in body]
        print("  sw.js: flasher excluded from cache" + ("  OK" if not bad else f"  FAIL {bad}"))
        if bad:
            problems.append(f"sw.js caches flasher assets {bad}")

    print()
    if problems:
        for p in problems:
            print(f"  FAIL: {p}", file=sys.stderr)
        return 1
    print("  all checks passed")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="only verify an existing docs/")
    args = ap.parse_args()

    if not args.verify:
        DOCS.mkdir(exist_ok=True)
        print("=== BUILD SITE ===")
        guides = build_guides()
        logger_ok = copy_logger()
        build_hub(guides, logger_ok)
        build_pwa()

    return verify()


if __name__ == "__main__":
    sys.exit(main())
