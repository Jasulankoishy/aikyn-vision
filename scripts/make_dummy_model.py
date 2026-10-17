"""
TEMPORARY: creates a fake model.joblib so you can test Java <-> FastAPI before training.
It NEVER reports a violation (always "no_violation"). Do not use it for the real submission.
Run train.py when you have the labelled videos - it overwrites model.joblib.
"""
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression

DIM = 512  # CLIP ViT-B-32 embedding size; features are [embedding, diff] = 2 * DIM

clf = LogisticRegression()
clf.classes_ = np.array([0, 1])
clf.coef_ = np.zeros((1, 2 * DIM))
clf.intercept_ = np.array([-10.0])          # sigmoid(-10) ~ 0.00005 -> never above threshold
clf.n_features_in_ = 2 * DIM

out = Path(__file__).with_name("model.joblib")
joblib.dump({"clf": clf, "threshold": 0.5, "centroids": np.zeros((1, DIM))}, out)
print(f"saved {out} (dummy model - always no_violation)")
