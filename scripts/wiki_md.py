"""Confluence rendered HTML (body.view) to Markdown for the `wiki` tool.

Adapted from confluence-markdown-exporter (MIT License, Copyright (c) 2025
Sebastian Penhouet, https://github.com/Spenhouet/confluence-markdown-exporter),
reduced to the handlers that need no page, attachment or settings objects.
Needs the `markdownify` package.
"""
import re
import urllib.parse

from bs4 import Tag
from markdownify import ATX, MarkdownConverter

_LEADING_BR_OR_WS = re.compile(r"^(?:\s|<br\s*/?>)+")
_TRAILING_BR_OR_WS = re.compile(r"(?:\s|<br\s*/?>)+$")

ALERTS = {"info": "IMPORTANT", "panel": "NOTE", "tip": "TIP",
          "note": "WARNING", "warning": "CAUTION"}
ALERT_EMOJI = {"NOTE": "\U0001f4dd", "TIP": "\U0001f4a1", "IMPORTANT": "❗",
               "WARNING": "⚠️", "CAUTION": "\U0001f6d1"}
EMOTICONS = {"smile": "😊", "sad": "😞", "cheeky": "😛", "laugh": "😁",
             "wink": "😉", "thumbs-up": "👍", "thumbs-down": "👎",
             "yes": "👍", "no": "👎", "information": "ℹ️", "tick": "✅",
             "cross": "❌", "warning": "⚠️", "plus": "➕", "minus": "➖",
             "question": "❓", "light-on": "💡", "light-off": "💡",
             "yellow-star": "⭐", "red-star": "⭐", "green-star": "⭐",
             "blue-star": "⭐", "heart": "❤️", "broken-heart": "💔"}


def _int_attr(cell, attr):
    try:
        return max(int(str(cell.get(attr, 1))), 1)
    except ValueError:
        return 1


def pad(rows):
    """Expand rowspan and colspan into a rectangular grid of cells.

    A merged cell fills every grid position it covers. The same Tag object
    is reused, so the caller converts each origin only once.
    """
    padded, occ = [], {}
    for r, row in enumerate(rows):
        if not row:
            continue
        cur, c = [], 0
        for cell in row:
            while (r, c) in occ:
                cur.append(occ.pop((r, c)))
                c += 1
            rs, cs = _int_attr(cell, "rowspan"), _int_attr(cell, "colspan")
            cur.extend([cell] * cs)
            for i in range(1, rs):
                for j in range(cs):
                    occ[(r + i, c + j)] = cell
            c += cs
        while (r, c) in occ:
            cur.append(occ.pop((r, c)))
            c += 1
        padded.append(cur)
    return padded


def cell_text(text):
    text = text.replace("|", "\\|").replace("\n", "<br/>")
    text = _LEADING_BR_OR_WS.sub("", text)
    return _TRAILING_BR_OR_WS.sub("", text)


def md_table(rows, headers):
    n = len(headers)
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * n) + " |"]
    for row in rows:
        row = (list(row) + [""] * n)[:n]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _tags(parent_tags):
    return parent_tags if isinstance(parent_tags, (list, set)) else set()


