"""Tesseract OCR 自动发现 + 文字识别"""
import os
import shutil
import subprocess
import tempfile
import traceback
import logging
from contextlib import suppress

from config import settings

_LOG = logging.getLogger("pdf")

# Tesseract 5路径自动发现
_TESSERACT: str | None = (
    os.environ.get("TESSERACT_CMD")
    or shutil.which("tesseract")
    or next(
        (
            p
            for p in [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            ]
            if os.path.isfile(p)
        ),
        None,
    )
)


def _tessdata_from_params():
    """从 tesseract --print-parameters 中提取 TESSDATA_PREFIX"""
    if not _TESSERACT:
        return
    try:
        r = subprocess.run(
            [_TESSERACT, "--print-parameters"],
            capture_output=True,
            timeout=5,
            text=True,
            errors="replace",
        )
        yield from (
            line.strip().split("\t")[-1]
            for line in r.stdout.split("\n")
            if "TESSDATA_PREFIX" in line
        )
    except Exception:
        pass


def _detect_tessdata() -> str:
    """检测 tessdata 目录路径（多路径探测）"""
    for p in filter(
        None,
        [
            os.environ.get("TESSDATA_PREFIX"),
            os.path.join(os.path.dirname(_TESSERACT), "tessdata") if _TESSERACT else "",
            *_tessdata_from_params(),
            *[
                d
                for d in [
                    r"C:\Program Files\Tesseract-OCR\tessdata",
                    r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
                    "/usr/share/tesseract-ocr/5/tessdata",
                    "/usr/share/tesseract-ocr/4/tessdata",
                    "/usr/share/tessdata",
                ]
                if os.path.isdir(d)
            ],
        ],
    ):
        return p
    return ""


_TESSDATA: str | None = None  # 懒加载


def get_tessdata() -> str:
    """获取 tessdata 目录（懒加载）"""
    global _TESSDATA
    if _TESSDATA is None:
        _TESSDATA = _detect_tessdata()
    return _TESSDATA


def tess_env() -> dict:
    """构建带 TESSDATA_PREFIX 的环境变量"""
    td = get_tessdata()
    return {**os.environ, "TESSDATA_PREFIX": td} if td else os.environ


def has_tesseract() -> bool:
    return _TESSERACT is not None


def scan_langs() -> list[str]:
    """扫描已安装的 Tesseract 语言包"""
    if not _TESSERACT:
        return []
    try:
        r = subprocess.run(
            [_TESSERACT, "--list-langs"],
            capture_output=True,
            timeout=10,
            env=tess_env(),
        )
        installed = [
            l.strip()
            for l in (r.stdout + r.stderr).decode("utf-8", errors="replace").split("\n")
            if l.strip() and not l.startswith("List")
        ]
    except Exception:
        installed = []

    seen: set[str] = set()
    langs: list[str] = []
    if "chi_sim" in installed and "eng" in installed:
        langs.append("chi_sim+eng")
        seen.add("chi_sim+eng")
    if "eng" in installed:
        langs.append("eng")
        seen.add("eng")
    if "chi_sim+eng" not in seen:
        langs.append("chi_sim+eng")
    return langs


def ocr(img: bytes, timeout: int | None = None, tsv: bool = False) -> str:
    """对 PNG 图片执行 OCR，支持多语言回退

    Args:
        img: PNG 图片字节
        timeout: 超时秒数（默认使用 settings.ocr_timeout）
        tsv: 是否输出 TSV 格式（用于表格检测）

    Returns:
        识别的文字内容
    """
    if not _TESSERACT:
        return ""

    timeout = timeout or settings.ocr_timeout
    langs = settings.ocr_langs or settings.fallback_langs
    env = tess_env()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(img)
        tmp = f.name

    try:
        for lang in langs:
            try:
                args = [_TESSERACT, tmp, "stdout", "-l", lang, "--psm", "6"]
                if tsv:
                    args.append("tsv")
                r = subprocess.run(
                    args,
                    capture_output=True,
                    timeout=timeout,
                    env=env,
                )
                if t := r.stdout.decode("utf-8", errors="replace").strip():
                    return t
            except Exception:
                _LOG.warning("OCR错误(%s): %s", lang, traceback.format_exc()[:120])
    finally:
        with suppress(OSError):
            os.unlink(tmp)
    return ""