"""The fast macOS decoder (ImageIO) must give the same upright picture as the Pillow fallback."""

import numpy as np
import pytest
from PIL import Image

from pixsift import decode as D

pytestmark = pytest.mark.skipif(D.Quartz is None, reason="ImageIO is macOS-only")


def make(path, orientation=None, mode="RGB"):
    img = Image.new(mode, (300, 200), (200, 40, 40, 255) if mode == "RGBA" else (200, 40, 40))
    img.paste((40, 40, 200) if mode == "RGB" else (40, 40, 200, 255), (0, 0, 150, 100))  # blue top-left corner
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    if path.suffix == ".png":
        img.save(path)
    else:
        img.save(path, quality=95, exif=exif)
    return path


@pytest.mark.parametrize("orientation", [None, 3, 6, 8])
def test_imageio_matches_pillow_including_rotation(tmp_path, orientation):
    p = make(tmp_path / "a.jpg", orientation)
    fast, slow = D._imageio(str(p), 1280), D._pillow(str(p), 1280)
    assert fast.size == slow.size
    diff = np.abs(np.asarray(fast, np.int16) - np.asarray(slow, np.int16)).mean()
    assert diff < 6  # same pixels up to colour management / JPEG decoder rounding


def test_downscales_and_flattens_transparency(tmp_path):
    img = Image.new("RGBA", (3000, 1000), (0, 0, 0, 0))
    img.save(tmp_path / "t.png")
    out = D.decode(str(tmp_path / "t.png"), 1280)
    assert out.size == (1280, 427) and out.mode == "RGB"
    assert np.asarray(out).min() > 240  # transparent -> white
