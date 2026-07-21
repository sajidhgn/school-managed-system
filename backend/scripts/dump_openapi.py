"""Dump the OpenAPI schema to `backend/openapi.json`.

The frontend generates its TypeScript types from this file (`npm run gen:api`),
so it is committed and must be regenerated whenever a route or schema changes:

    uv run python scripts/dump_openapi.py

Boots the app without a database — schema generation touches no I/O.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

os.environ.setdefault("DB_ENABLED", "false")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent.parent / "openapi.json"


def main() -> None:
    OUT.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(OUT.parent.parent)}")


if __name__ == "__main__":
    main()
