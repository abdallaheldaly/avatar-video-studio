# Avatar Video Studio - CPU image by default.  NVIDIA GPU:  docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
FROM python:3.11-slim-bookworm
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates git build-essential libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* && pip install uv
WORKDIR /app

# 1) app environment (Python 3.11): UI, Whisper, Chromium for the 3D scenes
COPY requirements.txt .
RUN uv venv --seed --python 3.11 .venv && uv pip install --python .venv/bin/python -r requirements.txt \
    && .venv/bin/python -m playwright install --with-deps chromium

# 2) MuseTalk environment (Python 3.10)
COPY third_party/MuseTalk/requirements.txt /tmp/mt_requirements.txt
RUN uv venv --seed --python 3.10 .venv-musetalk \
    && uv pip install --python .venv-musetalk/bin/python torch==2.2.2 torchvision==0.17.2 torchaudio==2.2.2 \
       --index-url ${TORCH_INDEX} --extra-index-url https://pypi.org/simple \
    && grep -v -i -E "^(tensorflow|tensorboard|gradio)" /tmp/mt_requirements.txt > /tmp/mt.txt \
    && uv pip install --python .venv-musetalk/bin/python -r /tmp/mt.txt

COPY . .
RUN chmod +x docker/entrypoint.sh
ENV GRADIO_SERVER_NAME=0.0.0.0 MUSETALK_PYTHON=/app/.venv-musetalk/bin/python
EXPOSE 7860
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["python", "studio.py", "run", "--no-ollama"]
