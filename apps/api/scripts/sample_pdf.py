"""A minimal PDF writer for fictional sample documents: text lines, Helvetica, standard library only.

Every page gets STAMP at the top and the bottom, in bold, so a sample can
never be mistaken for a real record, whichever page is looked at.
"""

from __future__ import annotations

PAGE_WIDTH, PAGE_HEIGHT = 595, 842  # A4 in points
LEFT, TOP, LINE_HEIGHT, FONT_SIZE = 56, 770, 16, 10
LINES_PER_PAGE = 42
STAMP = "SAMPLE DOCUMENT - FICTIONAL PATIENT"


def _escape(text: str) -> str:
    """PDF string syntax: backslash and parentheses are escaped; only Latin-1 text is allowed."""
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _page_stream(lines: list[str]) -> bytes:
    commands = [f"BT /F2 12 Tf {LEFT} {PAGE_HEIGHT - 36} Td ({STAMP}) Tj ET"]
    for row, text in enumerate(lines):
        commands.append(f"BT /F1 {FONT_SIZE} Tf {LEFT} {TOP - row * LINE_HEIGHT} Td ({_escape(text)}) Tj ET")
    commands.append(f"BT /F2 12 Tf {LEFT} 30 Td ({STAMP}) Tj ET")
    return " ".join(commands).encode("latin-1")


def write_pdf(lines: list[str]) -> bytes:
    """`lines` split into A4 pages of LINES_PER_PAGE, each page stamped top and bottom."""
    pages = [lines[i : i + LINES_PER_PAGE] for i in range(0, len(lines), LINES_PER_PAGE)] or [[]]
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    page_ids = [5 + 2 * i for i in range(len(pages))]
    objects.append(f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] /Count {len(pages)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    for page_id, page in zip(page_ids, pages, strict=True):
        stream = _page_stream(page)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] /Contents {page_id + 1} 0 R "
            "/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>".encode()
        )
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    body, offsets = b"%PDF-1.4\n", []
    for number, content in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{number} 0 obj\n".encode() + content + b"\nendobj\n"
    xref = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    body += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    body += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return body
