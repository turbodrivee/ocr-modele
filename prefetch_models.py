"""Run at Docker build time to bake PaddleOCR models into the image layer.

Without this, the first request to a fresh container would block for
1-3 minutes downloading ~500 MB of weights from BOS.
"""

from __future__ import annotations


def main() -> None:
    from paddleocr import PaddleOCR

    for lang in ("fr", "ar"):
        print(f"[prefetch] downloading PaddleOCR models for lang={lang!r}…", flush=True)
        PaddleOCR(lang=lang, use_textline_orientation=True)
        print(f"[prefetch] done lang={lang!r}", flush=True)


if __name__ == "__main__":
    main()
