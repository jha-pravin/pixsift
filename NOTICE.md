# Third-party components

PixSift downloads these models on first use. They are not included in this repository or in the app builds.

| Model | Used for | Source | License |
|-------|----------|--------|---------|
| YuNet (2023mar) | face detection | [OpenCV Zoo](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) | MIT |
| SFace (2021dec) | face recognition | [OpenCV Zoo](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface) | Apache-2.0 |
| CLIP ViT-B/32, quantised ONNX | picture type | [Xenova/clip-vit-base-patch32](https://huggingface.co/Xenova/clip-vit-base-patch32), from [OpenAI CLIP](https://github.com/openai/CLIP) | MIT |

Test images in `backend/tests/fixtures/` come from scikit-image's sample data: `astronaut.jpg` (NASA, public
domain), `cameraman.jpg` (CC0, Lav Varshney) and `page.jpg` (public domain).

Python and JavaScript dependencies are listed in `backend/pyproject.toml` and `frontend/package.json` and keep
their own licenses.
