#!/usr/bin/env python3
"""MCP Server: PDF Reader v4.0 — 终极版

功能：PDF文字提取(自动OCR) · 关键词搜索(正则) · 表格提取(三路径) · 页面预览 · 信息查询"""
import asyncio, os, sys, json, base64, traceback, io, tempfile, subprocess, re, shutil, logging
from collections import OrderedDict, defaultdict
from contextlib import suppress
from dataclasses import dataclass, field
from threading import Lock

import fitz

# ═══════════════════════════ 初始化 ═══════════════════════════
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stderr)
_LOG = logging.getLogger("pdf")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_MAX_CACHED, _MAX_SIZE_MB = 10, 200
_PAGE_CACHE, _OCR_CACHE, _TSV_CACHE = 500, 50, 20
_OCR_TIMEOUT, _OCR_MAX_CONCURRENT = 60, 2
_FALLBACK_LANGS = ["chi_sim+eng", "eng"]

# ═══════════════════════════ Tesseract ═══════════════════════════
_TESSERACT = (
    os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
    or next((p for p in [r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                          r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"]
             if os.path.isfile(p)), None)
)

def _detect_tessdata() -> str:
    for p in filter(None, [
        os.environ.get("TESSDATA_PREFIX"),
        os.path.join(os.path.dirname(_TESSERACT), "tessdata") if _TESSERACT else "",
        *_tessdata_from_params(),
        *[d for d in [
            r"C:\Program Files\Tesseract-OCR\tessdata",
            r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
            "/usr/share/tesseract-ocr/5/tessdata",
            "/usr/share/tesseract-ocr/4/tessdata",
            "/usr/share/tessdata",
        ] if os.path.isdir(d)]
    ]):
        return p
    return ""

def _tessdata_from_params():
    try:
        r = subprocess.run([_TESSERACT, "--print-parameters"], capture_output=True, timeout=5,
                           text=True, errors="replace")
        yield from (line.strip().split("\t")[-1] for line in r.stdout.split("\n")
                    if "TESSDATA_PREFIX" in line)
    except Exception:
        pass

_TESSDATA: str | None = None  # 懒加载，首次调用 _tess_env() 时初始化
_OCR_LANGS: list[str] = []
_OCR_SEM: asyncio.Semaphore = asyncio.Semaphore(_OCR_MAX_CONCURRENT)  # initialize中可覆盖

def _tess_env() -> dict:
    global _TESSDATA
    if _TESSDATA is None:
        _TESSDATA = _detect_tessdata()
    return {**os.environ, "TESSDATA_PREFIX": _TESSDATA} if _TESSDATA else os.environ

def _scan_langs() -> list[str]:
    if not _TESSERACT:
        return []
    try:
        r = subprocess.run([_TESSERACT, "--list-langs"], capture_output=True, timeout=10, env=_tess_env())
        installed = [l.strip() for l in (r.stdout + r.stderr).decode("utf-8", errors="replace").split("\n")
                     if l.strip() and not l.startswith("List")]
    except Exception:
        installed = []
    seen = set()
    langs = []
    if "chi_sim" in installed and "eng" in installed:
        langs.append("chi_sim+eng"); seen.add("chi_sim+eng")
    if "eng" in installed:
        langs.append("eng"); seen.add("eng")
    if "chi_sim+eng" not in seen:
        langs.append("chi_sim+eng")
    return langs

def _ocr(img: bytes, timeout: int = 60, tsv: bool = False) -> str:
    if not _TESSERACT:
        return ""
    langs, env = _OCR_LANGS or _FALLBACK_LANGS, _tess_env()
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(img); tmp = f.name
    try:
        for lang in langs:
            try:
                r = subprocess.run(
                    [_TESSERACT, tmp, "stdout", "-l", lang, "--psm", "6"] + (["tsv"] if tsv else []),
                    capture_output=True, timeout=timeout, env=env)
                if t := r.stdout.decode("utf-8", errors="replace").strip():
                    return t
            except Exception:
                _LOG.warning("OCR错误(%s): %s", lang, traceback.format_exc()[:120])
    finally:
        with suppress(OSError):
            os.unlink(tmp)
    return ""

# ═══════════════════════════ TSV → Table（方案二：无边框表格） ═══════════════════════════

def _tsv_to_tables(tsv: str) -> list[dict]:
    if not tsv:
        return []
    rows_map = defaultdict(list)
    for line in tsv.split("\n")[1:]:
        cols = line.split("\t")
        if len(cols) < 12 or cols[0] != "5":
            continue
        try:
            text = cols[11].strip()
            if text and int(float(cols[8])) > 0:
                rows_map[(int(cols[2]), int(cols[4]))].append(
                    {"x": int(float(cols[6])), "t": text})
        except (ValueError, IndexError):
            continue
    if not rows_map:
        return []

    sorted_rows = sorted(rows_map.items(), key=lambda kv: kv[0][1])
    tables, cluster, prev = [], [], -99
    for (_, ln), words in sorted_rows:
        if ln - prev > 1 and cluster:
            if _is_table(cluster):
                tables.append(_cluster_to_result(cluster))
            cluster = []
        row = [w["t"] for w in sorted(words, key=lambda w: w["x"])]
        if len(row) >= 2:
            cluster.append(row)
        elif cluster and _is_table(cluster):
            tables.append(_cluster_to_result(cluster))
            cluster = []
        prev = ln
    if _is_table(cluster):
        tables.append(_cluster_to_result(cluster))
    return tables

def _is_table(cluster: list[list[str]]) -> bool:
    if len(cluster) < 2:
        return False
    cols = [len(r) for r in cluster]
    avg = sum(cols) / len(cols)
    return sum(1 for c in cols if abs(c - avg) <= 2) >= len(cols) * 0.7

def _cluster_to_result(rows: list[list[str]]) -> dict:
    max_cols = max(len(r) for r in rows)
    return {"rows": [r + [""] * (max_cols - len(r)) for r in rows],
            "num_rows": len(rows), "num_cols": max_cols}

# ═══════════════════════════ PDFDoc ═══════════════════════════

def _lru(cache: OrderedDict, maxsize: int):
    while len(cache) > maxsize:
        cache.pop(next(iter(cache)), None)

@dataclass
class PDFDoc:
    path: str
    _doc: fitz.Document | None = None
    _needs_pass: bool | None = None
    _tcache: OrderedDict[int, str] = field(default_factory=OrderedDict)
    _ocache: OrderedDict[int, str] = field(default_factory=OrderedDict)
    _tsvcache: OrderedDict[int, str] = field(default_factory=OrderedDict)
    _tabcache: OrderedDict[int, list[dict]] = field(default_factory=OrderedDict)
    _lock: Lock = field(default_factory=Lock)

    def open(self):
        with self._lock:
            if self._doc is None:
                doc = fitz.open(self.path)
                if doc.needs_pass:
                    doc.close(); raise PermissionError("PDF已加密，需要密码")
                self._doc, self._needs_pass = doc, False
        return self._doc

    def close(self):
        if self._doc:
            self._doc.close(); self._doc = None
        for c in (self._tcache, self._ocache, self._tsvcache, self._tabcache):
            c.clear()

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()

    @property
    def pages(self): return self.open().page_count
    @property
    def meta(self): return dict(self.open().metadata or {})
    @property
    def has_text(self): return any(self.open()[i].get_text().strip() for i in range(min(5, self.pages)))

    def _page(self, p: int): return self.open()[p - 1]

    def render_png(self, page: int, scale: float = 2.0) -> bytes:
        return self._page(page).get_pixmap(matrix=fitz.Matrix(scale, scale)).tobytes("png")

    def get_text(self, page: int) -> str:
        if page in self._tcache:
            return self._tcache[page]
        if t := self._page(page).get_text().strip():
            self._tcache[page] = t; _lru(self._tcache, _PAGE_CACHE); return t
        if page in self._ocache:
            return f"[OCR] {self._ocache[page]}" if self._ocache[page] else ""
        if _TESSERACT:
            _LOG.info("page=%d OCR...", page)
            ocr = _ocr(self.render_png(page, 3.0), _OCR_TIMEOUT)
            self._ocache[page] = ocr; _lru(self._ocache, _OCR_CACHE)
            if ocr:
                r = f"[OCR] {ocr}"; self._tcache[page] = r; _lru(self._tcache, _PAGE_CACHE)
                _LOG.info("page=%d OK: %d chars", page, len(ocr))
                return r
        self._tcache[page] = ""; _lru(self._tcache, _PAGE_CACHE); return ""

    async def get_texts(self, start: int, end: int) -> list[str]:
        async def _one(p):
            async with _OCR_SEM:
                return await asyncio.to_thread(self.get_text, p)
        return await asyncio.gather(*[_one(p) for p in range(start, end + 1)])

    def _get_tsv(self, page: int) -> str:
        if page in self._tsvcache:
            return self._tsvcache[page]
        if _TESSERACT:
            _LOG.info("page=%d TSV OCR...", page)
            self._tsvcache[page] = _ocr(self.render_png(page, 3.0), _OCR_TIMEOUT, tsv=True)
            _lru(self._tsvcache, _TSV_CACHE)
        return self._tsvcache.get(page, "")

    def search(self, kw: str, start: int = 1, end: int = 0, regex: bool = False) -> list[dict]:
        end = end or self.pages
        pat = re.compile(kw if regex else re.escape(kw), re.IGNORECASE)
        results = []
        for p in range(start, end + 1):
            pg, text = self._page(p), self.get_text(p)
            cnt = len(re.findall(pat, text))
            if not cnt:
                # re.findall 对某些 PDF 提取文字会丢失位置信息，回退到 PyMuPDF search_for
                try:
                    cnt = len(pg.search_for(kw))
                except Exception:
                    pass
            if cnt:
                ctx = [l.strip() for l in text.split("\n") if pat.search(l)][:20]
                results.append({"page": p, "count": cnt, "context": ctx})
        return results

    def tables(self, page: int) -> list[dict]:
        if page in self._tabcache:
            return self._tabcache[page]

        pg = self._page(page)
        results, seen = [], set()

        def _add(r):
            h = tuple(r["rows"][0]) if r.get("rows") else None
            if h and h not in seen:
                seen.add(h); r["page"] = page; results.append(r)

        # 方法1: find_tables（PyMuPDF内置表格检测）
        if (ft := pg.find_tables()):
            for t in ft.tables:
                rows = [r for r in ([(c or "").strip() for c in row] for row in t.extract()) if any(r)]
                if len(rows) >= 2:
                    _add({"rows": rows, "num_rows": len(rows), "num_cols": max(map(len, rows))})

        # 方法2: block/line 结构化解析
        if not results:
            for block in pg.get_text("dict")["blocks"]:
                if block.get("type") != 0: continue
                lines = block.get("lines", [])
                if len(lines) < 2: continue
                rows = [[s["text"].strip() for s in l.get("spans", []) if s["text"].strip()] for l in lines]
                rows = [r for r in rows if len(r) >= 2]
                if len(rows) >= 2:
                    _add({"rows": rows, "num_rows": len(rows), "num_cols": max(map(len, rows))})

        # 方法3: TSV坐标聚类（无边框表格兜底）
        if not results and (tsv := self._get_tsv(page)):
            for t in _tsv_to_tables(tsv):
                if t["num_rows"] >= 2:
                    _add(t)

        self._tabcache[page] = results; _lru(self._tabcache, _TSV_CACHE)
        return results


# ═══════════════════════════ 文档缓存（线程安全） ═══════════════════════════
_docs_cache: OrderedDict[str, PDFDoc] = OrderedDict()
_docs_lock = Lock()

def _get_doc(path: str) -> PDFDoc:
    ap = os.path.abspath(path)
    if not os.path.isfile(ap): raise FileNotFoundError(f"文件不存在: {path}")
    if (sz := os.path.getsize(ap) / 1_048_576) > _MAX_SIZE_MB:
        raise MemoryError(f"文件过大({sz:.1f}MB)，限制{_MAX_SIZE_MB}MB")
    with _docs_lock:
        if ap in _docs_cache: _docs_cache.move_to_end(ap); return _docs_cache[ap]
    doc = PDFDoc(ap)
    try: doc.open()
    except Exception: doc.close(); raise
    with _docs_lock:
        _docs_cache[ap] = doc
        if len(_docs_cache) > _MAX_CACHED: _docs_cache.popitem(last=False)[1].close()
    return doc

def _close_docs():
    with _docs_lock:
        for d in list(_docs_cache.values()):
            with suppress(Exception): d.close()
        _docs_cache.clear()

# ═══════════════════════════ 辅助 ═══════════════════════════
_e = lambda m: {"isError": True, "content": [{"type": "text", "text": m}]}
_o = lambda t: {"content": [{"type": "text", "text": t}]}

def _resolve(args):
    if not (p := args.get("file_path", "")): return None, _e("缺少 file_path")
    try: return _get_doc(p), None
    except (FileNotFoundError, PermissionError, MemoryError) as e: return None, _e(str(e))
    except Exception as e: return None, _e(f"无法打开文件: {e}")

def _interval(args, total):
    ps, pe = int(args.get("page_start", 1)), int(args.get("page_end", total))
    if not (1 <= ps <= pe <= total): raise ValueError(f"页码 {ps}-{pe} 无效 (1-{total})")
    return ps, pe

def _fmt_pages(pages, ps, fmt):
    if fmt == "json":
        return json.dumps([{"page": ps + i, "text": t or "[无文字]",
                            "is_ocr": t.startswith("[OCR]") if t else False}
                           for i, t in enumerate(pages)], ensure_ascii=False, indent=2)
    md = fmt == "markdown"
    sep = "\n\n" if md else "\n"
    return sep.join(_fmt_page(md, ps + i, t) for i, t in enumerate(pages))


def _fmt_page(md: bool, page: int, text: str) -> str:
    body = text or ("*[无文字]*" if md else "[无文字]")
    if md:
        return f"## 第 {page} 页\n\n{body}"
    return f"=== 第 {page} 页 ===\n{body}"

def _fmt_tables(tables):
    parts = [f"## 共 {len(tables)} 个表格\n"]
    for i, t in enumerate(tables):
        h, n = t["rows"][0], len(t["rows"][0])
        parts.append(f"### 表格 {i+1}（第 {t['page']} 页）\n| {' | '.join(h)} |\n|{' --- |' * n}")
        for row in t["rows"][1:]:
            parts.append("| " + " | ".join(row + [""] * (n - len(row))) + " |")
        parts.append(f"*{t['num_rows']}行 x {t['num_cols']}列*\n")
    return "\n".join(parts)

# ═══════════════════════════ 工具处理 ═══════════════════════════

async def _read_pdf(args):
    if e := (r := _resolve(args))[1]: return e
    try:
        ps, pe = _interval(args, r[0].pages)
        return _o(_fmt_pages(await r[0].get_texts(ps, pe), ps, args.get("format", "text")))
    except ValueError as e: return _e(str(e))
    except Exception as ex: return _e(f"读取失败: {ex}")

async def _list_info(args):
    if e := (r := _resolve(args))[1]: return e
    try:
        p = os.path.abspath(args["file_path"])
        return _o(json.dumps(dict(total_pages=r[0].pages, file_path=p,
            file_size=(fs := os.path.getsize(p)), file_size_mb=round(fs / 1_048_576, 2),
            metadata=r[0].meta, has_text=r[0].has_text, encrypted=r[0]._needs_pass or False,
            ocr_available=_TESSERACT is not None, ocr_languages=_OCR_LANGS, tessdata=_TESSDATA),
            ensure_ascii=False, indent=2))
    except Exception as ex: return _e(f"获取失败: {ex}")

async def _search_pdf(args):
    if e := (r := _resolve(args))[1]: return e
    if not (q := args.get("query", "")): return _e("缺少 query")
    try:
        ps, pe = _interval(args, r[0].pages)
        results = r[0].search(q, ps, pe, regex=args.get("regex") in (True, "true", "True", "1"))
        if not results: return _o(f"未找到「{q}」")
        total = sum(x["count"] for x in results)
        lines = [f"## 搜索「{q}」共 {total} 处匹配\n"]
        for x in results:
            lines.append(f"### 第 {x['page']} 页（{x['count']} 处）")
            lines.extend(f"> {c}" for c in x["context"]); lines.append("")
        return _o("\n".join(lines))
    except ValueError as e: return _e(str(e))
    except Exception as ex: return _e(f"搜索失败: {ex}")

async def _extract_tables(args):
    if e := (r := _resolve(args))[1]: return e
    try:
        ps, pe = _interval(args, r[0].pages)
        tables = [t for p in range(ps, pe + 1) for t in r[0].tables(p)]
        return _o(_fmt_tables(tables)) if tables else _o("未检测到表格数据")
    except ValueError as e: return _e(str(e))
    except Exception as ex: return _e(f"表格提取失败: {ex}")

async def _preview_page(args):
    if e := (r := _resolve(args))[1]: return e
    try:
        page = int(args.get("page_num", 1))
        if not 1 <= page <= r[0].pages: return _e(f"页码 {page} 无效 (1-{r[0].pages})")
        return {"content": [{"type": "text", "text": f"第{page}页（共{r[0].pages}页）"},
                {"type": "image", "data": base64.b64encode(r[0].render_png(page)).decode(), "mimeType": "image/png"}]}
    except Exception as ex: return _e(f"预览失败: {ex}")


_TOOLS = {"read_pdf": _read_pdf, "list_pdf_info": _list_info, "search_pdf": _search_pdf,
          "extract_tables": _extract_tables, "preview_page": _preview_page}

# ═══════════════════════════ MCP 协议 ═══════════════════════════
_BASE = {"type": "object", "required": ["file_path"], "properties": {
    "file_path": {"type": "string", "description": "PDF路径"},
    "page_start": {"type": "number", "description": "起始页"},
    "page_end": {"type": "number", "description": "结束页"}}}

_SCHEMA = [
    {"name": "read_pdf", "description": "读取PDF文字(自动OCR)", "inputSchema": {
        **_BASE, "properties": {**_BASE["properties"],
        "format": {"type": "string", "enum": ["text", "json", "markdown"]}}}},
    {"name": "list_pdf_info", "description": "PDF信息(页数/大小/加密/OCR)",
     "inputSchema": {"type": "object", "required": ["file_path"],
                     "properties": {"file_path": {"type": "string"}}}},
    {"name": "search_pdf", "description": "搜索关键词(支持正则)", "inputSchema": {
        **_BASE, "required": ["file_path", "query"], "properties": {**_BASE["properties"],
        "query": {"type": "string"}, "regex": {"type": "boolean"}}}},
    {"name": "extract_tables", "description": "提取PDF表格(有边框+无边框)", "inputSchema": _BASE},
    {"name": "preview_page", "description": "页面渲染PNG", "inputSchema": {
        "type": "object", "required": ["file_path", "page_num"],
        "properties": {"file_path": {"type": "string"}, "page_num": {"type": "number"}}}},
]

R: dict[str, callable] = {}


def _on(m: str):
    def decorator(f):
        R[m] = f
        return f
    return decorator

@_on("initialize")
async def _init(_):
    global _OCR_LANGS, _OCR_SEM
    _OCR_LANGS, _OCR_SEM = _scan_langs(), asyncio.Semaphore(_OCR_MAX_CONCURRENT)
    _LOG.info("v4.0 | tesseract=%s | tessdata=%s | langs=%s | max_ocr=%d",
              bool(_TESSERACT), _TESSDATA, _OCR_LANGS, _OCR_MAX_CONCURRENT)
    return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
            "serverInfo": {"name": "deepseek-pdf-reader", "version": "4.0.0"}}

