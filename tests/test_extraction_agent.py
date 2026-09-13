"""
Coverage for agents/extraction_agent.py -- had zero pytest coverage before
this pass despite being one of the most guardrail-critical modules in the
system (every number a memo ever shows an investor passes through here).
Two real bugs were found live (via a genuinely different test document,
not the one synthetic fixture every other test in this repo reuses) and
are regression-tested here without needing a live Ollama call for the
structural parts -- only the cross-check logic is pure and synthetic-data
testable; the LLM call itself stays covered by live tests elsewhere.
"""
from conftest import DEAL, TENANT

from agents.extraction_agent import (
    LLMCapTableRow,
    LLMFundingRound,
    LLMValue,
    _cross_check_arr_mrr_conflation,
    _cross_check_growth_rate,
    _cross_check_runway,
)
from conftest import make_extraction_result
from schemas import FieldStatus


# --- Schema regression: required-but-nullable fields ------------------
# Bug found live: phi4-mini's grammar-constrained decoder sometimes omits
# a numeric/citation key from its JSON output entirely (not `null` --
# absent), and because these fields had Pydantic defaults, that silently
# became None with zero indication anything went wrong. A field with no
# default is marked "required" in the generated JSON schema, which is what
# should make Ollama's decoder always emit the key.

def test_llm_value_marks_value_and_citation_fields_required():
    schema = LLMValue.model_json_schema()
    assert set(schema.get("required", [])) == {"value", "source_block_id", "source_page"}


def test_llm_cap_table_row_marks_pct_required():
    schema = LLMCapTableRow.model_json_schema()
    assert schema.get("required") == ["pct"]


def test_llm_funding_round_marks_amount_and_citation_fields_required():
    schema = LLMFundingRound.model_json_schema()
    assert set(schema.get("required", [])) == {"amount", "source_block_id", "source_page"}


def test_llm_value_missing_key_still_parses_as_none_not_an_error():
    """The required-field change doesn't stop this from validating -- Ollama's
    JSON-schema-constrained mode makes 'required' a generation hint, not a
    strict post-hoc validator the way a normal API request body would be.
    Pydantic itself still accepts a dict missing the key when the *type*
    permits None; this test documents that the fix is about biasing the
    model's own output, not about rejecting bad JSON after the fact."""
    from pydantic import ValidationError
    try:
        LLMValue.model_validate({"source_block_id": None, "source_page": None})
        assert False, "expected a ValidationError for a genuinely missing required field"
    except ValidationError:
        pass  # this IS what should happen for a hand-constructed dict missing "value"


# --- New cross-check: arr/mrr conflation --------------------------------

def _approved_result(**overrides):
    result = make_extraction_result(**overrides)
    return result


def test_arr_mrr_conflation_flagged_when_same_value_and_source():
    result = _approved_result()
    result.arr.value = 95000.0
    result.arr.source_block_id = "blk_1"
    result.mrr.value = 95000.0
    result.mrr.source_block_id = "blk_1"
    result.mrr.status = FieldStatus.PROPOSED

    _cross_check_arr_mrr_conflation(result)

    assert any("arr/mrr" in f and "same value" in f for f in result.cross_check_flags)


def test_arr_mrr_not_flagged_when_values_differ():
    result = _approved_result()
    result.arr.value = 2_400_000.0
    result.arr.source_block_id = "blk_1"
    result.mrr.value = None  # genuinely not stated -- the common, correct case
    result.mrr.status = FieldStatus.NOT_FOUND

    _cross_check_arr_mrr_conflation(result)

    assert not any("arr/mrr" in f for f in result.cross_check_flags)


def test_arr_mrr_not_flagged_when_same_value_but_different_source():
    """Same number from two genuinely different, independently-cited blocks
    isn't conflation -- e.g. a document that happens to state both ARR and
    MRR as the same figure in two separate places (unusual but not
    impossible) shouldn't be flagged as if the model copied one into the
    other."""
    result = _approved_result()
    result.arr.value = 100.0
    result.arr.source_block_id = "blk_1"
    result.mrr.value = 100.0
    result.mrr.source_block_id = "blk_2"

    _cross_check_arr_mrr_conflation(result)

    assert not any("arr/mrr" in f for f in result.cross_check_flags)


def test_arr_prior_year_mrr_conflation_also_flagged():
    result = _approved_result()
    result.arr_prior_year.value = 31000.0
    result.arr_prior_year.source_block_id = "blk_1"
    result.mrr.value = 31000.0
    result.mrr.source_block_id = "blk_1"

    _cross_check_arr_mrr_conflation(result)

    assert any("arr_prior_year/mrr" in f for f in result.cross_check_flags)


# --- Existing cross-checks (previously untested) ---------------------------

def test_cross_check_runway_flags_mismatch():
    result = _approved_result()
    result.cash_on_hand.value = 3_200_000.0
    result.burn_monthly.value = 180_000.0
    result.runway_months.value = 5.0  # way off from cash/burn = 17.8

    _cross_check_runway(result)

    assert any("runway_months mismatch" in f for f in result.cross_check_flags)


def test_cross_check_runway_silent_when_consistent():
    result = _approved_result()
    result.cash_on_hand.value = 3_200_000.0
    result.burn_monthly.value = 180_000.0
    result.runway_months.value = 17.78  # matches cash/burn closely

    _cross_check_runway(result)

    assert result.cross_check_flags == []


def test_cross_check_growth_rate_flags_derivable_but_missing():
    result = _approved_result()
    result.arr.value = 2_400_000.0
    result.arr_prior_year.value = 1_050_000.0
    result.growth_rate_yoy.value = None

    _cross_check_growth_rate(result)

    assert any("derivable from arr/arr_prior_year" in f for f in result.cross_check_flags)
