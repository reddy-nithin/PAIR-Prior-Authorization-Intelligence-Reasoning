"""IMR base model: the overturn base rate a strength estimate starts from (step 7, ADR-0019).

Time split: train on years up to 2022, calibrate on 2023, test once on 2024 and
later. Two models (logistic regression on one-hot categories, histogram gradient
boosting on native categoricals) times three training windows (all years up to
2022, 2016 to 2022, all years with recency weights) are compared on 2023 Brier
score; the best pair is kept. Venn-Abers is fit per ``TreatmentCategory`` on 2023
and Mondrian 90% sets on the same scores.

A PAIR case has no IMR row, so its base rate comes from a profile of its policy
group (``policies/_imr-mapping.yaml``): the most common value of each feature
among the group's rows in the window plus 2023, with ``AgeRange`` set to "65+".
The shown range is the Venn-Abers range widened to the group's 90% Wilson width.

Every number here describes California IMR reviews of commercial plans, not
Medicare Advantage appeals.
"""

import logging
import math
import pickle
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from pair.score.calibration import (
    OTHER,
    CoverageReport,
    MondrianSets,
    VennAbers,
    pool_small_groups,
    wilson_floor,
)
from pair.score.imr_data import FEATURE_COLUMNS
from pair.score.imr_mapping import PolicyImrMapping, select_rows

logger = logging.getLogger(__name__)

TRAIN_LAST_YEAR = 2022
CALIBRATION_YEAR = 2023
MAX_LEVELS = 250
MIN_LEVEL_COUNT = 5
MISSING = "missing"
MEDICARE_AGE = "65+"
ALL = "all"
CANDIDATE_MODELS = ("logreg", "hgb")
N_RELIABILITY_BINS = 10


@dataclass(frozen=True)
class Window:
    """A training window: a first year (or all years) and optional recency weights."""

    first_year: int | None = None
    half_life: float | None = None

    def mask(self, years: pd.Series) -> pd.Series:
        """Rows inside the window, up to and including the calibration year."""
        inside = years <= CALIBRATION_YEAR
        if self.first_year is not None:
            inside &= years >= self.first_year
        return inside.fillna(False).astype(bool)

    def weights(self, years: pd.Series) -> np.ndarray:
        """Sample weights: 1, or halving every ``half_life`` years before the last training year."""
        if self.half_life is None:
            return np.ones(len(years))
        age = TRAIN_LAST_YEAR - years.astype(float).to_numpy()
        return np.asarray(0.5 ** (age / self.half_life), dtype=float)


WINDOWS: dict[str, Window] = {
    "upto2022": Window(),
    "2016to2022": Window(first_year=2016),
    "upto2022_recency": Window(half_life=5.0),
}


