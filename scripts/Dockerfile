# Python analysis service (FastAPI + CLIP + classifier). Put this file in the scripts/ folder.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/opt/hf

RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# torch AND torchvision together from the same CPU index, so their versions match.
# requirements.txt then sees both as already installed and does not replace them.
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r requirements.txt

# Download the CLIP weights NOW (build needs internet) so the running service never does
RUN python -c "import open_clip; open_clip.create_model_and_transforms('ViT-B-32', pretrained='laion2b_s34b_b79k')"
ENV HF_HUB_OFFLINE=1

COPY . .

# 0.0.0.0 is only reachable inside the private compose network: docker-compose.yml publishes NO port for this service
EXPOSE 8001
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8001"]