import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from schemas import ExtractedValue, ExtractionResult, FieldStatus
from store import Store

TENANT = "tenant_test"
DEAL = "deal_test"
DOC = "doc_test"


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.db")
    yield s
    s.close()


def make_extraction_result(**overrides) -> ExtractionResult:
    """A minimal but realistic ExtractionResult for review-decision tests --
    every scalar field proposed with a valid citation, mirroring what a
    real extraction pass produces before human review."""
    defaults = dict(
        tenant_id=TENANT, deal_id=DEAL, document_id=DOC,
        arr=ExtractedValue(value=2_400_000, unit="USD", source_block_id="blk_1", source_page=1),
        arr_prior_year=ExtractedValue(value=1_050_000, unit="USD", source_block_id="blk_1", source_page=1),
        mrr=ExtractedValue(value=None, unit="USD", status=FieldStatus.NOT_FOUND, reason="not_found_in_source"),
        growth_rate_yoy=ExtractedValue(value=None, unit="%", status=FieldStatus.NOT_FOUND, reason="not_found_in_source"),
        burn_monthly=ExtractedValue(value=180_000, unit="USD", source_block_id="blk_1", source_page=1),
        cash_on_hand=ExtractedValue(value=3_200_000, unit="USD", source_block_id="blk_1", source_page=1),
        runway_months=ExtractedValue(value=17.8, source_block_id="blk_1", source_page=1),
        headcount=ExtractedValue(value=34, source_block_id="blk_2", source_page=1),
    )
    defaults.update(overrides)
    return ExtractionResult(**defaults)
