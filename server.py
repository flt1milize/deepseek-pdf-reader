#!/usr/bin/env python3
"""MCP Server: PDF Reader v5.2.0

功能：PDF文字提取(自动OCR) · 搜索(正则+高亮) · 表格(三路+经) · 预览 · 摘要 · 图片提取 · 单页阅读 · OCR进度推送

基于官方 mcp Python SDK，使用 @mcp.tool() 装饰器自动生成 inputSchema。
兼容旧的 JSON-RPC 自实现模式 —— 当 mcp 包不可用时自动回退到内置 JSON-RPC 引擎。
"""
import asyncio
import inspect
import io
import json
import logging
import os
import sys
import traceback

# ═══════════════════════════ 日志初始化 ═══════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
_LOG = logging.getLogger("pdf")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ═══════════════════════════ 尝试加载官方 mcp SDK ═══════════════════════════
try:
    from mcp.server import MCPServer
    from contextlib import asynccontextmanager
    _HAS_MCP_SDK = True
except ImportError:
    _HAS_MCP_SDK = False
    _LOG.warning("mcp SDK 未安装，使用内置 JSON-RPC 引擎")

# ═══════════════════════════ 导入业务模块 ═══════════════════════════
from config import settings
from ocr import scan_langs, has_tesseract, get_tessdata
from doc import close_docs as _close_docs
from tools.read_pdf import read_pdf, read_pdf_page
from tools.list_info import list_pdf_info
from tools.search_pdf import search_pdf
from tools.extract_tables import extract_tables
from tools.preview_page import preview_page
from tools.summarize_pdf import summarize_pdf
from tools.extract_images import extract_images


# ═══════════════════════════ 工具注册 ═══════════════════════════
_TOOLS = {
    "read_pdf": read_pdf,
    "read_pdf_page": read_pdf_page,
    "list_pdf_info": list_pdf_info,
    "search_pdf": search_pdf,
    "extract_tables": extract_tables,
    "preview_page": preview_page,
    "summarize_pdf": summarize_pdf,
    "extract_images": extract_images,
}

_SCHEMA = [
    {
        "name": "read_pdf",
        "description": "读取PDF文字(自动OCR)，支持OCR进度推送",
        "inputSchema": {
            "type": "object",
            "required": ["file_path"],
            "properties": {
                "file_path": {"type": "string", "description": "PDF路径"},
                "page_start": {"type": "number", "description": "起始页"},
                "page_end": {"type": "number", "description": "结束页"},
                "format": {
                    "type": "string",
                    "enum": ["text", "json", "markdown"],
                },
            },
        },
    },
    {
        "name": "read_pdf_page",
        "description": "读取PDF单页文字(自动OCR)，适合交互式问答",
        "inputSchema": {
            "type": "object",
            "required": ["file_path", "page_num"],
            "properties": {
                "file_path": {"type": "string", "description": "PDF路径"},
                "page_num": {"type": "number", "description": "页码"},
                "format": {
                    "type": "string",
                    "enum": ["text", "markdown"],
                },
            },
        },
    },
    {
        "name": "list_pdf_info",
        "description": "PDF信息(页数/大小/加密/OCR)",
        "inputSchema": {
            "type": "object",
            "required": ["file_path"],
            "properties": {"file_path": {"type": "string"}},
        },
    },
    {
        "name": "search_pdf",
        "description": "搜索关键词(支持正则)，匹配词自动高亮",
        "inputSchema": {
            "type": "object",
            "required": ["file_path", "query"],
            "properties": {
                "file_path": {"type": "string", "description": "PDF路径"},
                "page_start": {"type": "number", "description": "起始页"},
                "page_end": {"type": "number", "description": "结束页"},
                "query": {"type": "string"},
                "regex": {"type": "boolean"},
            },
        },
    },
    {
        "name": "extract_tables",
        "description": "提取PDF表格(有边框+无边框)",
        "inputSchema": {
            "type": "object",
            "required": ["file_path"],
            "properties": {
                "file_path": {"type": "string", "description": "PDF路径"},
                "page_start": {"type": "number", "description": "起始页"},
                "page_end": {"type": "number", "description": "结束页"},
            },
        },
    },
    {
        "name": "preview_page",
        "description": "页面渲染PNG",
        "inputSchema": {
            "type": "object",
            "required": ["file_path", "page_num"],
            "properties": {
                "file_path": {"type": "string"},
                "page_num": {"type": "number"},
            },
        },
    },
    {
        "name": "summarize_pdf",
        "description": "自动生成PDF内容摘要(首尾关键页)",
        "inputSchema": {
            "type": "object",
            "required": ["file_path"],
            "properties": {
                "file_path": {"type": "string", "description": "PDF路径"},
                "preview_pages": {"type": "number", "description": "开头预览页数（默认3）"},
            },
        },
    },
    {
        "name": "extract_images",
        "description": "提取PDF中嵌入的图片(Base64 PNG)",
        "inputSchema": {
            "type": "object",
            "required": ["file_path"],
            "properties": {
                "file_path": {"type": "string", "description": "PDF路径"},
                "page_start": {"type": "number", "description": "起始页"},
                "page_end": {"type": "number", "description": "结束页"},
                "page_only": {"type": "number", "description": "仅提取单页(优先于起止页)"},
            },
        },
    },
]


