# DeepSeek PDF Reader MCP Server v4.0

[![Version](https://img.shields.io/badge/version-4.0.0-blue.svg)](https://github.com/FLT1milize/deepseek-pdf-reader)
[![Python](https://img.shields.io/badge/python-3.10+-green.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-brightgreen.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-42%2F42%20passed-success.svg)](test_server.py)

MCP 服务器，提供全面的 PDF 处理能力：文字提取（自动 OCR）、关键词搜索（支持正则）、表格提取（三路径）、页面预览（Base64 PNG）。

## 功能概览

| 工具 | 说明 |
|------|------|
| `read_pdf` | 读取 PDF 文字，支持 `text` / `json` / `markdown` 三种输出格式，扫描件自动 OCR |
| `list_pdf_info` | 获取 PDF 元信息：页数、文件大小、是否加密、是否有文字层、OCR 状态、Tesseract 语言包 |
| `search_pdf` | 搜索关键词，支持正则表达式，返回页码、命中次数、上下文摘录 |
| `extract_tables` | 三路径表格提取策略：PyMuPDF 内置检测（有边框）→ block/line 结构化解析 → TSV 坐标聚类（无边框兜底） |
| `preview_page` | 指定页码渲染为 PNG 图片（Base64 编码），可直接在聊天界面展示 |

## 系统要求

- **Python** 3.10+
- **Tesseract OCR**（可选，用于扫描件 PDF 的文字识别）：

| 平台 | 安装命令 |
|------|----------|
| Windows | 下载安装 [Tesseract-OCR](https://github.com/UB-Mannheim/tesseract/wiki)，安装时勾选中文语言包 |
| macOS | `brew install tesseract tesseract-lang` |
| Ubuntu/Debian | `sudo apt install tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng` |
| Arch Linux | `sudo pacman -S tesseract tesseract-data-eng tesseract-data-chi_sim` |

## 安装

```bash
# 克隆仓库
git clone https://github.com/FLT1milize/deepseek-pdf-reader.git
cd deepseek-pdf-reader

# 安装 Python 依赖
pip install -r requirements.txt
```

## 运行测试

```bash
python test_server.py
```

预期输出：`[OK] All 42 tests passed!`

## 在 Cline 中配置

编辑 Cline 的 MCP 配置文件，添加如下条目：

```json
{
  "mcpServers": {
    "deepseek-pdf-reader": {
      "command": "python",
      "args": ["path/to/deepseek-pdf-reader/server.py"],
      "env": {
        "TESSERACT_CMD": "C:/Program Files/Tesseract-OCR/tesseract.exe"
      }
    }
  }
}
```

> **提示**：`TESSERACT_CMD` 可选；若留空，服务器会自动搜索常见安装路径。也可以通过环境变量 `TESSDATA_PREFIX` 指定语言包路径。

## 配置选项

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `TESSERACT_CMD` | Tesseract 可执行文件路径 | 自动搜索 |
| `TESSDATA_PREFIX` | tessdata 语言包目录 | 自动搜索 |

## 架构说明

```
server.py (504行) — 单体文件，无外部 MCP 框架依赖
├── Tesseract 自动发现（5 路径）
├── PDFDoc 类（线程安全缓存 + LRU 淘汰）
├── 表格提取（PyMuPDF → block/line → TSV 聚类）
├── JSON-RPC 2.0 协议处理
└── 5 个 MCP 工具
```

核心依赖：仅 [PyMuPDF](https://pymupdf.readthedocs.io/) (fitz)，OCR 通过 subprocess 调用 Tesseract CLI。

## 许可证

MIT · 详见 [LICENSE](LICENSE)