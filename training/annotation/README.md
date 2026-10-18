# Aikyn Vision local review UI

These are the UI sources used by the local video review workspace.

- `automatic.html`, `automatic.css`, `automatic.js`: automatic analysis view, served at `/` on port 4321.
- `index.html`, `style.css`, `app.js`: manual annotation view, served at `/manual` on port 4321.
- `fragments.html`, `fragments.css`, `fragments.js`: fragment review view, served on port 4323.

These pages require the existing local annotation service. They are not a standalone AI server and must not be served as a working detector without its API. The automatic view reads `GET /api/automatic`, `GET /api/automatic/{video_id}` and local `/media/` resources. The manual editors require their local catalog and write APIs with an X-Local-Token header. Keep these services bound to loopback.

The primary product frontend remains in `frontend/` and uses the team Java API. Its loopback `/local-session` bootstrap is optional; servers without that route use the existing manual API settings.

No video datasets, annotations, private results, model weights, credentials, or model-training services are included in this UI change. Moving UI files does not train a model or establish detection accuracy.

The automatic view shows an animated loading state until analysis completes. Network errors and incomplete analysis remain distinguishable from a completed result. Reduced-motion settings are respected. The model subtitle and model-size badge have been removed from the header.
