"""Build-time assets shipped inside PixSift (run when prompts or models change; not needed at runtime).

1. prompt_embeddings.npy: CLIP ViT-B/32 text embeddings (full-precision text model) for the picture-type
   prompts in analyzer.py, so the app needs neither the text model nor a tokenizer library at runtime.
2. face_detection_yunet.onnx: OpenCV Zoo's YuNet with its fixed 640x640 input relaxed to any size
   (ONNX Runtime enforces declared shapes; OpenCV didn't). Weights are unchanged.

Usage (needs: pip install onnx tokenizers):
    python tools/build_model_assets.py <dir with text_model.onnx + tokenizer.json> <yunet_2023mar.onnx>
    (text model + tokenizer: huggingface.co/Xenova/clip-vit-base-patch32, files onnx/text_model.onnx, tokenizer.json)
"""

import json
import sys
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
from tokenizers import Tokenizer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from pixsift.analyzer import CATEGORY_PROMPTS  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "backend" / "pixsift" / "data"


def prompts(clip_dir: Path) -> None:
    tok = Tokenizer.from_file(str(clip_dir / "tokenizer.json"))
    texts = [p for items in CATEGORY_PROMPTS.values() for p in items]
    eos = tok.token_to_id("<|endoftext|>")
    ids = [tok.encode(t).ids for t in texts]
    width = max(map(len, ids))
    # Pad with EOS: CLIP pools at the first EOS (argmax of ids), so padding doesn't change the result.
    batch = np.array([i + [eos] * (width - len(i)) for i in ids], dtype=np.int64)
    sess = ort.InferenceSession(str(clip_dir / "text_model.onnx"), providers=["CPUExecutionProvider"])
    emb = sess.run(None, {"input_ids": batch})[0]
    emb /= np.linalg.norm(emb, axis=1, keepdims=True)
    np.save(DATA / "prompt_embeddings.npy", emb.astype(np.float32))
    (DATA / "prompts.json").write_text(json.dumps(CATEGORY_PROMPTS, indent=1) + "\n")
    print(f"{len(texts)} prompt embeddings written")


def yunet(src: Path) -> None:
    m = onnx.load(str(src))
    dims = m.graph.input[0].type.tensor_type.shape.dim
    for d, name in ((dims[2], "height"), (dims[3], "width")):
        d.ClearField("dim_value")
        d.dim_param = name
    for out in m.graph.output:
        out.type.tensor_type.shape.dim[1].ClearField("dim_value")
        out.type.tensor_type.shape.dim[1].dim_param = "anchors"
    onnx.save(m, str(DATA / "face_detection_yunet.onnx"))
    print("YuNet with dynamic input written")


if __name__ == "__main__":
    prompts(Path(sys.argv[1]))
    yunet(Path(sys.argv[2]))
