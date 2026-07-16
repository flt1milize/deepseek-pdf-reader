"""PDFDoc 类 + 线程安全文档缓存池"""
import asyncio
import os
import re
import logging
from collections import OrderedDict
from contextlib import suppress
from dataclasses import dataclass, field
from threading import Lock

import fitz

from config import settings
from ocr import ocr as _ocr_raw, has_tesseract
from table import _tsv_to_tables as tsv_to_tables

_LOG = logging.getLogger("pdf")

# Semaphore 限制 OCR 并发数
_OCR_SEM = asyncio.Semaphore(settings.ocr_max_concurrent)


def resolve_and_validate(file_path: str) -> str:
    """统一的路径标准化和基础验证

    Args:
        file_path: 用户输入的 PDF 路径

    Returns:
        标准化后的绝对路径

    Raises:
        FileNotFoundError: 文件不存在
        MemoryError: 文件超过大小限制
        ValueError: 非 PDF 文件
    """
    ap = os.path.abspath(file_path)
    if not os.path.isfile(ap):
        raise FileNotFoundError(f"文件不存在: {file_path}")
    if not ap.lower().endswith('.pdf'):
        raise ValueError(f"不是PDF文件: {file_path}")
    if (sz := os.path.getsize(ap) / 1_048_576) > settings.max_file_size_mb:
        raise MemoryError(f"文件过大({sz:.1f}MB)，限制{settings.max_file_size_mb}MB")
    return ap


