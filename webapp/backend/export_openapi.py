"""
webapp/backend/export_openapi.py

Writes the API's machine-readable description (OpenAPI JSON) to a file, so the
frontend's TypeScript types can be GENERATED from the same schemas.py the
backend validates with. The frontend never hand-copies a response shape:
if schemas.py changes, regenerating makes the TypeScript compiler point at
every place in the UI that no longer matches.

    python webapp/backend/export_openapi.py webapp/frontend/openapi.json
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from webapp.backend.main import app  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "openapi.json"
with open(out, "w", encoding="utf-8") as f:
    json.dump(app.openapi(), f, indent=1)
print(f"wrote {out} ({len(app.openapi()['paths'])} paths)")
