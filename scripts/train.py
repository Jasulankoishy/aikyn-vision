"""
Train the lightweight violation classifier from the organisers' labelled videos.

labels.csv columns:  video,violation,time_sec
    video_001.mov,1,11.0
    video_001.mov,1,47.5      <- several rows for the same video = several violations
    video_002.mov,0,
time_sec may be plain seconds (47.5) or mm:ss / hh:mm:ss (00:47).
Usage:
    python train.py --videos ./videos --labels labels.csv --clusters 4
Outputs model.joblib next to this file.
"""
import argparse
import csv
from pathlib import Path

import joblib
import numpy as np
import cv2
from sklearn.cluster import KMeans
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold, cross_val_predict

from common import Embedder, log, make_features, sample_frames

POS_WIN = 1.5   # seconds around a labelled time that count as "violation"
NEG_GAP = 4.0   # frames at least this far from EVERY label count as "normal"
                # (frames in between are skipped; careful: an unlabelled violation = label noise)


def augment_video(frames, rng):
    """Same random perspective warp (+ optional flip) for the whole video: fakes another camera angle."""
    h, w = frames[0].shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = src + rng.uniform(-0.08, 0.08, (4, 2)).astype(np.float32) * np.float32([w, h])
    M = cv2.getPerspectiveTransform(src, dst)
    flip = rng.random() < 0.5
    out = []
    for f in frames:
        g = cv2.warpPerspective(f, M, (w, h), borderMode=cv2.BORDER_REFLECT)
        out.append(cv2.flip(g, 1) if flip else g)
    return out


def parse_time(s):
    """'47.5' -> 47.5, '00:47' -> 47.0, '1:02:03' -> 3723.0"""
    s = s.strip().replace(",", ".")
    if ":" in s:
        sec = 0.0
        for part in s.split(":"):
            sec = sec * 60 + float(part)
        return sec
    return float(s)


def load_labels(path):
    """Group rows by video. Returns [(video_name, [violation_times_sec])].
    A video with no violation rows (or only violation=0 rows) gets an empty list."""
    d = {}
    # utf-8-sig: Excel's "CSV UTF-8" export starts the file with a BOM
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            name = (r.get("video") or "").strip()
            if not name:
                continue                                   # blank line
            ts = d.setdefault(name, [])
            if int(float(r["violation"])):
                if not (r.get("time_sec") or "").strip():
                    raise ValueError(f"{name}: violation=1 but time_sec is empty")
                ts.append(parse_time(r["time_sec"]))
    return list(d.items())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--videos", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--aug", type=int, default=2, help="augmented copies per video (0 = fast test run)")
    ap.add_argument("--clusters", type=int, default=4, help="candidate violation types")
    args = ap.parse_args()

    rng = np.random.default_rng(0)
    emb = Embedder()

    labels = []
    for name, ts in load_labels(args.labels):
        if (Path(args.videos) / name).is_file():
            labels.append((name, ts))
        else:
            log(f"WARNING: {name} is in labels.csv but not in {args.videos} - skipped")
    n_pos = sum(1 for _, ts in labels if ts)
    log(f"videos: {len(labels)} ({n_pos} with violations, {len(labels) - n_pos} without), "
        f"violation labels: {sum(len(ts) for _, ts in labels)}")
    if n_pos == 0 or n_pos == len(labels):
        raise SystemExit("need both violation and non-violation videos to train")

    X, y, g, meta = [], [], [], []
    for vi, (name, ts) in enumerate(labels):
        log(f"[{vi + 1}/{len(labels)}] {name}  ({len(ts)} violation(s))")
        frames = sample_frames(str(Path(args.videos) / name))
        times = [t for t, _ in frames]
        imgs = [f for _, f in frames]
        for a in range(1 + args.aug):
            seq = imgs if a == 0 else augment_video(imgs, rng)
            feats = make_features(emb(seq))
            for i, t in enumerate(times):
                if not ts:
                    yy = 0
                else:
                    dist = min(abs(t - x) for x in ts)      # distance to the nearest labelled violation
                    if dist <= POS_WIN:
                        yy = 1
                    elif dist >= NEG_GAP:
                        yy = 0
                    else:
                        continue
                X.append(feats[i]); y.append(yy); g.append(vi); meta.append((name, t, a))

    X, y, g = np.array(X), np.array(y), np.array(g)
    log(f"samples: {len(y)}, positives: {int(y.sum())}")

    clf = LogisticRegression(C=1.0, class_weight="balanced", max_iter=3000)
    cv = GroupKFold(n_splits=min(5, len(labels)))
    oof = cross_val_predict(clf, X, y, groups=g, cv=cv, method="predict_proba")[:, 1]

    # Video-level check (criterion 1 is scored per video): flagged if any frame >= threshold
    video_truth = {vi: int(bool(ts)) for vi, (_, ts) in enumerate(labels)}
    best_thr, best_acc = 0.5, -1.0
    for thr in np.arange(0.3, 0.95, 0.05):
        correct = sum(int((oof[g == vi].max() >= thr) == bool(video_truth[vi]))
                      for vi in video_truth if (g == vi).any())
        acc = correct / len(video_truth)
        log(f"threshold {thr:.2f}: video-level accuracy {acc:.2f}")
        if acc >= best_acc:           # ties -> higher threshold (fewer false alarms)
            best_thr, best_acc = float(thr), acc
    log(f"chosen threshold {best_thr:.2f} (cross-validated video accuracy {best_acc:.2f})")

    clf.fit(X, y)

    # Discover candidate violation types by clustering the positive frames (original frames only)
    D = X.shape[1] // 2
    pos_idx = [i for i in range(len(y)) if y[i] == 1 and meta[i][2] == 0]
    k = min(args.clusters, len(pos_idx))
    km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(X[pos_idx][:, :D])
    log("\nCandidate types - look at these moments in the videos, then name them in violation_types.py TYPES:")
    for c in range(k):
        members = [pos_idx[i] for i in range(len(pos_idx)) if km.labels_[i] == c]
        ex = ", ".join(f"{meta[m][0]}@{meta[m][1]:.1f}s" for m in members[:5])
        log(f"  type {c}: {len(members)} frames, e.g. {ex}")

    out = Path(__file__).with_name("model.joblib")
    joblib.dump({"clf": clf, "threshold": best_thr, "centroids": km.cluster_centers_}, out)
    log(f"saved {out}")


if __name__ == "__main__":
    main()
