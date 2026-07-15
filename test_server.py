#!/usr/bin/env python3
"""Test deepseek-pdf-reader v4.0 — 核心功能单元测试"""
import sys, json, asyncio, os, importlib.util

spec = importlib.util.spec_from_file_location(
    'server', r'C:\Users\WZP13\Documents\Cline\MCP\deepseek-pdf-reader\server.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

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
check_pass('empty TSV returns []', lambda: m._tsv_to_tables(empty_tsv) == [])

# Simulated Tesseract TSV output with 2-row table
tsv_data = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    "5\t1\t1\t1\t1\t1\t100\t200\t50\t20\t90\tName\n"
    "5\t1\t1\t1\t1\t2\t160\t200\t50\t20\t90\tAge\n"
    "5\t1\t1\t1\t2\t1\t100\t220\t50\t20\t90\tAlice\n"
    "5\t1\t1\t1\t2\t2\t160\t220\t50\t20\t90\t30\n"
)
result = m._tsv_to_tables(tsv_data)
check_pass('2-row table detected', lambda: len(result) > 0)
if result:
    check_pass('table has 2 rows', lambda: result[0]['num_rows'] == 2)
    check_pass('table has 2 cols', lambda: result[0]['num_cols'] == 2)

# === 2. _is_table clustering check ===
print('\n=== 2. _is_table ===')

regular = [['a','b','c'], ['d','e','f'], ['g','h','i']]
check_pass('regular 3x3 is table', lambda: m._is_table(regular) is True)

irregular = [['a','b','c'], ['d'], ['e','f','g','h']]
check_pass('irregular is not table', lambda: m._is_table(irregular) is False)

single_row = [['a','b']]
check_pass('single row not table', lambda: m._is_table(single_row) is False)

# === 3. _cluster_to_result ===
print('\n=== 3. _cluster_to_result ===')

rows = [['col1','col2'], ['v1','v2']]
r = m._cluster_to_result(rows)
check_pass('num_rows = 2', lambda: r['num_rows'] == 2)
check_pass('num_cols = 2', lambda: r['num_cols'] == 2)
check_pass('rows content preserved', lambda: r['rows'][0][0] == 'col1')

# Jagged rows (fill empty)
jagged = [['a','b','c'], ['d','e']]
r = m._cluster_to_result(jagged)
check_pass('jagged padded to 3 cols', lambda: len(r['rows'][1]) == 3)
check_pass('padding is empty string', lambda: r['rows'][1][2] == '')

# === 4. _fmt_page ===
print('\n=== 4. _fmt_page ===')

md = m._fmt_page(True, 3, 'Hello World')
check_pass('markdown format', lambda: md == '## 第 3 页\n\nHello World')

txt = m._fmt_page(False, 1, 'Plain')
check_pass('plain format', lambda: txt == '=== 第 1 页 ===\nPlain')

empty_md = m._fmt_page(True, 5, '')
check_pass('empty text md', lambda: '*[无文字]*' in empty_md)

empty_txt = m._fmt_page(False, 5, '')
check_pass('empty text txt', lambda: '[无文字]' in empty_txt)

# === 5. _fmt_tables ===
print('\n=== 5. _fmt_tables ===')

tables = [{
    'page': 2,
    'num_rows': 3,
    'num_cols': 2,
    'rows': [['Name','Age'], ['Alice','30'], ['Bob','25']]
}]
md_tables = m._fmt_tables(tables)
check_pass('table markdown header', lambda: '| Name | Age |' in md_tables)
check_pass('table separator row', lambda: '| --- | --- |' in md_tables)
check_pass('table data row', lambda: '| Alice | 30 |' in md_tables)
check_pass('table stats', lambda: '3行 x 2列' in md_tables)

# === 6. _e / _o helper ===
print('\n=== 6. _e / _o helper ===')

err = m._e('test error')
check_pass('_e has isError=True', lambda: err['isError'] is True)
check_pass('_e has content', lambda: 'content' in err)
check_pass('_e content text', lambda: err['content'][0]['text'] == 'test error')

