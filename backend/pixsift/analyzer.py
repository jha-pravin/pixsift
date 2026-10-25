"""Image understanding: face detection + embeddings (OpenCV YuNet/SFace) and picture type (CLIP zero-shot)."""

import re
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
from PIL import Image
from tokenizers import Tokenizer

from .decode import ANALYSIS_MAX_SIDE, decode
from .models import ModelStore

cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
cv2.setNumThreads(1)  # pictures are analysed in parallel already; nested OpenCV threads only oversubscribe the CPU

FACE_DETECT_MAX_SIDE = 960  # detection input: ~45% less work than 1280, keeps faces down to ~24 px
FACE_SCORE_MIN = 0.85
FACE_MIN_PX = 24
FACE_MIN_REL = 0.025  # face width relative to the longer image side; drops crowd/background faces
FACE_CROP_PX = 160

# Prompts per picture type. A group's score is its best-matching prompt (max), which beats averaging
# for broad groups like "photo" whose prompts are deliberately diverse.
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
CATEGORIES = (*CATEGORY_PROMPTS, "people")

SCREENSHOT_NAME = re.compile(
    r"screen ?shot|screenshot|bildschirmfoto|capture d.?écran|schermafbeelding|captura de pantalla|snip", re.I
)

_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)


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


def load_rgb(path: str, max_side: int = ANALYSIS_MAX_SIDE) -> Image.Image:
    return decode(path, max_side)


class Analyzer:
    def __init__(self, models: ModelStore, threads: int = 2):
        self.models = models
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.log_severity_level = 3
        self._vision = ort.InferenceSession(str(models.path("clip_vision_quantized.onnx")), opts,
                                            providers=["CPUExecutionProvider"])
        self._vision_input = self._vision.get_inputs()[0].name
        self._vision_output = _pick_output(self._vision, "image_embeds")
        self._local = threading.local()  # OpenCV face models are not thread-safe
        self._group_of_prompt, self._text_emb = self._encode_prompts(opts)

    # ---- CLIP -------------------------------------------------------------------------------------

    def _encode_prompts(self, opts: ort.SessionOptions) -> tuple[list[str], np.ndarray]:
        tok = Tokenizer.from_file(str(self.models.path("clip_tokenizer.json")))
        eos = tok.token_to_id("<|endoftext|>")
        groups, prompts = [], []
        for group, items in CATEGORY_PROMPTS.items():
            groups += [group] * len(items)
            prompts += items
        ids = [tok.encode(p).ids for p in prompts]
        width = max(map(len, ids))
        # Pad with EOS: CLIP pools at the first EOS (argmax of ids), so padding doesn't change the result.
        batch = np.array([i + [eos] * (width - len(i)) for i in ids], dtype=np.int64)
        text = ort.InferenceSession(str(self.models.path("clip_text_quantized.onnx")), opts,
                                    providers=["CPUExecutionProvider"])
        feeds = {"input_ids": batch}
        if "attention_mask" in {i.name for i in text.get_inputs()}:
            feeds["attention_mask"] = np.array([[1] * len(i) + [0] * (width - len(i)) for i in ids], dtype=np.int64)
        emb = text.run([_pick_output(text, "text_embeds")], feeds)[0]
        return groups, _unit(emb)

    def _clip_embed(self, img: Image.Image) -> np.ndarray:
        w, h = img.size
        s = 224 / min(w, h)
        img = img.resize((max(224, round(w * s)), max(224, round(h * s))), Image.BICUBIC)
        left, top = (img.width - 224) // 2, (img.height - 224) // 2
        arr = np.asarray(img.crop((left, top, left + 224, top + 224)), dtype=np.float32) / 255.0
        arr = ((arr - _MEAN) / _STD).transpose(2, 0, 1)[None]
        return _unit(self._vision.run([self._vision_output], {self._vision_input: arr})[0])[0]

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

    # ---- Faces ------------------------------------------------------------------------------------

    def _face_models(self) -> tuple[cv2.FaceDetectorYN, cv2.FaceRecognizerSF]:
        if not hasattr(self._local, "det"):
            self._local.det = cv2.FaceDetectorYN.create(
                str(self.models.path("face_detection_yunet_2023mar.onnx")), "", (320, 320), FACE_SCORE_MIN, 0.3, 5000
            )
            self._local.rec = cv2.FaceRecognizerSF.create(
                str(self.models.path("face_recognition_sface_2021dec.onnx")), ""
            )
        return self._local.det, self._local.rec

    def detect_faces(self, img: Image.Image) -> list[FaceResult]:
        det, rec = self._face_models()
        small = img
        if max(img.size) > FACE_DETECT_MAX_SIDE:
            small = img.copy()
            small.thumbnail((FACE_DETECT_MAX_SIDE, FACE_DETECT_MAX_SIDE))
        bgr = cv2.cvtColor(np.asarray(small), cv2.COLOR_RGB2BGR)
        h, w = bgr.shape[:2]
        sx, sy = img.width / w, img.height / h  # crops are cut from the full-size image
        det.setInputSize((w, h))
        _, rows = det.detect(bgr)
        results = []
        for row in rows if rows is not None else []:
            x, y, fw, fh = (float(v) for v in row[:4])
            if fw < FACE_MIN_PX or fw < FACE_MIN_REL * max(w, h):
                continue
            aligned = rec.alignCrop(bgr, row)
            emb = _unit(rec.feature(aligned).astype(np.float32))[0]
            results.append(FaceResult(
                box=(max(0.0, x / w), max(0.0, y / h), min(fw / w, 1.0), min(fh / h, 1.0)),
                score=float(row[-1]),
                embedding=emb,
                crop=_square_crop(img, x * sx, y * sy, fw * sx, fh * sy),
            ))
        return results

    # ---- Combined ---------------------------------------------------------------------------------

    def analyze(self, path: str, *, filename: str, camera: bool) -> AnalysisResult:
        return self.analyze_image(load_rgb(path), filename=filename, camera=camera)

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


def _pick_output(sess: ort.InferenceSession, preferred: str) -> str:
    names = [o.name for o in sess.get_outputs()]
    return preferred if preferred in names else names[0]


def save_crop(crop: Image.Image, thumbs_dir: Path, rel: str) -> None:
    out = thumbs_dir / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    crop.save(out, "WEBP", quality=82)
