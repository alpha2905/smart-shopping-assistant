# utils/logging_config.py
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

def setup_logging(log_filename: str = "app.log"):
    """
    Sets up logging to both console and a rotating file.
    """
    # Đảm bảo console xuất UTF-8 để log tiếng Việt không lỗi encoding
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Clear existing handlers to avoid duplicates
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # File Handler
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, log_filename), maxBytes=5*1024*1024, backupCount=3
    )
    file_handler.setFormatter(log_formatter)
    root_logger.addHandler(file_handler)

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)
    root_logger.addHandler(console_handler)

    logging.info(f"Logging configured. Outputting to console and logs/{log_filename}")