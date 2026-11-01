"""Turn an uploaded PDF or image into text the extractors can read.

Order of preference per page: embedded text layer -> local Tesseract OCR -> keep the rendered PNG so the
extractor can send it to a vision-capable LLM. Nothing here interprets numbers."""

import io
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field

IMAGE_EXTS = (".png", ".jpg", ".jpeg")
MAX_VISION_PAGES = 6
from security import MAX_IMAGE_PIXELS, MAX_PDF_PAGES  # noqa: E402


@dataclass
class DocContent:
    text: str = ""
    source: str = "text"  # text | ocr | vision
    images: list[bytes] = field(default_factory=list)  # PNG pages that still need a vision model
    warnings: list[str] = field(default_factory=list)

    @property
    def readable(self) -> bool:
        return bool(self.text.strip() or self.images)


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def ocr_image(png: bytes) -> str:
    """Tesseract on one image; '' when it isn't installed or fails."""
    exe = shutil.which("tesseract")
    if not exe:
        return ""
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        f.write(png)
        f.flush()
        try:
            out = subprocess.run([exe, f.name, "-", "--psm", "6"], capture_output=True, text=True, timeout=60)
        except (subprocess.SubprocessError, OSError):
            return ""
    return out.stdout if out.returncode == 0 else ""


def _page_png(page) -> bytes:
    buf = io.BytesIO()
    page.to_image(resolution=200).original.save(buf, format="PNG")
    return buf.getvalue()


def _normalize_image(data: bytes) -> bytes:
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS  # Pillow raises DecompressionBombError past 2x this

    buf = io.BytesIO()
    Image.open(io.BytesIO(data)).convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def read_image(data: bytes) -> DocContent:
    png = _normalize_image(data)
    text = ocr_image(png)
    if text.strip():
        return DocContent(text=text, source="ocr")
    return DocContent(images=[png], source="vision")


def read_pdf(data: bytes) -> DocContent:
    import pdfplumber

    texts: list[str] = []
    images: list[bytes] = []
    used_ocr = False
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        if len(pdf.pages) > MAX_PDF_PAGES:
            raise ValueError(f"PDF has {len(pdf.pages)} pages; the limit is {MAX_PDF_PAGES}")
        for page in pdf.pages:
            txt = page.extract_text() or ""
            if txt.strip():
                texts.append(txt)
                continue
            png = _page_png(page)  # image-only page (scan / print-to-PDF)
            ocr = ocr_image(png)
            if ocr.strip():
                texts.append(ocr)
                used_ocr = True
            elif len(images) < MAX_VISION_PAGES:
                images.append(png)
    doc = DocContent(text="\n".join(texts), images=images, source="vision" if images else "ocr" if used_ocr else "text")
    if images and not tesseract_available():
        doc.warnings.append("Scanned page read by the vision model (Tesseract is not installed)")
    return doc
