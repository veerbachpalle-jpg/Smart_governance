"""Generate docs/openapi.json from the live FastAPI app."""

import json
import pathlib
import sys

# Ensure project root is on sys.path
project_root = str(pathlib.Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.main import app  # noqa: E402


def main() -> None:
    schema = app.openapi()
    out_path = pathlib.Path(project_root) / "docs" / "openapi.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, default=str)
    print(f"[OK] OpenAPI spec written to {out_path} ({len(schema.get('paths', {}))} paths)")


if __name__ == "__main__":
    main()
