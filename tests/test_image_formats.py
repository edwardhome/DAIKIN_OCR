import io

import pytest
from PIL import Image

from app.errors import AppError
from app.image import ImagePreprocessor, inspect_image


def phone_mpo():
    """An ordinary JPEG primary image plus an auxiliary MPF image, no user data."""
    first = Image.new("RGB", (300, 200), "red")
    auxiliary = Image.new("RGB", (30, 20), "blue")
    exif = Image.Exif()
    exif[274] = 6
    output = io.BytesIO()
    first.save(output, "MPO", save_all=True, append_images=[auxiliary], exif=exif)
    return output.getvalue()


def test_phone_multi_picture_jpeg_uses_primary_frame_and_preserves_original(tmp_path):
    content = phone_mpo()
    assert content.startswith(b"\xff\xd8")
    with Image.open(io.BytesIO(content)) as image:
        assert image.format == "MPO"
        assert image.n_frames == 2
    assert inspect_image(content, 100_000) == ("jpg", "image/jpeg")
    # Acceptance depends on decoded contents, even when a filename has no image suffix.
    original = tmp_path / "original.bin"
    original.write_bytes(content)
    output = tmp_path / "inference.jpg"
    ImagePreprocessor().process(
        original, output, {"max_edge": 512, "contrast": 1, "sharpness": 1}, 100_000
    )
    assert original.read_bytes() == content
    with Image.open(output) as image:
        assert image.format == "JPEG"
        assert getattr(image, "n_frames", 1) == 1
        assert image.size == (200, 300)  # Primary frame EXIF orientation was applied.
        red, green, blue = image.getpixel((100, 150))
        assert red > 240 and green < 15 and blue < 15
        assert not image.getexif()


def test_mpo_primary_frame_pixel_limit_cannot_be_bypassed_by_small_auxiliary():
    with pytest.raises(AppError) as error:
        inspect_image(phone_mpo(), 50_000)
    assert error.value.code == "IMAGE_TOO_LARGE"


def test_new_mpo_support_still_rejects_other_multiframe_formats(tmp_path):
    payload = io.BytesIO()
    Image.new("RGB", (30, 20), "red").save(
        payload, "GIF", save_all=True, append_images=[Image.new("RGB", (30, 20), "blue")]
    )
    original = tmp_path / "misleading.jpeg"
    original.write_bytes(payload.getvalue())
    with pytest.raises(AppError) as error:
        ImagePreprocessor().process(
            original,
            tmp_path / "inference.jpg",
            {"max_edge": 512, "contrast": 1, "sharpness": 1},
            100_000,
        )
    assert error.value.code == "UNSUPPORTED_FORMAT"
