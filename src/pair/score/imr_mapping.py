"""Map each PAIR policy to the IMR cases that count as "similar" for its base rate.

The mapping lives in ``policies/_imr-mapping.yaml``. Each policy lists filters in
``match_any``; a case matches if it satisfies any filter, and a filter is
satisfied when every named column takes one of the listed values. Only
pre-decision feature columns may be used (spec §5.4).
"""

import logging
from pathlib import Path
from typing import Annotated, Self

import pandas as pd
import pydantic
import yaml
from pydantic import Field, model_validator

from pair.contracts._base import ContractModel, NonEmptyStr
from pair.score.imr_data import FEATURE_COLUMNS

logger = logging.getLogger(__name__)

ColumnFilter = dict[str, Annotated[list[NonEmptyStr], Field(min_length=1)]]


class ImrMappingError(ValueError):
    """The IMR mapping file is malformed or uses a non-feature column."""


class PolicyImrMapping(ContractModel):
    """Which IMR cases are comparable to one policy, and why."""

    rationale: NonEmptyStr
    match_any: list[ColumnFilter] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_columns(self) -> Self:
        """Each filter names at least one column, and only feature columns."""
        for column_filter in self.match_any:
            if not column_filter:
                raise ValueError("each filter needs at least one column")
            not_features = sorted(set(column_filter) - set(FEATURE_COLUMNS))
            if not_features:
                raise ValueError(f"only pre-decision feature columns may be matched, not {not_features}")
        return self


def load_imr_mapping(path: Path) -> dict[str, PolicyImrMapping]:
    """Load and validate the policy → IMR mapping file.

    Raises:
        ImrMappingError: If the YAML is malformed or any entry is invalid.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ImrMappingError("top level must be a mapping of policy id to entry")
        return {str(pid): PolicyImrMapping.model_validate(entry) for pid, entry in data.items()}
    except (yaml.YAMLError, pydantic.ValidationError, ImrMappingError) as error:
        logger.error("invalid IMR mapping %s: %s", path, error)
        raise ImrMappingError(f"{path}: {error}") from error


def select_rows(frame: pd.DataFrame, mapping: PolicyImrMapping) -> pd.Series:
    """Return a boolean mask of the rows in ``frame`` that ``mapping`` matches."""
    matched = pd.Series(False, index=frame.index)
    for column_filter in mapping.match_any:
        rule = pd.Series(True, index=frame.index)
        for column, values in column_filter.items():
            rule &= frame[column].isin(values).fillna(False).astype(bool)
        matched |= rule
    return matched
