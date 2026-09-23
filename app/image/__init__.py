import hashlib
import io
import warnings
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps
from pillow_heif import register_heif_opener

from app.errors import AppError

register_heif_opener()
FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "HEIF": ("heic", "image/heic"),
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inspect_image(data, max_pixels):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as im:
                fmt = im.format
                if fmt not in FORMATS:
                    raise AppError("UNSUPPORTED_FORMAT", "請上傳 JPEG、PNG 或 HEIC 圖片。", 415)
                if im.width * im.height > max_pixels:
                    raise AppError("IMAGE_TOO_LARGE", "圖片像素超過限制。", 413)
                im.load()
        return FORMATS[fmt]
    except AppError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise AppError("IMAGE_TOO_LARGE", "圖片像素超過限制。", 413)
    except Exception:
        raise AppError("INVALID_IMAGE", "圖片無法解碼，請重新選擇照片。", 415)


class ImagePreprocessor:
    def process(self, original, output, config, max_pixels):
        original, output = Path(original), Path(output)
        data = original.read_bytes()
        inspect_image(data, max_pixels)
        with Image.open(io.BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            edge = config["max_edge"]
            if not 256 <= edge <= 8192:
                raise AppError("PREPROCESS_CONFIG_INVALID", "推論圖尺寸設定無效。")
            image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
            image = ImageEnhance.Contrast(image).enhance(config["contrast"])
            image = ImageEnhance.Sharpness(image).enhance(config["sharpness"])
            output.parent.mkdir(parents=True, exist_ok=True)
            # JPEG is derived from decoded pixels; original EXIF/GPS is never copied.
            with output.open("xb") as stream:
                image.save(stream, "JPEG", quality=95)
        return digest(output.read_bytes())
