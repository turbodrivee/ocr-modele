import logging
import sys

from pythonjsonlogger import jsonlogger

from middleware.request_id import current_request_id


class RequestIDFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = current_request_id()
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(request_id)s %(message)s",
        rename_fields={"asctime": "ts", "levelname": "level", "name": "logger"},
    )
    handler.setFormatter(formatter)
    handler.addFilter(RequestIDFilter())

    root = logging.getLogger()
    # Avoid duplicate handlers when reloading (uvicorn --reload).
    root.handlers = [handler]
    root.setLevel(level)

    # Silence noisy uvicorn access log (we log per-request ourselves).
    logging.getLogger("uvicorn.access").setLevel("WARNING")
