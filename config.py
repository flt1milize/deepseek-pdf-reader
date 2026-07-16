"""全局配置常量"""
import logging
import sys
from dataclasses import dataclass, field

@dataclass
class Settings:
    """运行时配置，可在 lifespan 中修改"""
    max_cached_docs: int = 10
    max_file_size_mb: float = 200.0
    max_image_size_mb: float = 50.0       # OCR 图片大小上限
    page_cache_size: int = 500
    ocr_cache_size: int = 50
    tsv_cache_size: int = 20
    ocr_timeout: int = 60
    ocr_max_concurrent: int = 2
    fallback_langs: list[str] = field(default_factory=lambda: ["chi_sim+eng", "eng"])
    ocr_langs: list[str] = field(default_factory=list)

settings = Settings()


def configure_logging(log_level: int = logging.INFO) -> logging.Logger:
    """统一配置日志，返回 'pdf' logger"""
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )
    return logging.getLogger("pdf")
