"""Turn files in the inbox into RawDocuments.

- .pdf  -> one document (pdfplumber words grouped into lines/segments)
- .eml  -> one document per PDF attachment; if there are none, the email
           body text becomes the document.
"""
from __future__ import annotations

import email
import email.policy
import hashlib
import io
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterator, List, Optional

import pdfplumber

from ..models import Line, RawDocument, Segment

SUPPORTED = {".pdf", ".eml"}

# Gap (points) between words that splits them into separate segments.
# A normal inter-word space is ~2.5-5pt at invoice font sizes.
SEGMENT_GAP = 8.0
LINE_TOLERANCE = 3.0


def iter_inbox(inbox: Path) -> Iterator[Path]:
    for p in sorted(Path(inbox).iterdir(), key=lambda p: p.name.lower()):
        if p.is_file() and p.suffix.lower() in SUPPORTED and not p.name.startswith("_"):
            yield p


def load(path: Path) -> List[RawDocument]:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        doc = load_pdf_bytes(path.read_bytes(), path.name)
        doc.received_at = _mtime(path)
        return [doc]
    if suffix == ".eml":
        return load_eml(path)
    raise ValueError(f"Unsupported file type: {path.name}")


# ---------------------------------------------------------------- PDF ----

def load_pdf_bytes(data: bytes, source_file: str, origin: str = "pdf") -> RawDocument:
    lines: List[Line] = []
    texts: List[str] = []
    y_offset = 0.0
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=1.5, y_tolerance=2)
            for ln in group_words(words):
                for s in ln.segments:  # stack pages vertically
                    s.top += y_offset
                    s.bottom += y_offset
                lines.append(ln)
            texts.append(page.extract_text() or "")
            y_offset += float(page.height)
    return RawDocument(
        source_file=source_file,
        text="\n".join(texts),
        lines=lines,
        sha256=hashlib.sha256(data).hexdigest(),
        origin=origin,
    )


def group_words(words: List[dict]) -> List[Line]:
    """Group pdfplumber words into lines (by baseline) then segments (by gap)."""
    rows: List[List[dict]] = []
    for w in sorted(words, key=lambda w: (round(w["bottom"]), w["x0"])):
        if rows and abs(rows[-1][0]["bottom"] - w["bottom"]) <= LINE_TOLERANCE:
            rows[-1].append(w)
        else:
            rows.append([w])
    lines = []
    for row in rows:
        row.sort(key=lambda w: w["x0"])
        segs: List[Segment] = []
        for w in row:
            if segs and w["x0"] - segs[-1].x1 <= SEGMENT_GAP:
                s = segs[-1]
                s.text += " " + w["text"]
                s.x1 = w["x1"]
                s.top = min(s.top, w["top"])
                s.bottom = max(s.bottom, w["bottom"])
            else:
                segs.append(Segment(w["text"], w["x0"], w["x1"], w["top"], w["bottom"]))
        lines.append(Line(segs))
    return lines


# ---------------------------------------------------------------- EML ----

def load_eml(path: Path) -> List[RawDocument]:
    msg = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
    received = _email_date(msg.get("Date")) or _mtime(path)
    pdfs = [part for part in msg.iter_attachments()
            if part.get_content_type() == "application/pdf"
            or (part.get_filename() or "").lower().endswith(".pdf")]
    if pdfs:
        docs = []
        for part in pdfs:
            src = path.name if len(pdfs) == 1 else f"{path.name}#{part.get_filename()}"
            doc = load_pdf_bytes(part.get_content(), src, origin="eml-attachment")
            doc.received_at = received
            docs.append(doc)
        return docs
    body = msg.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body else ""
    if body is not None and body.get_content_type() == "text/html":
        text = re.sub(r"<[^>]+>", " ", text)
    header = f"From: {msg.get('From', '')}\nSubject: {msg.get('Subject', '')}\n"
    doc = load_text(header + text, path.name, origin="eml-body")
    doc.received_at = received
    return [doc]


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _email_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(str(value))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def load_text(text: str, source_file: str, origin: str = "text") -> RawDocument:
    """Build a RawDocument from plain text.

    Segments are split on runs of 2+ spaces, tabs, or after a colon, so
    "Invoice number: KIS-1" -> ["Invoice number:", "KIS-1"].
    """
    lines = []
    for i, raw in enumerate(text.splitlines()):
        parts = [p for p in re.split(r"\s{2,}|\t|(?<=:)\s+", raw.strip()) if p]
        if not parts:
            continue
        segs, x = [], 0.0
        for p in parts:
            segs.append(Segment(p, x, x + len(p) * 5.0, i * 12.0, i * 12.0 + 10))
            x += len(p) * 5.0 + 20
        lines.append(Line(segs))
    return RawDocument(source_file=source_file, text=text, lines=lines,
                       sha256=hashlib.sha256(text.encode()).hexdigest(), origin=origin)
