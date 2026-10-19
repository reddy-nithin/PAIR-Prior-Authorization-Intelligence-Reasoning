"""The tolerant format handler drops malformed items, not whole chunks (Phase 2 fix)."""

import json
from collections.abc import Mapping

from pair.extract.tolerant_format import TolerantFormatHandler


def output(*groups: Mapping[str, object]) -> str:
    """Model output in LangExtract's JSON wrapper format."""
    return json.dumps({"extractions": list(groups)})


def test_valid_items_pass_through() -> None:
    """Well-formed items are returned unchanged and nothing is counted."""
    handler = TolerantFormatHandler()
    group = {"ahi": "AHI 18.2", "ahi_attributes": {"value": "18.2", "status": "asserted"}}
    assert handler.parse_output(output(group)) == [group]
    assert (handler.malformed, handler.nulls) == (0, 0)


def test_list_or_object_span_is_dropped_with_its_attributes_and_counted() -> None:
    """A list/object where a quoted phrase belongs is malformed: dropped and counted, siblings kept."""
    handler = TolerantFormatHandler()
    bad = {"group2_conditions": ["edema"], "group2_conditions_attributes": {"status": "asserted"}}
    worse = {"spo2": {"text": "SpO2 87%"}}
    good = {"pao2": "PaO2 54 mmHg", "pao2_attributes": {"value": "54"}}
    assert handler.parse_output(output(bad, worse, good)) == [good]
    assert handler.malformed == 2
    assert handler.nulls == 0


def test_null_span_is_a_blank_placeholder() -> None:
    """A null span means "not found": counted as a null, not as malformed."""
    handler = TolerantFormatHandler()
    assert handler.parse_output(output({"home_benefit": None, "home_benefit_attributes": None})) == []
    assert (handler.malformed, handler.nulls) == (0, 1)


def test_bad_attributes_are_dropped_but_the_span_kept() -> None:
    """Non-dict attributes are removed; the extraction itself survives."""
    handler = TolerantFormatHandler()
    assert handler.parse_output(output({"ahi": "AHI 18.2", "ahi_attributes": "18.2"})) == [{"ahi": "AHI 18.2"}]
    assert handler.malformed == 0


def test_bool_span_is_malformed() -> None:
    """``true`` is not quoted text, so it is dropped (LangExtract would accept it as an int)."""
    handler = TolerantFormatHandler()
    assert handler.parse_output(output({"expected_to_improve": True})) == []
    assert handler.malformed == 1


def test_counts_accumulate_across_chunks_and_reset() -> None:
    """Counts add up over calls (chunks) until reset."""
    handler = TolerantFormatHandler()
    handler.parse_output(output({"a": None}))
    handler.parse_output(output({"b": ["x"]}))
    assert (handler.malformed, handler.nulls) == (1, 1)
    handler.reset()
    assert (handler.malformed, handler.nulls) == (0, 0)
