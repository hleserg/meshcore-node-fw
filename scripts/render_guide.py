#!/usr/bin/env python3
"""Render a field guide from Markdown into a self-contained offline HTML page.

The conversion is deliberately faithful: nothing is summarised, reordered or
reworded. Every heading, table, list item and code block in the source has to
survive into the output, because these are field instructions and a dropped line
is a failure in the field.

What it adds on top of plain Markdown rendering:
  * a copy button baked into every code block AT BUILD TIME, so "every block has
    one" is a static property of the HTML rather than something JS might miss;
  * blockquotes led by an emoji marker become callout cards
    (warning / danger / tip / success);
  * an anchored table of contents with sticky nav and a back-to-top control;
  * all CSS and JS inlined - the page must open with the network off.

Used by scripts/build_site.py; run directly to convert a single file.
"""

import argparse
import html
import re
import sys
from pathlib import Path

try:
    import markdown
except ImportError:
    sys.exit("Python-Markdown missing - run: pip install markdown pymdown-extensions")

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "scripts" / "guide_template.html"

# Blockquote marker -> callout kind. Order matters only for readability.
CALLOUTS = {
    "⚠️": ("warning", "Внимание"),
    "🚨": ("danger", "Опасно"),
    "💡": ("tip", "Подсказка"),
    "✅": ("success", "Чек-лист"),
}
# Any other emoji-led blockquote still becomes a card, just a neutral one, so a
# marker we have not seen before does not silently fall back to a grey quote.
DEFAULT_CALLOUT = ("note", "Заметка")

EMOJI_LEAD = re.compile(
    "^["
    "\U0001F300-\U0001FAFF"   # pictographs, symbols, emoticons
    "☀-➿"           # misc symbols & dingbats
    "⬀-⯿"
    "️⃣]+"
)

MD_EXTENSIONS = [
    "tables",
    "fenced_code",
    "attr_list",
    "sane_lists",
    "md_in_html",
    "pymdownx.tasklist",
    "pymdownx.tilde",
]
MD_EXTENSION_CONFIGS = {
    "pymdownx.tasklist": {"custom_checkbox": True},
}


def slugify(text: str) -> str:
    """Anchor id from heading text. Keeps Cyrillic - these docs are Russian."""
    s = re.sub(r"<[^>]+>", "", text)
    s = html.unescape(s).strip().lower()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return s or "section"


def add_copy_buttons(body: str) -> tuple[str, int]:
    """Wrap every <pre> in a toolbar with a copy button. Returns (html, count)."""
    count = 0

    def wrap(m: re.Match) -> str:
        nonlocal count
        count += 1
        return (
            '<div class="code-wrap">'
            '<button class="copy-btn" type="button" aria-label="Скопировать код">'
            "копировать</button>"
            f"{m.group(0)}"
            "</div>"
        )

    return re.sub(r"<pre\b.*?</pre>", wrap, body, flags=re.DOTALL), count


def _callout_card(marker: str, inner: str) -> str:
    kind, label = CALLOUTS.get(marker, DEFAULT_CALLOUT)
    inner = inner.replace(marker, "", 1)  # the card header already shows the icon
    return (
        f'<div class="callout callout-{kind}">'
        f'<div class="callout-head"><span class="callout-icon">{marker}</span>'
        f"<span>{label}</span></div>"
        f'<div class="callout-body">{inner}</div>'
        "</div>"
    )


def convert_callouts(body: str) -> tuple[str, int]:
    """Turn emoji-led blockquotes into callout cards.

    Markdown merges blockquotes that are only separated by a blank line into a
    single <blockquote> holding several <p>. Three consecutive callouts in the
    source therefore arrive as one node, and taking only its first marker would
    render a red 'this destroys the board' danger as a mild yellow warning. So
    split on every paragraph that opens with a marker and emit one card each.
    """
    count = 0

    def repl(m: re.Match) -> str:
        nonlocal count
        inner = m.group(1)

        starts: list[tuple[int, str]] = []
        for pm in re.finditer(r"<p>([^<]*)", inner):
            lead = html.unescape(pm.group(1)).lstrip()
            known = next((m for m in CALLOUTS if lead.startswith(m)), None)
            if known:
                starts.append((pm.start(), known))
                continue
            other = EMOJI_LEAD.match(lead)
            if other:
                starts.append((pm.start(), other.group(0)))
        if not starts:
            return m.group(0)

        out = []
        head = inner[: starts[0][0]].strip()
        if head:  # text before the first marker stays an ordinary quote
            out.append(f"<blockquote>{head}</blockquote>")
        for i, (pos, marker) in enumerate(starts):
            end = starts[i + 1][0] if i + 1 < len(starts) else len(inner)
            count += 1
            out.append(_callout_card(marker, inner[pos:end]))
        return "".join(out)

    return re.sub(r"<blockquote>(.*?)</blockquote>", repl, body, flags=re.DOTALL), count


