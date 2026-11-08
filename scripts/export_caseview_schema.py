"""Write the CaseView JSON Schema the web app's TypeScript types are generated from.

Usage:
    uv run python scripts/export_caseview_schema.py && npm --prefix web run gen:types

Writes ``web/src/types/caseview.schema.json``. ``tests/ui/test_caseview_schema.py`` fails if it is stale.
"""

import json
from pathlib import Path

from pair.ui.view import caseview_schema

OUT = Path("web/src/types/caseview.schema.json")

if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(caseview_schema(), indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT}")
