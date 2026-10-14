import io

from PIL import Image

from dam.enrichment import images


def _jpeg(w=3000, h=2000, exif=None) -> bytes:
    img = Image.new("RGB", (w, h), (200, 120, 60))
    buf = io.BytesIO()
    kwargs = {"format": "JPEG"}
    if exif is not None:
        kwargs["exif"] = exif
    img.save(buf, **kwargs)
    return buf.getvalue()


def test_probe_reads_dimensions_and_capture_time():
    exif = Image.Exif()
    exif[0x0132] = "2025:06:01 10:30:00"  # DateTime
    exif[0x010F] = "TestCam"  # Make
    data = _jpeg(exif=exif.tobytes())
    info = images.probe(data)
    assert (info.width, info.height) == (3000, 2000)
    assert info.captured_at is not None and info.captured_at.year == 2025
    assert info.exif["Make"] == "TestCam"
    assert info.has_gps is False


def test_derive_resizes_and_strips_metadata():
    exif = Image.Exif()
    exif[0x010F] = "TestCam"
    out = images.derive(_jpeg(exif=exif.tobytes()))
    preview, pw, ph = out["preview"]
    thumb, tw, th = out["thumb"]
    assert (pw, ph) == (1600, 1067) and (tw, th) == (256, 171)
    for blob in (preview, thumb):
        with Image.open(io.BytesIO(blob)) as img:
            assert img.format == "WEBP"
            assert dict(img.getexif()) == {}


def test_derive_handles_small_images_without_upscaling():
    out = images.derive(_jpeg(100, 80))
    assert out["preview"][1:] == (100, 80)
    assert out["thumb"][1:] == (100, 80)
