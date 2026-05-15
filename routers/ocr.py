import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from config import get_settings
from errors import OCRError, OCRErrorCode
from metrics import ocr_confidence, ocr_errors_total, ocr_field_present_total, ocr_latency_seconds
from middleware.auth import require_internal_secret
from ocr_engine import confidence_to_status, run_ocr
from utils.image_processor import preprocess_image
from utils.parser import parse_fields


router = APIRouter(tags=["ocr"], dependencies=[Depends(require_internal_secret)])
logger = logging.getLogger(__name__)


@router.post("/ocr/extract")
async def ocr_extract(
    request: Request,
    file: Annotated[UploadFile, File(description="Image file (jpg/png/webp)")],
    doc_type: Annotated[str, Form(description="permis | cin | carte_grise | assurance")],
) -> dict:
    settings = get_settings()

    if doc_type not in settings.SUPPORTED_DOC_TYPES:
        raise OCRError(
            OCRErrorCode.INVALID_DOC_TYPE,
            f"Invalid doc_type '{doc_type}'",
            {"allowed": sorted(settings.SUPPORTED_DOC_TYPES)},
        )

    content_type = file.content_type or ""
    if content_type not in settings.SUPPORTED_CONTENT_TYPES:
        raise OCRError(
            OCRErrorCode.UNSUPPORTED_MEDIA,
            f"Unsupported content type '{content_type}'",
            {"allowed": sorted(settings.SUPPORTED_CONTENT_TYPES)},
        )

    # Size check via Content-Length BEFORE reading the body.
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > settings.MAX_UPLOAD_BYTES:
                raise OCRError(
                    OCRErrorCode.PAYLOAD_TOO_LARGE,
                    "Upload exceeds maximum allowed size",
                    {"max_bytes": settings.MAX_UPLOAD_BYTES},
                )
        except ValueError:
            pass  # malformed header — fall through to chunked check below

    image_bytes = await _read_with_cap(file, settings.MAX_UPLOAD_BYTES)

    t_start = time.perf_counter()

    try:
        img_array = preprocess_image(image_bytes)
    except ValueError as exc:
        if str(exc) == "image_too_small":
            raise OCRError(
                OCRErrorCode.IMAGE_TOO_SMALL,
                "Image is too small — minimum dimensions are 200x200 px",
                {"min_dimension": 200},
            ) from exc
        raise OCRError(OCRErrorCode.VALIDATION_ERROR, f"Image processing error: {exc}") from exc

    try:
        raw_text, confidence, per_engine = run_ocr(img_array)
    except Exception as exc:  # noqa: BLE001
        logger.exception("ocr_pipeline_crash")
        raise OCRError(
            OCRErrorCode.ENGINE_FAILURE,
            "OCR engine failure",
            {"error": str(exc)},
        ) from exc

    status = confidence_to_status(confidence) if raw_text.strip() else "failed"

    parsed = parse_fields(raw_text, doc_type)
    parsed["raw_text"] = raw_text

    processing_time_ms = round((time.perf_counter() - t_start) * 1000)

    # Metrics
    ocr_latency_seconds.labels(doc_type=doc_type).observe(processing_time_ms / 1000.0)
    ocr_confidence.labels(doc_type=doc_type).observe(confidence)
    for k, v in parsed.items():
        if k == "raw_text":
            continue
        ocr_field_present_total.labels(
            doc_type=doc_type,
            field=k,
            present="true" if v is not None and v != [] else "false",
        ).inc()

    logger.info(
        "ocr_extract_done",
        extra={
            "doc_type": doc_type,
            "confidence": confidence,
            "confidence_fr": per_engine.get("fr"),
            "confidence_ar": per_engine.get("ar"),
            "status": status,
            "processing_time_ms": processing_time_ms,
            "fields_present": {k: v is not None for k, v in parsed.items() if k != "raw_text"},
        },
    )

    return {
        "success": True,
        "data": {
            "doc_type": doc_type,
            "confidence": confidence,
            "status": status,
            "data": parsed,
            "processing_time_ms": processing_time_ms,
        },
    }


async def _read_with_cap(file: UploadFile, max_bytes: int) -> bytes:
    """Read upload in chunks, abort if total exceeds cap (defense against missing Content-Length)."""
    chunk_size = 64 * 1024
    accumulated = bytearray()
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        accumulated.extend(chunk)
        if len(accumulated) > max_bytes:
            raise OCRError(
                OCRErrorCode.PAYLOAD_TOO_LARGE,
                "Upload exceeds maximum allowed size",
                {"max_bytes": max_bytes},
            )
    return bytes(accumulated)
