from __future__ import annotations

import logging
import secrets

from fastapi import Header

from config import get_settings
from errors import OCRError, OCRErrorCode


logger = logging.getLogger(__name__)


async def require_internal_secret(
    x_internal_secret: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),  # legacy
) -> None:
    settings = get_settings()

    # Dev mode: open if no secret configured at all.
    if settings.ENV == "dev" and not settings.INTERNAL_SECRET and not settings.LEGACY_API_KEY:
        return

    if x_internal_secret and _matches_secret(x_internal_secret, settings):
        return

    if (
        x_api_key
        and settings.LEGACY_API_KEY
        and secrets.compare_digest(x_api_key, settings.LEGACY_API_KEY)
    ):
        logger.warning("legacy_api_key_used", extra={"deprecation": True})
        return

    raise OCRError(OCRErrorCode.UNAUTHORIZED, "Invalid or missing internal credentials")


def _matches_secret(provided: str, settings) -> bool:
    if settings.INTERNAL_SECRET and secrets.compare_digest(provided, settings.INTERNAL_SECRET):
        return True
    if settings.INTERNAL_SECRET_PREVIOUS and secrets.compare_digest(
        provided, settings.INTERNAL_SECRET_PREVIOUS
    ):
        logger.warning("previous_secret_used", extra={"rotation_in_progress": True})
        return True
    return False
