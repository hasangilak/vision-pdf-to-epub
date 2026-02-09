"""EPUB3 assembler with RTL support."""

from __future__ import annotations

import html
from pathlib import Path

from ebooklib import epub

from app.config import settings

LANG_CONFIG = {
    "fa": {"dir": "rtl", "lang": "fa", "font_family": "Tahoma, 'Noto Naskh Arabic', serif"},
    "ar": {"dir": "rtl", "lang": "ar", "font_family": "Tahoma, 'Noto Naskh Arabic', serif"},
    "en": {"dir": "ltr", "lang": "en", "font_family": "Georgia, serif"},
}

RTL_CSS = """
body {{
    direction: {dir};
    unicode-bidi: embed;
    font-family: {font_family};
    font-size: 1.1em;
    line-height: 1.8;
    margin: 1em;
    text-align: justify;
}}
p {{
    margin: 0.5em 0;
    text-indent: 1em;
}}
.failed-page {{
    color: #999;
    font-style: italic;
    text-align: center;
    padding: 2em 0;
}}
"""


def assemble_epub(
    pages: dict[int, str],
    total_pages: int,
    output_path: Path,
    *,
    title: str = "Converted Book",
    language: str = "fa",
    pages_per_chapter: int = settings.pages_per_chapter,
) -> Path:
    """Build an EPUB3 file from ordered page texts.

    Args:
        pages: Mapping of page_number -> extracted text. Missing pages get a
               placeholder.
        total_pages: Total number of pages in the source PDF.
        output_path: Where to write the .epub file.
        title: Book title metadata.
        language: Language code (fa, ar, en).
        pages_per_chapter: How many pages per EPUB chapter.

    Returns:
        The output_path.
    """
    lang_cfg = LANG_CONFIG.get(language, LANG_CONFIG["fa"])

    book = epub.EpubBook()
    book.set_identifier("vision-pdf-to-epub")
    book.set_title(title)
    book.set_language(lang_cfg["lang"])
    book.set_direction(lang_cfg["dir"])

    css_content = RTL_CSS.format(**lang_cfg)
    style = epub.EpubItem(
        uid="style",
        file_name="style/default.css",
        media_type="text/css",
        content=css_content.encode("utf-8"),
    )
    book.add_item(style)

    chapters = []
    spine = ["nav"]

    for ch_start in range(0, total_pages, pages_per_chapter):
        ch_end = min(ch_start + pages_per_chapter, total_pages)
        ch_num = ch_start // pages_per_chapter + 1

        body_parts = []
        for page_num in range(ch_start, ch_end):
            text = pages.get(page_num)
            if text:
                paragraphs = text.strip().split("\n\n")
                for para in paragraphs:
                    para = para.strip()
                    if para:
                        escaped = html.escape(para).replace("\n", "<br/>")
                        body_parts.append(f"<p>{escaped}</p>")
            else:
                body_parts.append(
                    f'<p class="failed-page">[Page {page_num + 1}: OCR failed]</p>'
                )

        chapter = epub.EpubHtml(
            title=f"Pages {ch_start + 1}–{ch_end}",
            file_name=f"chapter_{ch_num:03d}.xhtml",
            lang=lang_cfg["lang"],
        )
        chapter.content = (
            f'<html xmlns="http://www.w3.org/1999/xhtml" dir="{lang_cfg["dir"]}" '
            f'xml:lang="{lang_cfg["lang"]}">\n'
            f"<head><title>Pages {ch_start + 1}–{ch_end}</title></head>\n"
            f'<body dir="{lang_cfg["dir"]}">{"".join(body_parts)}</body>\n'
            f"</html>"
        )
        chapter.add_item(style)
        book.add_item(chapter)
        chapters.append(chapter)
        spine.append(chapter)

    book.toc = chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine

    output_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(output_path), book)
    return output_path
