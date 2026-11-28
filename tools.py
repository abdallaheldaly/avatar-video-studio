"""Small cross-platform helpers (ffmpeg discovery, platform checks)."""
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def ensure_ffmpeg():
    """Return the path of an ffmpeg binary, adding it to PATH.
    Uses the system ffmpeg if present, otherwise the static binary bundled in `imageio-ffmpeg`."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None
    d = HERE / ".bin"
    d.mkdir(exist_ok=True)
    dst = d / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if not dst.exists():
        shutil.copy(exe, dst)
        dst.chmod(0o755)
    os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
    return str(dst)


def is_mac():
    return sys.platform == "darwin"


def cpu_count():
    return os.cpu_count() or 2
