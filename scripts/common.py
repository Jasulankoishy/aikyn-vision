"""Shared helpers for train.py and analyze.py."""
import base64
import sys

import cv2
import numpy as np
from PIL import Image

SAMPLE_FPS = 2.0     # frames per second analysed (raise for fast actions, costs time)
MAX_W = 800          # downscale width: keeps memory sane (145 s * 2 fps ~ 290 frames)


def log(*args):
    print(*args, file=sys.stderr, flush=True)


def sample_frames(path, fps=SAMPLE_FPS):
    """Return [(time_sec, bgr_frame), ...] sampled at ~fps."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {path}")
    native = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(native / fps))
    frames, idx = [], 0
    while cap.grab():
        if idx % step == 0:
            ok, bgr = cap.retrieve()
            if ok:
                h, w = bgr.shape[:2]
                if w > MAX_W:
                    bgr = cv2.resize(bgr, (MAX_W, int(h * MAX_W / w)))
                frames.append((idx / native, bgr))
        idx += 1
    cap.release()
    return frames


def jpeg_b64(bgr, quality=80):
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("jpeg encode failed")
    return base64.b64encode(buf).decode("ascii")


def letterbox(bgr):
    """Pad to a square so CLIP's centre-crop doesn't cut off the sides of a wide frame."""
    h, w = bgr.shape[:2]
    s = max(h, w)
    top, left = (s - h) // 2, (s - w) // 2
    return cv2.copyMakeBorder(bgr, top, s - h - top, left, s - w - left,
                              cv2.BORDER_CONSTANT, value=(0, 0, 0))


class Embedder:
    """Local CLIP image embeddings (no network needed once the weights are cached)."""

    def __init__(self, model_name="ViT-B-32", pretrained="laion2b_s34b_b79k"):
        import open_clip
        import torch
        self.torch = torch
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            model_name, pretrained=pretrained)
        self.model.eval()

    def __call__(self, bgr_frames, batch=32, deadline=None):
        import time
        out = []
        with self.torch.no_grad():
            for i in range(0, len(bgr_frames), batch):
                if deadline is not None and time.time() > deadline:
                    raise TimeoutError("time budget exceeded while embedding frames")
                imgs = [self.preprocess(Image.fromarray(cv2.cvtColor(letterbox(f), cv2.COLOR_BGR2RGB)))
                        for f in bgr_frames[i:i + batch]]
                e = self.model.encode_image(self.torch.stack(imgs))
                e = e / e.norm(dim=-1, keepdim=True)
                out.append(e.cpu().numpy())
        return np.vstack(out)


def make_features(embs):
    """Frame embedding + change since previous sampled frame (a cheap motion cue)."""
    diff = np.vstack([np.zeros((1, embs.shape[1])), np.diff(embs, axis=0)])
    return np.hstack([embs, diff])
