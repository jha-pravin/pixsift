"""Per-file work: quick hash, EXIF metadata and thumbnail, all from a single image open."""

import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()
Image.MAX_IMAGE_PIXELS = 200_000_000  # allow big panoramas, still guard against decompression bombs

_CHUNK = 1 << 20  # 1 MiB
_EXIF_IFD = ExifTags.IFD.Exif
_GPS_IFD = ExifTags.IFD.GPSInfo
_T = ExifTags.Base
_G = ExifTags.GPS


def quick_hash(path: str, size: int) -> str:
    """blake2b over size + first and last MiB. Cheap on huge files, good enough to flag duplicates."""
    h = hashlib.blake2b(digest_size=16)
    h.update(size.to_bytes(8, "little"))
    with open(path, "rb") as f:
        h.update(f.read(_CHUNK))
        if size > 2 * _CHUNK:
            f.seek(-_CHUNK, os.SEEK_END)
            h.update(f.read(_CHUNK))
    return h.hexdigest()


def _parse_exif_date(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip().replace("\x00", "")
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d"):
        try:
            return datetime.strptime(text[:19], fmt).isoformat()
        except ValueError:
            continue
    return None


def _dms_to_deg(dms: Any, ref: Any) -> float | None:
    try:
        d, m, s = (float(x) for x in dms)
    except (TypeError, ValueError):
        return None
    deg = d + m / 60 + s / 3600
    return -deg if str(ref).upper() in ("S", "W") else deg


def read_exif(img: Image.Image) -> dict[str, Any]:
    exif = img.getexif()
    if not exif:
        return {"has_exif": 0}
    sub = exif.get_ifd(_EXIF_IFD)
    gps = exif.get_ifd(_GPS_IFD)
    lat = lon = None
    if gps:
        lat = _dms_to_deg(gps.get(_G.GPSLatitude), gps.get(_G.GPSLatitudeRef))
        lon = _dms_to_deg(gps.get(_G.GPSLongitude), gps.get(_G.GPSLongitudeRef))
    taken = _parse_exif_date(sub.get(_T.DateTimeOriginal)) or _parse_exif_date(exif.get(_T.DateTime))
    make = (str(exif.get(_T.Make) or "").strip("\x00 ") or None)
    model = (str(exif.get(_T.Model) or "").strip("\x00 ") or None)
    return {
        "has_exif": 1,
        "taken_at": taken,
        "camera_make": make,
        "camera_model": model,
        "gps_lat": lat,
        "gps_lon": lon,
    }


def thumb_relpath(digest: str) -> str:
    return f"{digest[:2]}/{digest}.webp"


def process_file(path: str, size: int, mtime: float, thumbs_dir: Path, thumb_size: int) -> dict[str, Any]:
    """Build a full `images` row for one file. Never raises: failures are recorded in `error`."""
    p = Path(path)
    rec: dict[str, Any] = {
        "path": path, "folder": str(p.parent), "filename": p.name, "ext": p.suffix.lower(),
        "size": size, "mtime": mtime, "quick_hash": None, "width": None, "height": None,
        "taken_at": None, "camera_make": None, "camera_model": None, "gps_lat": None, "gps_lon": None,
        "has_exif": 0, "date_source": None, "thumb": None, "error": None,
    }
    try:
        digest = quick_hash(path, size)
        rec["quick_hash"] = digest
        with Image.open(path) as img:
            rec.update(read_exif(img))
            w, h = img.size  # from the header; no pixel decode yet
            if img.getexif().get(_T.Orientation) in (5, 6, 7, 8):
                w, h = h, w  # report dimensions as the user sees them
            rec["width"], rec["height"] = w, h
            rel = thumb_relpath(digest)
            out = thumbs_dir / rel
            if not out.exists():
                img.draft("RGB", (thumb_size * 2, thumb_size * 2))  # fast JPEG downscale on decode
                img = ImageOps.exif_transpose(img)
                img.thumbnail((thumb_size, thumb_size))
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
                out.parent.mkdir(parents=True, exist_ok=True)
                img.save(out, "WEBP", quality=80, method=4)
            rec["thumb"] = rel
    except Exception as exc:  # corrupt / unsupported files must not stop a scan
        rec["error"] = f"{type(exc).__name__}: {exc}"[:500]
    rec["date_source"] = "exif" if rec["taken_at"] else "file"
    if not rec["taken_at"]:
        # No EXIF date: fall back to file modification time so every image sits on the timeline.
        rec["taken_at"] = datetime.fromtimestamp(mtime).isoformat(timespec="seconds")
    return rec
