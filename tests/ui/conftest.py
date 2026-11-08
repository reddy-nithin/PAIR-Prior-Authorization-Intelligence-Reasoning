"""Fixtures for the UI tests: a real pipeline run on the fixture case with fake LLM, extractor and verifier."""

from collections.abc import Mapping
from typing import Any

import pytest

from pair.draft.template import LetterTemplate, load_letter_template
from pair.llm import Backend, LLMConfig, LLMResult, LLMUsage
from pair.pipeline import (
    CoreRun,
    Resources,
    TrustRun,
    load_resources,
    run_core,
    run_trust,
)
from pair.score.base_model import BaseEstimate
from pair.score.strength import ShipLink, load_adjustments, load_ship_links
from pair.trust_cli import case_flags
from pair.ui.copy import load_ui_headings
from pair.ui.view import CaseView, build_view
from pair.verify.conformal import Threshold
from tests.conftest import REPO_ROOT
from tests.fakes import FakeLLM
from tests.test_pipeline import CASE, denial_reply, gold_extract

DRAFTER = "fake-drafter"


class EmptyWordingLLM:
    """Always returns an empty sentence, so every claim falls back to the verbatim record quote."""

    def generate_json(self, prompt: str, schema: Mapping[str, Any]) -> LLMResult:
        """Return an empty sentence."""
        usage = LLMUsage(prompt_tokens=1, output_tokens=1, thinking_tokens=None)
        return LLMResult(data={"sentence": ""}, raw_text="{}", usage=usage, backend=Backend.OLLAMA, model=DRAFTER)


class FirstLowVerifier:
    """Scores the first claim 0.1 (FLAGGED under q̂ 0.5) and every other claim 0.9 (KEPT)."""

    def __init__(self) -> None:
        self.calls = 0

    def score(self, claim: str, premise: str) -> float:
        """Return 0.1 for the first call, then 0.9."""
        self.calls += 1
        return 0.1 if self.calls == 1 else 0.9

    def describe(self) -> dict[str, str]:
        """Run metadata."""
        return {"verifier_backend": "minicheck", "verifier_model": "bespoke-minicheck", "verifier_host": "test"}


@pytest.fixture(scope="session")
def resources() -> Resources:
    """The shipped policy resources."""
    return load_resources(REPO_ROOT / "policies")


@pytest.fixture(scope="session")
def template() -> LetterTemplate:
    """The shipped letter template."""
    return load_letter_template(REPO_ROOT / "policies" / "_letter.yaml")


@pytest.fixture(scope="session")
def ship_links() -> tuple[ShipLink, ...]:
    """The shipped get-a-human links."""
    return load_ship_links(REPO_ROOT / "policies" / "_ship.yaml")


@pytest.fixture(scope="session")
def ui_headings(resources: Resources) -> dict[str, str]:
    """The shipped UI headings."""
    return load_ui_headings(REPO_ROOT / "policies" / "_ui.yaml", resources.checklists)


@pytest.fixture(scope="session")
def documents() -> dict[str, str]:
    """The fixture case's record texts."""
    return CASE.record_text()


@pytest.fixture(scope="session")
def titles() -> dict[str, str]:
    """The fixture case's record titles."""
    return {note.doc_id: note.title for note in CASE.notes}


@pytest.fixture(scope="session")
def core(resources: Resources, documents: dict[str, str]) -> CoreRun:
    """Steps 1 to 4 on the fixture case with a perfect reader."""
    return run_core(
        CASE.denial_text, documents, resources, FakeLLM([denial_reply()]), LLMConfig.from_env({}),
        context=CASE.context, extract_fn=gold_extract,
    )  # fmt: skip


def _trust(core: CoreRun, resources: Resources, documents: dict[str, str], template: LetterTemplate,
           quote_met: bool) -> TrustRun:  # fmt: skip
    """Steps 5 to 7 with the fake drafter and a verifier that flags the first claim."""
    threshold = Threshold(
        q_hat=0.5, n=54, k=1, alpha=0.1, drafter=DRAFTER,
        verifier_backend="minicheck", verifier_model="bespoke-minicheck",
    )  # fmt: skip
    base = BaseEstimate(p=0.6, low=0.5, high=0.7, n_similar=120, imr_category="DME", widened=False)
    return run_trust(
        core, documents, resources.checklists["pap-osa"], EmptyWordingLLM(), FirstLowVerifier(), threshold,
        DRAFTER, template, case_flags(CASE), base,
        load_adjustments(REPO_ROOT / "src" / "pair" / "score" / "adjustments.yaml"), quote_met=quote_met,
    )  # fmt: skip


@pytest.fixture(scope="session")
def trust(core: CoreRun, resources: Resources, documents: dict[str, str], template: LetterTemplate) -> TrustRun:
    """Steps 5 to 7: verbatim fallback sentences, first claim FLAGGED then quoted (its criterion is met, ADR-0024)."""
    return _trust(core, resources, documents, template, quote_met=True)


@pytest.fixture(scope="session")
def trust_unquoted(core: CoreRun, resources: Resources, documents: dict[str, str], template: LetterTemplate) -> TrustRun:
    """The same run with quoting off, so the first claim stays FLAGGED (as for an unmet criterion)."""
    return _trust(core, resources, documents, template, quote_met=False)


@pytest.fixture(scope="session")
def view(
    core: CoreRun,
    trust: TrustRun,
    resources: Resources,
    template: LetterTemplate,
    ship_links: tuple[ShipLink, ...],
    documents: dict[str, str],
    titles: dict[str, str],
    ui_headings: dict[str, str],
) -> CaseView:
    """The view of the fixture case (f2f insufficient, 3 met; first claim quoted; strength abstains)."""
    return build_view(
        "pap-osa-fixture", core, trust, resources, template, ship_links, documents, titles, headings=ui_headings
    )


@pytest.fixture(scope="session")
def view_flagged(
    core: CoreRun,
    trust_unquoted: TrustRun,
    resources: Resources,
    template: LetterTemplate,
    ship_links: tuple[ShipLink, ...],
    documents: dict[str, str],
    titles: dict[str, str],
    ui_headings: dict[str, str],
) -> CaseView:
    """The fixture view with one FLAGGED claim kept out of the letter."""
    return build_view(
        "pap-osa-fixture", core, trust_unquoted, resources, template, ship_links, documents, titles,
        headings=ui_headings,
    )  # fmt: skip
