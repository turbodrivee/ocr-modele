from PIL import Image, ImageEnhance
import numpy as np
import io


MIN_DIMENSION = 200
TARGET_WIDTH = 1200
UPSCALE_THRESHOLD = 1000
CONTRAST_FACTOR = 1.4


def preprocess_image(image_bytes: bytes) -> np.ndarray:
    image = Image.open(io.BytesIO(image_bytes))

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