def anchor_headings(body: str) -> tuple[str, list[dict]]:
    """Give h1/h2/h3 stable ids and collect them for the TOC.

    h1 is included on purpose: these guides use it for the major parts
    ("ЧАСТЬ 1", "ГРАБЛИ"), so a table of contents built from h2/h3 alone would
    drop the entire top level of the document.
    """
    toc: list[dict] = []
    seen: dict[str, int] = {}

    def repl(m: re.Match) -> str:
        level, attrs, text = int(m.group(1)), m.group(2), m.group(3)
        if re.search(r"\bid=", attrs):
            return m.group(0)
        slug = slugify(text)
        seen[slug] = seen.get(slug, 0) + 1
        if seen[slug] > 1:
            slug = f"{slug}-{seen[slug]}"
        toc.append({"level": level, "id": slug, "text": re.sub(r"<[^>]+>", "", text)})
        return (
            f'<h{level} id="{slug}"{attrs}>{text}'
            f'<a class="anchor" href="#{slug}" aria-label="Ссылка на раздел">#</a></h{level}>'
        )

    body = re.sub(r"<h([123])([^>]*)>(.*?)</h\1>", repl, body, flags=re.DOTALL)
    return body, toc


def split_title(md: str) -> tuple[str | None, str]:
    """Pull a leading '# Title' off the document.

    The guides open with their own title, which would otherwise be rendered a
    second time under the page heading. Using it as the page title keeps the
    document the single source of truth for its own name.
    """
    m = re.match(r"\s*#\s+(.+?)\s*\n", md)
    if not m:
        return None, md
    return m.group(1).strip(), md[m.end():]


def wrap_tables(body: str) -> tuple[str, int]:
    """Tables scroll inside their own box so the page never scrolls sideways."""
    count = len(re.findall(r"<table\b", body))
    body = re.sub(r"<table\b", '<div class="table-wrap"><table', body)
    body = body.replace("</table>", "</table></div>")
    return body, count


def render_toc(toc: list[dict]) -> str:
    if not toc:
        return ""
    items = "".join(
        f'<li class="toc-l{e["level"]}"><a href="#{e["id"]}">{html.escape(e["text"])}</a></li>'
        for e in toc
    )
    return f"<ul class='toc-list'>{items}</ul>"


def render(md_path: Path, title: str, subtitle: str) -> tuple[str, dict]:
    source = md_path.read_text(encoding="utf-8")

    doc_title, source = split_title(source)
    if doc_title:
        title = doc_title

    md = markdown.Markdown(
        extensions=MD_EXTENSIONS, extension_configs=MD_EXTENSION_CONFIGS
    )
    body = md.convert(source)

    body, n_callouts = convert_callouts(body)
    body, toc = anchor_headings(body)
    body, n_tables = wrap_tables(body)
    body, n_code = add_copy_buttons(body)

    page = TEMPLATE.read_text(encoding="utf-8")
    page = page.replace("{{TITLE}}", html.escape(title))
    page = page.replace("{{SUBTITLE}}", html.escape(subtitle))
    page = page.replace("{{TOC}}", render_toc(toc))
    page = page.replace("{{BODY}}", body)
    page = page.replace("{{SOURCE_NAME}}", html.escape(md_path.name))

    stats = {
        "headings": len(toc),
        "tables": n_tables,
        "code_blocks": n_code,
        "callouts": n_callouts,
        "source_bytes": len(source),
    }
    return page, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("output")
    ap.add_argument("--title", default="Инструкция")
    ap.add_argument("--subtitle", default="")
    args = ap.parse_args()

    page, stats = render(Path(args.source), args.title, args.subtitle)
    Path(args.output).write_text(page, encoding="utf-8")
    print(f"{args.source} -> {args.output}  {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
