"""Document text extraction: txt/md/csv/pdf/docx + unsupported fallback."""

from __future__ import annotations

import csv

import pytest

from bot.services.doc_extractor import (
    DocExtractError,
    EmptyDocumentError,
    UnsupportedDocumentError,
    extract,
)


def test_txt_happy(tmp_path):
    p = tmp_path / "note.txt"
    p.write_text("hello\nworld\n", encoding="utf-8")
    assert extract(str(p), "text/plain", "note.txt") == "hello\nworld\n"


def test_txt_strips_bom(tmp_path):
    p = tmp_path / "bom.txt"
    p.write_bytes("﻿hello".encode("utf-8"))
    assert extract(str(p), "text/plain", "bom.txt") == "hello"


def test_md_happy(tmp_path):
    body = "# Title\n\n- one\n- two\n"
    p = tmp_path / "doc.md"
    p.write_text(body, encoding="utf-8")
    assert extract(str(p), "text/markdown", "doc.md") == body


def test_csv_happy(tmp_path):
    p = tmp_path / "data.csv"
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "score"])
        w.writerow(["alice", "10"])
        w.writerow(["bob", "20"])
    out = extract(str(p), "text/csv", "data.csv")
    assert "name | score" in out
    assert "alice | 10" in out
    assert "bob | 20" in out


def test_pdf_with_text(tmp_path):
    reportlab = pytest.importorskip("reportlab")
    from reportlab.pdfgen.canvas import Canvas

    p = tmp_path / "agenda.pdf"
    c = Canvas(str(p))
    c.drawString(72, 720, "MEETING AGENDA TOKEN")
    c.showPage()
    c.save()

    out = extract(str(p), "application/pdf", "agenda.pdf")
    assert "MEETING AGENDA TOKEN" in out


def test_pdf_empty_raises(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    from pypdf import PdfWriter

    p = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with open(p, "wb") as f:
        writer.write(f)

    with pytest.raises(EmptyDocumentError):
        extract(str(p), "application/pdf", "blank.pdf")


def test_docx_happy(tmp_path):
    docx = pytest.importorskip("docx")

    p = tmp_path / "meeting.docx"
    doc = docx.Document()
    doc.add_paragraph("Discussion on roadmap.")
    table = doc.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "Owner"
    table.rows[0].cells[1].text = "Status"
    table.rows[1].cells[0].text = "Alice"
    table.rows[1].cells[1].text = "Done"
    doc.save(str(p))

    out = extract(
        str(p),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "meeting.docx",
    )
    assert "Discussion on roadmap." in out
    assert "Owner" in out and "Status" in out
    assert "Alice" in out and "Done" in out


def test_unsupported_binary_raises(tmp_path):
    p = tmp_path / "x.msi"
    p.write_bytes(b"\x00\x01\x02\xff\xfe\xfd" * 1024)
    with pytest.raises(UnsupportedDocumentError):
        extract(str(p), "application/x-msi", "x.msi")


def test_unknown_mime_text_fallback(tmp_path):
    p = tmp_path / "data.bar"
    p.write_text("plain ascii lines\n", encoding="utf-8")
    assert extract(str(p), None, "data.bar") == "plain ascii lines\n"


def test_extension_wins_over_mime(tmp_path):
    p = tmp_path / "agenda.txt"
    p.write_text("hello agenda", encoding="utf-8")
    assert (
        extract(str(p), "application/octet-stream", "agenda.txt") == "hello agenda"
    )


def test_docextracterror_unused():
    """Sanity: import surface stable."""
    assert issubclass(EmptyDocumentError, DocExtractError)
    assert issubclass(UnsupportedDocumentError, DocExtractError)
