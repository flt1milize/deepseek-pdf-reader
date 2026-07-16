"""extract_images: 提取 PDF 中嵌入的图片"""
import base64
import logging

from doc import get_doc

_LOG = logging.getLogger("pdf")


async def extract_images(
    file_path: str,
    page_start: int = 1,
    page_end: int = 0,
    page_only: int = 0,
) -> dict:
    """提取 PDF 中嵌入的图片，返回 Base64 编码的 PNG 列表。

    Args:
        file_path: PDF 文件路径
        page_start: 起始页码（从 1 开始，与 page_end 配合使用）
        page_end: 结束页码（0 表示到最后一页）
        page_only: 仅提取单页的图片（优先级高于 page_start/page_end）
    """
    doc = get_doc(file_path)
    total = doc.pages

    if page_only > 0:
        page_start = page_end = page_only
    else:
        page_end = page_end or total

    if not (1 <= page_start <= page_end <= total):
        raise ValueError(f"页码范围 {page_start}-{page_end} 无效 (1-{total})")

    images = []
    for p in range(page_start, page_end + 1):
        pg = doc._page(p)
        for img_index, img_info in enumerate(pg.get_image_info()):
            xref = img_info["xref"]
            if xref == 0:
                continue
            try:
                base_image = doc._doc.extract_image(xref)
                img_bytes = base_image["image"]
                ext = base_image["ext"]

                # 转换为 MIME 类型
                mime_map = {"png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg", "bmp": "image/bmp"}
                mime_type = mime_map.get(ext, f"image/{ext}")

                images.append({
                    "page": p,
                    "index": img_index,
                    "format": ext,
                    "width": img_info.get("width", 0),
                    "height": img_info.get("height", 0),
                    "size_bytes": len(img_bytes),
                    "base64": base64.b64encode(img_bytes).decode(),
                    "mime_type": mime_type,
                })
            except Exception:
                _LOG.warning("图片提取失败: page=%d, xref=%d", p, xref)

    if not images:
        return {"content": [{"type": "text", "text": f"第 {page_start}-{page_end} 页未检测到嵌入图片"}]}

    # 构建多图片输出
    total_imgs = len(images)
    text_summary = f"## 提取 {total_imgs} 张图片（第 {page_start}-{page_end} 页）\n\n"

    content_list = [{"type": "text", "text": text_summary}]

    for img in images:
        content_list.append({
            "type": "text",
            "text": f"### 第 {img['page']} 页 · 图片 {img['index'] + 1}\n"
                    f"- 格式: {img['format']} · 尺寸: {img['width']}×{img['height']} · 大小: {img['size_bytes']:,} bytes"
        })
        content_list.append({
            "type": "image",
            "data": img["base64"],
            "mimeType": img["mime_type"],
        })

    return {"content": content_list}