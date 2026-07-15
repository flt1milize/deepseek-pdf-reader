"""TSV 坐标 → 表格结构解析（无边框表格兜底方案）"""
from collections import defaultdict


def _tsv_to_tables(tsv: str) -> list[dict]:
    """将 Tesseract TSV 输出解析为表格列表

    基于 TSV 中的 word-level 坐标信息 (level=5)，
    按行号聚类，检测表格结构。
    """
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
                # cols[2]=block_num, cols[4]=line_num, cols[6]=left
                rows_map[(int(cols[2]), int(cols[4]))].append(
                    {"x": int(float(cols[6])), "t": text}
                )
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

        # 按 X 坐标排序，确保列顺序正确
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
    """判断聚类是否为表格结构

    规则：至少 2 行，且 70% 的行列数与平均列数偏差 ≤ 2
    """
    if len(cluster) < 2:
        return False
    cols = [len(r) for r in cluster]
    avg = sum(cols) / len(cols)
    return sum(1 for c in cols if abs(c - avg) <= 2) >= len(cols) * 0.7


def _cluster_to_result(rows: list[list[str]]) -> dict:
    """将聚类结果转换为统一输出格式（填充空单元格）"""
    max_cols = max(len(r) for r in rows)
    return {
        "rows": [r + [""] * (max_cols - len(r)) for r in rows],
        "num_rows": len(rows),
        "num_cols": max_cols,
    }