@_on("notifications/initialized")
async def _noop(_): return None

@_on("tools/list")
async def _tl(_): return {"tools": _SCHEMA}

@_on("resources/list")
async def _rl(_): return {"resources": []}

@_on("shutdown")
async def _down(_): _close_docs(); return None

@_on("exit")
async def _xit(_): _close_docs(); raise SystemExit()

@_on("ping")
async def _ping(_): return {}

@_on("tools/call")
async def _call(req):
    a = req.get("params", {}).get("arguments", {})
    n = req.get("params", {}).get("name", "")
    return await _TOOLS[n](a) if n in _TOOLS else _e(f"未知工具: {n}")

def _send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n"); sys.stdout.flush()

async def main():
    while line := sys.stdin.readline():
        try: req = json.loads(line.strip())
        except Exception: continue
        rid, m = req.get("id"), req.get("method", "")
        try:
            if h := R.get(m):
                r = await h(req)
                if rid is not None and r is not None: _send({"jsonrpc": "2.0", "id": rid, "result": r})
            else: _send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"未知: {m}"}})
        except SystemExit: _send({"jsonrpc": "2.0", "id": rid, "result": None}); break
        except Exception:
            _send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": f"内部错误: {traceback.format_exc()}"}})

if __name__ == "__main__":
    asyncio.run(main())