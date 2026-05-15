import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from config import get_settings
from errors import OCRError, OCRErrorCode, envelope_error, ocr_error_handler, unhandled_exception_handler
from middleware.logging import configure_logging
from middleware.request_id import RequestIDMiddleware
from ocr_engine import set_engines
from routers import health, metrics as metrics_router, ocr


settings = get_settings()
configure_logging(settings.LOG_LEVEL)
logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address, default_limits=[f"{settings.RATE_LIMIT_PER_MINUTE}/minute"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ocr_service_starting", extra={"env": settings.ENV})
    from paddleocr import PaddleOCR

    use_orient = settings.OCR_USE_ORIENTATION_DETECTION
    fr = PaddleOCR(
        lang="fr",
        text_detection_model_name="PP-OCRv5_mobile_det",
        text_recognition_model_name="latin_PP-OCRv5_mobile_rec",
        use_textline_orientation=use_orient,
        use_doc_orientation_classify=use_orient,
        use_doc_unwarping=False,
    )
    ar = PaddleOCR(
        lang="ar",
        text_detection_model_name="PP-OCRv5_mobile_det",
        text_recognition_model_name="arabic_PP-OCRv5_mobile_rec",
        use_textline_orientation=use_orient,
        use_doc_orientation_classify=use_orient,
        use_doc_unwarping=False,
    )
    set_engines(fr, ar)
    logger.info(
        "ocr_service_ready",
        extra={"langs": ["fr", "ar"], "orientation_detection": use_orient},
    )
    yield
    logger.info("ocr_service_stopping")


app = FastAPI(title="OCR Document Service", version="1.0.0", lifespan=lifespan)

app.state.limiter = limiter
app.add_middleware(RequestIDMiddleware)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    from fastapi.responses import JSONResponse

    rid = getattr(request.state, "request_id", None)
    headers = {"X-Request-ID": rid} if rid else {}
    return JSONResponse(
        status_code=429,
        content=envelope_error(OCRErrorCode.RATE_LIMITED, "Too many requests"),
        headers=headers,
    )


app.add_exception_handler(OCRError, ocr_error_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(health.router, prefix="/v1")
app.include_router(ocr.router, prefix="/v1")
app.include_router(metrics_router.router)  # /metrics — no /v1 prefix (standard Prometheus path)
