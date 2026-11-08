"""Fixtures for the API tests: a demo cache from the fixture view and a live runner on fakes."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pair.api.app import ApiSettings, create_app
from pair.llm import LLMConfig
from pair.ui.cache import CacheEntry, write_cache
from pair.ui.export import to_docx, to_pdf
from pair.ui.runner import Runner
from pair.ui.view import CaseView
from pair.verify.conformal import Threshold, ThresholdBook
from tests.conftest import REPO_ROOT
from tests.test_pipeline import gold_extract
from tests.ui.conftest import (  # noqa: F401  shared fixtures: the fixture case's view and what builds it
    FirstLowVerifier,
    core,
    documents,
    resources,
    ship_links,
    template,
    titles,
    trust,
    ui_headings,
    view,
)
from tests.ui.test_demo_build import DemoLLM


class FakeRunner(Runner):
    """A runner on fakes whose model server is reachable unless told otherwise."""

    up = True

    def reachable(self) -> bool:
        """Pretend to ping the lab."""
        return self.up


@pytest.fixture(scope="session")
def demo_cache(tmp_path_factory: pytest.TempPathFactory, view: CaseView) -> Path:  # noqa: F811
    """A one-case demo cache with the fixture view, DOCX and PDF."""
    root = tmp_path_factory.mktemp("api") / "demo-cache"
    entry = CacheEntry(view=view, input_sha256="0" * 64, extras={"docx": to_docx(view), "pdf": to_pdf(view)})
    return write_cache(root, [entry], {"drafter": "gemma4:e4b"})


@pytest.fixture(scope="session")
def runner(tmp_path_factory: pytest.TempPathFactory) -> FakeRunner:
    """A live runner: gold denial parse, gold extraction, verbatim wording, first claim flagged."""
    thresholds = tmp_path_factory.mktemp("thr") / "thresholds.json"
    ThresholdBook([Threshold(q_hat=0.5, n=54, k=1, alpha=0.1, drafter="gemma4:e4b", verifier_backend="minicheck",
                             verifier_model="bespoke-minicheck")]).save(thresholds)  # fmt: skip
    return FakeRunner(DemoLLM(), LLMConfig.from_env({}), gold_extract, FirstLowVerifier(), REPO_ROOT / "policies",
                      thresholds, thresholds.parent / "no-model.pkl")  # fmt: skip


@pytest.fixture
def settings(demo_cache: Path, runner: FakeRunner) -> ApiSettings:
    """Cached + live, no Presidio (its own tests cover it)."""
    runner.up = True
    return ApiSettings(cache_dir=demo_cache, runner=runner, redact_logs=False)


@pytest.fixture
def client(settings: ApiSettings) -> TestClient:
    """A test client for the app."""
    return TestClient(create_app(settings))
