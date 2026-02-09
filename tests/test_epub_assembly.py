"""Tests for the EPUB builder (architecture §8)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.pipeline.assembler import assemble_epub


class TestEpubAssembly:
    def test_produces_valid_epub(self, tmp_path: Path):
        pages = {0: "Hello world", 1: "Page two", 2: "Page three"}
        out = tmp_path / "output.epub"
        assemble_epub(pages, 3, out, title="Test Book", pages_per_chapter=20)

        assert out.exists()
        assert out.stat().st_size > 0
        # EPUB is a ZIP file
        assert zipfile.is_zipfile(out)

    def test_rtl_for_farsi(self, tmp_path: Path):
        pages = {0: "متن فارسی"}
        out = tmp_path / "fa.epub"
        assemble_epub(pages, 1, out, language="fa", pages_per_chapter=20)

        with zipfile.ZipFile(out) as z:
            # Check CSS for RTL direction
            css_files = [n for n in z.namelist() if n.endswith(".css")]
            assert css_files
            css = z.read(css_files[0]).decode("utf-8")
            assert "direction: rtl" in css
            # Check chapter has Farsi language
            chapter_files = [n for n in z.namelist() if n.endswith(".xhtml") and "chapter" in n]
            assert chapter_files
            content = z.read(chapter_files[0]).decode("utf-8")
            assert 'lang="fa"' in content

    def test_rtl_for_arabic(self, tmp_path: Path):
        pages = {0: "نص عربي"}
        out = tmp_path / "ar.epub"
        assemble_epub(pages, 1, out, language="ar", pages_per_chapter=20)

        with zipfile.ZipFile(out) as z:
            css_files = [n for n in z.namelist() if n.endswith(".css")]
            css = z.read(css_files[0]).decode("utf-8")
            assert "direction: rtl" in css
            chapter_files = [n for n in z.namelist() if n.endswith(".xhtml") and "chapter" in n]
            content = z.read(chapter_files[0]).decode("utf-8")
            assert 'lang="ar"' in content

    def test_ltr_for_english(self, tmp_path: Path):
        pages = {0: "English text"}
        out = tmp_path / "en.epub"
        assemble_epub(pages, 1, out, language="en", pages_per_chapter=20)

        with zipfile.ZipFile(out) as z:
            css_files = [n for n in z.namelist() if n.endswith(".css")]
            css = z.read(css_files[0]).decode("utf-8")
            assert "direction: ltr" in css
            chapter_files = [n for n in z.namelist() if n.endswith(".xhtml") and "chapter" in n]
            content = z.read(chapter_files[0]).decode("utf-8")
            assert 'lang="en"' in content

    def test_unknown_language_defaults_to_farsi(self, tmp_path: Path):
        pages = {0: "Unknown lang text"}
        out = tmp_path / "unknown.epub"
        assemble_epub(pages, 1, out, language="xx", pages_per_chapter=20)

        with zipfile.ZipFile(out) as z:
            css_files = [n for n in z.namelist() if n.endswith(".css")]
            css = z.read(css_files[0]).decode("utf-8")
            assert "direction: rtl" in css
            chapter_files = [n for n in z.namelist() if n.endswith(".xhtml") and "chapter" in n]
            content = z.read(chapter_files[0]).decode("utf-8")
            assert 'lang="fa"' in content

    def test_missing_pages_get_placeholder(self, tmp_path: Path):
        # Only page 0 has text, pages 1 and 2 are missing
        pages = {0: "Some text"}
        out = tmp_path / "missing.epub"
        assemble_epub(pages, 3, out, pages_per_chapter=20)

        with zipfile.ZipFile(out) as z:
            chapter_files = [n for n in z.namelist() if n.endswith(".xhtml") and "chapter" in n]
            content = z.read(chapter_files[0]).decode("utf-8")
            assert "[Page 2: OCR failed]" in content
            assert "[Page 3: OCR failed]" in content

    def test_chapter_grouping(self, tmp_path: Path):
        pages = {i: f"Page {i}" for i in range(5)}
        out = tmp_path / "chapters.epub"
        assemble_epub(pages, 5, out, pages_per_chapter=2)

        with zipfile.ZipFile(out) as z:
            chapter_files = sorted(
                n for n in z.namelist() if n.endswith(".xhtml") and "chapter" in n
            )
            # 5 pages / 2 per chapter = 3 chapters
            assert len(chapter_files) == 3

    def test_html_escaping(self, tmp_path: Path):
        pages = {0: "<script>alert('xss')</script> & more"}
        out = tmp_path / "escape.epub"
        assemble_epub(pages, 1, out, pages_per_chapter=20)

        with zipfile.ZipFile(out) as z:
            chapter_files = [n for n in z.namelist() if n.endswith(".xhtml") and "chapter" in n]
            content = z.read(chapter_files[0]).decode("utf-8")
            assert "<script>" not in content
            assert "&lt;script&gt;" in content
            assert "&amp; more" in content

    def test_paragraph_splitting(self, tmp_path: Path):
        pages = {0: "First paragraph\n\nSecond paragraph\n\nThird paragraph"}
        out = tmp_path / "paras.epub"
        assemble_epub(pages, 1, out, pages_per_chapter=20)

        with zipfile.ZipFile(out) as z:
            chapter_files = [n for n in z.namelist() if n.endswith(".xhtml") and "chapter" in n]
            content = z.read(chapter_files[0]).decode("utf-8")
            assert content.count("<p>") >= 3

    def test_book_metadata(self, tmp_path: Path):
        pages = {0: "Content"}
        out = tmp_path / "meta.epub"
        assemble_epub(pages, 1, out, title="My Book", language="en", pages_per_chapter=20)

        with zipfile.ZipFile(out) as z:
            # Check OPF file for metadata
            opf_files = [n for n in z.namelist() if n.endswith(".opf")]
            assert opf_files
            opf_content = z.read(opf_files[0]).decode("utf-8")
            assert "My Book" in opf_content
            assert ">en<" in opf_content
