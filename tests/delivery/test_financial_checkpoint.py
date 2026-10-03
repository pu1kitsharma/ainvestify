from delivery.worker import financial_checkpoint, draft_memo_issue, memo_coverage_issue


def test_uploaded_workbook_errors_block_projection_generation():
    inventory = {"source": {"findings": [
        {"code": "stored_cell_error", "part": "xl/worksheets/sheet1.xml", "cell": "A1"},
        {"code": "broken_formula_reference", "part": "xl/worksheets/sheet1.xml", "cell": "A1"},
    ]}}
    result = financial_checkpoint(inventory)
    assert result == {"state": "blocked", "reason": "source_workbook_formula_errors",
                      "error_count": 2}


def test_clean_structure_still_requires_recalculation():
    assert financial_checkpoint({"source": {"findings": []}}) == {
        "state": "blocked", "reason": "formula_dependency_and_recalculation_review_required"}


def test_single_publisher_can_only_generate_a_deferred_internal_draft():
    one = {'public_publishers': 1, 'private_documents': 0,
           'coverage_complete': True, 'omitted_passages': 0}
    assert draft_memo_issue(one, 'defer_pending_evidence') is None
    assert draft_memo_issue(one, 'advance_to_diligence') == 'single_source_requires_model_defer'
    assert draft_memo_issue(one, 'decline') == 'single_source_requires_model_defer'
    assert draft_memo_issue({'public_publishers': 0, 'private_documents': 0,
                             'coverage_complete': True, 'omitted_passages': 0},
                            'defer_pending_evidence') == 'no_usable_source_group'
    assert draft_memo_issue({'public_publishers': 2, 'private_documents': 0,
                             'coverage_complete': True, 'omitted_passages': 0},
                            'advance_to_diligence') is None


def test_incomplete_source_inventory_blocks_even_saved_defer_or_advance():
    coverage = {'public_publishers': 2, 'private_documents': 1,
                'coverage_complete': False, 'omitted_passages': 1}
    assert memo_coverage_issue(coverage) == 'source_coverage_incomplete'
    assert draft_memo_issue(coverage, 'defer_pending_evidence') == 'source_coverage_incomplete'
    assert draft_memo_issue(coverage, 'advance_to_diligence') == 'source_coverage_incomplete'
    assert memo_coverage_issue({**coverage, 'coverage_complete': True}) == 'source_coverage_incomplete'
    assert memo_coverage_issue({**coverage, 'omitted_passages': 0}) == 'source_coverage_incomplete'
