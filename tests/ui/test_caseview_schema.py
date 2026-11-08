"""The web app's CaseView types come from ``caseview_schema()``; the checked-in schema must match it (Phase 4 T8)."""

import json

from pair.ui.view import caseview_schema
from tests.conftest import REPO_ROOT

SCHEMA = REPO_ROOT / "web" / "src" / "types" / "caseview.schema.json"


def test_web_schema_is_current() -> None:
    """Run ``uv run python scripts/export_caseview_schema.py`` then ``npm --prefix web run gen:types`` if this fails."""
    assert json.loads(SCHEMA.read_text()) == caseview_schema()
