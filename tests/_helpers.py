"""Helpers to generate in-memory test images without committing fixtures."""

from __future__ import annotations

import io

from PIL import Image


def make_jpeg(width: int = 800, height: int = 600, color=(255, 255, 255)) -> bytes:
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def make_oversize(target_bytes: int) -> bytes:
    """Produces a JPEG roughly larger than target_bytes by padding with noise."""
    import os

    return make_jpeg(2000, 2000) + os.urandom(target_bytes)