@dataclass
class PDFDoc:
    """线程安全的 PDF 文档封装，带多级缓存"""

    path: str
    _doc: fitz.Document | None = None
    _needs_pass: bool | None = None
    _tcache: OrderedDict[int, str] = field(default_factory=OrderedDict)
    _ocache: OrderedDict[int, str] = field(default_factory=OrderedDict)
    _tsvcache: OrderedDict[int, str] = field(default_factory=OrderedDict)
    _tabcache: OrderedDict[int, list[dict]] = field(default_factory=OrderedDict)
    _lock: Lock = field(default_factory=Lock)

    @staticmethod
    def _lru(cache: OrderedDict, maxsize: int):
        """LRU 淘汰超出上限的缓存项"""
        while len(cache) > maxsize:
            cache.pop(next(iter(cache)), None)

    def open(self, password: str | None = None) -> fitz.Document:
        with self._lock:
            if self._doc is None:
                doc = fitz.open(self.path)
                if doc.needs_pass:
                    if password:
                        if not doc.authenticate(password):
                            doc.close()
                            raise PermissionError("PDF密码错误")
                    else:
                        doc.close()
                        raise PermissionError("PDF已加密，请提供密码参数打开")
                self._doc, self._needs_pass = doc, doc.needs_pass
        return self._doc

    def close(self):
        if self._doc:
            self._doc.close()
            self._doc = None
        for c in (self._tcache, self._ocache, self._tsvcache, self._tabcache):
            c.clear()

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()

    @property
    def pages(self) -> int:
        return self.open().page_count

    @property
    def meta(self) -> dict:
        return dict(self.open().metadata or {})

    @property
    def has_text(self) -> bool:
        doc = self.open()
        return any(
            doc[i].get_text().strip() for i in range(min(5, self.pages))
        )

    def _page(self, p: int):
        return self.open()[p - 1]

    def render_png(self, page: int, scale: float = 2.0) -> bytes:
        return (
            self._page(page)
            .get_pixmap(matrix=fitz.Matrix(scale, scale))
            .tobytes("png")
        )

    def get_text(self, page: int) -> str:
        """获取单页文字（优先缓存 → 原生提取 → OCR）"""
        if page in self._tcache:
            return self._tcache[page]

        if t := self._page(page).get_text().strip():
            self._tcache[page] = t
            self._lru(self._tcache, settings.page_cache_size)
            return t

        if page in self._ocache:
            cached = self._ocache[page]
            return f"[OCR] {cached}" if cached else ""

        if has_tesseract():
            _LOG.info("page=%d OCR...", page)
            ocr_text = _ocr_raw(self.render_png(page, 3.0), settings.ocr_timeout)
            self._ocache[page] = ocr_text
            self._lru(self._ocache, settings.ocr_cache_size)
            if ocr_text:
                result = f"[OCR] {ocr_text}"
                self._tcache[page] = result
                self._lru(self._tcache, settings.page_cache_size)
                _LOG.info("page=%d OK: %d chars", page, len(ocr_text))
                return result

        self._tcache[page] = ""
        self._lru(self._tcache, settings.page_cache_size)
        return ""

    async def get_texts(self, start: int, end: int) -> list[str]:
        """异步并发获取多页文字"""
        async def _one(p):
            async with _OCR_SEM:
                return await asyncio.to_thread(self.get_text, p)
        return await asyncio.gather(*[_one(p) for p in range(start, end + 1)])

    def _get_tsv(self, page: int) -> str:
        """获取 TSV 格式 OCR 结果（用于表格检测）"""
        if page in self._tsvcache:
            return self._tsvcache[page]
        if has_tesseract():
            _LOG.info("page=%d TSV OCR...", page)
            self._tsvcache[page] = _ocr_raw(
                self.render_png(page, 3.0), settings.ocr_timeout, tsv=True
            )
            self._lru(self._tsvcache, settings.tsv_cache_size)
        return self._tsvcache.get(page, "")

    def search(
        self, kw: str, start: int = 1, end: int = 0, regex: bool = False
    ) -> list[dict]:
        """关键词搜索，支持正则"""
        end = end or self.pages
        pat = re.compile(kw if regex else re.escape(kw), re.IGNORECASE)
        results = []
        for p in range(start, end + 1):
            pg, text = self._page(p), self.get_text(p)
            cnt = len(re.findall(pat, text))
            if not cnt:
                try:
                    cnt = len(pg.search_for(kw))
                except Exception:
                    pass
            if cnt:
                ctx = [l.strip() for l in text.split("\n") if pat.search(l)][:20]
                results.append({"page": p, "count": cnt, "context": ctx})
        return results

    def tables(self, page: int) -> list[dict]:
        """三路径表格提取"""
        if page in self._tabcache:
            return self._tabcache[page]

        pg = self._page(page)
        results, seen = [], set()

        def _add(r):
            h = tuple(r["rows"][0]) if r.get("rows") else None
            if h and h not in seen:
                seen.add(h)
                r["page"] = page
                results.append(r)

        # 方法1: find_tables（有边框表格）
        if ft := pg.find_tables():
            for t in ft.tables:
                rows = [
                    r for r in (
                        [(c or "").strip() for c in row] for row in t.extract()
                    ) if any(r)
                ]
                if len(rows) >= 2:
                    _add({
                        "rows": rows,
                        "num_rows": len(rows),
                        "num_cols": max(map(len, rows)),
                    })

        # 方法2: block/line 结构化解析
        if not results:
            for block in pg.get_text("dict")["blocks"]:
                if block.get("type") != 0:
                    continue
                lines = block.get("lines", [])
                if len(lines) < 2:
                    continue
                rows = [
                    [s["text"].strip() for s in l.get("spans", []) if s["text"].strip()]
                    for l in lines
                ]
                rows = [r for r in rows if len(r) >= 2]
                if len(rows) >= 2:
                    _add({
                        "rows": rows,
                        "num_rows": len(rows),
                        "num_cols": max(map(len, rows)),
                    })

        # 方法3: TSV 坐标聚类（无边框兜底）
        if not results and (tsv := self._get_tsv(page)):
            for t in tsv_to_tables(tsv):
                if t["num_rows"] >= 2:
                    _add(t)

        self._tabcache[page] = results
        self._lru(self._tabcache, settings.tsv_cache_size)
        return results


# ═══════════════════════════ 全局文档缓存池 ═══════════════════════════
_docs_cache: OrderedDict[str, PDFDoc] = OrderedDict()
_docs_lock = Lock()


def get_doc(path: str, password: str | None = None) -> PDFDoc:
    """获取或创建 PDF 文档对象（线程安全 LRU 缓存）

    Args:
        path: PDF 文件路径
        password: PDF 打开密码（加密文件需要）
    """
    ap = resolve_and_validate(path)
    # 清理 docs_cache 的引用名也标准化
    with _docs_lock:
        if ap in _docs_cache:
            _docs_cache.move_to_end(ap)
            return _docs_cache[ap]

    doc = PDFDoc(ap)
    try:
        doc.open(password=password)
    except Exception:
        doc.close()
        raise

    with _docs_lock:
        _docs_cache[ap] = doc
        if len(_docs_cache) > settings.max_cached_docs:
            _docs_cache.popitem(last=False)[1].close()
    return doc


def close_docs():
    """关闭所有缓存的文档"""
    with _docs_lock:
        for d in list(_docs_cache.values()):
            with suppress(Exception):
                d.close()
        _docs_cache.clear()