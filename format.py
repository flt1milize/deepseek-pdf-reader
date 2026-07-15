"""格式化工具：将内部数据转换为 text / json / markdown 输出"""
import json


def fmt_pages(pages: list[str], start_page: int, fmt: str = "text") -> str:
    """格式化多页文字输出

    Args:
        pages: 每页文字列表
        start_page: 起始页码（用于标注）
        fmt: 输出格式 — "text" | "json" | "markdown"
    """
    if fmt == "json":
        return json.dumps(
            [
                {
                    "page": start_page + i,
                    "text": t or "[无文字]",
                    "is_ocr": t.startswith("[OCR]") if t else False,
                }
                for i, t in enumerate(pages)
            ],
            ensure_ascii=False,
            indent=2,
        )

    is_md = fmt == "markdown"
    sep = "\n\n" if is_md else "\n"
    return sep.join(fmt_page(is_md, start_page + i, t) for i, t in enumerate(pages))


def fmt_page(is_md: bool, page_num: int, text: str) -> str:
    """格式化单页文字"""
    body = text or ("*[无文字]*" if is_md else "[无文字]")
    if is_md:
        return f"## 第 {page_num} 页\n\n{body}"
    return f"=== 第 {page_num} 页 ===\n{body}"


def fmt_tables(tables: list[dict]) -> str:
    """将表格列表格式化为 Markdown 表格"""
    parts = [f"## 共 {len(tables)} 个表格\n"]

    for i, t in enumerate(tables):
        header = t["rows"][0]
        n = len(header)
        parts.append(
            f"### 表格 {i + 1}（第 {t['page']} 页）\n"
            f"| {' | '.join(header)} |\n"
            f"|{' --- |' * n}"
        )
        for row in t["rows"][1:]:
            parts.append("| " + " | ".join(row + [""] * (n - len(row))) + " |")
        parts.append(f"*{t['num_rows']}行 x {t['num_cols']}列*\n")

    return "\n".join(parts)