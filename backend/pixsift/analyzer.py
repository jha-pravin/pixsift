"""Image understanding on ONNX Runtime: faces (YuNet + SFace) and picture type (OpenAI CLIP ViT-B/32, zero-shot).

On macOS the face-fingerprint model runs on the GPU/Neural Engine via Core ML, which leaves the CPU free for
decoding, face detection and CLIP. Everywhere else everything runs on the CPU. (Smaller CLIP-style models were
evaluated; the good ones are licensed for research only, which rules them out for PixSift.)
"""

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image

from . import facenet
from .decode import ANALYSIS_MAX_SIDE, decode
from .models import ModelStore

DATA = Path(__file__).parent / "data"
FACE_MIN_PX = 24
FACE_MIN_REL = 0.025  # face width relative to the longer image side; drops crowd/background faces
FACE_CROP_PX = 160
CLIP_SIZE = 224
_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)

# Prompts per picture type. A group's score is its best-matching prompt (max), which beats averaging
# for broad groups like "photo" whose prompts are deliberately diverse. Their embeddings are computed at
# build time (tools/build_model_assets.py) and shipped in data/; change both together.
CATEGORY_PROMPTS: dict[str, list[str]] = {
    "document": [
        "a scanned document with text", "a page of printed text", "a paper receipt",
        "an invoice or a form with text", "handwritten notes on paper", "a photo of a document on a table",
    ],
    "screenshot": [
        "a screenshot of a computer screen", "a screenshot of a phone app", "a screenshot of a website",
        "a screenshot of a chat conversation", "a screenshot of software user interface",
    ],
    "photo": [
        "a photo of a person", "a portrait photo", "a group photo of people", "a photo of a landscape",
        "a photo of food or drink", "a photo of an animal", "a photo of a city street", "a close-up photo of an object",
    ],
    "graphic": ["an illustration or drawing", "a logo", "a meme", "a poster design", "a cartoon"],
}

SCREENSHOT_NAME = re.compile(
    r"screen ?shot|screenshot|bildschirmfoto|capture d.?écran|schermafbeelding|captura de pantalla|snip", re.I
)


@dataclass
class FaceResult:
    box: tuple[float, float, float, float]  # normalised x, y, w, h
    score: float
    embedding: np.ndarray  # float32[128], unit length
    crop: Image.Image


@dataclass
class AnalysisResult:
    category: str
    scores: dict[str, float]
    clip_embedding: np.ndarray  # float16[512]
    faces: list[FaceResult]


def _session(path: Path, accelerate: bool = False, fixed: dict[str, int] | None = None) -> ort.InferenceSession:
    """CPU session, or Core ML (GPU/Neural Engine) on macOS for models verified to convert cleanly."""
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1  # pictures are analysed in parallel already
    opts.log_severity_level = 3
    for name, size in (fixed or {}).items():
        opts.add_free_dimension_override_by_name(name, size)  # Core ML needs static shapes
    if accelerate and sys.platform == "darwin" and "CoreMLExecutionProvider" in ort.get_available_providers():
        try:
            return ort.InferenceSession(str(path), opts, providers=[
                ("CoreMLExecutionProvider", {"MLComputeUnits": "ALL", "ModelFormat": "MLProgram"}),
                "CPUExecutionProvider"])
        except Exception:
            pass
    return ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])


