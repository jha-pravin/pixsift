"""On-device ML models: downloaded once into the data dir, then used fully offline."""

import hashlib
import os
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModelFile:
    name: str
    url: str
    size: int
    sha256: str  # pinned: a changed or tampered upstream file is rejected
    purpose: str


MODELS = (
    ModelFile("face_recognition_sface_2021dec.onnx",
              "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
              38_696_353, "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79", "face recognition"),
    ModelFile("clip_vision_quantized.onnx",
              "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/onnx/vision_model_quantized.onnx",
              89_117_001, "583fd1110a514667812fee7d684952aaf82a99b959760c8d7dca7e0ab9839299", "picture type"),
)
# Face detection (YuNet, 233 KB) and the picture-type prompt embeddings ship inside the app (pixsift/data).

# Files earlier versions downloaded that are no longer needed (prompt embeddings and the face detector now
# ship with the app); removed to free ~67 MB.
OBSOLETE = ("clip_text_quantized.onnx", "clip_tokenizer.json", "face_detection_yunet_2023mar.onnx",
            "mobileclip_s0_vision.onnx")


class ModelStore:
    def __init__(self, models_dir: Path):
        self.dir = models_dir
        self._lock = threading.Lock()
        self.downloading: str | None = None
        self.downloaded_bytes = 0

    def path(self, name: str) -> Path:
        return self.dir / name

    def missing(self) -> list[ModelFile]:
        return [m for m in MODELS if not self._ok(m)]

    def _ok(self, m: ModelFile) -> bool:
        p = self.path(m.name)
        return p.is_file() and p.stat().st_size == m.size  # size check is cheap; sha256 verified on download

    def status(self) -> dict:
        return {
            "ready": not self.missing(),
            "total_bytes": sum(m.size for m in MODELS),
            "missing_bytes": sum(m.size for m in self.missing()),
            "downloading": self.downloading,
            "downloaded_bytes": self.downloaded_bytes,
        }

    def ensure(self, cancel: threading.Event | None = None) -> None:
        """Download any missing model files (atomic rename, so a partial file is never used)."""
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            for name in OBSOLETE:
                self.path(name).unlink(missing_ok=True)
            for m in self.missing():
                if cancel is not None and cancel.is_set():
                    return
                self.downloading, self.downloaded_bytes = m.name, 0
                tmp = self.path(m.name + ".part")
                try:
                    req = urllib.request.Request(m.url, headers={"User-Agent": "PixSift"})
                    digest = hashlib.sha256()
                    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                        while chunk := r.read(1 << 20):
                            if cancel is not None and cancel.is_set():
                                return
                            f.write(chunk)
                            digest.update(chunk)
                            self.downloaded_bytes += len(chunk)
                    if digest.hexdigest() != m.sha256:
                        raise OSError(f"{m.name}: checksum mismatch, download rejected")
                    os.replace(tmp, self.path(m.name))
                finally:
                    tmp.unlink(missing_ok=True)
                    self.downloading = None
