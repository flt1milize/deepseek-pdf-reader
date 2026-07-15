"""extract_tables: 提取 PDF 表格（三路径策略）"""
from doc import get_doc
from format import fmt_tables


async def extract_tables(
    file_path: str,
    page_start: int = 1,
    page_end: int = 0,
) -> str:
    """提取 PDF 表格，支持有边框/无边框/TSV聚类三种检测路径。

    Args:
        file_path: PDF 文件路径
        page_start: 起始页码（从 1 开始）
        page_end: 结束页码（0 表示到最后一页）
    """
    doc = get_doc(file_path)
    total = doc.pages
    end = page_end or total

    if not (1 <= page_start <= end <= total):
        raise ValueError(f"页码范围 {page_start}-{end} 无效 (1-{total})")

    tables = []
    for p in range(page_start, end + 1):
        tables.extend(doc.tables(p))

    if tables:
        return fmt_tables(tables)
    return "未检测到表格数据"