import logging
import os
from datetime import datetime

# Define log directory
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
LOG_DIR = os.path.join(ROOT_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)


def get_daily_log_filename(base_name):
    """Generate a log filename for the current date."""
    date_str = datetime.now().strftime("%Y%m%d")
    return os.path.join(LOG_DIR, f"{base_name}_{date_str}.log")


class DailyRotatingFileHandler(logging.Handler):
    """Custom handler to rotate log files daily with a consistent naming scheme."""

    def __init__(self, base_name, level=logging.INFO):
        super().__init__(level)
        self.base_name = base_name
        self.current_date = datetime.now().date()
        self.log_file = get_daily_log_filename(self.base_name)
        self.file_handler = self._create_file_handler()

    def _create_file_handler(self):
        handler = logging.FileHandler(self.log_file, mode="a", encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        return handler

    def emit(self, record):
        current_date = datetime.now().date()
        if current_date != self.current_date:
            self.current_date = current_date
            self.file_handler.close()
            self.log_file = get_daily_log_filename(self.base_name)
            self.file_handler = self._create_file_handler()
        self.file_handler.emit(record)

    def close(self):
        self.file_handler.close()
        super().close()


def setup_logging():
    """Setup logging with daily rotating logs and suppress noisy third-party logs."""
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger()

    # Suppress noisy third-party library logs
    # Set httpx (used by telegram bot) to WARNING level
    logging.getLogger("httpx").setLevel(logging.WARNING)
    
    # Set urllib3 (used by requests) to WARNING level
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    
    # Set telegram library logs to WARNING level
    logging.getLogger("telegram").setLevel(logging.WARNING)
    
    # Set requests library to WARNING level
    logging.getLogger("requests").setLevel(logging.WARNING)
    
    # Set other common noisy loggers to WARNING
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("h11").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    # Add a console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(console_handler)

    # Add a daily rotating file handler for info logs
    info_handler = DailyRotatingFileHandler("info", level=logging.INFO)
    logger.addHandler(info_handler)

    # Add a separate file handler for error logs
    error_handler = DailyRotatingFileHandler("error", level=logging.ERROR)
    logger.addHandler(error_handler)

    # Log that logging has been configured
    logger.info("Logging configured - third-party HTTP logs suppressed")

    return logger