class Converter(MarkdownConverter):
    class Options(MarkdownConverter.DefaultOptions):
        bullets = "-"
        heading_style = ATX

    def __init__(self, base_url="", **options):
        super().__init__(**options)
        self.base_url = base_url

    def absolute(self, url):
        return urllib.parse.urljoin(self.base_url + "/", url) if url else url

    # ---- tables ----------------------------------------------------------

    def convert_table(self, el, text, parent_tags):
        if "table" in _tags(parent_tags):
            return str(el)  # nested table: keep as HTML
        trs = []
        for child in el.find_all(["thead", "tbody", "tfoot", "tr"], recursive=False):
            trs.extend([child] if child.name == "tr"
                       else child.find_all("tr", recursive=False))
        rows = [tr.find_all(["td", "th"], recursive=False) for tr in trs]
        if not any(rows):
            return ""
        padded = pad(rows)
        cache, converted = {}, []
        for row in padded:
            out = []
            for cell in row:
                if id(cell) not in cache:
                    cache[id(cell)] = self.process_tag(cell, parent_tags={"table"})
                out.append(cache[id(cell)])
            converted.append(out)
        has_header = all(cell.name == "th" for cell in rows[0])
        body = converted[1:] if has_header else converted
        headers = converted[0] if has_header else [""] * len(converted[0])
        return "\n\n" + md_table(body, headers) + "\n\n"

    def convert_th(self, el, text, parent_tags):
        return cell_text(text)

    convert_td = convert_th

    def convert_tr(self, el, text, parent_tags):
        return text

    convert_thead = convert_tbody = convert_tfoot = convert_tr

    # ---- block elements inside cells -------------------------------------

    def convert_p(self, el, text, parent_tags):
        md = super().convert_p(el, text, _tags(parent_tags))
        if "td" in _tags(parent_tags) or "th" in _tags(parent_tags):
            md = md.replace("\n", "") + "<br/>"
        return md

    def convert_ul(self, el, text, parent_tags):
        if "td" in _tags(parent_tags):
            items = [i for i in text.splitlines() if i.strip()]
            if len(items) <= 1:
                return "".join(items)
            return "- " + "<br>- ".join(items)
        return super().convert_ul(el, text, _tags(parent_tags))

    def convert_ol(self, el, text, parent_tags):
        if "td" in _tags(parent_tags):
            start = int(el.get("start") or 1)
            return "<br>".join(f"{start + i}. {item}".rstrip()
                               for i, item in enumerate(text.splitlines()) if item.strip())
        return super().convert_ol(el, text, _tags(parent_tags))

    def convert_li(self, el, text, parent_tags):
        if "td" in _tags(parent_tags):
            return text.strip().removesuffix("<br/>") + "\n"
        md = super().convert_li(el, text, _tags(parent_tags))
        if el.has_attr("data-inline-task-id"):  # Confluence task list
            checked = "checked" in (el.get("class") or [])
            return md.replace("- ", "- [x] " if checked else "- [ ] ", 1)
        return md

    # ---- macros ----------------------------------------------------------

    def convert_div(self, el, text, parent_tags):
        macro = str(el.get("data-macro-name", ""))
        if macro in ALERTS:
            alert = ALERTS[macro]
            if "td" in _tags(parent_tags) or "th" in _tags(parent_tags):
                return f"{ALERT_EMOJI[alert]} {text.strip()}"
            quote = super().convert_blockquote(el, text, _tags(parent_tags))
            return f"\n> [!{alert}]{quote}"
        classes = str(el.get("class", ""))
        if "expand-container" in classes:
            label = el.find("span", class_="expand-control-text")
            label = label.get_text().strip() if label else "Click here to expand..."
            body = el.find("div", class_="expand-content")
            body = self.process_tag(body, _tags(parent_tags)).strip() if body else ""
            return f"\n<details>\n<summary>{label}</summary>\n\n{body}\n\n</details>\n\n"
        return super().convert_div(el, text, _tags(parent_tags))

    def convert_pre(self, el, text, parent_tags):
        if not text:
            return ""
        lang = ""
        m = re.search(r"brush:\s*([^;]+)", str(el.get("data-syntaxhighlighter-params", "")))
        if m:
            lang = m.group(1)
        return f"\n\n```{lang}\n{text}\n```\n\n"

    def convert_sub(self, el, text, parent_tags):
        return f"<sub>{text}</sub>"

    def convert_sup(self, el, text, parent_tags):
        return f"<sup>{text}</sup>"

    # ---- links and images ------------------------------------------------

    def convert_a(self, el, text, parent_tags):
        if "user-mention" in str(el.get("class")):
            return text
        href = str(el.get("href", ""))
        if href and not href.startswith("#"):
            href = self.absolute(href)
            el["href"] = href.replace(" ", "%20").replace("(", "%28").replace(")", "%29")
        return super().convert_a(el, text, _tags(parent_tags))

    def convert_img(self, el, text, parent_tags):
        emoticon = el.get("data-emoji-fallback") or EMOTICONS.get(
            str(el.get("data-emoticon-name", "")))
        if emoticon:
            return emoticon
        if el.get("src"):
            el["src"] = self.absolute(str(el["src"]))
        return super().convert_img(el, text, _tags(parent_tags))


def to_markdown(view_html, base_url=""):
    return Converter(base_url=base_url).convert(view_html).strip() + "\n"
