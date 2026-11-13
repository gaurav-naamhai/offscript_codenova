"""Document text & OCR extraction (digital PDFs, scanned PDFs, images)."""

import logging
from typing import Optional
import pymupdf
from google.genai import types

from retrieval.config import GEMINI_MODEL, get_genai_client
from retrieval.schemas import ContentPayload, ExtractedDocument, PageText

logger = logging.getLogger(__name__)

# Minimum character count on a PDF page before falling back to Gemini vision OCR
MIN_DIGITAL_PAGE_CHARS = 25


def _ocr_image_bytes(image_bytes: bytes, mime_type: str = "image/png") -> str:
    """Use Gemini multimodal (`gemini-3.5-flash-lite`) to extract text from an image."""
    try:
        client = get_genai_client()
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                (
                    "Extract all visible text from this image or scanned document page accurately. "
                    "Preserve headings and paragraph breaks. Return ONLY the extracted text, with no extra commentary."
                ),
            ],
        )
        return (response.text or "").strip()
    except Exception as exc:
        logger.warning("Gemini OCR failed: %s", exc)
        return ""


def extract_document(
    file_bytes: bytes,
    filename: str = "document.pdf",
    mime_type: Optional[str] = None,
) -> ExtractedDocument:
    """Extract text and page metadata from a PDF, image, or plain-text file.

    - Digital PDFs: extracted per page via PyMuPDF (`fitz`).
    - Scanned PDF pages (little/no digital text): rendered to PNG and OCR'd via Gemini.
    - Images (`png`, `jpg`, `jpeg`, `webp`): OCR'd via Gemini.
    """
    lower_name = (filename or "").lower()
    mime = (mime_type or "").lower()

    # 1. PDF Handling
    if lower_name.endswith(".pdf") or mime == "application/pdf" or file_bytes[:4] == b"%PDF":
        pages: list[PageText] = []
        doc = pymupdf.open(stream=file_bytes, filetype="pdf")
        try:
            for idx, page in enumerate(doc):
                page_num = idx + 1
                raw_text = (page.get_text("text") or "").strip()
                if len(raw_text) >= MIN_DIGITAL_PAGE_CHARS:
                    pages.append(
                        PageText(
                            page_number=page_num,
                            text=raw_text,
                            extraction_method="digital_pdf",
                        )
                    )
                else:
                    # Scanned page fallback -> render page at 150 DPI and run Gemini OCR
                    pix = page.get_pixmap(dpi=150)
                    png_bytes = pix.tobytes("png")
                    ocr_text = _ocr_image_bytes(png_bytes, mime_type="image/png")
                    pages.append(
                        PageText(
                            page_number=page_num,
                            text=ocr_text or raw_text,
                            extraction_method="ocr_gemini",
                        )
                    )
        finally:
            doc.close()

        full_text = "\n\n".join(
            f"[Page {p.page_number}]\n{p.text}" for p in pages if p.text.strip()
        )
        return ExtractedDocument(
            filename=filename,
            content_type="pdf",
            page_count=len(pages),
            pages=pages,
            full_text=full_text,
        )

    # 2. Image Handling
    if (
        any(lower_name.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp"))
        or mime.startswith("image/")
        or file_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        or file_bytes[:3] == b"\xff\xd8\xff"
    ):
        detected_mime = mime if mime.startswith("image/") else "image/png"
        if lower_name.endswith((".jpg", ".jpeg")) or file_bytes[:3] == b"\xff\xd8\xff":
            detected_mime = "image/jpeg"
        elif lower_name.endswith(".webp"):
            detected_mime = "image/webp"

        ocr_text = _ocr_image_bytes(file_bytes, mime_type=detected_mime)
        page = PageText(page_number=1, text=ocr_text, extraction_method="ocr_gemini")
        return ExtractedDocument(
            filename=filename,
            content_type="image",
            page_count=1,
            pages=[page],
            full_text=ocr_text,
        )

    # 3. Plain Text Fallback
    decoded = file_bytes.decode("utf-8", errors="replace").strip()
    page = PageText(page_number=1, text=decoded, extraction_method="plain_text")
    return ExtractedDocument(
        filename=filename,
        content_type="text",
        page_count=1,
        pages=[page],
        full_text=decoded,
    )


def extract_from_payload(content: ContentPayload) -> str:
    """Helper to get usable text from Gaurav's `ContentPayload` (text, image, or PDF)."""
    if content.text and content.text.strip():
        return content.text.strip()
    if content.file_bytes:
        extracted = extract_document(
            file_bytes=content.file_bytes,
            filename=content.file_name or f"upload.{content.content_type}",
            mime_type=content.file_mime,
        )
        return extracted.full_text.strip()
    return ""
