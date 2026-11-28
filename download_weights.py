"""Download all MuseTalk weights from their official sources into third_party/MuseTalk/models.
Run it with the MuseTalk environment python:  .venv-musetalk/bin/python download_weights.py"""
import os, sys, urllib.request
from pathlib import Path
from huggingface_hub import hf_hub_download

MT = Path(__file__).resolve().parent / "third_party" / "MuseTalk"
M = MT / "models"
os.chdir(MT)

def hf(repo, files, sub=""):
    for f in files:
        print("->", repo, f)
        hf_hub_download(repo, f, local_dir=str(M / sub))

hf("TMElyralab/MuseTalk", ["musetalk/musetalk.json", "musetalk/pytorch_model.bin",
                          "musetalkV15/musetalk.json", "musetalkV15/unet.pth"])
hf("stabilityai/sd-vae-ft-mse", ["config.json", "diffusion_pytorch_model.bin"], "sd-vae")
hf("openai/whisper-tiny", ["config.json", "pytorch_model.bin", "preprocessor_config.json"], "whisper")
hf("yzd-v/DWPose", ["dw-ll_ucoco_384.pth"], "dwpose")          # only needed with mmpose
hf("ByteDance/LatentSync", ["latentsync_syncnet.pt"], "syncnet")

fp = M / "face-parse-bisent"; fp.mkdir(parents=True, exist_ok=True)
if not (fp / "resnet18-5c106cde.pth").exists():
    urllib.request.urlretrieve("https://download.pytorch.org/models/resnet18-5c106cde.pth", fp / "resnet18-5c106cde.pth")
if not (fp / "79999_iter.pth").exists():
    import gdown
    gdown.download(id="154JgKpzCPW82qINcVieuPH3fZ2e0P812", output=str(fp / "79999_iter.pth"))

# S3FD face detector (MuseTalk would fetch it at run time; we keep it locally)
s3 = MT / "musetalk/utils/face_detection/detection/sfd/s3fd.pth"
if not s3.exists():
    urllib.request.urlretrieve("https://www.adrianbulat.com/downloads/python-fan/s3fd-619a316812.pth", s3)
print("\nDone. Weights are in:", M, "- keep a backup copy.")
