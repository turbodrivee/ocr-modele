from fastapi import APIRouter, Response

from ocr_engine import engines_ready


router = APIRouter(tags=["health"])


@router.get("/health/live")
def liveness() -> dict:
    return {"status": "ok"}


@router.get("/health/ready")
def readiness(response: Response) -> dict:
    if engines_ready():
        return {"status": "ok", "model": "paddleocr", "langs": ["ar", "fr"]}
    response.status_code = 503
    return {"status": "loading", "model": "paddleocr", "langs": ["ar", "fr"]}
