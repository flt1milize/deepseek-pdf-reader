"""summarize_pdf: 自动生成 PDF 内容摘要"""
import logging

from doc import get_doc

_LOG = logging.getLogger("pdf")


async def summarize_pdf(
    file_path: str,
    preview_pages: int = 3,
    ctx: object = None,
) -> str:
    """自动生成 PDF 内容摘要，读取首尾关键页。

    Args:
        file_path: PDF 文件路径
        preview_pages: 开头读取页数（默认 3 页）
        ctx: MCP Context（可选，用于进度推送）
    """
    import asyncio

    doc = get_doc(file_path)
    total = doc.pages

    if ctx is not None:
        try:
            await ctx.info(f"正在摘要 PDF ({total} 页)...")
        except Exception:
            pass

    # 读取开头几页
    head_pages = min(preview_pages, total)
    head_texts = []
    for p in range(1, head_pages + 1):
        head_texts.append(await asyncio.to_thread(doc.get_text, p))

    # 读取最后一页（如果不同于开头页）
    tail_text = ""
    if total > head_pages:
        tail_text = await asyncio.to_thread(doc.get_text, total)

    # 构建摘要 Markdown
    lines = [
        "## 📊 PDF 内容摘要",
        "",
        f"**文件**: `{file_path}`",
        f"**总页数**: {total}",
        f"**元信息**: {doc.meta.get('title', 'N/A') or 'N/A'}",
        f"**创建工具**: {doc.meta.get('creator', 'N/A')}",
        "",
        "---",
        "",
        f"### 📖 开头内容（前 {head_pages} 页）",
        "",
    ]

    for i, text in enumerate(head_texts):
        lines.append(f"#### 第 {i + 1} 页")
        # 取前 500 字作为摘要
        snippet = _extract_key_sentences(text, max_chars=500)
        lines.append(snippet)
        lines.append("")

    if tail_text:
        lines.append("---")
        lines.append("")
        lines.append(f"### 🔚 结尾内容（第 {total} 页）")
        lines.append("")
        snippet = _extract_key_sentences(tail_text, max_chars=500)
        lines.append(snippet)
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("> 💡 使用 `read_pdf` 读取完整内容，或 `search_pdf` 搜索特定关键词。")

    return "\n".join(lines)


def _extract_key_sentences(text: str, max_chars: int = 500) -> str:
    """提取文本中的关键句子，控制长度"""
    if not text:
        return "*(无文字)*"

    # 移除 OCR 标记
    clean = text.replace("[OCR] ", "").strip()

    if len(clean) <= max_chars:
        return clean

    # 截取前 max_chars 个字符，到最近一个完整句子结束
    truncated = clean[:max_chars]
    last_period = max(
        truncated.rfind("。"),
        truncated.rfind("."),
        truncated.rfind("\n"),
    )
    if last_period > max_chars * 0.5:
        truncated = truncated[: last_period + 1]

    return truncated + "\n\n*(内容已截断，使用 read_pdf_page 查看完整内容)*"