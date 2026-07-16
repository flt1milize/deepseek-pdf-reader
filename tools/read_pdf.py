"""read_pdf & read_pdf_page: 读取 PDF 文字（自动 OCR）"""
import logging

from doc import get_doc
from format import fmt_pages, fmt_page

_LOG = logging.getLogger("pdf")


async def read_pdf(
    file_path: str,
    page_start: int = 1,
    page_end: int = 0,
    format: str = "text",
    ctx: object = None,
) -> str:
    """读取 PDF 指定页码范围文字，支持 text / json / markdown 格式。扫描件自动 OCR。

    Args:
        file_path: PDF 文件路径
        page_start: 起始页码（从 1 开始）
        page_end: 结束页码（0 表示到最后一页）
        format: 输出格式 — "text" | "json" | "markdown"
        ctx: MCP Context（可选，用于进度推送）
    """
    doc = get_doc(file_path)
    total = doc.pages
    end = page_end or total

    if not (1 <= page_start <= end <= total):
        raise ValueError(f"页码范围 {page_start}-{end} 无效 (1-{total})")

    total_to_read = end - page_start + 1

    # OCR 进度推送（如果 ctx 可用）
    if ctx is not None:
        await _push_progress(ctx, 0, total_to_read, f"开始读取 PDF ({total_to_read} 页)...")

    texts = []
    for i, p in enumerate(range(page_start, end + 1)):
        # 逐页读取 + 推送进度
        texts.append(await _read_single(doc, p))
        if ctx is not None:
            await _push_progress(ctx, i + 1, total_to_read, f"第 {p}/{end} 页")

    if ctx is not None:
        await _push_progress(ctx, total_to_read, total_to_read, "读取完成")

    return fmt_pages(texts, page_start, format)


async def read_pdf_page(
    file_path: str,
    page_num: int = 1,
    format: str = "text",
    ctx: object = None,
) -> str:
    """读取 PDF 单页文字，适合交互式问答场景。扫描件自动 OCR。

    Args:
        file_path: PDF 文件路径
        page_num: 页码（从 1 开始）
        format: 输出格式 — "text" | "json" | "markdown"
        ctx: MCP Context（可选，用于进度推送）
    """
    doc = get_doc(file_path)
    if not (1 <= page_num <= doc.pages):
        raise ValueError(f"页码 {page_num} 无效 (1-{doc.pages})")

    if ctx is not None:
        await _push_progress(ctx, 0, 1, f"正在读取第 {page_num} 页...")

    text = await _read_single(doc, page_num)

    if ctx is not None:
        await _push_progress(ctx, 1, 1, "完成")

    return fmt_page(format == "markdown", page_num, text)


async def _read_single(doc, page_num: int) -> str:
    """读取单页文字（异步包装）"""
    import asyncio
    return await asyncio.to_thread(doc.get_text, page_num)


async def _push_progress(ctx, current: int, total: int, message: str):
    """推送进度到 MCP 客户端"""
    try:
        await ctx.report_progress(current, total)
        await ctx.info(message)
    except Exception:
        pass  # 内置引擎模式下 ctx 没有这些方法，静默忽略