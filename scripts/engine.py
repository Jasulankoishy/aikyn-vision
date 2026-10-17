"""Analysis logic. Models are loaded ONCE in Engine(), then analyze() can be called many times."""
import time
from pathlib import Path

import joblib
import numpy as np

from common import Embedder, jpeg_b64, log, make_features, sample_frames
from violation_types import TYPES

MODEL_PATH = Path(__file__).with_name("model.joblib")
MIN_CONSECUTIVE = 2     # a violation needs >= 2 consecutive sampled frames above threshold
MERGE_GAP_SEC = 3.0     # merge detections closer than this into one event


def segments_from_hits(hit, times):
    segs, i = [], 0
    while i < len(hit):
        if hit[i]:
            j = i
            while j + 1 < len(hit) and hit[j + 1]:
                j += 1
            if j - i + 1 >= MIN_CONSECUTIVE:
                segs.append([i, j])
            i = j + 1
        else:
            i += 1
    merged = []
    for s in segs:
        if merged and times[s[0]] - times[merged[-1][1]] < MERGE_GAP_SEC:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    return merged


class Engine:
    def __init__(self):
        if not MODEL_PATH.exists():
            raise RuntimeError("model.joblib not found - run train.py first")
        t = time.time()
        self.bundle = joblib.load(MODEL_PATH)
        self.embedder = Embedder()
        log(f"models loaded in {time.time() - t:.1f}s")

    def analyze(self, video_path, budget_sec=240.0):
        deadline = time.time() + budget_sec
        frames = sample_frames(video_path)
        if not frames:
            raise RuntimeError("no frames decoded from video")

        times = np.array([t for t, _ in frames])
        imgs = [f for _, f in frames]
        embs = self.embedder(imgs, deadline=deadline)          # raises TimeoutError when over budget
        probs = self.bundle["clf"].predict_proba(make_features(embs))[:, 1]
        hit = probs >= self.bundle["threshold"]

        violations = []
        for i, j in segments_from_hits(hit, times):
            peak = i + int(np.argmax(probs[i:j + 1]))
            cluster = int(np.argmin(np.linalg.norm(self.bundle["centroids"] - embs[peak], axis=1)))
            info = TYPES.get(cluster, {"type": f"type_{cluster}", "description": "Event detected", "rule": None})

            idxs = [peak] + [k for k in (peak - 1, peak + 1) if i <= k <= j]   # peak frame first, up to 3
            v = {
                "type": info["type"],
                "timecode_sec": round(float(times[peak]), 1),
                "description": info["description"],
                "evidence_frames": [
                    {"timestamp_sec": round(float(times[k]), 1), "image_base64": jpeg_b64(imgs[k])}
                    for k in idxs
                ],
            }
            if info.get("rule"):
                v["rule"] = info["rule"]
            violations.append(v)

        return {"verdict": "violation" if violations else "no_violation", "violations": violations}
