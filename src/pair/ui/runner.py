"""Steps 1 to 7 on one case, turned into a ``CaseView`` (Phase 4). Used by the cache build and the live API.

Everything the run needs (policies, letter template, help links, UI headings,
threshold, IMR base model) loads once, when the ``Runner`` is made.
"""

import hashlib
import logging
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path

from pair.draft.template import load_letter_template
from pair.extract.runner import ExtractFn
from pair.llm import Backend, LLMClient, LLMConfig
from pair.pipeline import load_resources, run_core, run_trust
from pair.rules.active import ContextFlag
from pair.score.base_model import BaseModel, BaseModelError, load_base_model
from pair.score.strength import load_adjustments, load_ship_links
from pair.trust_cli import IMR_MODEL, TEMPLATE, THRESHOLDS
from pair.ui.copy import load_ui_headings
from pair.ui.view import CaseView, Mode, build_view
from pair.verify.conformal import Threshold, ThresholdBook
from pair.verify.nli import PREMISE_RULE, Verifier

logger = logging.getLogger(__name__)

POLICIES = Path("policies")
ADJUSTMENTS = Path(__file__).parent.parent / "score" / "adjustments.yaml"
PING_SECONDS = 2.0


def threshold_key(threshold: Threshold | None) -> str:
    """How run metadata names the threshold in use."""
    if threshold is None:
        return "none"
    return (f"{threshold.drafter} | {threshold.verifier_backend} | {threshold.verifier_model} "
            f"(q_hat {threshold.q_hat:.4f}, n {threshold.n})")  # fmt: skip


class Runner:
    """Runs the pipeline with one drafter and verifier and builds the view."""

    def __init__(
        self,
        client: LLMClient,
        config: LLMConfig,
        extract_fn: ExtractFn,
        verifier: Verifier,
        policies: Path = POLICIES,
        thresholds: Path = THRESHOLDS,
        imr_model: Path = IMR_MODEL,
    ) -> None:
        """Load resources, threshold and, if present, the IMR base model (without it, strength is not available)."""
        self.client, self.config, self.extract_fn, self.verifier = client, config, extract_fn, verifier
        self.resources = load_resources(policies)
        self.template = load_letter_template(policies / TEMPLATE.name)
        self.ship_links = load_ship_links(policies / "_ship.yaml")
        self.headings = load_ui_headings(policies / "_ui.yaml", self.resources.checklists)
        self.adjustments = load_adjustments(ADJUSTMENTS)
        self.info = verifier.describe()
        self.threshold = ThresholdBook.load(thresholds).lookup(
            config.model, self.info["verifier_backend"], self.info["verifier_model"]
        )
        self.base: BaseModel | None = None
        self.base_note: str | None = None
        self.imr_sha: str | None = None
        try:
            self.base = load_base_model(imr_model)
            self.imr_sha = hashlib.sha256(imr_model.read_bytes()).hexdigest()
        except BaseModelError as error:
            logger.warning("no IMR base model, strength not available: %s", error)
            self.base_note = str(error)

    def view(
        self,
        case_id: str,
        denial_text: str,
        notes: Mapping[str, str],
        titles: Mapping[str, str],
        flags: Mapping[str, ContextFlag],
        mode: Mode = "cached",
        policy_override: str | None = None,
    ) -> CaseView:
        """Steps 1 to 7 on one case. An unsupported denial gives a view with ``supported`` false and no letter.

        Raises:
            LLMError: If the drafter or verifier backend fails.
        """
        context = {name: flag.value for name, flag in flags.items()}
        core = run_core(denial_text, notes, self.resources, self.client, self.config, context, self.extract_fn,
                        policy_override=policy_override)  # fmt: skip
        trust = None
        if core.verdict is not None and core.denial is not None:
            checklist = self.resources.checklists[core.verdict.policy_id]
            base = self.base.estimate(checklist.id) if self.base else None
            trust = run_trust(core, notes, checklist, self.client, self.verifier, self.threshold, self.config.model,
                              self.template, flags, base, self.adjustments)  # fmt: skip
        return build_view(case_id, core, trust, self.resources, self.template, self.ship_links, notes, titles,
                          mode=mode, headings=self.headings)  # fmt: skip

    def meta(self) -> dict[str, str | None]:
        """Models, threshold and premise rule, for run metadata."""
        return {
            "drafter": self.config.model, "verifier_backend": self.info["verifier_backend"],
            "verifier_model": self.info["verifier_model"], "threshold": threshold_key(self.threshold),
            "premise_rule": PREMISE_RULE, "config_hash": self.config.config_hash(), "imr_model_sha256": self.imr_sha,
        }  # fmt: skip

    def reachable(self) -> bool:
        """True if the model server answers (Ollama through the lab tunnel); other backends aren't pinged."""
        if self.config.backend is not Backend.OLLAMA:
            return True
        try:
            with urllib.request.urlopen(f"{self.config.ollama_url}/api/version", timeout=PING_SECONDS) as reply:
                return bool(reply.status == 200)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.info("model server not reachable: %s", type(exc).__name__)
            return False

