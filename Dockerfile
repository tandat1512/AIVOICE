# SmartGen — FastAPI WebSocket server
#
# CPU build (default):
#   docker build -t smartgen .
#
# GPU build (requires NVIDIA Container Toolkit + cuDNN 9):
#   docker build --build-arg BASE=nvidia/cuda:12.1.1-cudnn9-runtime-ubuntu22.04 \
#                --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu121 \
#                -t smartgen-gpu .

ARG BASE=python:3.11-slim
FROM ${BASE}

WORKDIR /app

# System deps: ffmpeg (audio codecs used by soundfile / kokoro-onnx)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps before copying source (layer caching)
COPY requirements.txt .
ARG TORCH_INDEX=""
RUN if [ -n "$TORCH_INDEX" ]; then \
      pip install --no-cache-dir torch==2.3.1 --index-url "$TORCH_INDEX"; \
    fi && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY server/ ./server/
COPY web/ ./web/  # Static UI assets served by FastAPI StaticFiles mount

# Models are volume-mounted at runtime (./models → /app/models)
# to avoid baking multi-GB model files into the image.

EXPOSE 8000

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    KMP_DUPLICATE_LIB_OK=TRUE \
    STT_BACKEND=sherpa \
    ONNX_PROVIDER=CPUExecutionProvider

CMD ["python", "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
