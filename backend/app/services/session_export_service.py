from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from app.schemas.note import NoteItem, NotesPayload


class SessionExportService:
    """Build downloadable document exports from stored session notes."""

    def build_word_document(
        self,
        *,
        session: dict[str, Any],
        notes: NotesPayload,
    ) -> bytes:
        package = BytesIO()
        with ZipFile(package, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", self._build_content_types_xml())
            archive.writestr("_rels/.rels", self._build_root_relationships_xml())
            archive.writestr("docProps/core.xml", self._build_core_properties_xml(session))
            archive.writestr("docProps/app.xml", self._build_app_properties_xml())
            archive.writestr("word/document.xml", self._build_document_xml(session=session, notes=notes))
            archive.writestr("word/_rels/document.xml.rels", self._build_document_relationships_xml())
        return package.getvalue()

    def build_printable_html(
        self,
        *,
        session: dict[str, Any],
        notes: NotesPayload,
    ) -> str:
        title = self._text(session.get("page_title")) or "Studysis Notes"
        page_url = self._text(session.get("page_url"))
        overview = self._text(notes.overview_summary or notes.quick_summary)
        backend_message = self._text(notes.backend_message)
        structured = notes.structured_notes or []
        exam_points = notes.exam_points or []

        note_cards = "".join(self._build_note_card(note) for note in structured)
        exam_cards = "".join(self._build_exam_card(note) for note in exam_points)

        if not note_cards:
            note_cards = '<p class="empty">No structured notes are available yet.</p>'
        if not exam_cards:
            exam_cards = '<p class="empty">No exam points are available yet.</p>'

        overview_html = f"<p>{escape(overview)}</p>" if overview else (
            f'<p class="empty">{escape(backend_message or "No overview is available yet.")}</p>'
        )
        page_url_html = (
            f'<p class="meta"><strong>Page:</strong> <a href="{escape(page_url)}">{escape(page_url)}</a></p>'
            if page_url
            else ""
        )

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escape(title)}</title>
    <style>
      :root {{
        color-scheme: light;
        --bg: #f6f7fb;
        --card: #ffffff;
        --line: #d7ddea;
        --text: #172033;
        --muted: #5b687d;
        --accent: #1f6feb;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        background: var(--bg);
        color: var(--text);
        font: 16px/1.7 "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      }}
      .page {{
        max-width: 960px;
        margin: 0 auto;
        padding: 32px 24px 64px;
      }}
      .toolbar {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
        margin-bottom: 24px;
        padding: 16px 18px;
        border: 1px solid var(--line);
        border-radius: 16px;
        background: var(--card);
      }}
      .toolbar button {{
        border: 0;
        border-radius: 999px;
        background: var(--accent);
        color: #fff;
        font: inherit;
        font-weight: 600;
        padding: 10px 16px;
        cursor: pointer;
      }}
      .toolbar p {{
        margin: 0;
        color: var(--muted);
      }}
      .section {{
        margin-bottom: 20px;
        padding: 22px;
        border: 1px solid var(--line);
        border-radius: 18px;
        background: var(--card);
      }}
      h1, h2, h3 {{ margin: 0 0 12px; line-height: 1.35; }}
      h1 {{ font-size: 32px; }}
      h2 {{ font-size: 22px; }}
      h3 {{ font-size: 18px; }}
      .meta {{
        margin: 0 0 10px;
        color: var(--muted);
      }}
      .note {{
        padding-top: 18px;
        margin-top: 18px;
        border-top: 1px solid var(--line);
      }}
      .note:first-of-type {{
        margin-top: 0;
        padding-top: 0;
        border-top: 0;
      }}
      .note-meta {{
        margin: 0 0 8px;
        color: var(--muted);
        font-size: 14px;
      }}
      .note p {{
        margin: 0 0 10px;
        white-space: pre-wrap;
      }}
      .note ul {{
        margin: 0;
        padding-left: 20px;
      }}
      .gallery {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 12px;
        margin-top: 12px;
      }}
      .gallery img {{
        width: 100%;
        border-radius: 12px;
        border: 1px solid var(--line);
      }}
      .empty {{
        margin: 0;
        color: var(--muted);
      }}
      @media print {{
        body {{
          background: #fff;
        }}
        .page {{
          max-width: none;
          padding: 0;
        }}
        .toolbar {{
          display: none;
        }}
        .section {{
          border: 0;
          border-radius: 0;
          padding: 0 0 20px;
          margin-bottom: 20px;
          box-shadow: none;
        }}
      }}
    </style>
  </head>
  <body>
    <main class="page">
      <div class="toolbar">
        <p>Use your browser's "Save as PDF" destination to keep a local PDF copy.</p>
        <button type="button" onclick="window.print()">Print / Save PDF</button>
      </div>

      <section class="section">
        <h1>{escape(title)}</h1>
        {page_url_html}
      </section>

      <section class="section">
        <h2>Overview</h2>
        {overview_html}
      </section>

      <section class="section">
        <h2>Structured Notes</h2>
        {note_cards}
      </section>

      <section class="section">
        <h2>Exam Points</h2>
        {exam_cards}
      </section>
    </main>

    <script>
      const params = new URLSearchParams(window.location.search);
      if (params.get("autoprint") === "1") {{
        window.addEventListener("load", () => {{
          window.setTimeout(() => window.print(), 300);
        }});
      }}
    </script>
  </body>
