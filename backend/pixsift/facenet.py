"""Face detection (YuNet) and face fingerprints (SFace) on ONNX Runtime, without OpenCV.

This reproduces what OpenCV's FaceDetectorYN / FaceRecognizerSF do around the same two models (output
decoding, NMS, 5-point alignment), so embeddings are compatible with faces analysed by earlier versions.
"""

import numpy as np
import onnxruntime as ort

STRIDES = (8, 16, 32)
SCORE_MIN = 0.85
NMS_IOU = 0.3
TOP_K = 5000

# Where SFace expects the eyes, nose tip and mouth corners in its 112x112 input.
_SFACE_TEMPLATE = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                            [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float64)


def detect(session: ort.InferenceSession, rgb: np.ndarray, score_min: float = SCORE_MIN) -> np.ndarray:
    """Faces in an RGB uint8 image as rows [x, y, w, h, 5 landmark (x, y) pairs, score] in pixels."""
    h, w = rgb.shape[:2]
    ph, pw = -(-h // 32) * 32, -(-w // 32) * 32  # pad to a multiple of 32, like OpenCV
    blob = np.zeros((1, 3, ph, pw), np.float32)
    blob[0, :, :h, :w] = rgb[:, :, ::-1].transpose(2, 0, 1)  # BGR, 0..255
    outs = dict(zip([o.name for o in session.get_outputs()], session.run(None, {"input": blob})))
    rows = []
    for s in STRIDES:
        cols = pw // s
        cls = np.clip(outs[f"cls_{s}"][0, :, 0], 0, 1)
        obj = np.clip(outs[f"obj_{s}"][0, :, 0], 0, 1)
        score = np.sqrt(cls * obj)
        keep = np.flatnonzero(score >= score_min)
        if not len(keep):
            continue
        r, c = np.divmod(keep, cols)
        box = outs[f"bbox_{s}"][0, keep]
        kps = outs[f"kps_{s}"][0, keep].reshape(-1, 5, 2)
        cx, cy = (c + box[:, 0]) * s, (r + box[:, 1]) * s
        bw, bh = np.exp(box[:, 2]) * s, np.exp(box[:, 3]) * s
        lm = (kps + np.stack([c, r], axis=1)[:, None, :]) * s
        rows.append(np.column_stack([cx - bw / 2, cy - bh / 2, bw, bh, lm.reshape(-1, 10), score[keep]]))
    if not rows:
        return np.zeros((0, 15), np.float32)
    faces = np.concatenate(rows).astype(np.float32)
    return faces[_nms(faces[:, :4], faces[:, 14])][:TOP_K]


def _nms(boxes: np.ndarray, scores: np.ndarray) -> np.ndarray:
    order = np.argsort(-scores)
    x1, y1 = boxes[:, 0], boxes[:, 1]
    x2, y2 = x1 + boxes[:, 2], y1 + boxes[:, 3]
    area = boxes[:, 2] * boxes[:, 3]
    keep = []
    while len(order):
        i, rest = order[0], order[1:]
        keep.append(i)
        iw = np.clip(np.minimum(x2[i], x2[rest]) - np.maximum(x1[i], x1[rest]), 0, None)
        ih = np.clip(np.minimum(y2[i], y2[rest]) - np.maximum(y1[i], y1[rest]), 0, None)
        inter = iw * ih
        order = rest[inter / (area[i] + area[rest] - inter + 1e-9) <= NMS_IOU]
    return np.array(keep, dtype=np.int64)


def _similarity(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """2x3 similarity transform (rotation, uniform scale, shift) mapping src points onto dst (Umeyama)."""
    mu_s, mu_d = src.mean(0), dst.mean(0)
    s, d = src - mu_s, dst - mu_d
    u, sig, vt = np.linalg.svd(d.T @ s / len(src))
    sign = np.diag([1.0, np.sign(np.linalg.det(u @ vt)) or 1.0])
    rot = u @ sign @ vt
    scale = (sig * np.diag(sign)).sum() / (s ** 2).sum(axis=1).mean()
    return np.column_stack([scale * rot, mu_d - scale * rot @ mu_s])


def align(rgb: np.ndarray, landmarks: np.ndarray, size: int = 112) -> np.ndarray:
    """Warp the face so eyes/nose/mouth land on SFace's template (bilinear, black outside), like
    cv2.warpAffine(..., INTER_LINEAR)."""
    m = _similarity(landmarks.reshape(5, 2).astype(np.float64), _SFACE_TEMPLATE)
    inv = np.linalg.inv(np.vstack([m, [0, 0, 1]]))[:2]
    ys, xs = np.mgrid[0:size, 0:size]
    sx = inv[0, 0] * xs + inv[0, 1] * ys + inv[0, 2]
    sy = inv[1, 0] * xs + inv[1, 1] * ys + inv[1, 2]
    x0, y0 = np.floor(sx).astype(int), np.floor(sy).astype(int)
    fx, fy = (sx - x0)[..., None], (sy - y0)[..., None]
    h, w = rgb.shape[:2]
    padded = np.zeros((h + 2, w + 2, 3), np.float32)
    padded[1:-1, 1:-1] = rgb
    def px(yy, xx):  # sample with a 1-pixel black border, clamped beyond it
        return padded[np.clip(yy + 1, 0, h + 1), np.clip(xx + 1, 0, w + 1)]
    top = px(y0, x0) * (1 - fx) + px(y0, x0 + 1) * fx
    bottom = px(y0 + 1, x0) * (1 - fx) + px(y0 + 1, x0 + 1) * fx
    return top * (1 - fy) + bottom * fy  # float RGB 0..255, (size, size, 3)


def embed(session: ort.InferenceSession, aligned_rgb: np.ndarray) -> np.ndarray:
    """SFace fingerprint (128 floats, unit length) of an aligned 112x112 RGB face."""
    v = session.run(None, {"data": aligned_rgb.transpose(2, 0, 1)[None].astype(np.float32)})[0][0]
    return v / max(float(np.linalg.norm(v)), 1e-12)

