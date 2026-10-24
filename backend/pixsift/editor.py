"""Basic picture editing.

Operations apply in a fixed order: rotate/flip -> crop -> adjust, all in the orientation the user sees.
For JPEGs where only rotate/flip were requested, only the EXIF orientation tag is rewritten (lossless).
By default the result is saved as a new file next to the original; overwriting keeps a backup copy.
"""

import io
import shutil
import time
from pathlib import Path
from typing import Literal

from PIL import ExifTags, Image, ImageEnhance, ImageOps
from pydantic import BaseModel, Field, model_validator

ORIENTATION = ExifTags.Base.Orientation
SAVE_FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP", ".tif": "TIFF", ".tiff": "TIFF",
                ".bmp": "BMP", ".gif": "GIF"}


class Crop(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)


class EditRequest(BaseModel):
    rotate: Literal[0, 90, 180, 270] = 0  # clockwise
    flip_h: bool = False
    flip_v: bool = False
    crop: Crop | None = None  # normalised, after rotate/flip
    brightness: float = Field(1.0, ge=0.2, le=3.0)
    contrast: float = Field(1.0, ge=0.2, le=3.0)
    saturation: float = Field(1.0, ge=0.0, le=3.0)
    mode: Literal["copy", "overwrite"] = "copy"

    @model_validator(mode="after")
    def _check(self):
        if self.crop and (self.crop.x + self.crop.w > 1.0001 or self.crop.y + self.crop.h > 1.0001):
            raise ValueError("crop is outside the picture")
        return self

    @property
    def geometry_only(self) -> bool:
        return self.crop is None and (self.brightness, self.contrast, self.saturation) == (1.0, 1.0, 1.0)

    @property
    def is_noop(self) -> bool:
        return self.geometry_only and not (self.rotate or self.flip_h or self.flip_v)


def _transform(img: Image.Image, req: EditRequest) -> Image.Image:
    if req.rotate:
        img = img.rotate(-req.rotate, expand=True)  # PIL rotates counter-clockwise
    if req.flip_h:
        img = ImageOps.mirror(img)
    if req.flip_v:
        img = ImageOps.flip(img)
    return img


def _with_orientation(img: Image.Image, o: int) -> Image.Image:
    img = img.copy()
    img.getexif()[ORIENTATION] = o
    return img


def _new_orientation(current: int, req: EditRequest) -> int:
    """EXIF orientation that displays the raw pixels as `edit(current view)`.
    Found by applying both to a tiny probe image with unique pixels, so there's no lookup table to get wrong."""
    probe = Image.frombytes("L", (3, 2), bytes(range(6)))

    def key(img: Image.Image) -> tuple:
        return img.size, img.tobytes()

    target = key(_transform(ImageOps.exif_transpose(_with_orientation(probe, current)), req))
    for o in range(1, 9):
        if key(ImageOps.exif_transpose(_with_orientation(probe, o))) == target:
            return o
    raise RuntimeError("no matching orientation")


def _replace_jpeg_exif(data: bytes, exif: bytes) -> bytes:
    """Swap the APP1/Exif segment of a JPEG without touching the compressed image data."""
    payload = b"Exif\x00\x00" + exif if not exif.startswith(b"Exif") else exif
    segment = b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG")
    pos = 2
    insert_at = 2
    while pos + 4 <= len(data) and data[pos] == 0xFF:
        marker = data[pos + 1]
        if marker == 0xDA:  # start of scan: metadata segments are over
            break
        length = int.from_bytes(data[pos + 2:pos + 4], "big")
        end = pos + 2 + length
        if marker == 0xE1 and data[pos + 4:pos + 10] == b"Exif\x00\x00":
            return data[:pos] + segment + data[end:]
        if marker == 0xE0:  # keep JFIF APP0 first
            insert_at = end
        pos = end
    return data[:insert_at] + segment + data[insert_at:]


def output_path(src: Path) -> Path:
    for n in range(1, 1000):
        cand = src.with_name(f"{src.stem}_edited{'' if n == 1 else f'-{n}'}{src.suffix}")
        if not cand.exists():
            return cand
    raise FileExistsError("too many edited copies")


def apply_edit(src: str, req: EditRequest, backups_dir: Path) -> Path:
    """Write the edited picture and return its path."""
    src_path = Path(src)
    ext = src_path.suffix.lower()
    fmt = SAVE_FORMATS.get(ext)
    if fmt is None:  # HEIC etc.: save edits as JPEG
        ext, fmt = ".jpg", "JPEG"
    overwrite = req.mode == "overwrite" and ext == src_path.suffix.lower()  # HEIC edits always become a copy
    dest = src_path if overwrite else output_path(src_path.with_suffix(ext))
    if overwrite:
        backups_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, backups_dir / f"{int(time.time())}_{src_path.name}")

    if fmt == "JPEG" and ext == src_path.suffix.lower() and req.geometry_only:
        with Image.open(src_path) as img:
            exif = img.getexif()
        exif[ORIENTATION] = _new_orientation(exif.get(ORIENTATION, 1), req)
        # Written only after the source is closed: Windows can't replace a file that is open.
        _atomic_write(dest, _replace_jpeg_exif(src_path.read_bytes(), exif.tobytes()))
        return dest

    with Image.open(src_path) as img:
        exif = img.getexif()
        icc = img.info.get("icc_profile")

        out = _transform(ImageOps.exif_transpose(img), req)
        if req.crop:
            c = req.crop
            out = out.crop((round(c.x * out.width), round(c.y * out.height),
                            round((c.x + c.w) * out.width), round((c.y + c.h) * out.height)))
        if out.mode not in ("RGB", "RGBA", "L"):
            out = out.convert("RGBA" if "A" in out.getbands() else "RGB")
        if req.brightness != 1.0:
            out = ImageEnhance.Brightness(out).enhance(req.brightness)
        if req.contrast != 1.0:
            out = ImageEnhance.Contrast(out).enhance(req.contrast)
        if req.saturation != 1.0 and out.mode != "L":
            out = ImageEnhance.Color(out).enhance(req.saturation)
        exif[ORIENTATION] = 1  # pixels are now upright
        if fmt == "JPEG" and out.mode == "RGBA":
            out = out.convert("RGB")
        kwargs = {"exif": exif.tobytes()} if fmt in ("JPEG", "WEBP", "PNG", "TIFF") else {}
        if fmt == "JPEG":
            kwargs.update(quality=92, subsampling=0)
        if icc:
            kwargs["icc_profile"] = icc
        buf = io.BytesIO()
        out.save(buf, fmt, **kwargs)
    _atomic_write(dest, buf.getvalue())
    return dest


def _atomic_write(dest: Path, data: bytes) -> None:
    tmp = dest.with_name(dest.name + ".pixsift-tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)
