"""read_pdf: 读取 PDF 文字（自动 OCR）"""
import logging

from doc import get_doc
from format import fmt_pages

_LOG = logging.getLogger("pdf")


async def read_pdf(
    file_path: str,
    page_start: int = 1,
    page_end: int = 0,
    format: str = "text",
) -> str:
    """读取 PDF 文字，支持 text / json / markdown 格式。扫描件自动 OCR。

    Args:
        file_path: PDF 文件路径
        page_start: 起始页码（从 1 开始）
        page_end: 结束页码（0 表示到最后一页）
        format: 输出格式 — "text" | "json" | "markdown"
    """
    doc = get_doc(file_path)
    total = doc.pages
    end = page_end or total

    if not (1 <= page_start <= end <= total):
        raise ValueError(f"页码范围 {page_start}-{end} 无效 (1-{total})")

    texts = await doc.get_texts(page_start, end)
    return fmt_pages(texts, page_start, format)
