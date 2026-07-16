"""Upload normalization.

iPhones store photos as HEIC; Safari usually transcodes camera captures to
JPEG on upload, but photo-library and Files uploads can arrive as HEIC —
which no mainstream browser will display once we serve it back. Anything we
persist for display gets normalized to a browser-safe format here (the HEIF
opener itself is registered in core.apps at startup).
"""

import io
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageOps

BROWSER_SAFE_FORMATS = {"JPEG", "PNG", "GIF", "WEBP"}


def ensure_browser_displayable(uploaded):
    """Return the upload as-is if browsers render its format, else JPEG.

    Orientation is baked in on transcode (re-encoding would otherwise drop
    the EXIF rotation iPhones rely on).
    """
    image = Image.open(uploaded)
    if image.format in BROWSER_SAFE_FORMATS:
        uploaded.seek(0)
        return uploaded

    upright = ImageOps.exif_transpose(image).convert("RGB")
    buffer = io.BytesIO()
    upright.save(buffer, format="JPEG", quality=90)
    name = Path(uploaded.name or "upload").with_suffix(".jpg").name
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")
