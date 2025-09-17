#!/usr/bin/env python3
"""
Fetch a Wattpad story and export it to a PDF document.

Usage:
    python w4tty https://www.wattpad.com/story/123456-your-story [--out my_story.pdf]
"""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag
from fpdf import FPDF, HTMLMixin

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/115.0 Safari/537.36"
        )
    }
)

STYLE_SUFFIX_MAP: Tuple[Tuple[str, str], ...] = (
    ("boldoblique", "BI"),
    ("bolditalic", "BI"),
    ("bold", "B"),
    ("oblique", "I"),
    ("italic", "I"),
    ("regular", ""),
    ("book", ""),
)

ALIGN_VALUE_MAP = {"left": "L", "center": "C", "right": "R", "justify": "J"}
ALIGN_WORD_MAP = {"L": "left", "C": "center", "R": "right", "J": "justify"}
YI_RANGE_PATTERN = re.compile(r"([\uA000-\uA48F]+)")
PART_DATE_PATTERN = re.compile(r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}$", re.IGNORECASE)


class WattpadPDF(FPDF, HTMLMixin):
    """FPDF instance with HTML rendering helpers."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download a Wattpad story to PDF.")
    parser.add_argument("url", help="Full Wattpad story URL")
    parser.add_argument("--out", help="Output PDF path (defaults to '<slug>.pdf')")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout in seconds")
    return parser.parse_args()


def extract_story_id(url: str) -> str:
    parts = [p for p in url.split("/") if p]
    try:
        story_fragment = next(p for p in parts[::-1] if re.match(r"^\d+", p))
    except StopIteration:
        raise ValueError("Could not detect story ID in URL; please use the canonical story link.")
    return story_fragment.split("-")[0]


def _strip_wattpad_suffix(value: str) -> str:
    suffix = " - Wattpad"
    return value.rsplit(suffix, 1)[0].strip() if value.endswith(suffix) else value.strip()


def _sanitize_filename(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[<>:\"/\\|?*]", "_", value)
    cleaned = cleaned.replace("\x00", "_")
    cleaned = cleaned.strip()
    cleaned = cleaned.rstrip(". ")
    if len(cleaned) > 120:
        cleaned = cleaned[:120].rstrip(". ")
    return cleaned or fallback

def _clean_part_title(raw: str) -> str:
    cleaned = PART_DATE_PATTERN.sub('', raw).strip()
    cleaned = re.sub(r'[\s,:-]+$', '', cleaned).strip()
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)
    return cleaned


def register_available_fonts(pdf: FPDF) -> Dict[str, Set[str]]:
    fonts_dir = Path(__file__).parent
    registered: Dict[str, Set[str]] = {}
    seen: Set[Tuple[str, str]] = set()
    regular_files: Dict[str, Path] = {}

    for font_path in sorted(fonts_dir.glob("*.ttf")):
        stem = font_path.stem
        base = stem
        style = ""

        if "-" in stem:
            base_candidate, suffix = stem.split("-", 1)
            lowered_suffix = suffix.lower()
            for keyword, mapped_style in STYLE_SUFFIX_MAP:
                if lowered_suffix.endswith(keyword):
                    base = base_candidate
                    style = mapped_style
                    break

        key = (base, style)
        if key in seen:
            continue

        pdf.add_font(base, style, fname=str(font_path))
        registered.setdefault(base, set()).add(style)
        seen.add(key)
        if style in {"", "regular"}:
            regular_files.setdefault(base, font_path)

    if not registered:
        raise FileNotFoundError("No .ttf fonts found alongside the script.")

    for family, styles in list(registered.items()):
        regular_path = regular_files.get(family)
        if not regular_path:
            continue
        for fallback_style in ("B", "I", "BI"):
            if fallback_style not in styles:
                pdf.add_font(family, fallback_style, fname=str(regular_path))
                styles.add(fallback_style)

    return registered


def _extract_alignment(tag: Tag) -> str:
    style_value = (tag.get("style") or "").lower()
    for segment in style_value.split(";"):
        segment = segment.strip()
        if segment.startswith("text-align"):
            _, _, value = segment.partition(":")
            value = value.strip()
            if value in ALIGN_VALUE_MAP:
                return ALIGN_VALUE_MAP[value]
    align_attr = (tag.get("align") or "").lower()
    if align_attr in ALIGN_VALUE_MAP:
        return ALIGN_VALUE_MAP[align_attr]
    classes = [c.lower() for c in (tag.get("class") or [])]
    for cls in classes:
        if "center" in cls:
            return "C"
        if "right" in cls:
            return "R"
        if "justify" in cls:
            return "J"
    return "L"


def _wrap_yi_sequences(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        return f"<font face=\"NotoSansYi\">{match.group(1)}</font>"

    return YI_RANGE_PATTERN.sub(repl, text)


def _render_node(node: object) -> str:
    if isinstance(node, NavigableString):
        text = str(node)
        if not text:
            return ""
        text = text.replace("\xa0", " ")
        escaped = html.escape(text, quote=False)
        return _wrap_yi_sequences(escaped)

    if not isinstance(node, Tag):
        return ""

    name = node.name.lower()
    if name == "br":
        return "<br/>"
    if name == "hr":
        return "<hr/>"

    inner = "".join(_render_node(child) for child in node.children)
    if not inner and name not in {"img"}:
        return ""

    style_attr = (node.get("style") or "").lower()
    classes = [c.lower() for c in (node.get("class") or [])]

    def apply_wrapper(content: str, tag_name: str) -> str:
        return f"<{tag_name}>{content}</{tag_name}>"

    if name in {"b", "strong"}:
        inner = apply_wrapper(inner, "b")
    if name in {"i", "em"}:
        inner = apply_wrapper(inner, "i")
    if name == "u":
        inner = apply_wrapper(inner, "u")
    if name in {"sup", "sub"}:
        inner = apply_wrapper(inner, name)

    if "font-weight" in style_attr and "bold" in style_attr:
        inner = apply_wrapper(inner, "b")
    if "font-style" in style_attr and "italic" in style_attr:
        inner = apply_wrapper(inner, "i")
    if "text-decoration" in style_attr and "underline" in style_attr:
        inner = apply_wrapper(inner, "u")

    if any("bold" in cls for cls in classes):
        inner = apply_wrapper(inner, "b")
    if any("italic" in cls for cls in classes):
        inner = apply_wrapper(inner, "i")
    if any("underline" in cls for cls in classes):
        inner = apply_wrapper(inner, "u")

    if name == "a" and node.get("href"):
        href = html.escape(node["href"], quote=True)
        inner = f"<a href=\"{href}\">{inner}</a>"

    font_face = node.get("face") or node.get("data-font")
    if not font_face and name == "span":
        data_font = node.get("data-font")
        if data_font:
            font_face = data_font
    if font_face:
        face = html.escape(font_face, quote=True)
        inner = f"<font face=\"{face}\">{inner}</font>"

    if name == "font" and node.get("color"):
        color = html.escape(node["color"], quote=True)
        inner = f"<font color=\"{color}\">{inner}</font>"

    return inner


def _render_inline_children(tag: Tag) -> str:
    return "".join(_render_node(child) for child in tag.children)


def _render_blocks_from_node(node: object, inherited_align: str = "L") -> List[str]:
    blocks: List[str] = []

    if isinstance(node, NavigableString):
        content = _render_node(node).strip()
        if content:
            align_word = ALIGN_WORD_MAP.get(inherited_align, "left")
            blocks.append(f'<p align="{align_word}">{content}</p>')
        return blocks

    if not isinstance(node, Tag):
        return blocks

    name = node.name.lower()
    node_align = _extract_alignment(node)
    if node_align == "L":
        node_align = inherited_align
    align_word = ALIGN_WORD_MAP.get(node_align, "left")
    align_attr = f' align="{align_word}"' if node_align != "L" else ""

    if name == "div":
        child_blocks: List[str] = []
        for child in node.children:
            child_blocks.extend(_render_blocks_from_node(child, node_align))
        if child_blocks:
            if align_attr:
                return [f'<div{align_attr}>{block}</div>' for block in child_blocks]
            return child_blocks

    if name in {"p", "section", "article"}:
        inner = _render_inline_children(node).strip()
        if inner:
            blocks.append(f'<p{align_attr}>{inner}</p>')
        return blocks

    if name in {"h1", "h2", "h3", "h4"}:
        inner = _render_inline_children(node).strip()
        if inner:
            blocks.append(f'<{name}{align_attr}>{inner}</{name}>')
        return blocks

    if name == "blockquote":
        inner = _render_inline_children(node).strip()
        if inner:
            blocks.append(f'<blockquote{align_attr}>{inner}</blockquote>')
        return blocks

    if name in {"ul", "ol"}:
        items: List[str] = []
        for li in node.find_all("li", recursive=False):
            item_inner = _render_inline_children(li).strip()
            if item_inner:
                items.append(f'<li>{item_inner}</li>')
        if items:
            wrapper_open = f'<div{align_attr}>' if align_attr else ''
            wrapper_close = '</div>' if align_attr else ''
            blocks.append(f'{wrapper_open}<{name}>{"".join(items)}</{name}>{wrapper_close}')
        return blocks

    if name == "hr":
        blocks.append('<hr/>')
        return blocks

    inner = _render_inline_children(node).strip()
    if inner:
        blocks.append(f'<p{align_attr}>{inner}</p>')
    return blocks


def fetch_part_blocks(part_id: str, timeout: int) -> List[str]:
    resp = SESSION.get(
        "https://www.wattpad.com/apiv2/storytext",
        params={"id": part_id},
        timeout=timeout,
    )
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "").lower()
    if "json" in content_type:
        payload = resp.json()
        body = payload.get("text", "")
    else:
        body = resp.text

    if not body.strip():
        raise RuntimeError(f"Empty response for part {part_id}.")

    soup = BeautifulSoup(body, "html.parser")
    blocks: List[str] = []
    for child in soup.contents:
        blocks.extend(_render_blocks_from_node(child))
    return blocks


def scrape_story_overview(url: str, timeout: int) -> Tuple[str, List[Dict[str, str]]]:
    resp = SESSION.get(url, timeout=timeout)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    title: str | None = None
    meta_title = soup.find("meta", {"property": "og:title"})
    if isinstance(meta_title, Tag):
        content_attr = meta_title.attrs.get("content")
        if isinstance(content_attr, str):
            title = _strip_wattpad_suffix(content_attr)
    if not title:
        heading = soup.find(["h1", "h2"])
        if isinstance(heading, Tag):
            title = _strip_wattpad_suffix(heading.get_text(strip=True))
    if not title and soup.title and isinstance(soup.title.string, str):
        title = _strip_wattpad_suffix(soup.title.string.strip())
    if not title:
        raise RuntimeError("Couldn't locate the story title on the page.")

    parts: List[Dict[str, str]] = []
    for element in soup.select('ul[aria-label="story-parts"] a[href]'):
        if not isinstance(element, Tag):
            continue
        href_attr = element.get("href")
        if not isinstance(href_attr, str):
            continue
        part_url = urljoin(url, href_attr)
        part_id = extract_story_id(part_url)
        part_title = _clean_part_title(element.get_text(" ", strip=True))
        parts.append({"id": part_id, "title": part_title, "url": part_url})

    if not parts:
        raise RuntimeError("Couldn't find any public parts in the table of contents.")

    return title, parts


def build_pdf(story_title: str, chapters: List[Dict[str, object]], output: Path) -> None:
    pdf = WattpadPDF(format="Letter")
    pdf.set_auto_page_break(auto=True, margin=15)

    font_variants = register_available_fonts(pdf)
    base_family = "DejaVuSans" if "DejaVuSans" in font_variants else next(iter(font_variants))
    pdf.set_font(base_family, "", 16)

    html_parts: List[str] = [f'<h1 align="center">{html.escape(story_title)}</h1>']

    for chapter in chapters:
        title = chapter.get("title")
        blocks: List[str] = chapter.get("blocks", [])  # type: ignore[assignment]
        if title:
            html_parts.append(f'<h2 align="center">{html.escape(str(title))}</h2>')
        for block_html in blocks:
            html_parts.append(block_html)
        html_parts.append('<br/>')

    html_body = "\n".join(html_parts)

    pdf.add_page()
    pdf.write_html(html_body)

    output.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output))


def main() -> None:
    args = parse_args()
    story_title, parts = scrape_story_overview(args.url, timeout=args.timeout)

    chapters: List[Dict[str, object]] = []
    for part in parts:
        part_id = str(part["id"])
        part_title = _clean_part_title(part.get("title") or f"Part {part_id}")
        blocks = fetch_part_blocks(part_id, timeout=args.timeout)
        chapters.append({"title": part_title, "blocks": blocks})

    fallback_name = f"Wattpad Story {parts[0]['id']}" if parts else "Wattpad Story"
    base_name = _sanitize_filename(story_title, fallback_name)
    output_path = Path(args.out) if args.out else Path(f"{base_name}.pdf")
    build_pdf(story_title, chapters, output_path)
    print(f"Saved {story_title!r} to {output_path}")


if __name__ == "__main__":
    main()