</html>
"""

    def build_download_filename(self, *, session: dict[str, Any], extension: str) -> str:
        title = self._text(session.get("page_title")) or self._text(session.get("session_id")) or "studysis-notes"
        safe = "".join(
            char if char.isascii() and (char.isalnum() or char in {"-", "_", " "}) else "-"
            for char in title
        ).strip()
        safe = safe[:80].strip() or "studysis-notes"
        return f"{safe}.{extension.lstrip('.')}"

    def _build_note_card(self, note: NoteItem) -> str:
        note_meta = " | ".join(part for part in [self._text(note.category), self._text(note.timestamp)] if part)
        content = self._text(note.content)
        detail = self._text(note.detail)
        images = "".join(
            f'<img src="{escape(url)}" alt="{escape(note.title or "note image")}" />'
            for url in note.image_urls
            if self._text(url)
        )
        gallery = f'<div class="gallery">{images}</div>' if images else ""
        content_html = f"<p>{escape(content)}</p>" if content else ""
        detail_html = f"<p>{escape(detail)}</p>" if detail else ""
        meta_html = f'<p class="note-meta">{escape(note_meta)}</p>' if note_meta else ""
        return (
            '<article class="note">'
            f"<h3>{escape(self._text(note.title) or 'Untitled chapter')}</h3>"
            f"{meta_html}"
            f"{content_html}"
            f"{detail_html}"
            f"{gallery}"
            "</article>"
        )

    def _build_exam_card(self, note: NoteItem) -> str:
        note_meta = " | ".join(part for part in [self._text(note.category), self._text(note.timestamp)] if part)
        meta_html = f'<p class="note-meta">{escape(note_meta)}</p>' if note_meta else ""
        return (
            '<article class="note">'
            f"<h3>{escape(self._text(note.title) or 'Exam point')}</h3>"
            f"{meta_html}"
            f"<p>{escape(self._text(note.content))}</p>"
            "</article>"
        )

    def _build_content_types_xml(self) -> str:
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
"""

    def _build_root_relationships_xml(self) -> str:
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""

    def _build_core_properties_xml(self, session: dict[str, Any]) -> str:
        now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        title = escape(self._text(session.get("page_title")) or "Studysis Notes")
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties
  xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
  xmlns:dc="http://purl.org/dc/elements/1.1/"
  xmlns:dcterms="http://purl.org/dc/terms/"
  xmlns:dcmitype="http://purl.org/dc/dcmitype/"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>{title}</dc:title>
  <dc:creator>Studysis</dc:creator>
  <cp:lastModifiedBy>Studysis</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>