class Analyzer:
    def __init__(self, models: ModelStore):
        self._clip = _session(models.path("clip_vision_quantized.onnx"))  # int8: fast on CPU, no gain on Core ML
        self._sface = _session(models.path("face_recognition_sface_2021dec.onnx"), accelerate=True)
        self._yunet = _session(DATA / "face_detection_yunet.onnx")  # Core ML can't convert it: CPU
        if json.loads((DATA / "prompts.json").read_text()) != CATEGORY_PROMPTS:
            raise RuntimeError("prompt embeddings are stale: run tools/build_model_assets.py")
        self._text_emb = np.load(DATA / "prompt_embeddings.npy")
        self._group_of_prompt = [g for g, items in CATEGORY_PROMPTS.items() for _ in items]

    # ---- picture type ------------------------------------------------------------------------------

    def _clip_embed(self, img: Image.Image) -> np.ndarray:
        w, h = img.size
        s = CLIP_SIZE / min(w, h)
        img = img.resize((max(CLIP_SIZE, round(w * s)), max(CLIP_SIZE, round(h * s))), Image.BICUBIC)
        left, top = (img.width - CLIP_SIZE) // 2, (img.height - CLIP_SIZE) // 2
        arr = np.asarray(img.crop((left, top, left + CLIP_SIZE, top + CLIP_SIZE)), dtype=np.float32) / 255.0
        arr = ((arr - _MEAN) / _STD).transpose(2, 0, 1)[None]
        return _unit(self._clip.run(None, {"pixel_values": arr})[0])[0]

    def classify(self, emb: np.ndarray, *, filename: str, camera: bool, face_rel: float = 0.0
                 ) -> tuple[str, dict[str, float]]:
        """face_rel: width of the largest face relative to the image (0 when none)."""
        sims = self._text_emb @ emb
        best = {g: max(float(s) for gg, s in zip(self._group_of_prompt, sims) if gg == g) for g in CATEGORY_PROMPTS}
        logits = np.array(list(best.values())) * 100.0
        probs = np.exp(logits - logits.max())
        scores = dict(zip(best, (probs / probs.sum()).tolist()))
        # Metadata hints.
        if SCREENSHOT_NAME.search(filename):
            scores["screenshot"] += 1.0
        if camera:  # camera EXIF: a real photo (possibly *of* a document), never a screenshot
            scores["screenshot"] *= 0.1
            scores["document"] *= 0.7
        if face_rel >= 0.1:  # a prominent face is a photo of people, not a document or UI
            scores["photo"] += 0.5
        total = sum(scores.values())
        scores = {k: round(v / total, 4) for k, v in scores.items()}
        return max(scores, key=scores.__getitem__), scores

    # ---- faces ------------------------------------------------------------------------------------

    def detect_faces(self, img: Image.Image) -> list[FaceResult]:
        rgb = np.asarray(img.convert("RGB"))
        h, w = rgb.shape[:2]
        results = []
        for row in facenet.detect(self._yunet, rgb):
            x, y, fw, fh = (float(v) for v in row[:4])
            if fw < FACE_MIN_PX or fw < FACE_MIN_REL * max(w, h):
                continue
            results.append(FaceResult(
                box=(max(0.0, x / w), max(0.0, y / h), min(fw / w, 1.0), min(fh / h, 1.0)),
                score=float(row[14]),
                embedding=facenet.embed(self._sface, facenet.align(rgb, row[4:14])),
                crop=_square_crop(img, x, y, fw, fh),
            ))
        return results

    # ---- combined ---------------------------------------------------------------------------------

    def analyze(self, path: str, *, filename: str, camera: bool) -> AnalysisResult:
        return self.analyze_image(decode(path, ANALYSIS_MAX_SIDE), filename=filename, camera=camera)

    def analyze_image(self, img: Image.Image, *, filename: str, camera: bool) -> AnalysisResult:
        """Analyse an already-decoded picture (the scan decodes each file once for thumbnail + analysis)."""
        faces = self.detect_faces(img)
        emb = self._clip_embed(img)
        face_rel = max((f.box[2] for f in faces), default=0.0)
        category, scores = self.classify(emb, filename=filename, camera=camera, face_rel=face_rel)
        return AnalysisResult(category, scores, emb.astype(np.float16), faces)


def _square_crop(img: Image.Image, x: float, y: float, w: float, h: float) -> Image.Image:
    """Face thumbnail with some context around the box, clamped to the image."""
    side = max(w, h) * 1.6
    cx, cy = x + w / 2, y + h / 2
    left, top = max(0, cx - side / 2), max(0, cy - side / 2)
    right, bottom = min(img.width, cx + side / 2), min(img.height, cy + side / 2)
    crop = img.crop((round(left), round(top), round(right), round(bottom)))
    crop.thumbnail((FACE_CROP_PX, FACE_CROP_PX))
    return crop


def _unit(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)


def save_crop(crop: Image.Image, thumbs_dir: Path, rel: str) -> None:
    out = thumbs_dir / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    crop.save(out, "WEBP", quality=82)
