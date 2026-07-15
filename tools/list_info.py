"""list_pdf_info: 获取 PDF 文件元信息"""
import json
import os

from doc import get_doc
from ocr import has_tesseract, get_tessdata
from config import settings


async def list_pdf_info(file_path: str) -> str:
    """获取 PDF 文件信息：页数、大小、是否加密、OCR 状态等。

    Args:
        file_path: PDF 文件路径
    """
    doc = get_doc(file_path)
    p = os.path.abspath(file_path)
    fs = os.path.getsize(p)

    info = dict(
        total_pages=doc.pages,
        file_path=p,
        file_size=fs,
        file_size_mb=round(fs / 1_048_576, 2),
        metadata=doc.meta,
        has_text=doc.has_text,
        encrypted=doc._needs_pass or False,
        ocr_available=has_tesseract(),
        ocr_languages=settings.ocr_langs,
        tessdata=get_tessdata(),
    )
    return json.dumps(info, ensure_ascii=False, indent=2)