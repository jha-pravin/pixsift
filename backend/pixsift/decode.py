"""Decode a picture once, already downscaled and upright, as RGB.

On macOS this uses Apple's ImageIO, which decodes HEIC/JPEG with the hardware media engine and can produce a
downscaled image directly. That's ~3-4x faster than Pillow for iPhone HEIC photos. Everywhere else, or for
files ImageIO can't read, Pillow is used.
"""

import sys

import numpy as np
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()

ANALYSIS_MAX_SIDE = 960  # one decode at this size feeds the thumbnail, face detection, crops and models

try:  # pyobjc's Quartz bindings ship with the macOS desktop dependencies
    if sys.platform != "darwin":
        raise ImportError
    import Quartz
except ImportError:
    Quartz = None


def _imageio(path: str, max_side: int) -> Image.Image | None:
    url = Quartz.NSURL.fileURLWithPath_(path)
    src = Quartz.CGImageSourceCreateWithURL(url, None)
    if src is None:
        return None
    opts = {
        Quartz.kCGImageSourceCreateThumbnailFromImageAlways: True,  # never use a tiny embedded preview
        Quartz.kCGImageSourceThumbnailMaxPixelSize: max_side,
        Quartz.kCGImageSourceCreateThumbnailWithTransform: True,    # apply EXIF orientation
        Quartz.kCGImageSourceShouldCacheImmediately: True,
    }
    cg = Quartz.CGImageSourceCreateThumbnailAtIndex(src, 0, opts)
    if cg is None:
        return None
    w, h = Quartz.CGImageGetWidth(cg), Quartz.CGImageGetHeight(cg)
    ctx = Quartz.CGBitmapContextCreate(None, w, h, 8, w * 4, Quartz.CGColorSpaceCreateDeviceRGB(),
                                       Quartz.kCGImageAlphaPremultipliedLast)
    # Transparent areas (PNG screenshots, graphics) become white, like the Pillow path.
    Quartz.CGContextSetRGBFillColor(ctx, 1, 1, 1, 1)
    Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, w, h))
    Quartz.CGContextDrawImage(ctx, Quartz.CGRectMake(0, 0, w, h), cg)
    data = Quartz.CGBitmapContextGetData(ctx)
    rgba = np.frombuffer(data.as_buffer(w * h * 4), dtype=np.uint8).reshape(h, w, 4)
    return Image.fromarray(np.ascontiguousarray(rgba[:, :, :3]))


def _pillow(path: str, max_side: int) -> Image.Image:
    with Image.open(path) as img:
        img.draft("RGB", (max_side, max_side))  # JPEG: decode at reduced size
        img = ImageOps.exif_transpose(img)
        img.thumbnail((max_side, max_side))
        if img.mode in ("RGBA", "LA", "P") and ("A" in img.getbands() or "transparency" in img.info):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, "white")
            bg.paste(img, mask=img.split()[3])
            return bg
        return img.convert("RGB")


def decode(path: str, max_side: int) -> Image.Image:
    """Upright RGB image whose longer side is at most max_side. Raises if the file can't be decoded."""
    if Quartz is not None and not path.lower().endswith(".gif"):  # GIFs: Pillow handles frames/palettes well
        try:
            img = _imageio(path, max_side)
            if img is not None:
                return img
        except Exception:
            pass  # fall back to Pillow
    return _pillow(path, max_side)
