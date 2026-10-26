# Third-party components

| Model | Used for | Source | License | How it ships |
|-------|----------|--------|---------|--------------|
| YuNet (2023mar) | face detection | [OpenCV Zoo](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) | MIT | bundled (`backend/pixsift/data/face_detection_yunet.onnx`, input shape relaxed; weights unchanged) |
| SFace (2021dec) | face recognition | [OpenCV Zoo](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface) | Apache-2.0 | downloaded on first use |
| CLIP ViT-B/32, quantised ONNX | picture type | [Xenova/clip-vit-base-patch32](https://huggingface.co/Xenova/clip-vit-base-patch32), from [OpenAI CLIP](https://github.com/openai/CLIP) | MIT | image model downloaded on first use; text embeddings of the category prompts precomputed and bundled (`prompt_embeddings.npy`) |

`tools/build_model_assets.py` regenerates the bundled files.

Test images in `backend/tests/fixtures/` come from scikit-image's sample data: `astronaut.jpg` (NASA, public
domain), `cameraman.jpg` (CC0, Lav Varshney) and `page.jpg` (public domain).

Python and JavaScript dependencies are listed in `backend/pyproject.toml` and `frontend/package.json` and keep
their own licenses.
