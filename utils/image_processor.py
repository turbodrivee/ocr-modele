from PIL import Image, ImageEnhance
import numpy as np
import io


MIN_DIMENSION = 200
TARGET_WIDTH = 1200
UPSCALE_THRESHOLD = 1000
CONTRAST_FACTOR = 1.4

# 30 MP cap on decoded pixels. A legitimate 12 MP phone photo decodes to
# 4032×3024 ≈ 12 MP, so 30 MP gives 2.5× headroom. Above this we assume
# a decompression bomb (PNG/WebP that's tiny on disk but huge in memory)
# rather than a real document scan.
_MAX_PIXELS = 30 * 1_000_000
Image.MAX_IMAGE_PIXELS = _MAX_PIXELS


def preprocess_image(image_bytes: bytes) -> np.ndarray:
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
    except Image.DecompressionBombError as exc:
        raise ValueError("image_too_large") from exc
    except (Image.UnidentifiedImageError, OSError, SyntaxError) as exc:
        # Truncated JPEG, corrupted PNG, bytes that don't look like an image
        # at all (e.g. caller mislabelled a PDF as image/jpeg). All map to
        # "invalid input", never to a 5xx.
        raise ValueError("image_unreadable") from exc

    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    width, height = image.size
    if width < MIN_DIMENSION or height < MIN_DIMENSION:
        raise ValueError("image_too_small")

    if width < UPSCALE_THRESHOLD:
        scale = TARGET_WIDTH / width
        new_height = int(height * scale)
        image = image.resize((TARGET_WIDTH, new_height), Image.LANCZOS)

    if image.mode != "L":
        image = image.convert("L").convert("RGB")

    enhancer = ImageEnhance.Contrast(image)
    image = enhancer.enhance(CONTRAST_FACTOR)

    return np.array(image)
