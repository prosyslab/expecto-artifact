import datetime
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

project_root = Path(__file__).parent
logger_save_dir = project_root / "logs"
os.makedirs(logger_save_dir, exist_ok=True)


class ColoredFormatter(logging.Formatter):
    """Custom formatter to add colors to log messages based on their level."""

    COLORS = {
        "DEBUG": "\033[94m",  # Blue
        "INFO": "\033[92m",  # Green
        "WARNING": "\033[93m",  # Yellow
        "ERROR": "\033[91m",  # Red
        "CRITICAL": "\033[1;91m",  # Bold Red
        "RESET": "\033[0m",  # Reset color
    }

    def format(self, record):
        log_message = super().format(record)
        if record.levelname in self.COLORS:
            return f"{self.COLORS[record.levelname]}{log_message}{self.COLORS['RESET']}"
        return log_message


now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def get_logger(path: str):
    # File handler with standard formatter (no colors in log files)
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
    file_handler = RotatingFileHandler(
        os.path.join(path, "log.log"),
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=10,
    )
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
    )
    file_handler.setLevel(logging.DEBUG)

    # Configure the root logger
    logging.basicConfig(level=logging.INFO, handlers=[file_handler], force=True)
    logger = logging.getLogger(__name__)
    return logger
