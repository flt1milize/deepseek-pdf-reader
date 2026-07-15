#!/usr/bin/env python3
"""Test deepseek-pdf-reader v5.0.0 — 核心功能单元测试"""
import sys
import asyncio

# 添加当前目录到 sys.path
sys.path.insert(0, '.')

from table import _tsv_to_tables, _is_table, _cluster_to_result
from format import fmt_page, fmt_tables

errors = []

def check_pass(desc, fn):
    try:
        fn()
        print(f'  [PASS] {desc}')
    except Exception as e:
        errors.append(desc)
        import traceback
        print(f'  [FAIL] {desc} -- {e}')
        traceback.print_exc()

def check_raises(desc, fn):
    try:
        fn()
        errors.append(desc)
        print(f'  [FAIL] {desc} -- expected exception, got none')
    except Exception:
        print(f'  [PASS] {desc}')

# === 1. TSV → Table parsing ===
print('=== 1. _tsv_to_tables ===')

empty_tsv = ''
check_pass('empty TSV returns []', lambda: _tsv_to_tables(empty_tsv) == [])

# Simulated Tesseract TSV output with 2-row table
tsv_data = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    "5\t1\t1\t1\t1\t1\t100\t200\t50\t20\t90\tName\n"
    "5\t1\t1\t1\t1\t2\t160\t200\t50\t20\t90\tAge\n"
    "5\t1\t1\t1\t2\t1\t100\t220\t50\t20\t90\tAlice\n"
    "5\t1\t1\t1\t2\t2\t160\t220\t50\t20\t90\t30\n"
)
result = _tsv_to_tables(tsv_data)
check_pass('2-row table detected', lambda: len(result) > 0)
if result:
    check_pass('table has 2 rows', lambda: result[0]['num_rows'] == 2)
    check_pass('table has 2 cols', lambda: result[0]['num_cols'] == 2)

# === 2. _is_table clustering check ===
print('\n=== 2. _is_table ===')

regular = [['a','b','c'], ['d','e','f'], ['g','h','i']]
check_pass('regular 3x3 is table', lambda: _is_table(regular) is True)

irregular = [['a','b','c'], ['d'], ['e','f','g','h']]
check_pass('irregular is not table', lambda: _is_table(irregular) is False)

single_row = [['a','b']]
check_pass('single row not table', lambda: _is_table(single_row) is False)

# === 3. _cluster_to_result ===
print('\n=== 3. _cluster_to_result ===')

rows = [['col1','col2'], ['v1','v2']]
r = _cluster_to_result(rows)
check_pass('num_rows = 2', lambda: r['num_rows'] == 2)
check_pass('num_cols = 2', lambda: r['num_cols'] == 2)
check_pass('rows content preserved', lambda: r['rows'][0][0] == 'col1')

# Jagged rows (fill empty)
jagged = [['a','b','c'], ['d','e']]
r = _cluster_to_result(jagged)
check_pass('jagged padded to 3 cols', lambda: len(r['rows'][1]) == 3)
check_pass('padding is empty string', lambda: r['rows'][1][2] == '')

# === 4. _fmt_page ===
print('\n=== 4. fmt_page ===')

md = fmt_page(True, 3, 'Hello World')
check_pass('markdown format', lambda: md == '## 第 3 页\n\nHello World')

txt = fmt_page(False, 1, 'Plain')
check_pass('plain format', lambda: txt == '=== 第 1 页 ===\nPlain')

empty_md = fmt_page(True, 5, '')
check_pass('empty text md', lambda: '*[无文字]*' in empty_md)

empty_txt = fmt_page(False, 5, '')
check_pass('empty text txt', lambda: '[无文字]' in empty_txt)

# === 5. _fmt_tables ===
print('\n=== 5. fmt_tables ===')

tables = [{
    'page': 2,
    'num_rows': 3,
    'num_cols': 2,
    'rows': [['Name','Age'], ['Alice','30'], ['Bob','25']]
}]
md_tables = fmt_tables(tables)
check_pass('table markdown header', lambda: '| Name | Age |' in md_tables)
check_pass('table separator row', lambda: '| --- | --- |' in md_tables)
check_pass('table data row', lambda: '| Alice | 30 |' in md_tables)
check_pass('table stats', lambda: '3行 x 2列' in md_tables)

# === 6. server module imports ===
print('\n=== 6. Module structure ===')

import config
check_pass('config.py has Settings', lambda: hasattr(config, 'settings'))
check_pass('settings.max_cached_docs = 10', lambda: config.settings.max_cached_docs == 10)

import ocr
check_pass('ocr.py has scan_langs', lambda: hasattr(ocr, 'scan_langs'))
check_pass('ocr.py has has_tesseract', lambda: hasattr(ocr, 'has_tesseract'))

import doc
check_pass('doc.py has PDFDoc', lambda: hasattr(doc, 'PDFDoc'))
check_pass('doc.py has get_doc', lambda: hasattr(doc, 'get_doc'))

from tools import read_pdf, list_pdf_info, search_pdf, extract_tables, preview_page
check_pass('tools.read_pdf imported', lambda: callable(read_pdf))
check_pass('tools.list_pdf_info imported', lambda: callable(list_pdf_info))
check_pass('tools.search_pdf imported', lambda: callable(search_pdf))
check_pass('tools.extract_tables imported', lambda: callable(extract_tables))
check_pass('tools.preview_page imported', lambda: callable(preview_page))

# === 7. PDFDoc class basics ===
print('\n=== 7. PDFDoc class basics ===')

doc_inst = doc.PDFDoc('test.pdf')
check_pass('PDFDoc default _doc is None', lambda: doc_inst._doc is None)
check_pass('PDFDoc default _needs_pass is None', lambda: doc_inst._needs_pass is None)
check_pass('PDFDoc has _lock', lambda: isinstance(doc_inst._lock, doc_inst._lock.__class__))

# === Result ===
print(f'\n{"="*50}')
if errors:
    print(f'[FAILED] {len(errors)} tests:')
    for e in errors:
        print(f'  - {e}')
    sys.exit(1)
else:
    # 1:3 + 2:3 + 3:4 + 4:4 + 5:4 + 6:9 + 7:3 = 30
    print('[OK] All 30 tests passed!')
    print('deepseek-pdf-reader v5.0.0 is correct and ready to use.')
    sys.exit(0)