async def _execute_tool(name: str, args: dict) -> dict:
    """统一工具执行入口"""
    if name not in _TOOLS:
        return {"isError": True, "content": [{"type": "text", "text": f"未知工具: {name}"}]}
    try:
        result = await _TOOLS[name](**args)
        if isinstance(result, dict) and "content" in result:
            return result
        return {"content": [{"type": "text", "text": str(result)}]}
    except ValueError as e:
        return {"isError": True, "content": [{"type": "text", "text": str(e)}]}
    except Exception as e:
        _LOG.error("工具 %s 执行失败: %s", name, traceback.format_exc())
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"执行失败: {e}"}],
        }


# ═══════════════════════════ 官方 SDK 模式 ═══════════════════════════
if _HAS_MCP_SDK:

    @asynccontextmanager
    async def lifespan(server: MCPServer):
        """服务器生命周期管理"""
        settings.ocr_langs = scan_langs()
        _LOG.info(
            "v5.2.0 | tesseract=%s | tessdata=%s | langs=%s | max_ocr=%d",
            has_tesseract(),
            get_tessdata() or "N/A",
            settings.ocr_langs,
            settings.ocr_max_concurrent,
        )
        try:
            yield
        finally:
            _close_docs()

    mcp = MCPServer(
        "deepseek-pdf-reader",
        version="5.2.0",
        description="PDF文字提取(自动OCR) · 搜索(正则+高亮) · 表格(三路径) · 预览 · 摘要 · 图片提取 · 单页阅读",
        lifespan=lifespan,
    )

    # 注册工具
    mcp.add_tool(read_pdf)
    mcp.add_tool(read_pdf_page)
    mcp.add_tool(list_pdf_info)
    mcp.add_tool(search_pdf)
    mcp.add_tool(extract_tables)
    mcp.add_tool(preview_page)
    mcp.add_tool(summarize_pdf)
    mcp.add_tool(extract_images)


# ═══════════════════════════ 兼容模式：内置 JSON-RPC 引擎 ═══════════════════════════
def _send(obj: dict) -> None:
    """发送 JSON-RPC 响应"""
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _respond(rid, result):
    """构建 JSON-RPC 2.0 成功响应"""
    if rid is not None and result is not None:
        _send({"jsonrpc": "2.0", "id": rid, "result": result})


def _cleanup_handler(req=None):
    """关闭文档并返回 None（用于 shutdown/exit）"""
    _close_docs()
    return None


async def _handle_builtin_call(req):
    """处理 tools/call 请求"""
    params = req.get("params", {})
    args = params.get("arguments", {})
    name = params.get("name", "")
    return await _execute_tool(name, args)


async def _run_builtin():
    """内置 JSON-RPC 引擎（当 mcp SDK 不可用时的回退方案）"""
    settings.ocr_langs = scan_langs()
    _LOG.info(
        "v5.2.0 (builtin) | tesseract=%s | langs=%s | max_ocr=%d",
        has_tesseract(),
        settings.ocr_langs,
        settings.ocr_max_concurrent,
    )

    R = {
        "initialize": lambda _: {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "deepseek-pdf-reader", "version": "5.2.0"},
        },
        "notifications/initialized": lambda _: None,
        "tools/list": lambda _: {"tools": _SCHEMA},
        "resources/list": lambda _: {"resources": []},
        "shutdown": _cleanup_handler,
        "exit": _cleanup_handler,
        "ping": lambda _: {},
        "tools/call": _handle_builtin_call,
    }

    while line := sys.stdin.readline():
        try:
            req = json.loads(line.strip())
        except Exception:
            continue

        rid = req.get("id")
        method = req.get("method", "")

        try:
            handler = R.get(method)
            if handler:
                result = handler(req)
                if inspect.isawaitable(result):
                    result = await result
                _respond(rid, result)
            else:
                _send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"未知: {method}"}})
        except SystemExit:
            _send({"jsonrpc": "2.0", "id": rid, "result": None})
            break
        except Exception:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "error": {"code": -32603, "message": f"内部错误: {traceback.format_exc()}"},
                }
            )


# ═══════════════════════════ 入口 ═══════════════════════════
async def main():
    if _HAS_MCP_SDK:
        await mcp.run_stdio_async()
    else:
        await _run_builtin()


if __name__ == "__main__":
    asyncio.run(main())