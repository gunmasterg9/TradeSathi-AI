import re
import uuid
from email import policy
from email.parser import BytesParser
from io import BytesIO
from pathlib import Path

from docx import Document as DocxDocument
from fastapi import HTTPException, UploadFile
from pypdf import PdfReader

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".eml", ".docx"}


def sanitize_filename(filename: str) -> str:
    """Prevent directory traversal and strip unsafe characters."""
    raw_name = Path(filename).name
    # Remove control characters and unsafe characters
    clean = re.sub(r'[\\/*?:"<>|]', "", raw_name).strip()
    return clean or "document.txt"


def detect_document_type(filename: str, text: str = "") -> str:
    """Heuristically identify export document type from filename and text."""
    lower_name = Path(filename).name.lower()
    lower_text = text.lower() if text else ""

    if any(k in lower_name for k in ("invoice", "ci_", "inv_", "inv-", "commercial-invoice")):
        return "commercial_invoice"
    if any(k in lower_name for k in ("packing", "packing_list", "pl_", "pkg_", "packing-list")):
        return "packing_list"
    if any(k in lower_name for k in ("purchase_order", "po_", "po-", "order")):
        return "purchase_order"
    if any(k in lower_name for k in ("shipping_instruction", "shipping-instruction", "si_")):
        return "shipping_instructions"

    if "commercial invoice" in lower_text or "invoice no" in lower_text:
        return "commercial_invoice"
    if "packing list" in lower_text or "packing details" in lower_text:
        return "packing_list"
    if "purchase order" in lower_text and "invoice" not in lower_text:
        return "purchase_order"
    if "shipping instruction" in lower_text:
        return "shipping_instructions"

    return "unknown"


def extract_text_with_metadata(
    filename: str, content: bytes
) -> tuple[str, list[dict], str]:
    """Extract readable text with page-level bounds and format classification.
    Returns (extracted_text, pages_metadata, extraction_method).
    """
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{suffix or '(no extension)'}'. Use PDF, TXT, EML, or DOCX."
        )
    if not content or not content.strip():
        raise ValueError(f"{filename} is empty.")

    if suffix == ".txt":
        text = content.decode("utf-8-sig", errors="replace").strip()
        return text, [], "plain_text"

    if suffix == ".eml":
        message = BytesParser(policy=policy.default).parsebytes(content)
        parts = [
            f"Subject: {message.get('subject', '')}",
            f"From: {message.get('from', '')}",
            f"To: {message.get('to', '')}",
        ]
        body = message.get_body(preferencelist=("plain",))
        if body:
            parts.append(body.get_content())
        elif message.get_content_type() == "text/plain":
            parts.append(str(message.get_content()))
        text = "\n".join(part for part in parts if part).strip()
        return text, [], "email_parsed"

    if suffix == ".pdf":
        reader = PdfReader(BytesIO(content))
        if len(reader.pages) == 0:
            raise ValueError(f"PDF document {filename} contains no pages.")
        pages_meta: list[dict] = []
        page_texts: list[str] = []
        current_offset = 0
        for idx, page in enumerate(reader.pages):
            p_text = (page.extract_text() or "").strip()
            start_off = current_offset
            end_off = start_off + len(p_text)
            pages_meta.append({
                "page_number": idx + 1,
                "char_start": start_off,
                "char_end": end_off,
                "text": p_text,
            })
            page_texts.append(p_text)
            current_offset = end_off + 1
        full_text = "\n".join(page_texts).strip()
        if not full_text:
            raise ValueError(
                f"No selectable text found in {filename}. Scanned PDFs require OCR, which is not supported in this MVP."
            )
        return full_text, pages_meta, "pdf_embedded_text"

    if suffix == ".docx":
        doc = DocxDocument(BytesIO(content))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                cells_text = [cell.text.strip() for cell in row.cells]
                if any(cells_text):
                    paragraphs.append(" | ".join(cells_text))
        text = "\n".join(paragraphs).strip()
        return text, [], "docx_document"

    raise ValueError("Unsupported file type.")


def extract_text(filename: str, content: bytes) -> str:
    """Extract readable text from supported, text-based document formats."""
    text, _, _ = extract_text_with_metadata(filename, content)
    return text


async def read_upload_with_bytes(upload: UploadFile, max_bytes: int) -> tuple[str, str, str, bytes]:
    """Read and validate an uploaded file, returning (doc_id, sanitized_filename, extracted_text, raw_bytes)."""
    raw_filename = upload.filename or "upload.txt"
    filename = sanitize_filename(raw_filename)
    suffix = Path(filename).suffix.lower()

    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type for {filename}. Use PDF, TXT, EML, or DOCX.",
        )

    content = await upload.read(max_bytes + 1)
    if len(content) > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"{filename} exceeds the {limit_mb} MB upload limit.",
        )

    try:
        text = extract_text(filename, content)
    except ValueError as exc:
        msg = str(exc)
        if "Scanned PDFs require OCR" in msg:
            raise HTTPException(status_code=422, detail=msg) from exc
        raise HTTPException(status_code=400, detail=msg) from exc

    doc_id = f"doc-{uuid.uuid4().hex[:8]}"
    return doc_id, filename, text, content


async def read_upload(upload: UploadFile, max_bytes: int) -> tuple[str, str, str]:
    """Read and validate an uploaded file, returning (doc_id, sanitized_filename, extracted_text)."""
    doc_id, filename, text, _ = await read_upload_with_bytes(upload, max_bytes)
    return doc_id, filename, text
