"""preview_page: 渲染 PDF 页面为 PNG 图片"""
import base64

from doc import get_doc


async def preview_page(
    file_path: str,
    page_num: int = 1,
) -> dict:
    """渲染 PDF 指定页面为 PNG 图片（Base64 编码）。

    Args:
        file_path: PDF 文件路径
        page_num: 页码（从 1 开始）

    Returns:
        MCP content list: [TextContent, ImageContent]
    """
    doc = get_doc(file_path)

    if not (1 <= page_num <= doc.pages):
        raise ValueError(f"页码 {page_num} 无效 (1-{doc.pages})")

    png_bytes = doc.render_png(page_num)
    b64 = base64.b64encode(png_bytes).decode()

    return {
        "content": [
            {"type": "text", "text": f"第{page_num}页（共{doc.pages}页）"},
            {"type": "image", "data": b64, "mimeType": "image/png"},
        ]
    }