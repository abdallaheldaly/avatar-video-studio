# Third-party components

Everything here is open source and runs locally. Check each license before commercial use.

## Included in this folder
| Component | Location | License |
|---|---|---|
| MuseTalk (commit 2536eaf, 2026-11-19) | `third_party/MuseTalk` | MIT (code). Weights: the README states any use incl. commercial; its NOTICE says they were trained on HDTF and private data and recommends checking with the HDTF owner before commercial use |
| SadTalker (commit cd4c046, 2023-10-11), optional backend | `third_party/SadTalker` | Apache 2.0, with third-party components excluded as stated in its LICENSE |
| three.js r128 | `vendor/three.min.js` | MIT |
| Cairo font (via @fontsource/cairo 5.3.0) | `vendor/fonts` | SIL OFL 1.1 |
| Lucide icons (lucide-static 1.77.0) | `vendor/icons/lucide` | ISC |

Example folders and demo icons/SVGs in `examples/` are generated from the above; `examples/avatar_placeholder.png` is a drawing made for this project.

## Installed by `studio setup` (not copied here)
| Component | License |
|---|---|
| Ollama (local model server) | MIT |
| Qwen3 language models (downloaded by Ollama) | Apache 2.0 |
| faster-whisper / CTranslate2 | MIT |
| Whisper model weights (OpenAI) | MIT |
| Gradio | Apache 2.0 |
| Playwright / Chromium | Apache 2.0 / BSD-style |
| ffmpeg (static build via `imageio-ffmpeg`, or your system ffmpeg) | GPL/LGPL builds |
| PyTorch, diffusers, transformers, OpenCV, librosa, ... (MuseTalk environment) | BSD / Apache 2.0 / MIT |

## Optional
| Component | License |
|---|---|
| XTTS-v2 voice cloning (`pip install coqui-tts`) | model weights under the Coqui Public Model License, which to my knowledge is non-commercial |

## Local changes to MuseTalk
Marked with `[local patch]`: `scripts/inference.py` (device chosen from cuda / mps / cpu via `MUSETALK_DEVICE`) and
`musetalk/utils/preprocessing.py` (mmpose is optional; without it the face detector's box is used). The rest is unchanged.
Example/docs folders of MuseTalk and SadTalker were removed to save space; their LICENSE files are kept.