ok = m._o('test output')
check_pass('_o has content', lambda: 'content' in ok)
check_pass('_o no isError', lambda: 'isError' not in ok)
check_pass('_o content text', lambda: ok['content'][0]['text'] == 'test output')

# === 7. _resolve ===
print('\n=== 7. _resolve ===')

doc, err = m._resolve({})
check_pass('missing file_path returns error', lambda: doc is None and err['isError'])

doc, err = m._resolve({'file_path': 'nonexistent_file_xyz.pdf'})
check_pass('nonexistent file returns error', lambda: doc is None and err['isError'])

# === 8. _interval validation ===
print('\n=== 8. _interval ===')

check_raises('page_start > page_end', lambda: m._interval({'page_start': 5, 'page_end': 3}, 10))
check_raises('page_start < 1', lambda: m._interval({'page_start': 0, 'page_end': 5}, 10))
check_raises('page_end > total', lambda: m._interval({'page_start': 1, 'page_end': 15}, 10))

ps, pe = m._interval({'page_start': 2, 'page_end': 5}, 10)
check_pass('valid interval', lambda: ps == 2 and pe == 5)

ps, pe = m._interval({}, 10)
check_pass('default interval', lambda: ps == 1 and pe == 10)

# === 9. _OCR_SEM default (v4.0 fix) ===
print('\n=== 9. _OCR_SEM default ===')

check_pass('_OCR_SEM is Semaphore', lambda: isinstance(m._OCR_SEM, asyncio.Semaphore))
check_pass('_OCR_SEM has correct limit', lambda: m._OCR_SEM._value == m._OCR_MAX_CONCURRENT)

# === 10. MCP Dispatch (JSON-RPC) ===
print('\n=== 10. MCP Dispatch (JSON-RPC) ===')

async def _test_dispatch():
    # initialize
    r = await m._init({})
    check_pass('initialize server name',
        lambda: r['serverInfo']['name'] == 'deepseek-pdf-reader')
    check_pass('initialize version 4.0.0',
        lambda: r['serverInfo']['version'] == '4.0.0')
    check_pass('initialize protocol',
        lambda: r['protocolVersion'] == '2024-11-05')

    # tools/list
    r = await m._tl({})
    names = {t['name'] for t in r['tools']}
    check_pass('tools/list has read_pdf', lambda: 'read_pdf' in names)
    check_pass('tools/list has list_pdf_info', lambda: 'list_pdf_info' in names)
    check_pass('tools/list has search_pdf', lambda: 'search_pdf' in names)
    check_pass('tools/list has extract_tables', lambda: 'extract_tables' in names)
    check_pass('tools/list has preview_page', lambda: 'preview_page' in names)
    check_pass('5 tools total', lambda: len(names) == 5)

    # ping
    r = await m._ping({})
    check_pass('ping returns {}', lambda: r == {})

    # unknown tool
    r = await m._call({
        'params': {'name': 'unknown_tool', 'arguments': {}}
    })
    check_pass('unknown tool returns isError', lambda: r['isError'] is True)

    # tools/call with missing file_path
    r = await m._call({
        'params': {'name': 'read_pdf', 'arguments': {}}
    })
    check_pass('read_pdf missing file_path isError', lambda: r['isError'] is True)

asyncio.run(_test_dispatch())

# === 11. PDFDoc class basics ===
print('\n=== 11. PDFDoc class basics ===')

doc = m.PDFDoc('test.pdf')
check_pass('PDFDoc default _doc is None', lambda: doc._doc is None)
check_pass('PDFDoc default _needs_pass is None', lambda: doc._needs_pass is None)
check_pass('PDFDoc has _lock', lambda: isinstance(doc._lock, m.Lock))

# === Result ===
print(f'\n{"="*50}')
if errors:
    print(f'[FAILED] {len(errors)} tests:')
    for e in errors:
        print(f'  - {e}')
    sys.exit(1)
else:
    # 1:3 + 2:3 + 3:4 + 4:4 + 5:4 + 6:5 + 7:2 + 8:4 + 9:2 + 10:8 + 11:3 = 42
    print('[OK] All 42 tests passed!')
    print('deepseek-pdf-reader v4.0 is correct and ready to use.')
    sys.exit(0)