def split_years(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(train ≤ 2022, calibration = 2023, test ≥ 2024)."""
    years = frame["report_year"]
    return (
        frame[(years <= TRAIN_LAST_YEAR).fillna(False)],
        frame[(years == CALIBRATION_YEAR).fillna(False)],
        frame[(years > CALIBRATION_YEAR).fillna(False)],
    )


def feature_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    """Only the pre-decision feature columns, in schema order."""
    return frame[list(FEATURE_COLUMNS)]


class LevelPooler:
    """Caps each categorical feature at ``MAX_LEVELS`` levels; rare and unseen levels become ``other``."""

    def __init__(self) -> None:
        """Create an unfitted pooler."""
        self._levels: dict[str, list[str]] = {}

    @staticmethod
    def _strings(column: pd.Series) -> pd.Series:
        """Values as strings, missing as ``missing``."""
        return column.astype(object).where(column.notna(), MISSING).astype(str)

    def fit(self, frame: pd.DataFrame) -> "LevelPooler":
        """Learn the kept levels from training rows."""
        for column in FEATURE_COLUMNS:
            counts = self._strings(frame[column]).value_counts()
            kept = [str(v) for v, c in counts.items() if c >= MIN_LEVEL_COUNT and v not in (OTHER, MISSING)]
            self._levels[column] = sorted(kept[: MAX_LEVELS - 2])
        return self

    def transform(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Pooled features as categoricals with fixed categories."""
        out = {}
        for column in FEATURE_COLUMNS:
            levels = self._levels[column]
            values = self._strings(frame[column])
            values = values.where(values.isin(levels) | (values == MISSING), OTHER)
            out[column] = pd.Categorical(values, categories=[*levels, OTHER, MISSING])
        return pd.DataFrame(out, index=frame.index)


def _make_model(name: str, seed: int) -> Any:
    """An unfitted candidate model."""
    if name == "logreg":
        return Pipeline([
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
            ("logreg", LogisticRegression(max_iter=2000)),
        ])
    return HistGradientBoostingClassifier(
        categorical_features="from_dtype", learning_rate=0.05, max_iter=200, early_stopping=False, random_state=seed
    )


def _fit(name: str, x: pd.DataFrame, y: np.ndarray, weights: np.ndarray, seed: int) -> Any:
    """Fit one candidate with sample weights."""
    model = _make_model(name, seed)
    if name == "logreg":
        model.fit(x, y, logreg__sample_weight=weights)
    else:
        model.fit(x, y, sample_weight=weights)
    return model


@dataclass(frozen=True)
class SelectionRow:
    """One (model, window) candidate and its 2023 Brier score."""

    model: str
    window: str
    brier_2023: float


@dataclass(frozen=True)
class BaseEstimate:
    """The unshifted base rate for one policy group.

    Attributes:
        p: Venn-Abers point estimate.
        low: Lower end of the shown range (after the Wilson floor).
        high: Upper end of the shown range.
        n_similar: Group rows in the training window plus 2023.
        imr_category: The ``TreatmentCategory`` whose calibrator was used.
        widened: True if the Wilson floor widened the Venn-Abers range.
    """

    p: float
    low: float
    high: float
    n_similar: int
    imr_category: str
    widened: bool


@dataclass(frozen=True)
class WidthRow:
    """The width rule on 2023 for one policy group."""

    width: float
    abstain: bool
    n_similar: int


@dataclass(frozen=True)
class ReliabilityBin:
    """One bin of the reliability table."""

    low: float
    high: float
    n: int
    mean_predicted: float
    observed: float


@dataclass(frozen=True)
class GroupReport:
    """2024+ numbers for one policy group (descriptive only)."""

    n: int
    brier: float
    coverage: CoverageReport


@dataclass(frozen=True)
class TestReport:
    """2024+ numbers, computed once after every choice is frozen."""

    n: int
    auroc: float
    brier: float
    brier_raw: float
    reliability: tuple[ReliabilityBin, ...]
    coverage: CoverageReport
    per_group: dict[str, GroupReport]


class BaseModel:
    """The chosen model, its pooler and calibrators, and the policy-group mappings."""

    def __init__(
        self,
        model_name: str,
        window: str,
        estimator: Any,
        pooler: LevelPooler,
        calibrators: dict[str, VennAbers],
        mondrian: MondrianSets,
        history: pd.DataFrame,
        mappings: Mapping[str, PolicyImrMapping],
        selection: tuple[SelectionRow, ...],
    ) -> None:
        """Bundle the fitted parts (use ``fit_base_model``)."""
        self.model_name = model_name
        self.window = window
        self._estimator = estimator
        self._pooler = pooler
        self._calibrators = calibrators
        self._mondrian = mondrian
        self._history = history
        self._mappings = mappings
        self.selection = selection

    def scores(self, frame: pd.DataFrame) -> np.ndarray:
        """Model P(overturned) for raw IMR-like rows."""
        x = self._pooler.transform(feature_matrix(frame))
        return np.asarray(self._estimator.predict_proba(x)[:, 1], dtype=float)

    def _calibrator_name(self, category: object) -> str:
        """The calibrator for a raw ``TreatmentCategory`` value."""
        name = str(category)
        if name in self._calibrators:
            return name
        return OTHER if OTHER in self._calibrators else ALL

    def calibrated(self, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Venn-Abers ``(p0, p1, p)`` per row, by its treatment category."""
        scores = self.scores(frame)
        names = np.array([self._calibrator_name(c) for c in frame["TreatmentCategory"].astype(object)])
        p0 = np.empty(len(frame))
        p1 = np.empty(len(frame))
        for name in set(names.tolist()):
            rows = names == name
            p0[rows], p1[rows] = self._calibrators[name].predict(scores[rows])
        return p0, p1, VennAbers.point(p0, p1)

    def _group_rows(self, policy_id: str) -> pd.DataFrame:
        """The policy group's rows in the window plus 2023 (KeyError for an unmapped policy)."""
        mapping = self._mappings[policy_id]
        history = self._history
        return history[select_rows(history, mapping)]

    def estimate(self, policy_id: str) -> BaseEstimate:
        """The unshifted base rate and range for a case under ``policy_id``.

        Raises:
            KeyError: If the policy has no IMR mapping.
        """
        rows = self._group_rows(policy_id)
        profile = {}
        for column in FEATURE_COLUMNS:
            modes = rows[column].dropna().astype(object).mode()
            profile[column] = [modes.iloc[0] if len(modes) else None]
        profile["AgeRange"] = [MEDICARE_AGE]
        frame = pd.DataFrame(profile)
        category = str(profile["TreatmentCategory"][0])
        p0, p1, p = self.calibrated(frame)
        n = len(rows)
        if n == 0:
            return BaseEstimate(float(p[0]), 0.0, 1.0, 0, category, True)
        low, high, widened = wilson_floor(float(p[0]), float(p0[0]), float(p1[0]), int(rows["label"].sum()), n)
        return BaseEstimate(float(p[0]), low, high, n, category, widened)

    def width_check(self, max_width: float) -> dict[str, WidthRow]:
        """Rule 1 of the abstention rules per policy group, using 2023 and earlier only."""
        rows = {}
        for policy_id in self._mappings:
            estimate = self.estimate(policy_id)
            width = estimate.high - estimate.low
            rows[policy_id] = WidthRow(width, width > max_width, estimate.n_similar)
        return rows

    def evaluate(self, test: pd.DataFrame) -> TestReport:
        """AUROC, Brier, reliability and Mondrian coverage on the test rows, overall and per policy group."""
        labels = test["label"].astype(int).to_numpy()
        scores = self.scores(test)
        _, _, p = self.calibrated(test)
        groups = test["TreatmentCategory"].astype(object).astype(str).to_numpy()
        per_group = {}
        for policy_id, mapping in self._mappings.items():
            mask = select_rows(test, mapping).to_numpy()
            per_group[policy_id] = GroupReport(
                n=int(mask.sum()),
                brier=float(brier_score_loss(labels[mask], p[mask])) if mask.any() else math.nan,
                coverage=self._mondrian.evaluate(scores[mask], labels[mask], groups[mask]),
            )
        return TestReport(
            n=len(test),
            auroc=float(roc_auc_score(labels, p)),
            brier=float(brier_score_loss(labels, p)),
            brier_raw=float(brier_score_loss(labels, scores)),
            reliability=_reliability(p, labels),
            coverage=self._mondrian.evaluate(scores, labels, groups),
            per_group=per_group,
        )


def _reliability(p: np.ndarray, labels: np.ndarray) -> tuple[ReliabilityBin, ...]:
    """Equal-width bins of the predicted probability (the last bin includes 1.0)."""
    edges = np.linspace(0.0, 1.0, N_RELIABILITY_BINS + 1)
    index = np.minimum(np.digitize(p, edges[1:-1]), N_RELIABILITY_BINS - 1)
    bins = []
    for i in range(N_RELIABILITY_BINS):
        rows = index == i
        n = int(rows.sum())
        bins.append(ReliabilityBin(
            float(edges[i]), float(edges[i + 1]), n,
            float(p[rows].mean()) if n else math.nan, float(labels[rows].mean()) if n else math.nan,
        ))
    return tuple(bins)


def _calibrators(scores: np.ndarray, labels: np.ndarray, categories: np.ndarray) -> dict[str, VennAbers]:
    """Venn-Abers per category (small or one-class categories pooled into ``other``), plus ``all``."""
    pooled = pool_small_groups(categories)
    for name in set(pooled.tolist()):
        if len(set(labels[pooled == name].tolist())) < 2:
            pooled[pooled == name] = OTHER
    calibrators = {ALL: VennAbers().fit(scores, labels)}
    for name in sorted(set(pooled.tolist())):
        rows = pooled == name
        if len(set(labels[rows].tolist())) == 2:
            calibrators[name] = VennAbers().fit(scores[rows], labels[rows])
    return calibrators


def fit_base_model(
    frame: pd.DataFrame,
    mappings: Mapping[str, PolicyImrMapping],
    seed: int = 0,
    log: Callable[[str], None] = logger.info,
) -> BaseModel:
    """Choose the model and window on 2023 Brier, then fit the calibrators on 2023.

    Rows after 2023 are dropped before anything is fit, so the test years can't
    affect any choice.
    """
    train, calib, _ = split_years(frame)
    y_calib = calib["label"].astype(int).to_numpy()
    candidates: list[tuple[SelectionRow, Any, LevelPooler]] = []
    for window_name, window in WINDOWS.items():
        rows = train[window.mask(train["report_year"])]
        pooler = LevelPooler().fit(feature_matrix(rows))
        x = pooler.transform(feature_matrix(rows))
        y = rows["label"].astype(int).to_numpy()
        weights = window.weights(rows["report_year"])
        x_calib = pooler.transform(feature_matrix(calib))
        for name in CANDIDATE_MODELS:
            model = _fit(name, x, y, weights, seed)
            brier = float(brier_score_loss(y_calib, model.predict_proba(x_calib)[:, 1]))
            candidates.append((SelectionRow(name, window_name, brier), model, pooler))
            log(f"candidate {name} / {window_name}: 2023 Brier {brier:.4f} on {len(rows)} training rows")
    best, estimator, pooler = min(candidates, key=lambda item: item[0].brier_2023)
    scores = np.asarray(estimator.predict_proba(pooler.transform(feature_matrix(calib)))[:, 1], dtype=float)
    categories = calib["TreatmentCategory"].astype(object).astype(str).to_numpy()
    history = pd.concat([train, calib])
    history = history[WINDOWS[best.window].mask(history["report_year"])]
    model = BaseModel(
        model_name=best.model,
        window=best.window,
        estimator=estimator,
        pooler=pooler,
        calibrators=_calibrators(scores, y_calib, categories),
        mondrian=MondrianSets(alpha=0.1).fit(scores, y_calib, categories),
        history=history,
        mappings=mappings,
        selection=tuple(row for row, _, _ in candidates),
    )
    log(f"chose {best.model} / {best.window} (2023 Brier {best.brier_2023:.4f})")
    return model


class BaseModelError(RuntimeError):
    """The saved base model is missing or unreadable."""


def save_base_model(model: BaseModel, path: Path) -> Path:
    """Pickle the fitted model (under ``data/``, never committed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pickle.dumps(model))
    return path


def load_base_model(path: Path) -> BaseModel:
    """Load a model this project saved with ``save_base_model``.

    Raises:
        BaseModelError: If the file is missing or isn't a ``BaseModel``.
    """
    if not path.exists():
        raise BaseModelError(f"no IMR base model at {path} (run `pair imr-fit`)")
    try:
        model = pickle.loads(path.read_bytes())
    except (pickle.UnpicklingError, EOFError, AttributeError) as exc:
        logger.error("unreadable base model %s: %s", path, exc)
        raise BaseModelError(f"{path}: {exc}") from exc
    if not isinstance(model, BaseModel):
        raise BaseModelError(f"{path} does not hold an IMR base model")
    return model
