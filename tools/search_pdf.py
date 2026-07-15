"""search_pdf: 搜索 PDF 关键词（支持正则）"""
from doc import get_doc


async def search_pdf(
    file_path: str,
    query: str,
    page_start: int = 1,
    page_end: int = 0,
    regex: bool = False,
) -> str:
    """搜索 PDF 关键词，支持正则表达式。

    Args:
        file_path: PDF 文件路径
        query: 搜索关键词或正则表达式
        page_start: 起始页码（从 1 开始）
        page_end: 结束页码（0 表示到最后一页）
        regex: 是否将 query 视为正则表达式
    """
    if not query:
        raise ValueError("缺少 query 参数")

    doc = get_doc(file_path)
    total = doc.pages
    end = page_end or total

    if not (1 <= page_start <= end <= total):
        raise ValueError(f"页码范围 {page_start}-{end} 无效 (1-{total})")

    results = doc.search(query, page_start, end, regex=regex)

    if not results:
        return f"未找到「{query}」"

    total_matches = sum(x["count"] for x in results)
    lines = [f"## 搜索「{query}」共 {total_matches} 处匹配\n"]

    for x in results:
        lines.append(f"### 第 {x['page']} 页（{x['count']} 处）")
        lines.extend(f"> {c}" for c in x["context"])
        lines.append("")

    return "\n".join(lines)