</cp:coreProperties>
"""

    def _build_app_properties_xml(self) -> str:
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties
  xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
  xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Studysis</Application>
</Properties>
"""

    def _build_document_relationships_xml(self) -> str:
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships" />
"""

    def _build_document_xml(self, *, session: dict[str, Any], notes: NotesPayload) -> str:
        parts: list[str] = []

        title = self._text(session.get("page_title")) or "Studysis Notes"
        page_url = self._text(session.get("page_url"))
        overview = self._text(notes.overview_summary or notes.quick_summary)
        backend_message = self._text(notes.backend_message)

        parts.append(self._paragraph(title, bold=True, size=34))
        if page_url:
            parts.append(self._paragraph(f"Page URL: {page_url}", color="5B687D"))

        parts.append(self._spacer())
        parts.append(self._paragraph("Overview", bold=True, size=26))
        parts.extend(self._paragraphs_from_text(overview or backend_message or "No overview is available yet."))

        parts.append(self._spacer())
        parts.append(self._paragraph("Structured Notes", bold=True, size=26))
        if notes.structured_notes:
            for note in notes.structured_notes:
                parts.extend(self._build_note_paragraphs(note))
        else:
            parts.append(self._paragraph("No structured notes are available yet.", color="5B687D"))

        parts.append(self._spacer())
        parts.append(self._paragraph("Exam Points", bold=True, size=26))
        if notes.exam_points:
            for note in notes.exam_points:
                label = self._compose_exam_line(note)
                parts.extend(self._paragraphs_from_text(label, indent=360))
        else:
            parts.append(self._paragraph("No exam points are available yet.", color="5B687D"))

        body = "".join(parts) + """
<w:sectPr>
  <w:pgSz w:w="11906" w:h="16838"/>
  <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="708" w:footer="708" w:gutter="0"/>
</w:sectPr>
"""
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    {body}
  </w:body>
</w:document>
"""

    def _build_note_paragraphs(self, note: NoteItem) -> list[str]:
        paragraphs = [
            self._paragraph(self._text(note.title) or "Untitled chapter", bold=True, size=24),
        ]
        meta = " | ".join(part for part in [self._text(note.category), self._text(note.timestamp)] if part)
        if meta:
            paragraphs.append(self._paragraph(meta, color="5B687D"))
        if self._text(note.content):
            paragraphs.extend(self._paragraphs_from_text(note.content))
        if self._text(note.detail):
            paragraphs.extend(self._paragraphs_from_text(note.detail))
        if note.image_urls:
            paragraphs.append(self._paragraph("Reference images:", bold=True))
            for url in note.image_urls:
                if self._text(url):
                    paragraphs.append(self._paragraph(f"- {url}", indent=360, color="1F6FEB"))
        paragraphs.append(self._spacer())
        return paragraphs

    def _compose_exam_line(self, note: NoteItem) -> str:
        prefix_parts = [self._text(note.title), self._text(note.timestamp)]
        prefix = " | ".join(part for part in prefix_parts if part)
        content = self._text(note.content)
        if prefix and content:
            return f"- {prefix}: {content}"
        if content:
            return f"- {content}"
        return f"- {prefix or 'Exam point'}"

    def _paragraphs_from_text(
        self,
        text: str,
        *,
        indent: int = 0,
    ) -> list[str]:
        lines = [line.strip() for line in self._text(text).splitlines()]
        normalized = [line for line in lines if line]
        if not normalized:
            return [self._paragraph("", indent=indent)]
        return [self._paragraph(line, indent=indent) for line in normalized]

    def _paragraph(
        self,
        text: str,
        *,
        bold: bool = False,
        size: int | None = None,
        color: str | None = None,
        indent: int = 0,
    ) -> str:
        paragraph_props = []
        if indent:
            paragraph_props.append(f'<w:ind w:left="{indent}"/>')
        paragraph_props_xml = f"<w:pPr>{''.join(paragraph_props)}</w:pPr>" if paragraph_props else ""

        run_props = []
        if bold:
            run_props.append("<w:b/>")
        if size is not None:
            run_props.append(f'<w:sz w:val="{size}"/>')
        if color:
            run_props.append(f'<w:color w:val="{color}"/>')
        run_props_xml = f"<w:rPr>{''.join(run_props)}</w:rPr>" if run_props else ""

        safe_text = escape(self._text(text))
        if safe_text:
            text_xml = f'<w:t xml:space="preserve">{safe_text}</w:t>'
        else:
            text_xml = "<w:t></w:t>"
        return f"<w:p>{paragraph_props_xml}<w:r>{run_props_xml}{text_xml}</w:r></w:p>"

    def _spacer(self) -> str:
        return '<w:p><w:pPr><w:spacing w:after="120"/></w:pPr></w:p>'

    def _text(self, value: Any) -> str:
        return str(value or "").strip()


session_export_service = SessionExportService()
