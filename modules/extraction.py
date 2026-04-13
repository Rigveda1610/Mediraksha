import io
import logging

import pdfplumber
import pypdf

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
# PDF TEXT EXTRACTION
# ─────────────────────────────────────────
def extract_pdf_text(file_bytes):
    logger.info("Extracting PDF text")
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for i, page in enumerate(pdf.pages):
                t = page.extract_text()
                if t:
                    text += f"\n--- Page {i+1} ---\n{t}\n"
    except Exception:
        logger.warning("pdfplumber extraction failed, falling back to pypdf")
        try:
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            for i, page in enumerate(reader.pages):
                text += f"\n--- Page {i+1} ---\n{page.extract_text()}\n"
        except Exception as e:
            logger.error("PDF extraction failed: %s", e)
            raise RuntimeError(f"Cannot read PDF: {e}")
    return text.strip()
