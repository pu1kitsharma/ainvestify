"""Synthetic memo contract checks; no real company content or network calls."""
import json

import pytest

from agents.research.investment_memo import Source, Memo, Review, generate_memo, renderable_sections, validate_memo, _assertion_numbers
from agents.research.staged_memo import (MemoPartA, ProsePatchA, SingleClaimField, apply_prose_patch,
                                         apply_single_claim_field,
                                         _check_temporal_relation, _quote_candidates,
                                         quote_issues, claim_number_issues,
                                         isolated_field_result, single_claim_payload,
                                         SINGLE_CLAIM_FIELD, run_stage)
from agents.inference.model_authorship import recorded_call
from agents.preparation.preparation_budget import PreparationBudget, preparation_budget


QUOTE = "Example Labs describes a scheduling tool for clinics and a pilot with one clinic."
SOURCE = Source(id="S1", url="https://example.org/company", title="Example Labs",
                passage=QUOTE + " The report does not disclose revenue or customer retention.",
                version="version123", attribution="Example source")


def test_month_equivalence_does_not_turn_modal_may_into_a_number():
    assert _assertion_numbers('Funding date is June 2026.') == {'06', '2026'}
    assert _assertion_numbers('The result may change.') == set()


@pytest.mark.parametrize('amount', [
    {'original': '100000', 'currency': 'USD'},
    'USD 100,000',
])
def test_reviewed_memo_cannot_claim_a_reported_amount_is_missing(amount):
    source = SOURCE.model_copy(update={'passage': json.dumps({
        'description': SOURCE.passage, 'amount': amount})})
    output = draft()
    # The source is a structured record, so each numeric claim quotes all of it.
    output['recommendation_claims'][0]['quote'] = source.passage
    for field in ('investment_thesis', 'business_and_market', 'differentiation_and_execution',
                  'risks_and_countercase', 'diligence_plan'):
        output[field]['claims'][0]['quote'] = source.passage
    validate_memo(Memo.model_validate(output), [source])
    output['recommendation_reason'] += ' The source does not establish the funding amount [S1].'
    with pytest.raises(ValueError, match='source reports an amount'):
        validate_memo(Memo.model_validate(output), [source])


RECORD_SOURCE = Source(id='S2', url='https://example.invalid/registry', title='Registry',
                       passage=json.dumps({'company': 'Example Labs', 'label': 'Seed',
                                           'date': '2025-06', 'amount': 'USD 100000',
                                           'status': 'unknown'}, separators=(',', ':')),
                       version='registry-v1', attribution='Synthetic registry')
# Shape of the saved full-draft quote: the record cut off after its date.
TRUNCATED = '{"company":"Example Labs","label":"Seed","date":"2025-06"'


def record_draft(assertion, quote):
    output = draft()
    output['risks_and_countercase']['claims'] = [
        {'source_id': 'S2', 'quote': quote, 'assertion': assertion}]
    output['risks_and_countercase']['analysis'] = (
        'A registry lists a seed financing entry with unknown status [S2]. The entry is a source '
        'report and does not show that the round closed or that the company holds the cash, so '
        'available capital may be lower than the listing implies until records are obtained.')
    return output


def test_drafting_contract_requires_the_complete_record_for_a_numeric_structured_claim():
    from agents.research.investment_memo import WRITE, claim_quote_issue
    from agents.research.staged_memo import PART_A, PART_B
    for prompt in (PART_A, PART_B, WRITE):
        assert 'COMPLETE record' in prompt
    for prompt in (PART_A, PART_B):
        assert 'at the END of the clause' in prompt and 'do not stack two markers' in prompt
        assert 'contiguous key/value span' not in prompt
    description = Memo.model_json_schema()['$defs']['Claim']['properties']['quote']['description']
    assert 'the quote is the complete record' in description
    sources = [SOURCE, RECORD_SOURCE]
    record = RECORD_SOURCE.passage

    amount = 'A Seed round is recorded for 2025-06 with an amount of USD 100000.'
    # Truncated after the date: the amount is not covered, the existing number rule fires.
    with pytest.raises(ValueError, match='numbers absent from its source quote'):
        validate_memo(Memo.model_validate(record_draft(amount, TRUNCATED)), sources)
    # Truncated but covering every stated number: still not the complete record.
    dated = 'The Seed entry is dated 2025-06.'
    with pytest.raises(ValueError, match='without quoting the complete record'):
        validate_memo(Memo.model_validate(record_draft(dated, TRUNCATED)), sources)
    validate_memo(Memo.model_validate(record_draft(dated, record)), sources)
    validate_memo(Memo.model_validate(record_draft(amount, record)), sources)
    # A claim that states no number or date may quote part of the record.
    plain = 'The registry record gives the entry status as unknown.'
    validate_memo(Memo.model_validate(record_draft(plain, '"status":"unknown"')), sources)
    # Number validation is unchanged: a number the record does not hold still fails.
    with pytest.raises(ValueError, match='numbers absent from its source quote'):
        validate_memo(Memo.model_validate(record_draft(
            'A Seed round is recorded with an amount of USD 250000.', record)), sources)
    # Prose passages and records too long to quote whole are outside this rule.
    assert claim_quote_issue('The pilot began in 2025-08.', QUOTE, SOURCE.passage) is None
    long_record = json.dumps({'company': 'Example Labs', 'date': '2025-06', 'note': 'x' * 700})
    assert claim_quote_issue(dated, '"date": "2025-06"', long_record) is None
    assert claim_quote_issue(dated, TRUNCATED, record)


def test_truncated_record_quote_is_repaired_by_the_claim_patch_with_the_complete_record():
    whole = record_draft('The Seed entry is dated 2025-06.', TRUNCATED)
    first_fields = ('recommendation', 'recommendation_reason', 'recommendation_claims',
                    'investment_thesis', 'business_and_market', 'unknowns')
    second_fields = ('differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')
    sources = [SOURCE, RECORD_SOURCE]
    fixed = {'c0': {'assertion': 'The registry record reports a Seed entry dated 2025-06 with an '
                                 'amount of USD 100000 and an unknown status.',
                    'quote': RECORD_SOURCE.passage}}
    model = FakeLocalModel([{key: whole[key] for key in first_fields},
                            {key: whole[key] for key in second_fields}, fixed])
    attempts = []
    result = run_stage('Example Labs', sources, attempts, lambda: None, draft_model=model,
                       correction_model=model, review_model=FakeLocalModel([passing_review()]),
                       budget=PreparationBudget(105, max_calls=6, max_requests=8))
    assert result['state'] == 'accepted'
    patch = attempts[2]
    assert patch['task'] == 'investment_memo_part_b_claim_patch'
    # The only quote the model may choose for a structured record is the whole record.
    assert patch['input']['targets'][0]['choices'] == [RECORD_SOURCE.passage]
    claim = result['accepted']['memo']['risks_and_countercase']['claims'][0]
    assert claim['quote'] == RECORD_SOURCE.passage and 'USD 100000' in claim['assertion']
    assert renderable_sections(result['accepted'], sources, attempts)


def test_reviewed_memo_cannot_expose_internal_renderer_language():
    output = draft()
    output['risks_and_countercase']['analysis'] += (
        ' The model-authored claims remain frozen beside this prose by the renderer.')
    with pytest.raises(ValueError, match='internal workflow language'):
        validate_memo(Memo.model_validate(output), [SOURCE])


def test_reviewed_memo_cannot_pass_a_numeric_prompt_constraint_to_materials():
    output = draft()
    output['business_and_market']['analysis'] += (
        ' The allowed numeric values list is empty [S1].')
    with pytest.raises(ValueError, match='internal workflow language'):
        validate_memo(Memo.model_validate(output), [SOURCE])


def test_currency_scale_and_source_integer_are_numeric_equivalents():
    assert _assertion_numbers('$9M Seed in October 2025') == {'9000000', '10', '2025'}
    assert _assertion_numbers('USD 9 million') == {'9000000'}
    assert _assertion_numbers('"original":"9000000","date":"2025-10"') == {
        '9000000', '2025', '10'}
    assert _assertion_numbers('$8M') != _assertion_numbers('9000000 USD')


def test_quote_repair_never_pads_a_short_fact_into_unrelated_sentence():
    passage = 'Seed. Another entity reported $5M in 2025.'
    assert _quote_candidates(passage, 'Seed') == [] or all(
        not ('Seed' in option and '$5M' in option)
        for option in _quote_candidates(passage, 'Seed'))


def test_recorded_as_of_date_rejects_false_temporal_direction():
    with pytest.raises(ValueError, match='past source month is future'):
        _check_temporal_relation('The June 2026 event is future relative to October 2026.',
                                 '2026-10-02')
    _check_temporal_relation('The June 2026 event is past relative to October 2026.',
                             '2026-10-02')


def test_prose_patch_cannot_embed_a_citation_marker():
    part = MemoPartA.model_validate({k: draft()[k] for k in (
        'recommendation', 'recommendation_reason', 'recommendation_claims',
        'investment_thesis', 'business_and_market', 'unknowns')})
    sentence = {'text': 'The reported clinic pilot [S1] warrants checking dated use records and buyer decisions.',
                'claim_index': 0}
    patch = ProsePatchA.model_validate({key: [sentence, sentence] for key in (
        'recommendation_reason', 'investment_thesis_analysis', 'business_and_market_analysis')})
    with pytest.raises(ValueError, match='citation marker belongs'):
        apply_prose_patch(part, patch)


def test_two_claims_from_one_source_cannot_pool_numbers_for_one_citation():
    source = SOURCE.model_copy(update={"passage": SOURCE.passage +
        " Example raised $5M. Example was founded in 2019."})
    output = draft()
    output['investment_thesis']['claims'] = [
        {'source_id': 'S1', 'quote': 'Example raised $5M.',
         'assertion': 'Example reports raising $5M.'},
        {'source_id': 'S1', 'quote': 'Example was founded in 2019.',
         'assertion': 'Example reports founding in 2019.'}]
    output['investment_thesis']['analysis'] = (
        'The company raised $5M in 2019 [S1], which might fund a product pilot. '
        'Further records would be needed to verify the raise, the founding date, '
        'customer use, and whether the business can earn sustainable revenue.')
    with pytest.raises(ValueError, match='adjacent source claim'):
        validate_memo(Memo.model_validate(output), [source])


def test_digits_in_exact_cited_company_name_are_not_treated_as_a_financial_number():
    quote = QUOTE.replace('Example Labs', '1001 AI')
    source = SOURCE.model_copy(update={'title': '1001 AI',
        'passage': SOURCE.passage.replace('Example Labs', '1001 AI')})
    output = draft()
    for field in ('recommendation_claims',):
        output[field][0]['quote'] = quote
    for field in ('investment_thesis', 'business_and_market',
                  'differentiation_and_execution', 'risks_and_countercase',
                  'diligence_plan'):
        output[field]['claims'][0]['quote'] = quote
    output['investment_thesis']['analysis'] = output['investment_thesis']['analysis'].replace(
        'The source describes', '1001 AI describes')
    validate_memo(Memo.model_validate(output), [source])


def test_company_name_digits_cannot_support_an_unrelated_quantity():
    quote = QUOTE.replace('Example Labs', 'Series 12 Corp')
    source = SOURCE.model_copy(update={'title': 'Series 12 Corp',
        'passage': SOURCE.passage.replace('Example Labs', 'Series 12 Corp')})
    output = draft()
    output['recommendation_claims'][0]['quote'] = quote
    for field in ('investment_thesis', 'business_and_market',
                  'differentiation_and_execution', 'risks_and_countercase',
                  'diligence_plan'):
        output[field]['claims'][0]['quote'] = quote
    output['investment_thesis']['analysis'] = (
        'The company reports 12 new customers [S1]. ' + output['investment_thesis']['analysis'])
    with pytest.raises(ValueError, match='numeric prose is not covered'):
        validate_memo(Memo.model_validate(output), [source])


def test_company_name_number_cannot_credit_a_second_numeric_use():
    quote = QUOTE.replace('Example Labs', 'Series 12 Corp')
    source = SOURCE.model_copy(update={'title': 'Series 12 Corp',
        'passage': SOURCE.passage.replace('Example Labs', 'Series 12 Corp')})
    output = draft()
    output['recommendation_claims'][0]['quote'] = quote
    for field in ('investment_thesis', 'business_and_market',
                  'differentiation_and_execution', 'risks_and_countercase',
                  'diligence_plan'):
        output[field]['claims'][0]['quote'] = quote
    output['investment_thesis']['analysis'] = (
        'Series 12 Corp reports 12 new customers [S1]. '
        'This would change the diligence question, but the retained passage only '
        'describes a clinic scheduling pilot and does not establish customer count, '
        'repeat buying, revenue, or durable use of the product.')
    with pytest.raises(ValueError, match='numeric prose is not covered'):
        validate_memo(Memo.model_validate(output), [source])

    part = MemoPartA.model_validate({key: output[key] for key in (
        'recommendation', 'recommendation_reason', 'recommendation_claims',
        'investment_thesis', 'business_and_market', 'unknowns')})
    patch = {'sentences': [
        'Series 12 Corp reports 12 new customers, which would materially change the commercial diligence case.',
        'The retained source describes a pilot, so diligence needs dated buyer records before inferring demand.']}
    with pytest.raises(ValueError, match='numbers absent from the isolated exact claim'):
        apply_single_claim_field(part, 'investment_thesis', patch,
                                 as_of_date='2026-10-03', company='Series 12 Corp')
    output['investment_thesis']['claims'][0]['assertion'] = (
        'Series 12 Corp reports 12 new customers.')
    with pytest.raises(ValueError, match='assertion contains numbers absent'):
        validate_memo(Memo.model_validate(output), [source])
    assert any('investment_thesis' in issue for issue in
               claim_number_issues(Memo.model_validate(output), [source]))


def test_spelled_quantity_after_last_citation_still_needs_a_source():
    output = draft()
    output['investment_thesis']['analysis'] += ' The company has five new markets.'
    with pytest.raises(ValueError, match='numeric prose needs an adjacent source citation'):
        validate_memo(Memo.model_validate(output), [SOURCE])


def test_isolated_field_cannot_reuse_company_name_digits_as_a_metric():
    value = {key: draft()[key] for key in (
        'recommendation', 'recommendation_reason', 'recommendation_claims',
        'investment_thesis', 'business_and_market', 'unknowns')}
    value['recommendation_claims'][0]['quote'] = QUOTE.replace('Example Labs', 'Series 12 Corp')
    part = MemoPartA.model_validate(value)
    patch = {'sentences': [
        'The source reports 12 new customers, which would materially alter the commercial diligence decision if verified.',
        'The reported pilot still needs dated buyer records and revenue evidence before it can support an investment thesis.']}
    with pytest.raises(ValueError, match='numbers absent from the isolated exact claim'):
        apply_single_claim_field(part, 'recommendation_reason', patch,
                                 as_of_date='2026-10-02', company='Series 12 Corp')


def section(heading):
    return {"heading": heading,
            "analysis": ("The source describes a scheduling tool and one pilot [S1]. "
                         "This may warrant investigation, but the record does not establish repeat demand, "
                         "earned revenue, retention, or an attractive price. The proposed diligence would "
                         "test whether the reported pilot supports a repeatable business rather than assume it does."),
            "claims": [{"source_id": "S1", "quote": QUOTE,
                        "assertion": "The source reports a scheduling tool for clinics and a pilot with one clinic."}]}


def draft():
    return {"recommendation": "defer_pending_evidence",
            "recommendation_reason": ("The reported pilot [S1] is an initial reason to ask further questions, "
                                      "but it does not establish commercial demand or an investable price. "
                                      "The next decision should follow evidence on repeated use and actual economics."),
            "recommendation_claims": [{"source_id": "S1", "quote": QUOTE,
                "assertion": "The source reports a scheduling tool for clinics and a pilot with one clinic."}],
            "investment_thesis": section("Investment thesis"),
            "business_and_market": section("Business and market"),
            "differentiation_and_execution": section("Differentiation and execution"),
            "risks_and_countercase": section("Risks and countercase"),
            "diligence_plan": section("Diligence plan"),
            "unknowns": [{"question": "Does the pilot show repeat customer demand?",
                          "why_it_matters": "One pilot does not establish a repeatable commercial product.",
                          "evidence_needed": "Dated product use and customer decision records."},
                         {"question": "What revenue and cost are attributable to this product?",
                          "why_it_matters": "The source does not report economic results or margins.",
                          "evidence_needed": "Company accounts and a scoped recognition policy."}]}


def passing_review():
    return {"verdict": "pass", "issues": [],
            "recommendation_check": "The defer decision is proportional to the thin evidence and leaves the outcome open.",
            "source_check": "The reported pilot and product are cited to the retained passage without invented results.",
            "reasoning_check": "The analysis distinguishes a pilot from proven repeat demand and company economics."}


class FakeLocalModel:
    name = "offline-test-model"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.last_response_text = ""
        self.last_call = {"host": "test-double"}

    def generate(self, instruction, evidence, schema):
        self.last_response_text = json.dumps(self.outputs.pop(0))
        return schema.model_validate_json(self.last_response_text)


def test_draft_phase_checkpoints_two_parts_without_spending_analysis_calls():
    whole = draft()
    first_fields = ('recommendation', 'recommendation_reason', 'recommendation_claims',
                    'investment_thesis', 'business_and_market', 'unknowns')
    second_fields = ('differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')
    attempts = []
    first_pass = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=FakeLocalModel([{key: whole[key] for key in first_fields}]),
        part_b_model=FakeLocalModel([]),
        review_model=FakeLocalModel([]), phase='draft_only',
        as_of_date='2026-10-03', budget=PreparationBudget(105, max_calls=1))
    assert first_pass == {'state': 'needs_resume', 'phase': 'part_b_draft_retry_pending'}
    assert [row['task'] for row in attempts] == ['investment_memo_part_a']
    result = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=FakeLocalModel([]),
        part_b_model=FakeLocalModel([{key: whole[key] for key in second_fields}]),
        review_model=FakeLocalModel([]), phase='draft_only',
        as_of_date='2026-10-03', budget=PreparationBudget(105, max_calls=1))
    assert result['state'] == 'draft_ready'
    assert result['draft']['part_a_response_id'] == attempts[0]['id']
    assert result['draft']['part_b_response_id'] == attempts[1]['id']
    assert [row['task'] for row in attempts] == ['investment_memo_part_a', 'investment_memo_part_b']
    replay = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=FakeLocalModel([]), review_model=FakeLocalModel([]),
        phase='draft_only', as_of_date='2026-10-03',
        budget=PreparationBudget(105, max_calls=1))
    assert replay == result and len(attempts) == 2
    accepted = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=FakeLocalModel([]), review_model=FakeLocalModel([passing_review()]),
        phase='analysis_only', as_of_date='2026-10-03',
        budget=PreparationBudget(105, max_calls=2))
    assert accepted['state'] == 'accepted'
    assert [row['task'] for row in attempts[:2]] == ['investment_memo_part_a', 'investment_memo_part_b']
    assert sum(row['task'] == 'investment_memo_review' for row in attempts) == 1


def test_analysis_phase_requires_saved_source_bound_drafts():
    attempts = []
    with pytest.raises(ValueError, match='Part A draft'):
        run_stage('Example Labs', [SOURCE], attempts, lambda: None,
            draft_model=FakeLocalModel([]), review_model=FakeLocalModel([]),
            phase='analysis_only', as_of_date='2026-10-03')
    assert not attempts


def test_finite_correction_ledger_review_phases_replay_exact_model_outputs():
    from tests.research.test_memo_challenge import evidence_review

    whole = draft()
    first_fields = ('recommendation', 'recommendation_reason', 'recommendation_claims',
                    'investment_thesis', 'business_and_market', 'unknowns')
    second_fields = ('differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')
    attempts = []
    common = {'as_of_date': '2026-10-03', 'compact_part_a': False,
              'compact_part_b': False}
    ready = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=FakeLocalModel([{key: whole[key] for key in first_fields}]),
        part_b_model=FakeLocalModel([{key: whole[key] for key in second_fields}]),
        review_model=FakeLocalModel([]), phase='draft_only', **common)
    assert ready['state'] == 'draft_ready'
    corrected = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=FakeLocalModel([]), review_model=FakeLocalModel([]),
        phase='correction_only', **common)
    assert corrected['state'] == 'correction_ready'
    before = len(attempts)
    with pytest.raises(ValueError, match='checkpoint'):
        run_stage('Example Labs', [SOURCE], attempts, lambda: None,
            draft_model=FakeLocalModel([]), review_model=FakeLocalModel([]),
            challenge_model=FakeLocalModel([]), phase='ledger_only', **common)
    assert len(attempts) == before
    ledger = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=FakeLocalModel([]), review_model=FakeLocalModel([]),
        challenge_model=FakeLocalModel([]), phase='ledger_only',
        phase_checkpoint=corrected, **common)
    assert ledger['state'] == 'ledger_ready'
    assert ledger['corrected_memo_digest'] == corrected['corrected_memo_digest']
    accepted = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=FakeLocalModel([]), review_model=FakeLocalModel([evidence_review()]),
        challenge_model=FakeLocalModel([]), phase='review_only',
        phase_checkpoint=ledger, **common)
    assert accepted['state'] == 'accepted'
    assert [row['task'] for row in attempts][-1] == 'investment_memo_review'
    changed = SOURCE.model_copy(update={'version': 'changed'})
    with pytest.raises(ValueError, match='Part A draft|checkpoint'):
        run_stage('Example Labs', [changed], attempts, lambda: None,
            draft_model=FakeLocalModel([]), review_model=FakeLocalModel([]),
            phase='review_only', phase_checkpoint=ledger, **common)


def test_analysis_phase_rejects_a_saved_draft_for_another_source_version():
    whole = draft()
    first_fields = ('recommendation', 'recommendation_reason', 'recommendation_claims',
                    'investment_thesis', 'business_and_market', 'unknowns')
    second_fields = ('differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')
    attempts = []
    run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=FakeLocalModel([{key: whole[key] for key in first_fields}]),
        part_b_model=FakeLocalModel([{key: whole[key] for key in second_fields}]),
        review_model=FakeLocalModel([]), phase='draft_only',
        as_of_date='2026-10-03', budget=PreparationBudget(105, max_calls=2))
    changed = SOURCE.model_copy(update={'version': 'version456'})
    with pytest.raises(ValueError, match='Part A draft'):
        run_stage('Example Labs', [changed], attempts, lambda: None,
            draft_model=FakeLocalModel([]), review_model=FakeLocalModel([]),
            phase='analysis_only', as_of_date='2026-10-03')
    assert len(attempts) == 2


def test_model_authored_memo_and_review_are_recorded_exactly():
    attempts = []
    saves = []
    result = generate_memo("Example Labs", [SOURCE], model=FakeLocalModel([draft(), passing_review()]),
                           attempts=attempts, save=lambda: saves.append(len(attempts)))
    assert result["memo"]["recommendation"] == "defer_pending_evidence"
    assert result["draft_response_id"] == "response_1"
    assert result["review_response_id"] == "response_2"
    assert saves == [1, 2]
    assert all(row["raw_response"] and row["response_hash"] for row in attempts)
    sections = renderable_sections(result, [SOURCE], attempts)
    assert len(sections) == 8
    assert "https://example.org/company" in sections[1][2]
    attempts[0]["raw_response"] = "{}"
    with pytest.raises(ValueError, match="modified"):
        renderable_sections(result, [SOURCE], attempts)


def test_wrong_source_quote_gets_model_authored_correction_before_review():
    output = draft()
    output["investment_thesis"]["claims"][0]["quote"] = "A quote absent from the source"
    attempts = []
    model = FakeLocalModel([output, draft(), passing_review()])
    result = generate_memo("Example Labs", [SOURCE], model=model, attempts=attempts)
    assert result["draft_response_id"] == "response_2"
    assert [row["task"] for row in attempts] == [
        "investment_memo_draft", "investment_memo_correction", "investment_memo_review"]


def test_short_quote_schema_failure_is_recorded_then_corrected():
    output = draft()
    output["diligence_plan"]["claims"][0]["quote"] = "too short"
    attempts = []
    result = generate_memo("Example Labs", [SOURCE],
        model=FakeLocalModel([output, draft(), passing_review()]), attempts=attempts)
    assert result["draft_response_id"] == "response_2"
    assert attempts[0]["failure_kind"] == "schema_validation"
    assert attempts[0]["raw_response"]


def test_unsupported_number_fails_deterministically():
    output = draft()
    output["investment_thesis"]["analysis"] += " The company has 900 customers [S1]."
    with pytest.raises(ValueError, match="numeric prose"):
        validate_memo(Memo.model_validate(output), [SOURCE])


def test_recommendation_and_adjacent_citation_numbers_are_source_bound():
    other = Source(id="S2", url="https://example.org/other", title="Other source",
                   passage="The reported team includes 20 employees, with no revenue figure disclosed.",
                   version="other1234", attribution="Other publisher")
    output = draft()
    output["recommendation_reason"] = ("The company has 900 customers [S1], which would support diligence, "
                                       "but the retained sources do not report such customer records and the "
                                       "recommendation therefore remains defer pending evidence.")
    with pytest.raises(ValueError, match="numeric prose"):
        validate_memo(Memo.model_validate(output), [SOURCE, other])

    output = draft()
    output["investment_thesis"]["claims"].append({"source_id": "S2",
        "quote": "The reported team includes 20 employees, with no revenue figure disclosed.",
        "assertion": "The reported team includes 20 employees."})
    output["investment_thesis"]["analysis"] = (
        "The team has 20 employees [S1]. The source describes a scheduling pilot [S2]. "
        "Further evidence on revenue, retention and price would be needed before any investment decision. "
        "The present record leaves product adoption and commercial economics unresolved for a cautious reviewer.")
    with pytest.raises(ValueError, match="adjacent source claim"):
        validate_memo(Memo.model_validate(output), [SOURCE, other])


def test_model_review_rejection_is_retained_and_blocks_publication():
    review = passing_review()
    review["verdict"] = "revise"
    review["issues"] = [{"field": "investment_thesis", "defect": "The pilot is not enough to establish market demand."}]
    attempts = []
    with pytest.raises(ValueError, match="review rejected"):
        generate_memo("Example Labs", [SOURCE], model=FakeLocalModel([draft(), review]), attempts=attempts)
    assert len(attempts) == 2
    assert Review.model_validate(review).verdict == "revise"


def test_source_context_is_bounded():
    with pytest.raises(ValueError, match="distinct"):
        generate_memo("Example Labs", [SOURCE, SOURCE], model=FakeLocalModel([]))


def test_saved_draft_resumes_only_against_identical_source_payload():
    attempts = []
    first = generate_memo("Example Labs", [SOURCE],
                          model=FakeLocalModel([draft(), passing_review()]), attempts=attempts)
    resumed = generate_memo("Example Labs", [SOURCE], model=FakeLocalModel([passing_review()]),
                            attempts=attempts, draft_response_id=first["draft_response_id"])
    assert resumed["draft_response_id"] == first["draft_response_id"]
    assert resumed["review_response_id"] == "response_3"
    changed = SOURCE.model_copy(update={"passage": SOURCE.passage + " Later data was added."})
    with pytest.raises(ValueError, match="does not match"):
        generate_memo("Example Labs", [changed], model=FakeLocalModel([]),
                      attempts=attempts, draft_response_id=first["draft_response_id"])


def test_three_bounded_model_stages_reconstruct_exact_reviewed_memo():
    whole = draft()
    first_fields = ('recommendation', 'recommendation_reason', 'recommendation_claims',
                    'investment_thesis', 'business_and_market', 'unknowns')
    second_fields = ('differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')
    model = FakeLocalModel([{k: whole[k] for k in first_fields},
                            {k: whole[k] for k in second_fields}])
    reviewer = FakeLocalModel([passing_review()])
    attempts = []
    first = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
                      draft_model=model, review_model=reviewer,
                      as_of_date='2026-08-04')
    second = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
                       draft_model=model, review_model=reviewer,
                       as_of_date='2026-08-04')
    third = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
                      draft_model=model, review_model=reviewer,
                      as_of_date='2026-08-04')
    assert first['state'] == 'accepted'
    assert second['state'] == 'accepted'
    assert third['state'] == 'accepted'
    assert attempts[-1]['input']['as_of_date'] == '2026-08-04'
    assert len(renderable_sections(third['accepted'], [SOURCE], attempts)) == 8
    reviewed_reason = attempts[-1]['input']['memo']['recommendation_reason']
    attempts[-1]['input']['memo']['recommendation_reason'] = 'A different memo.'
    with pytest.raises(ValueError, match='exact memo'):
        renderable_sections(third['accepted'], [SOURCE], attempts)
    attempts[-1]['input']['memo']['recommendation_reason'] = reviewed_reason
    attempts[1]['raw_response'] = '{}'
    with pytest.raises(ValueError, match='modified'):
        renderable_sections(third['accepted'], [SOURCE], attempts)


def test_changed_model_part_requires_fresh_review_of_current_memo():
    whole = draft()
    first_fields = ('recommendation', 'recommendation_reason', 'recommendation_claims',
                    'investment_thesis', 'business_and_market', 'unknowns')
    second_fields = ('differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')
    draft_model = FakeLocalModel([{k: whole[k] for k in first_fields},
                                  {k: whole[k] for k in second_fields}])
    reviewer = FakeLocalModel([passing_review()])
    attempts = []
    for _ in range(3):
        prior = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
                          draft_model=draft_model, review_model=reviewer)
    assert prior['state'] == 'accepted'
    revised = {k: whole[k] for k in first_fields}
    revised['recommendation_reason'] = (
        'The reported clinic pilot [S1] supports a scoped diligence request, '
        'while buyer decisions and commercial economics remain unestablished. '
        'A fresh investment decision requires dated use records and accounts.')
    recorded_call(FakeLocalModel([revised]), 'investment_memo_part_a_correction',
                  'test revision', {'company': 'Example Labs',
                  'sources': [SOURCE.model_dump()]}, MemoPartA, attempts, lambda: None)
    refreshed = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
                          draft_model=FakeLocalModel([]),
                          review_model=FakeLocalModel([passing_review()]))
    assert refreshed['state'] == 'accepted'
    assert refreshed['accepted']['review_response_id'] != prior['accepted']['review_response_id']
    assert len([row for row in attempts if row['task'] == 'investment_memo_review']) == 2


def test_review_revisions_are_local_model_patches_and_exactly_reconstructed():
    whole = draft()
    first_fields = ('recommendation', 'recommendation_reason', 'recommendation_claims',
                    'investment_thesis', 'business_and_market', 'unknowns')
    second_fields = ('differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')
    rejected = passing_review()
    rejected['verdict'] = 'revise'
    rejected['issues'] = [{'field': 'investment_thesis.analysis',
                           'defect': 'The source reported pilot requires a clearer independent diligence test.'}]
    patch = {'sentences': [
        'The source reports a clinic scheduling pilot, which could justify further research into buyer needs.',
        'Diligence should obtain dated use records and buyer decisions before treating this pilot as repeatable demand.']}
    draft_model = FakeLocalModel([{k: whole[k] for k in first_fields},
                                  {k: whole[k] for k in second_fields}])
    prose_model = FakeLocalModel([patch])
    reviewer = FakeLocalModel([rejected, passing_review()])
    attempts = []
    first = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
                      draft_model=draft_model, prose_model=prose_model,
                      review_model=reviewer)
    assert first['state'] == 'needs_resume'
    assert len(attempts) == 3
    accepted = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
                         draft_model=draft_model, prose_model=prose_model,
                         review_model=reviewer)
    assert accepted['state'] == 'accepted'
    assert len(attempts) == 5  # one field correction and one fresh exact-memo review
    assert [row['task'] for row in attempts].count(
        'investment_memo_review_field_investment_thesis') == 1
    assert not any(row['task'].startswith('investment_memo_review_revision_')
                   for row in attempts)
    final_memo = accepted['accepted']['memo']
    for field in ('recommendation_reason', 'business_and_market',
                  'differentiation_and_execution', 'risks_and_countercase',
                  'diligence_plan', 'unknowns'):
        assert final_memo[field] == whole[field]
    assert final_memo['investment_thesis']['analysis'] != whole['investment_thesis']['analysis']
    assert attempts[-1]['input']['memo'] == final_memo
    assert renderable_sections(accepted['accepted'], [SOURCE], attempts)


def test_review_claim_defect_fails_closed_without_rewriting_other_fields():
    whole = draft()
    first_fields = ('recommendation', 'recommendation_reason', 'recommendation_claims',
                    'investment_thesis', 'business_and_market', 'unknowns')
    second_fields = ('differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')
    rejected = passing_review()
    rejected['verdict'] = 'revise'
    rejected['issues'] = [{'field': 'investment_thesis.claims',
                           'defect': 'The claim itself is unsupported by the retained exact quote.'}]
    attempts = []
    first = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=FakeLocalModel([{key: whole[key] for key in first_fields},
                                    {key: whole[key] for key in second_fields}]),
        review_model=FakeLocalModel([rejected]))
    assert first['state'] == 'needs_resume'
    with pytest.raises(ValueError, match='cannot be safely mapped'):
        run_stage('Example Labs', [SOURCE], attempts, lambda: None,
                  draft_model=FakeLocalModel([]), prose_model=FakeLocalModel([]),
                  review_model=FakeLocalModel([]))
    assert len(attempts) == 3


def test_four_review_fields_resume_with_three_calls_per_pass():
    whole = draft()
    first_fields = ('recommendation', 'recommendation_reason', 'recommendation_claims',
                    'investment_thesis', 'business_and_market', 'unknowns')
    second_fields = ('differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')
    fields = ('investment_thesis', 'business_and_market',
              'differentiation_and_execution', 'risks_and_countercase')
    rejected = passing_review()
    rejected['verdict'] = 'revise'
    rejected['issues'] = [{'field': field + '.analysis',
                           'defect': 'The reported pilot requires a specific independent diligence test.'}
                          for field in fields]
    correction = {'sentences': [
        'The reported scheduling pilot may justify a targeted inquiry into whether clinic users found it useful.',
        'Diligence should obtain dated user records and buyer decisions before inferring repeat demand.']}
    attempts = []
    draft_model = FakeLocalModel([{key: whole[key] for key in first_fields},
                                   {key: whole[key] for key in second_fields}])
    prose_model = FakeLocalModel([correction] * 4)
    reviewer = FakeLocalModel([rejected, passing_review()])
    first = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=draft_model, prose_model=prose_model, review_model=reviewer)
    assert first['state'] == 'needs_resume'
    assert len(attempts) == 3
    second = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=draft_model, prose_model=prose_model, review_model=reviewer)
    assert second == {'state': 'needs_resume', 'phase': 'review_field_pending'}
    assert len(attempts) == 6
    third = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=draft_model, prose_model=prose_model, review_model=reviewer)
    assert third['state'] == 'accepted'
    assert len(attempts) == 8
    assert set(third['accepted']['review_field_patch_ids']) == set(fields)
    assert renderable_sections(third['accepted'], [SOURCE], attempts)


def test_staged_memo_corrects_invalid_quote_with_local_model_before_review():
    whole = draft()
    first_fields = ('recommendation', 'recommendation_reason', 'recommendation_claims',
                    'investment_thesis', 'business_and_market', 'unknowns')
    second_fields = ('differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')
    part_a = {k: whole[k] for k in first_fields}
    invalid = json.loads(json.dumps(part_a))
    invalid['recommendation_claims'][0]['quote'] = 'A quote absent from the retained source'
    model = FakeLocalModel([invalid, {k: whole[k] for k in second_fields}, {"q0": QUOTE}])
    reviewer = FakeLocalModel([passing_review()])
    attempts = []
    pending = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=model, review_model=reviewer)
    assert pending == {'state': 'needs_resume', 'phase': 'review_pending'}
    result = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=model, review_model=reviewer)
    assert result['state'] == 'accepted'
    assert [row['task'] for row in attempts] == [
        'investment_memo_part_a', 'investment_memo_part_b',
        'investment_memo_part_a_quote_patch', 'investment_memo_review']
    assert len(renderable_sections(result['accepted'], [SOURCE], attempts)) == 8


def test_staged_correction_reports_all_nonexact_quotes():
    output = draft()
    output['recommendation_claims'][0]['quote'] = 'Invented recommendation quote'
    output['investment_thesis']['claims'][0]['quote'] = 'Invented thesis quote'
    issues = quote_issues(Memo.model_validate(output), [SOURCE])
    assert len(issues) == 2
    assert 'recommendation_reason' in issues[0]
    assert 'investment_thesis' in issues[1]


def test_schema_rejected_prose_is_reused_only_for_exact_saved_base():
    from agents.research.staged_memo import _schema_rejected_patch
    rejected = {'task': 'investment_memo_part_a_prose_patch',
                'failure_kind': 'schema_validation',
                'input': {'base_response_id': 'response_1', 'source_set_digest': 'version-a'},
                'answer': {'recommendation_reason': [{'text': 'Too short', 'claim_index': 0}]},
                'error': 'sentence too short'}
    assert _schema_rejected_patch([rejected], rejected['task'], 'response_1', 'version-a') == {
        'answer': rejected['answer'], 'issue': 'sentence too short'}
    assert _schema_rejected_patch([rejected], rejected['task'], 'response_2', 'version-a') is None
    assert _schema_rejected_patch([rejected], rejected['task'], 'response_1', 'version-b') is None


def test_unsupported_claim_number_routes_to_model_claim_correction():
    whole = draft()
    first_fields = ('recommendation', 'recommendation_reason', 'recommendation_claims',
                    'investment_thesis', 'business_and_market', 'unknowns')
    second_fields = ('differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')
    invalid = {key: whole[key] for key in first_fields}
    invalid = json.loads(json.dumps(invalid))
    invalid['recommendation_claims'][0]['assertion'] += ' It reports $5M in funding.'
    corrected = {'c0': {'assertion': whole['recommendation_claims'][0]['assertion'],
                        'quote': whole['recommendation_claims'][0]['quote']}}
    model = FakeLocalModel([invalid, {key: whole[key] for key in second_fields}, corrected])
    attempts = []
    first = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
                      draft_model=model, correction_model=model,
                      review_model=FakeLocalModel([passing_review()]))
    assert first == {'state': 'needs_resume', 'phase': 'review_pending'}
    assert [row['task'] for row in attempts] == [
        'investment_memo_part_a', 'investment_memo_part_b',
        'investment_memo_part_a_claim_patch']
    assert attempts[-1]['input']['targets'][0]['field'] == 'recommendation_reason'
    assert list(attempts[-1]['answer']) == ['c0']
    resumed = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
                        draft_model=FakeLocalModel([]),
                        correction_model=FakeLocalModel([]),
                        review_model=FakeLocalModel([passing_review()]))
    assert resumed['state'] == 'accepted'
    assert resumed['accepted']['claim_patch_ids'] == {'A': 'response_3'}
    assert [row['task'] for row in attempts].count('investment_memo_part_b') == 1
    # The renderer replays the claim patch: the accepted memo holds the corrected
    # claim, and a result that drops or forges the patch id cannot be rendered.
    assert resumed['accepted']['memo']['recommendation_claims'][0]['assertion'] == (
        whole['recommendation_claims'][0]['assertion'])
    sections = renderable_sections(resumed['accepted'], [SOURCE], attempts)
    assert len(sections) == 8 and '$5M' not in sections[0][1]
    with pytest.raises(ValueError, match='exact reviewed model memo'):
        renderable_sections({**resumed['accepted'], 'claim_patch_ids': {}}, [SOURCE], attempts)
    with pytest.raises(ValueError, match='Claim patch cannot be replayed'):
        renderable_sections({**resumed['accepted'], 'claim_patch_ids': {'A': 'response_2'}},
                            [SOURCE], attempts)
    with pytest.raises(ValueError, match='Unknown model claim patch'):
        renderable_sections({**resumed['accepted'], 'claim_patch_ids': {'C': 'response_3'}},
                            [SOURCE], attempts)


def test_claim_assertion_with_a_citation_marker_is_repaired_by_the_model_not_rendered():
    """Saved full-draft shape: the draft wrote "[S1]" inside a claim assertion."""
    whole = draft()
    first_fields = ('recommendation', 'recommendation_reason', 'recommendation_claims',
                    'investment_thesis', 'business_and_market', 'unknowns')
    second_fields = ('differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')
    clean = whole['investment_thesis']['claims'][0]['assertion']
    marked = json.loads(json.dumps({key: whole[key] for key in first_fields}))
    marked['investment_thesis']['claims'][0]['assertion'] = clean + ' [S1]'
    with pytest.raises(ValueError, match='claim assertion carries a citation marker'):
        validate_memo(Memo.model_validate({**whole, **marked}), [SOURCE])
    leaked = json.loads(json.dumps(whole))
    leaked['diligence_plan']['claims'][0]['assertion'] = (
        'The pilot is the only customer activity recorded in the source set.')
    with pytest.raises(ValueError, match='claim assertion uses internal workflow language'):
        validate_memo(Memo.model_validate(leaked), [SOURCE])

    fixed = {'c0': {'assertion': clean, 'quote': QUOTE}}
    still_marked = {'c0': {'assertion': clean + ' [S1]', 'quote': QUOTE}}
    model = FakeLocalModel([marked, {key: whole[key] for key in second_fields},
                            still_marked, fixed])
    attempts = []
    budget = PreparationBudget(105, max_calls=6, max_requests=8)
    result = run_stage('Example Labs', [SOURCE], attempts, lambda: None, draft_model=model,
                       correction_model=model, review_model=FakeLocalModel([passing_review()]),
                       budget=budget)
    assert result['state'] == 'accepted'
    assert [row['task'] for row in attempts] == [
        'investment_memo_part_a', 'investment_memo_part_b',
        'investment_memo_part_a_claim_patch', 'investment_memo_part_a_claim_patch',
        'investment_memo_review']
    # The model's own marked answer was rejected and fed back; software edited nothing.
    assert 'carries a citation marker' in attempts[2]['semantic_validation_error']
    assert attempts[3]['input']['previous_response_id'] == attempts[2]['id']
    assert attempts[0]['answer']['investment_thesis']['claims'][0]['assertion'].endswith('[S1]')
    assert result['accepted']['memo']['investment_thesis']['claims'][0]['assertion'] == clean
    sections = renderable_sections(result['accepted'], [SOURCE], attempts)
    thesis = next(body for heading, body, _ in sections if heading == 'Investment thesis')
    assert thesis.count('[S1] ' + clean) == 1 and clean + ' [S1]' not in thesis


def test_claim_patch_is_not_started_when_the_pass_cannot_finish_it():
    """Saved full-draft shape: a claim patch begun late in a pass was cancelled twice."""
    from agents.research.staged_memo import PART_A, PART_B
    assert 'NO [S#] marker' in PART_A and 'NO [S#] marker' in PART_B
    assert 'no [S#] marker' in Memo.model_json_schema()['$defs']['Claim']['properties'][
        'assertion']['description']
    whole = draft()
    first_fields = ('recommendation', 'recommendation_reason', 'recommendation_claims',
                    'investment_thesis', 'business_and_market', 'unknowns')
    second_fields = ('differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')
    clean = whole['investment_thesis']['claims'][0]['assertion']
    marked = json.loads(json.dumps({key: whole[key] for key in first_fields}))
    marked['investment_thesis']['claims'][0]['assertion'] = clean + ' [S1]'
    model = FakeLocalModel([marked, {key: whole[key] for key in second_fields},
                            {'c0': {'assertion': clean, 'quote': QUOTE}}])
    attempts = []
    budget = PreparationBudget(105, max_calls=6, max_requests=8)
    budget.started -= 70        # thirty-five seconds left: not enough for a claim patch
    first = run_stage('Example Labs', [SOURCE], attempts, lambda: None, draft_model=model,
                      correction_model=model, review_model=FakeLocalModel([passing_review()]),
                      budget=budget)
    assert first == {'state': 'needs_resume', 'phase': 'claim_patch_pending'}
    # Nothing was started and nothing timed out: no claim-patch row exists yet.
    assert [row['task'] for row in attempts] == ['investment_memo_part_a', 'investment_memo_part_b']
    second = run_stage('Example Labs', [SOURCE], attempts, lambda: None, draft_model=model,
                       correction_model=model, review_model=FakeLocalModel([passing_review()]),
                       budget=PreparationBudget(105, max_calls=6, max_requests=8))
    assert second['state'] == 'accepted'
    assert renderable_sections(second['accepted'], [SOURCE], attempts)


def test_reported_funding_stage_inversion_requires_prose_repair_only_for_progression():
    from agents.research.staged_memo import funding_timeline_conflicts, timeline_repair_targets
    rows = [Source(id='S2', url='https://example.org/round1', title='Round record one',
        passage=json.dumps({'company': 'Example Labs', 'label': 'Series A',
                            'date': '2026-06', 'status': 'unknown'}),
        version='version-s2', attribution='Synthetic source'),
        Source(id='S3', url='https://example.org/round2', title='Round record two',
        passage=json.dumps({'company': 'Example Labs', 'label': 'Pre-Seed',
                            'date': '2026-07', 'status': 'unknown'}),
        version='version-s3', attribution='Synthetic source')]
    conflicts = funding_timeline_conflicts(rows)
    assert len(conflicts) == 1
    assert conflicts[0]['earlier']['source_id'] == 'S2'
    assert conflicts[0]['later']['source_id'] == 'S3'
    other_company = rows[1].model_copy(update={'passage': json.dumps({
        'company': 'Other Labs', 'label': 'Pre-Seed',
        'date': '2026-07', 'status': 'unknown'})})
    assert funding_timeline_conflicts([rows[0], other_company]) == []
    unknown_entity = rows[1].model_copy(update={'passage': json.dumps({
        'company': None, 'label': 'Pre-Seed', 'date': '2026-07'})})
    assert funding_timeline_conflicts([rows[0], unknown_entity]) == []
    assert timeline_repair_targets(Memo.model_validate(draft()), conflicts) == [
        'risks_and_countercase']
    value = draft()
    value['investment_thesis']['analysis'] = (
        'The reported funding trajectory suggests commercial progress [S1]. '
        'The source does not establish revenue, so dated customer and account '
        'records remain necessary before interpreting this as repeatable demand.')
    targets = timeline_repair_targets(Memo.model_validate(value), conflicts)
    assert targets == ['investment_thesis', 'risks_and_countercase']
    value['investment_thesis']['analysis'] = (
        'The reported funding trajectory proves growth, although the stage '
        'discrepancy needs review [S1]. Dated primary records would still be '
        'needed to understand actual financing and commercial performance.')
    assert 'investment_thesis' in timeline_repair_targets(Memo.model_validate(value), conflicts)
    value['investment_thesis']['analysis'] = (
        'The funding trajectory is uncertain, so no progression can be inferred '
        'from the reported stage labels [S1]. Primary dated records are required '
        'before discussing financing or commercial implications.')
    assert timeline_repair_targets(Memo.model_validate(value), conflicts) == [
        'risks_and_countercase']
    value['investment_thesis']['analysis'] = (
        'The reported funding trajectory suggests commercial progress [S1]. '
        'The source does not establish revenue, so dated customer and account '
        'records remain necessary before interpreting this as repeatable demand.')
    value['unknowns'][0]['why_it_matters'] = (
        'The reported funding rounds indicate growth claims, so customer evidence '
        'would help evaluate whether the company can retain paying users.')
    assert 'unknowns[0]' in timeline_repair_targets(Memo.model_validate(value), conflicts)
    value['unknowns'][0] = draft()['unknowns'][0]
    value['unknowns'][0]['why_it_matters'] = (
        'The registry lists a Series A followed by a Pre-Seed, which is '
        'chronologically impossible if standard progression applies. '
        'This discrepancy requires primary financing records.')
    assert 'unknowns[0]' in timeline_repair_targets(Memo.model_validate(value), conflicts)
    value['unknowns'][0] = draft()['unknowns'][0]
    value['investment_thesis']['claims'][0]['assertion'] = (
        'The reported funding trajectory proves growth for the company.')
    assert 'investment_thesis' in timeline_repair_targets(Memo.model_validate(value), conflicts)
    value['investment_thesis']['claims'][0] = draft()['investment_thesis']['claims'][0]
    value['investment_thesis']['heading'] = 'Funding trajectory demonstrates growth'
    assert 'investment_thesis' in timeline_repair_targets(Memo.model_validate(value), conflicts)
    value['investment_thesis']['heading'] = draft()['investment_thesis']['heading']
    value['recommendation_claims'][0]['assertion'] = (
        'The reported funding trajectory proves growth for the company.')
    assert 'recommendation_reason' in timeline_repair_targets(Memo.model_validate(value), conflicts)
    value['recommendation_claims'][0] = draft()['recommendation_claims'][0]
    value['investment_thesis']['analysis'] = (
        'The reported funding trajectory is inconsistent with the listed stage dates [S1]. '
        'The entries require reconciliation against primary records before any '
        'commercial or financing progression could be inferred.')
    assert timeline_repair_targets(Memo.model_validate(value), conflicts) == [
        'risks_and_countercase']
    value['investment_thesis']['analysis'] = (
        'Funding records show contradictory progression and dates [S1]. '
        'Primary dated records are needed to reconcile the source listings. '
        'The supplied entries do not establish a completed financing sequence '
        'or commercial progress, so neither implication should be used yet.')
    assert timeline_repair_targets(Memo.model_validate(value), conflicts) == [
        'risks_and_countercase']
    value['investment_thesis']['analysis'] = (
        'The contradictory funding progression suggests growth [S1], although '
        'the dated entries require primary record reconciliation. The reported '
        'labels alone cannot verify capital receipt or operating performance.')
    assert 'investment_thesis' in timeline_repair_targets(Memo.model_validate(value), conflicts)


def test_review_issue_cannot_target_reviewers_own_check_text():
    from agents.research.investment_memo import ReviewIssue
    import pytest
    with pytest.raises(ValueError):
        ReviewIssue(field='recommendation_check',
                    defect='The reviewer has criticized its own check rather than the memo.')
    assert ReviewIssue(field='unknowns[0]',
                       defect='The unknowns sentence treats a reported event as impossible.').field == 'unknowns[0]'


def _timeline_conflict_fixture():
    rows = [SOURCE,
        Source(id='S2', url='https://example.org/round1', title='Round record one',
            passage=json.dumps({'company': 'Example Labs', 'label': 'Series A',
                                'date': '2026-06', 'status': 'unknown'}),
            version='version-s2', attribution='Synthetic source'),
        Source(id='S3', url='https://example.org/round2', title='Round record two',
            passage=json.dumps({'company': 'Example Labs', 'label': 'Pre-Seed',
                                'date': '2026-07', 'status': 'unknown'}),
            version='version-s3', attribution='Synthetic source')]
    whole = draft()
    whole['investment_thesis']['analysis'] = (
        'The reported funding trajectory suggests commercial progress [S1]. '
        'The source does not establish revenue, so dated customer and account '
        'records remain necessary before interpreting this as repeatable demand.')
    whole['investment_thesis']['claims'].append({
        'source_id': 'S2', 'quote': rows[1].passage,
        'assertion': 'The source reports an unverified Series A label in June 2026.'})
    repaired_thesis = section('Investment thesis')
    repaired_risk = section('Risks and countercase')
    repaired_risk['analysis'] = (
        'The source-reported stage labels and dates conflict and require reconciliation '
        'before they can support any financing sequence [S2] [S3]. Primary dated '
        'closing records would establish what each entry means for diligence.')
    repaired_risk['claims'] = [
        {'source_id': row.id, 'quote': row.passage,
         'assertion': f'The source reports an unverified {"Series A" if row.id == "S2" else "Pre-Seed"} label in {"June" if row.id == "S2" else "July"} 2026.'}
        for row in rows[1:]]
    return rows, whole, repaired_thesis, repaired_risk


def test_timeline_patch_replays_exact_snapshot_before_review():
    from agents.research.staged_memo import (
        timeline_patch_schema, apply_timeline_patch, funding_timeline_conflicts)
    rows, whole, repaired_thesis, repaired_risk = _timeline_conflict_fixture()
    patch = {'t0': repaired_thesis, 't1': repaired_risk}
    assert timeline_patch_schema(Memo.model_validate(whole), [
        'investment_thesis', 'risks_and_countercase']).model_validate(patch)
    conflicts = funding_timeline_conflicts(rows)
    omitted = {'t0': repaired_thesis, 't1': section('Risks and countercase')}
    with pytest.raises(ValueError, match='source conflict coverage'):
        apply_timeline_patch(Memo.model_validate(whole), omitted,
            ['investment_thesis', 'risks_and_countercase'], rows, conflicts)
    first_fields = ('recommendation', 'recommendation_reason', 'recommendation_claims',
                    'investment_thesis', 'business_and_market', 'unknowns')
    second_fields = ('differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')
    draft_model = FakeLocalModel([{key: whole[key] for key in first_fields},
                                  {key: whole[key] for key in second_fields}])
    correction_model = FakeLocalModel([{'t0': repaired_thesis}, {'t0': repaired_risk}])
    review_model = FakeLocalModel([passing_review()])
    attempts = []
    for _ in range(6):
        result = run_stage('Example Labs', rows, attempts, lambda: None,
            draft_model=draft_model, correction_model=correction_model,
            review_model=review_model, as_of_date='2026-10-03')
        if result['state'] != 'needs_resume':
            break
    assert result['state'] == 'accepted'
    assert [row['task'] for row in attempts][:2] == [
        'investment_memo_part_a', 'investment_memo_part_b']
    patch_rows = [row for row in attempts
                  if row['task'] == 'investment_memo_timeline_patch']
    assert [row['input']['targets'] for row in patch_rows] == [
        ['investment_thesis'], ['risks_and_countercase']]
    assert patch_rows[1]['input']['applied_patches'] == [
        {'target': 'investment_thesis', 'response_id': patch_rows[0]['id']}]
    assert result['accepted']['timeline_patch_id'] == patch_rows[-1]['id']
    assert renderable_sections(result['accepted'], rows, attempts)
    from copy import deepcopy
    tampered = deepcopy(attempts)
    tampered_next = next(row for row in tampered
                         if row['id'] == patch_rows[-1]['id'])
    tampered_next['input']['memo_digest'] = 'changed-snapshot'
    with pytest.raises(ValueError, match='Timeline repair cannot be replayed'):
        renderable_sections(result['accepted'], rows, tampered)

def test_timeline_patch_task_view_keeps_only_target_and_conflict_evidence():
    from agents.research.staged_memo import timeline_patch_payload
    rows = [SOURCE,
        Source(id='S2', url='https://example.org/round1', title='First record',
            passage=json.dumps({'company': 'Example Labs', 'label': 'Series A',
                                'date': '2026-06', 'status': 'unknown'}),
            version='version-s2', attribution='Synthetic source'),
        Source(id='S3', url='https://example.org/round2', title='Second record',
            passage=json.dumps({'company': 'Example Labs', 'label': 'Pre-Seed',
                                'date': '2026-07', 'status': 'unknown'}),
            version='version-s3', attribution='Synthetic source'),
        Source(id='S4', url='https://example.org/unrelated', title='Other record',
            passage='Unrelated source passage with no funding data.', version='version-s4',
            attribution='Synthetic source')]
    memo = Memo.model_validate(draft())
    conflicts = [{'earlier': {'source_id': 'S2'},
                  'later': {'source_id': 'S3'}}]
    base = {'company': 'Example Labs', 'as_of_date': '2026-10-03',
            'sources': [row.model_dump() for row in rows]}
    original = json.loads(json.dumps(base))
    result = timeline_patch_payload(base, memo, ['recommendation_reason'],
                                    conflicts, 'synthetic-digest')
    assert result['contract'] == 'funding-timeline-v2'
    assert result['targets'] == ['recommendation_reason']
    assert set(result['target_fields']) == {'recommendation_reason'}
    assert [row['id'] for row in result['sources']] == ['S1', 'S2', 'S3']
    assert base == original
    with pytest.raises(ValueError, match='unavailable source'):
        timeline_patch_payload({**base, 'sources': base['sources'][:1]}, memo,
                               ['recommendation_reason'], conflicts,
                               'synthetic-digest')


def test_timeline_patch_cannot_relabel_a_section():
    from agents.research.staged_memo import apply_timeline_patch
    memo = Memo.model_validate(draft())
    replacement = section('Investment thesis')
    replacement['analysis'] = (
        'The source describes one pilot [S1]. Primary signed contracts and '
        'dated payment records are needed to assess its commercial value. '
        'The reported pilot alone does not establish repeat revenue, retention '
        'or the economics of delivery, which require separate diligence.')
    assert replacement['heading'] != memo.risks_and_countercase.heading
    changed = apply_timeline_patch(memo, {'t0': replacement},
        ['risks_and_countercase'], [SOURCE], [])
    assert changed.risks_and_countercase.heading == memo.risks_and_countercase.heading


def test_timeline_patch_semantic_retry_is_saved_and_bounded():
    from agents.research.staged_memo import timeline_patch_result
    value = draft()
    value['investment_thesis']['analysis'] = (
        'The reported funding trajectory suggests commercial progress [S1]. '
        'The source does not establish revenue, so dated customer and account '
        'records remain necessary before interpreting this as repeatable demand.')
    memo = Memo.model_validate(value)
    corrected = section('Investment thesis')
    conflicts = []
    payload = {'company': 'Example Labs', 'memo': memo.model_dump(),
               'source_set_digest': 'synthetic-digest', 'conflicts': conflicts,
               'targets': ['investment_thesis'], 'contract': 'funding-timeline-v1'}
    model = FakeLocalModel([{'t0': value['investment_thesis']}, {'t0': corrected}])
    attempts = []
    with preparation_budget(PreparationBudget(105, max_calls=1, max_requests=2)) as budget:
        assert timeline_patch_result(memo, ['investment_thesis'], conflicts,
            [SOURCE], payload, attempts, lambda: None, model, budget) is None
    assert attempts[0]['semantic_validation_error']
    with preparation_budget(PreparationBudget(105, max_calls=1, max_requests=2)) as budget:
        result = timeline_patch_result(memo, ['investment_thesis'], conflicts,
            [SOURCE], payload, attempts, lambda: None, model, budget)
    assert result[0].investment_thesis.analysis == corrected['analysis']
    assert result[1] == 'response_2'
    assert attempts[1]['input']['previous_response_id'] == 'response_1'
    assert len(attempts) == 2


def _timeline_sequence_inputs():
    from agents.research.staged_memo import funding_timeline_conflicts
    rows, whole, repaired_thesis, repaired_risk = _timeline_conflict_fixture()
    base = {'company': 'Example Labs', 'as_of_date': '2026-10-03',
            'sources': [row.model_dump() for row in rows]}
    return (rows, Memo.model_validate(whole), funding_timeline_conflicts(rows), base,
            repaired_thesis, repaired_risk)


def test_timeline_patch_sends_one_target_per_call_across_pass_boundary():
    from agents.research.staged_memo import (
        timeline_patch_sequence, timeline_repair_targets)
    rows, memo, conflicts, base, repaired_thesis, repaired_risk = _timeline_sequence_inputs()
    targets = ['investment_thesis', 'risks_and_countercase']
    assert timeline_repair_targets(memo, conflicts) == targets
    model = FakeLocalModel([{'t0': repaired_thesis}, {'t0': repaired_risk}])
    attempts = []
    with preparation_budget(PreparationBudget(105, max_calls=1, max_requests=2)) as budget:
        assert timeline_patch_sequence(memo, conflicts, rows, base, 'synthetic-digest',
            attempts, lambda: None, model, budget) is None
    assert [row['input']['targets'] for row in attempts] == [['investment_thesis']]
    with preparation_budget(PreparationBudget(105, max_calls=1, max_requests=2)) as budget:
        repaired, ids = timeline_patch_sequence(memo, conflicts, rows, base,
            'synthetic-digest', attempts, lambda: None, model, budget)
    assert ids == [attempts[0]['id'], attempts[1]['id']]
    for index, row in enumerate(attempts):
        assert row['input']['targets'] == [targets[index]]
        assert set(row['input']['target_fields']) == {targets[index]}
        assert row['input']['all_targets'] == targets
        assert 'memo' not in row['input']
    assert attempts[0]['input']['applied_patches'] == []
    assert attempts[1]['input']['applied_patches'] == [
        {'target': 'investment_thesis', 'response_id': attempts[0]['id']}]
    assert attempts[1]['input']['memo_digest'] != attempts[0]['input']['memo_digest']
    assert repaired.investment_thesis.analysis == repaired_thesis['analysis']
    assert repaired.risks_and_countercase.analysis == repaired_risk['analysis']
    assert timeline_repair_targets(repaired, conflicts) == []


def test_timeline_patch_sequence_replays_exactly_without_new_calls():
    from copy import deepcopy
    from agents.research.staged_memo import timeline_patch_sequence
    rows, memo, conflicts, base, repaired_thesis, repaired_risk = _timeline_sequence_inputs()
    attempts = []
    with preparation_budget(PreparationBudget(105, max_calls=2, max_requests=4)) as budget:
        first = timeline_patch_sequence(memo, conflicts, rows, base, 'synthetic-digest',
            attempts, lambda: None,
            FakeLocalModel([{'t0': repaired_thesis}, {'t0': repaired_risk}]), budget)
    saved = deepcopy(attempts)
    with preparation_budget(PreparationBudget(105, max_calls=1, max_requests=2)) as budget:
        replayed = timeline_patch_sequence(memo, conflicts, rows, base,
            'synthetic-digest', attempts, lambda: None, FakeLocalModel([]), budget)
    assert replayed[1] == first[1] == [row['id'] for row in saved]
    assert replayed[0].model_dump() == first[0].model_dump()
    assert attempts == saved


def _analysis_only_timeline_case():
    from agents.research.staged_memo import funding_timeline_conflicts
    rows = [Source(id=source_id, url=f'https://example.org/{source_id}',
        title=f'Synthetic listing {source_id}',
        passage=json.dumps({'company': 'Example Labs', 'label': label,
                            'date': date, 'status': 'unknown'}),
        version=f'version-{source_id}', attribution='Synthetic source')
        for source_id, label, date in (
            ('S2', 'Series A', '2026-06'), ('S3', 'Pre-Seed', '2026-07'))]
    value = draft()
    value['risks_and_countercase']['claims'] = [
        {'source_id': row.id, 'quote': row.passage,
         'assertion': f'The listing for {row.id} reports a {label} label.'}
        for row, label in zip(rows, ('Series A', 'Pre-Seed'))]
    value['risks_and_countercase']['analysis'] = (
        'The funding trajectory proves commercial growth [S2]. '
        'The reported entries [S3] make this an attractive company despite the '
        'thin public evidence, so diligence can focus on execution rather than '
        'primary financing records or customer accounts.')
    return [SOURCE, *rows], Memo.model_validate(value), funding_timeline_conflicts(rows)


def test_timeline_analysis_packet_freezes_claims_and_replays_exactly():
    from agents.research.staged_memo import (timeline_patch_sequence,
        timeline_repair_targets, timeline_analysis_eligible)
    rows, memo, conflicts = _analysis_only_timeline_case()
    assert timeline_repair_targets(memo, conflicts) == ['risks_and_countercase']
    assert timeline_analysis_eligible(memo, ['risks_and_countercase'], conflicts)
    prose = ('The reported financing labels conflict [S2] [S3], and the listings '
             'do not establish a verified sequence or received capital. Diligence '
             'needs primary dated transaction records and issuer confirmation '
             'before drawing conclusions about financing or operating progress.')
    attempts = []
    base = {'company': 'Example Labs', 'as_of_date': '2026-10-03',
            'sources': [row.model_dump() for row in rows]}
    with preparation_budget(PreparationBudget(105, max_calls=1, max_requests=2)) as budget:
        repaired, ids = timeline_patch_sequence(memo, conflicts, rows, base,
            'synthetic-digest', attempts, lambda: None,
            FakeLocalModel([{'replacement': prose}]), budget)
    packet = attempts[0]['input']
    assert packet['contract'] == 'funding-timeline-analysis-v1'
    assert not any(key in packet for key in ('memo', 'sources', 'target_fields', 'company'))
    assert packet['conflicts'][0]['earlier']['source_id'] == 'S2'
    assert all('date' not in event for pair in packet['conflicts']
               for event in pair.values())
    assert 'passage' not in json.dumps(packet)
    assert memo.risks_and_countercase.claims == repaired.risks_and_countercase.claims
    assert memo.risks_and_countercase.heading == repaired.risks_and_countercase.heading
    assert repaired.risks_and_countercase.analysis == prose
    assert ids == [attempts[0]['id']]
    with preparation_budget(PreparationBudget(105, max_calls=1, max_requests=2)) as budget:
        replayed = timeline_patch_sequence(memo, conflicts, rows, base,
            'synthetic-digest', attempts, lambda: None, FakeLocalModel([]), budget)
    assert replayed[0].model_dump() == repaired.model_dump()
    assert replayed[1] == ids
    assert len(attempts) == 1


def test_timeline_analysis_rejects_quantity_and_unsupported_resolution():
    from agents.research.staged_memo import apply_timeline_analysis_patch
    rows, memo, conflicts = _analysis_only_timeline_case()
    for prose, message in (
        ('The July listing [S3] conflicts with the earlier listing [S2]. '
         'Primary records are needed before the financing sequence can be '
         'used for a diligence conclusion.', 'omit all quantities'),
        ('The reported labels [S2] [S3] prove fraud despite incomplete '
         'source records. Primary records must be reviewed before any '
         'decision about the company financing can follow.',
         'unsupported resolution')):
        with pytest.raises(ValueError, match=message):
            apply_timeline_analysis_patch(memo, {'replacement': prose},
                'risks_and_countercase', [], rows, conflicts, memo)


def test_timeline_analysis_covers_distributed_conflict_pairs_without_new_claims():
    from agents.research.staged_memo import (funding_timeline_conflicts,
        timeline_repair_targets, timeline_analysis_eligible,
        timeline_analysis_payload, apply_timeline_analysis_patch)
    rows, memo, _ = _analysis_only_timeline_case()
    third = Source(id='S4', url='https://example.org/S4',
        title='Synthetic listing S4', passage=json.dumps({
            'company': 'Example Labs', 'label': 'Seed',
            'date': '2025-10', 'status': 'unknown'}),
        version='version-S4', attribution='Synthetic source')
    value = memo.model_dump()
    value['differentiation_and_execution']['claims'] = [
        *value['risks_and_countercase']['claims'],
        {'source_id': 'S4', 'quote': third.passage,
         'assertion': 'The listing for S4 reports a Seed label.'}]
    value['differentiation_and_execution']['analysis'] = (
        'The source-reported stage labels show a chronological inversion [S2] '
        '[S3] [S4]. This contradiction remains unresolved and needs primary '
        'dated transaction records before a financing history or operating '
        'conclusion can be relied on for the diligence decision.')
    memo = Memo.model_validate(value)
    rows.append(third)
    conflicts = funding_timeline_conflicts(rows)
    targets = timeline_repair_targets(memo, conflicts)
    assert len(conflicts) == 2
    assert targets == ['risks_and_countercase']
    assert timeline_analysis_eligible(memo, targets, conflicts)
    packet = timeline_analysis_payload(memo, targets, 0, conflicts,
                                       'synthetic-digest', [])
    assert len(packet['conflicts']) == 1
    assert {packet['conflicts'][0][side]['source_id'] for side in
            ('earlier', 'later')} == {'S2', 'S3'}
    repaired = apply_timeline_analysis_patch(memo, {'replacement': (
        'The reported financing labels conflict [S2] [S3], and the listings '
        'cannot establish a verified sequence or capital received. Primary '
        'dated transaction records and issuer confirmation are needed before '
        'the financing history informs any diligence conclusion.')},
        'risks_and_countercase', [], rows, conflicts, memo)
    assert repaired.differentiation_and_execution == memo.differentiation_and_execution
    assert repaired.risks_and_countercase.claims == memo.risks_and_countercase.claims


def test_timeline_analysis_exact_renderer_replay_and_tamper_rejection():
    from copy import deepcopy
    rows, memo, _ = _analysis_only_timeline_case()
    whole = memo.model_dump()
    first_fields = ('recommendation', 'recommendation_reason',
                    'recommendation_claims', 'investment_thesis',
                    'business_and_market', 'unknowns')
    second_fields = ('differentiation_and_execution',
                     'risks_and_countercase', 'diligence_plan')
    prose = ('The reported financing labels conflict [S2] [S3], and the listings '
             'do not establish a verified sequence or capital received. Diligence '
             'needs primary dated transaction records and issuer confirmation '
             'before drawing conclusions about financing or operating progress.')
    attempts = []
    draft_model = FakeLocalModel([{key: whole[key] for key in first_fields},
                                  {key: whole[key] for key in second_fields}])
    correction_model = FakeLocalModel([{'replacement': prose}])
    review_model = FakeLocalModel([passing_review()])
    for _ in range(4):
        result = run_stage('Example Labs', rows, attempts, lambda: None,
            draft_model=draft_model, correction_model=correction_model,
            review_model=review_model, as_of_date='2026-10-03')
        if result['state'] != 'needs_resume':
            break
    assert result['state'] == 'accepted'
    assert result['accepted']['timeline_patch_ids'] == [
        row['id'] for row in attempts if row['task'] == 'investment_memo_timeline_patch']
    assert prose in '\n'.join(str(row) for row in renderable_sections(
        result['accepted'], rows, attempts))
    tampered = deepcopy(attempts)
    patch_row = next(row for row in tampered
                     if row['task'] == 'investment_memo_timeline_patch')
    patch_row['input']['memo_digest'] = 'forged-digest'
    with pytest.raises(ValueError, match='Timeline repair cannot be replayed'):
        renderable_sections(result['accepted'], rows, tampered)


def test_timeline_patch_sequence_replays_prior_monolithic_response():
    from copy import deepcopy
    from agents.research.staged_memo import (
        timeline_patch_payload, timeline_patch_result, timeline_patch_sequence)
    rows, memo, conflicts, base, repaired_thesis, repaired_risk = _timeline_sequence_inputs()
    targets = ['investment_thesis', 'risks_and_countercase']
    legacy_payload = timeline_patch_payload(base, memo, targets, conflicts,
                                            'synthetic-digest')
    attempts = []
    with preparation_budget(PreparationBudget(105, max_calls=1, max_requests=2)) as budget:
        legacy = timeline_patch_result(memo, targets, conflicts, rows, legacy_payload,
            attempts, lambda: None,
            FakeLocalModel([{'t0': repaired_thesis, 't1': repaired_risk}]), budget)
    saved = deepcopy(attempts)
    with preparation_budget(PreparationBudget(105, max_calls=1, max_requests=2)) as budget:
        repaired, ids = timeline_patch_sequence(memo, conflicts, rows, base,
            'synthetic-digest', attempts, lambda: None, FakeLocalModel([]), budget)
    assert ids == [legacy[1]]
    assert repaired.model_dump() == legacy[0].model_dump()
    assert attempts == saved


def test_timeline_patch_semantic_retry_targets_only_the_failed_field():
    from agents.research.staged_memo import digest, timeline_patch_sequence
    rows, memo, conflicts, base, repaired_thesis, repaired_risk = _timeline_sequence_inputs()
    model = FakeLocalModel([{'t0': memo.investment_thesis.model_dump()},
                            {'t0': repaired_thesis}, {'t0': repaired_risk}])
    attempts = []
    with preparation_budget(PreparationBudget(105, max_calls=3, max_requests=6)) as budget:
        repaired, ids = timeline_patch_sequence(memo, conflicts, rows, base,
            'synthetic-digest', attempts, lambda: None, model, budget)
    assert len(attempts) == 3
    assert 'repeated the rejected' in attempts[0]['semantic_validation_error']
    retry = attempts[1]['input']
    assert retry['targets'] == ['investment_thesis']
    assert retry['retry_base_digest'] == digest(attempts[0]['input'])
    assert retry['previous_response_id'] == attempts[0]['id']
    assert set(retry['previous_answer']) == {'t0'}
    assert 'memo' not in retry
    assert 'semantic_validation_error' not in attempts[1]
    assert attempts[2]['input']['targets'] == ['risks_and_countercase']
    assert attempts[2]['input']['applied_patches'] == [
        {'target': 'investment_thesis', 'response_id': attempts[1]['id']}]
    assert ids == [attempts[1]['id'], attempts[2]['id']]
    assert repaired.risks_and_countercase.analysis == repaired_risk['analysis']

@pytest.mark.parametrize('part', ['a', 'b'])
def test_schema_invalid_draft_gets_one_saved_feedback_retry(part):
    whole = draft()
    first_fields = ('recommendation', 'recommendation_reason', 'recommendation_claims',
                    'investment_thesis', 'business_and_market', 'unknowns')
    second_fields = ('differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')
    good_a = {key: whole[key] for key in first_fields}
    good_b = {key: whole[key] for key in second_fields}
    invalid = json.loads(json.dumps(good_a if part == 'a' else good_b))
    if part == 'a':
        invalid['recommendation_claims'][0]['quote'] = 'Seed'
        outputs = [invalid, good_a, good_b]
    else:
        invalid['diligence_plan']['claims'][0]['quote'] = 'Seed'
        outputs = [good_a, invalid, good_b]
    attempts = []
    model = FakeLocalModel(outputs)
    first = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=model, review_model=FakeLocalModel([passing_review()]),
        as_of_date='2026-10-03')
    assert first == {'state': 'needs_resume',
                     'phase': f'part_{part}_draft_retry_pending'}
    second = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=model, review_model=FakeLocalModel([passing_review()]),
        as_of_date='2026-10-03')
    assert second['state'] == 'accepted'
    task = f'investment_memo_part_{part}'
    rows = [row for row in attempts if row['task'] == task]
    assert len(rows) == 2
    assert rows[0]['failure_kind'] == 'schema_validation'
    assert rows[1]['input']['previous_response_id'] == rows[0]['id']
    assert 'at least 15 characters' in rows[1]['instruction']
    assert rows[1]['input']['retry_base_digest']


def test_claim_patch_replay_requires_exact_snapshot_and_target_list():
    from agents.research.staged_memo import claim_patch_schema, replay_claim_patch
    whole = draft()
    part = MemoPartA.model_validate({key: whole[key] for key in (
        'recommendation', 'recommendation_reason', 'recommendation_claims',
        'investment_thesis', 'business_and_market', 'unknowns')})
    value = part.model_dump()
    value['recommendation_claims'][0]['assertion'] += ' It reports $5M in funding.'
    invalid = MemoPartA.model_validate(value)
    _, targets = claim_patch_schema(invalid, [SOURCE])
    response = {'c0': {'assertion': part.recommendation_claims[0].assertion,
                       'quote': part.recommendation_claims[0].quote}}
    base = {'company': 'Example Labs', 'source_set_digest': 'snapshot-a',
            'base_response_id': 'response_1', 'targets': targets,
            'as_of_date': '2026-10-03'}
    saved = {'id': 'response_3', 'task': 'investment_memo_part_a_claim_patch',
             'input': base, 'answer': response}
    from agents.inference.model_authorship import digest
    saved['raw_response'] = json.dumps(response)
    saved['response_hash'] = digest(saved['raw_response'])
    kwargs = {'task': saved['task'], 'base_response_id': 'response_1',
              'company': 'Example Labs', 'source_set_digest': 'snapshot-a',
              'as_of_date': '2026-10-03', 'sources': [SOURCE]}
    assert replay_claim_patch(invalid, [saved], **kwargs)[1] == 'response_3'
    assert replay_claim_patch(invalid, [saved], **{**kwargs, 'company': 'Other Labs'}) is None
    assert replay_claim_patch(invalid, [saved], **{**kwargs, 'source_set_digest': 'snapshot-b'}) is None
    assert replay_claim_patch(invalid, [saved], **{**kwargs, 'as_of_date': '2026-10-04'}) is None
    tampered = json.loads(json.dumps(saved))
    tampered['input']['targets'][0]['assertion'] = 'Altered assertion'
    assert replay_claim_patch(invalid, [tampered], **kwargs) is None


def test_claim_patch_batches_fields_and_rejects_cross_claim_numbers():
    from agents.research.staged_memo import claim_patch_schema, apply_claim_patch
    whole = draft()
    part = MemoPartA.model_validate({key: whole[key] for key in (
        'recommendation', 'recommendation_reason', 'recommendation_claims',
        'investment_thesis', 'business_and_market', 'unknowns')})
    value = part.model_dump()
    value['recommendation_claims'][0]['assertion'] += ' It reports $5M.'
    value['investment_thesis']['claims'][0]['assertion'] += ' It reports $7M.'
    value['investment_thesis']['claims'].append({
        'source_id': 'S1', 'quote': QUOTE,
        'assertion': 'The source reports a scheduling tool for clinics.'})
    invalid = MemoPartA.model_validate(value)
    schema, targets = claim_patch_schema(invalid, [SOURCE])
    assert [target['field'] for target in targets] == [
        'recommendation_reason', 'investment_thesis']
    response = {f'c{index}': {
        'assertion': (part.recommendation_claims[0].assertion if index == 0 else
                      part.investment_thesis.claims[0].assertion),
        'quote': target['choices'][0]} for index, target in enumerate(targets)}
    assert schema.model_validate(response).model_dump() == response
    changed = apply_claim_patch(invalid, response, targets, [SOURCE])
    assert changed.recommendation_claims[0].assertion == part.recommendation_claims[0].assertion
    assert changed.investment_thesis.claims[0].assertion == part.investment_thesis.claims[0].assertion
    assert changed.investment_thesis.claims[1] == invalid.investment_thesis.claims[1]
    response['c1']['assertion'] += ' It reports $5M.'
    with pytest.raises(ValueError, match='numbers absent'):
        apply_claim_patch(invalid, response, targets, [SOURCE])


def test_claim_patch_uses_full_short_json_record_for_numeric_context():
    from agents.research.staged_memo import claim_patch_schema
    passage = json.dumps({'company': 'Example 42 AI', 'date': '2026-06',
                          'label': 'Series A', 'status': 'unknown'})
    source = Source(id='S1', url='https://example.invalid/record',
                    title='Example 42 AI', passage=passage,
                    version='synthetic-v1', attribution='Synthetic registry')
    value = {key: draft()[key] for key in (
        'recommendation', 'recommendation_reason', 'recommendation_claims',
        'investment_thesis', 'business_and_market', 'unknowns')}
    value['business_and_market']['claims'][0] = {
        'source_id': 'S1', 'quote': '"status": "unknown"',
        'assertion': 'The Example 42 AI entry dated 2026-06 has unknown status.'}
    part = MemoPartA.model_validate(value)
    _, targets = claim_patch_schema(part, [source])
    assert next(t for t in targets if t['field'] == 'business_and_market')['choices'] == [passage]


def test_claim_patch_timeout_and_numeric_rejection_use_three_saved_calls():
    from agents.research.staged_memo import (
        claim_patch_schema, claim_patch_result, replay_claim_patch)
    from agents.inference.model_authorship import digest
    whole = draft()
    part = MemoPartA.model_validate({key: whole[key] for key in (
        'recommendation', 'recommendation_reason', 'recommendation_claims',
        'investment_thesis', 'business_and_market', 'unknowns')})
    value = part.model_dump()
    value['recommendation_claims'][0]['assertion'] += ' It reports $5M.'
    invalid = MemoPartA.model_validate(value)
    schema, targets = claim_patch_schema(invalid, [SOURCE])
    base = {'company': 'Example Labs', 'source_set_digest': 'synthetic-snapshot',
            'base_response_id': 'response_draft', 'targets': targets,
            'as_of_date': '2026-10-03'}
    timeout = {'id': 'response_1', 'task': 'investment_memo_part_a_claim_patch',
               'input': base, 'error': 'Preparation reached its time limit during inference.',
               'raw_response': '', 'response_hash': digest('')}
    attempts = [timeout]
    model = FakeLocalModel([
        {'c0': {'assertion': invalid.recommendation_claims[0].assertion,
                'quote': QUOTE}},
        {'c0': {'assertion': part.recommendation_claims[0].assertion,
                'quote': QUOTE}}])
    kwargs = {'task': 'investment_memo_part_a_claim_patch',
              'base_payload': base, 'attempts': attempts,
              'save': lambda: None, 'model': model}
    with preparation_budget(PreparationBudget(105, max_calls=2, max_requests=3)) as budget:
        result = claim_patch_result(invalid, [SOURCE], targets, schema,
                                    budget=budget, **kwargs)
    assert attempts[1]['semantic_validation_error'] == (
        'Corrected claim has numbers absent from its exact quote')
    assert attempts[1]['input']['previous_response_id'] == 'response_1'
    assert 'previous_answer' not in attempts[1]['input']
    assert result[1] == 'response_3'
    assert attempts[2]['input']['previous_response_id'] == 'response_2'
    assert replay_claim_patch(invalid, attempts, task=kwargs['task'],
        base_response_id='response_draft', company='Example Labs',
        source_set_digest='synthetic-snapshot', as_of_date='2026-10-03',
        sources=[SOURCE])[1] == 'response_3'


def test_timeline_patch_saved_timeout_has_one_bounded_retry():
    from agents.research.staged_memo import timeline_patch_result
    from agents.inference.model_authorship import digest
    value = draft()
    memo = Memo.model_validate(value)
    targets = ['investment_thesis']
    payload = {'company': 'Example Labs', 'memo': memo.model_dump(),
               'source_set_digest': 'synthetic-snapshot',
               'conflicts': [], 'targets': targets,
               'contract': 'funding-timeline-v1'}
    timeout = {'id': 'response_1', 'task': 'investment_memo_timeline_patch',
               'input': payload, 'error': 'Preparation reached its time limit during inference.',
               'raw_response': '', 'response_hash': digest('')}
    attempts = [timeout]
    changed = section('Investment thesis')
    changed['analysis'] += ' Primary evidence remains necessary before any financing conclusion.'
    with preparation_budget(PreparationBudget(105, max_calls=1, max_requests=2)) as budget:
        result = timeline_patch_result(memo, targets, [], [SOURCE], payload,
            attempts, lambda: None, FakeLocalModel([{'t0': changed}]), budget)
    assert result[1] == 'response_2'
    assert attempts[1]['input']['previous_response_id'] == 'response_1'
    assert 'previous_answer' not in attempts[1]['input']


def test_timeline_patch_is_not_started_when_the_pass_cannot_finish_it():
    """Saved full-draft shape: a timeline patch begun with seconds left was cancelled
    and used up one of its three attempts."""
    from agents.research.staged_memo import timeline_patch_result
    sources, memo, conflicts, payload, _, _ = _timeline_sequence_inputs()
    targets = ['risks_and_countercase']
    attempts = []
    budget = PreparationBudget(105, max_calls=5, max_requests=7)
    budget.started -= 90        # fifteen seconds left
    model = FakeLocalModel([])
    with preparation_budget(budget):
        assert timeline_patch_result(memo, targets, conflicts, sources,
                                     {**payload, 'contract': 'funding-timeline-v2'}, attempts,
                                     lambda: None, model, budget) is None
    assert attempts == [] and budget.calls == 0


def test_timeline_semantic_retry_uses_remaining_pass_calls():
    from agents.research.staged_memo import timeline_patch_result
    memo = Memo.model_validate(draft())
    targets = ['investment_thesis']
    payload = {'company': 'Example Labs', 'memo': memo.model_dump(),
               'source_set_digest': 'synthetic-snapshot',
               'conflicts': [], 'targets': targets,
               'contract': 'funding-timeline-v1'}
    changed = section('Investment thesis')
    changed['analysis'] += ' Primary records remain necessary before deciding.'
    attempts = []
    with preparation_budget(PreparationBudget(105, max_calls=2, max_requests=3)) as budget:
        result = timeline_patch_result(memo, targets, [], [SOURCE], payload,
            attempts, lambda: None,
            FakeLocalModel([{'t0': memo.investment_thesis.model_dump()}, {'t0': changed}]),
            budget)
    assert result[1] == 'response_2'
    assert attempts[0]['semantic_validation_error']
    assert attempts[1]['input']['previous_response_id'] == 'response_1'


def test_claim_correction_can_choose_full_source_event_for_amount_and_date():
    from agents.research.staged_memo import _correction_schema
    event = ('{"company":"Example Labs","date":"2026-09","label":"Seed",'
             '"amount":{"currency":"USD","original":"5000000"}}')
    source = SOURCE.model_copy(update={'passage': event})
    value = {key: draft()[key] for key in (
        'recommendation', 'recommendation_reason', 'recommendation_claims',
        'investment_thesis', 'business_and_market', 'unknowns')}
    value['recommendation_claims'][0]['quote'] = '"original":"5000000"'
    part = MemoPartA.model_validate(value)
    schema = _correction_schema(part, [source], part_a=True).model_json_schema()
    assert event in schema['$defs']['BoundClaim']['properties']['quote']['enum']


def test_isolated_claim_prose_is_recorded_and_exactly_reconstructed():
    whole = draft()
    first_fields = ('recommendation', 'recommendation_reason', 'recommendation_claims',
                    'investment_thesis', 'business_and_market', 'unknowns')
    second_fields = ('differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')
    part_a = {key: whole[key] for key in first_fields}
    part_a['recommendation_reason'] = 'The company raised $5M [S1]. ' + part_a['recommendation_reason']
    isolated = {'sentences': [
        'The reported clinic scheduling pilot warrants checking dated use before treating it as repeatable demand.',
        'The source describes an initial pilot, so diligence should test buyer decisions and subsequent product use.']}
    attempts = []
    first = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=FakeLocalModel([part_a, {key: whole[key] for key in second_fields}]),
        prose_model=FakeLocalModel([isolated]),
        review_model=FakeLocalModel([passing_review()]))
    assert first == {'state': 'needs_resume', 'phase': 'review_pending'}
    accepted = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=FakeLocalModel([]), prose_model=FakeLocalModel([]),
        review_model=FakeLocalModel([passing_review()]))
    assert accepted['state'] == 'accepted'
    assert 'recommendation_reason' in accepted['accepted']['field_patch_ids']
    assert any(row['task'] == 'investment_memo_single_claim_recommendation_reason'
               for row in attempts)
    assert renderable_sections(accepted['accepted'], [SOURCE], attempts)


def test_invalid_isolated_numeric_response_retries_with_exact_feedback_and_replays():
    whole = draft()
    first_fields = ('recommendation', 'recommendation_reason', 'recommendation_claims',
                    'investment_thesis', 'business_and_market', 'unknowns')
    second_fields = ('differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')
    part_a = {key: whole[key] for key in first_fields}
    part_a['recommendation_reason'] = 'The company has 900 customers [S1]. ' + part_a['recommendation_reason']
    invalid = {'sentences': [
        'The reported clinic pilot has 900 customers, which would make commercial diligence a priority if verified.',
        'The source describes a scheduling tool, so buyer records are needed to check repeat demand.']}
    corrected = {'sentences': [
        'The reported clinic scheduling pilot warrants checking dated use before treating it as repeatable demand.',
        'The source describes an initial pilot, so diligence should test buyer decisions and subsequent product use.']}
    attempts = []
    draft_model = FakeLocalModel([part_a, {key: whole[key] for key in second_fields}])
    prose_model = FakeLocalModel([invalid, corrected])
    reviewer = FakeLocalModel([passing_review()])
    first = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=draft_model, prose_model=prose_model, review_model=reviewer,
        as_of_date='2026-10-03')
    assert first == {'state': 'needs_resume', 'phase': 'isolated_field_retry_pending'}
    assert 'numbers absent from the isolated exact claim' in (
        attempts[-1]['semantic_validation_error'])
    assert 'allowed numeric values' not in attempts[-1]['semantic_validation_error']
    failed_raw = attempts[-1]['raw_response']
    accepted = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=draft_model, prose_model=prose_model, review_model=reviewer,
        as_of_date='2026-10-03')
    assert accepted['state'] == 'accepted'
    assert attempts[2]['raw_response'] == failed_raw
    assert attempts[3]['input']['previous_response_id'] == attempts[2]['id']
    assert '900 customers' not in json.dumps(attempts[3]['input']['previous_answer'])
    assert '[quantity omitted] customers' in json.dumps(attempts[3]['input']['previous_answer'])
    assert 'numbers absent' in attempts[3]['input']['validation_issue']
    assert attempts[3]['input']['allowed_numeric_values'] == ['1']
    assert accepted['accepted']['field_patch_ids']['recommendation_reason'] == attempts[3]['id']
    assert renderable_sections(accepted['accepted'], [SOURCE], attempts)


def test_isolated_retry_omits_quote_numbers_missing_from_selected_assertion():
    part_data = {key: draft()[key] for key in (
        'recommendation', 'recommendation_reason', 'recommendation_claims',
        'investment_thesis', 'business_and_market', 'unknowns')}
    part_data['recommendation_claims'][0] = {
        'source_id': 'S1',
        'quote': 'Example Labs reports GBP 6800000 for a July 2026 funding entry.',
        'assertion': 'The publisher marks the funding entry as unconfirmed.'}
    part = MemoPartA.model_validate(part_data)
    invalid = {'sentences': [
        'The publisher reports GBP 6800000 for the funding entry, which would merit verification before diligence.',
        'The July 2026 entry is unconfirmed, so primary closing records are needed before treating it as complete.']}
    corrected = {'sentences': [
        'The publisher marks the funding entry as unconfirmed, so the decision depends on primary transaction evidence.',
        'Diligence should seek signed closing records before treating the reported entry as a completed transaction.']}
    attempts = []
    model = FakeLocalModel([invalid, corrected])
    payload = single_claim_payload('Example Labs', 'recommendation_reason', part,
        base_response_id='response_base', source_set_digest='source_digest',
        as_of_date='2026-10-03')
    assert payload['allowed_numeric_values'] == []
    task = 'investment_memo_single_claim_recommendation_reason'
    changed, response_id = isolated_field_result(part, 'recommendation_reason',
        task=task, instruction=SINGLE_CLAIM_FIELD, base_payload=payload,
        attempts=attempts, save=lambda: None, model=model,
        as_of_date='2026-10-03', company='Example Labs')
    assert attempts[0]['semantic_validation_error'].find('6800000') >= 0
    assert response_id == attempts[1]['id']
    assert attempts[1]['input']['allowed_numeric_values'] == []
    assert '6800000' not in json.dumps(attempts[1]['input']['previous_answer'])
    assert 'July' not in json.dumps(attempts[1]['input']['previous_answer'])
    assert '6800000' not in changed.recommendation_reason
    attempts[1]['input'].pop('allowed_numeric_values')
    replayed, replay_id = isolated_field_result(part, 'recommendation_reason',
        task=task, instruction=SINGLE_CLAIM_FIELD, base_payload=payload,
        attempts=attempts, save=lambda: None, model=FakeLocalModel([]),
        as_of_date='2026-10-03', company='Example Labs')
    assert replay_id == response_id
    assert replayed == changed


def test_isolated_claim_context_masks_unshared_amount_date_and_spelled_quantity():
    part_data = {key: draft()[key] for key in (
        'recommendation', 'recommendation_reason', 'recommendation_claims',
        'investment_thesis', 'business_and_market', 'unknowns')}
    original = {'source_id': 'S1',
        'quote': '1001 AI reports GBP 6.8 million (6800000) in July 2026 and one planned clinic trial.',
        'assertion': 'The publisher marks the funding entry for 1001 AI as unconfirmed.'}
    part_data['recommendation_claims'][0] = original
    part = MemoPartA.model_validate(part_data)
    payload = single_claim_payload('1001 AI', 'recommendation_reason', part,
        base_response_id='response_base', source_set_digest='snapshot',
        as_of_date='2026-10-03')
    from agents.inference.model_authorship import digest
    assert payload['original_claim_digest'] == digest(original)
    assert payload['claim']['source_id'] == 'S1'
    assert '1001 AI' in payload['claim']['quote']
    for hidden in ('6.8 million', '6800000', 'July', '2026', 'one planned'):
        assert hidden not in payload['claim']['quote']
    assert 'as_of_date' not in payload
    assert payload['as_of_date_digest'] == digest('2026-10-03')
    assert payload['claim']['assertion'] != original['assertion'] or payload['claim']['quote'] != original['quote']
    assert part.recommendation_claims[0].quote == original['quote']


def test_isolated_claim_context_keeps_shared_amount_and_date():
    part_data = {key: draft()[key] for key in (
        'recommendation', 'recommendation_reason', 'recommendation_claims',
        'investment_thesis', 'business_and_market', 'unknowns')}
    part_data['recommendation_claims'][0] = {
        'source_id': 'S1',
        'quote': 'The publisher reports GBP 6800000 in July 2026 for the funding entry.',
        'assertion': 'The publisher reports GBP 6800000 in July 2026 for the entry.'}
    payload = single_claim_payload('Example Labs', 'recommendation_reason',
        MemoPartA.model_validate(part_data), base_response_id='response_base',
        source_set_digest='snapshot', as_of_date='2026-10-03')
    assert 'GBP 6800000 in July 2026' in payload['claim']['quote']
    assert {'6800000', '07', '2026'} <= set(payload['allowed_numeric_values'])


def test_review_isolated_payload_masks_prior_prose_and_issue_numbers():
    from agents.research.staged_memo import review_field_payload
    from agents.research.investment_memo import ReviewIssue
    part_data = {key: draft()[key] for key in (
        'recommendation', 'recommendation_reason', 'recommendation_claims',
        'investment_thesis', 'business_and_market', 'unknowns')}
    part_data['recommendation_claims'][0] = {
        'source_id': 'S1',
        'quote': 'Example Labs reports GBP 6800000 in July 2026 for a funding entry.',
        'assertion': 'The publisher marks the funding entry as unconfirmed.'}
    part_data['recommendation_reason'] += ' GBP 6800000 was received in July 2026.'
    part = MemoPartA.model_validate(part_data)
    payload = review_field_payload('Example Labs', 'recommendation_reason', part,
        base_response_id='response_base', source_set_digest='snapshot',
        as_of_date='2026-10-03', review_response_id='review_1',
        reviewed_memo_digest='memo-digest', issues=[ReviewIssue(
            field='recommendation_reason',
            defect='GBP 6800000 in July 2026 is not supported by the assertion.')])
    visible = payload['prior_field'] + json.dumps(payload['review_issues'])
    assert '6800000' not in visible
    assert 'July' not in visible
    assert '2026' not in visible


def test_part_b_waits_when_measured_part_a_duration_exceeds_pass_time():
    import time
    whole = draft()
    first_fields = ('recommendation', 'recommendation_reason', 'recommendation_claims',
                    'investment_thesis', 'business_and_market', 'unknowns')
    attempts = []
    first_budget = PreparationBudget(105, max_calls=1)
    initial = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=FakeLocalModel([{key: whole[key] for key in first_fields}]),
        review_model=FakeLocalModel([]), budget=first_budget,
        as_of_date='2026-10-03')
    assert initial['state'] == 'needs_resume'
    attempts[0]['elapsed_seconds'] = 90
    second_budget = PreparationBudget(105, max_calls=3)
    second_budget.started = time.monotonic() - 20
    deferred = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=FakeLocalModel([]), review_model=FakeLocalModel([]),
        budget=second_budget, as_of_date='2026-10-03')
    assert deferred == {'state': 'needs_resume', 'phase': 'part_b_insufficient_time'}
    assert len(attempts) == 1


def test_legacy_isolated_response_replays_only_exact_original_claim_and_clock():
    part = MemoPartA.model_validate({key: draft()[key] for key in (
        'recommendation', 'recommendation_reason', 'recommendation_claims',
        'investment_thesis', 'business_and_market', 'unknowns')})
    current = single_claim_payload('Example Labs', 'recommendation_reason', part,
        base_response_id='response_base', source_set_digest='snapshot',
        as_of_date='2026-10-03')
    old = {**current, 'prompt_revision': 'isolated-claim-v3',
           'as_of_date': '2026-10-03', 'claim': part.recommendation_claims[0].model_dump()}
    old.pop('as_of_date_digest')
    old.pop('original_claim_digest')
    old.pop('claim_context')
    answer = {'sentences': [
        'The reported clinic pilot warrants checking dated use before treating it as repeatable demand.',
        'The source describes an initial pilot, so diligence should test buyer decisions and subsequent product use.']}
    attempts = []
    recorded_call(FakeLocalModel([answer]),
        'investment_memo_single_claim_recommendation_reason', SINGLE_CLAIM_FIELD,
        old, SingleClaimField,
        attempts, lambda: None)
    options = dict(task='investment_memo_single_claim_recommendation_reason',
        instruction=SINGLE_CLAIM_FIELD, base_payload=current, attempts=attempts,
        save=lambda: None, model=FakeLocalModel([]),
        as_of_date='2026-10-03', company='Example Labs')
    assert isolated_field_result(part, 'recommendation_reason', **options)[1] == 'response_1'
    assert isolated_field_result(part, 'recommendation_reason',
        **{**options, 'as_of_date': '2026-10-04', 'model': None}) is None


def test_unparsed_spelled_quantities_are_masked_and_rejected_in_isolated_prose():
    from agents.research.staged_memo import _mask_unshared_quantities
    assert 'thirty' not in _mask_unshared_quantities(
        'thirty million users', set(), 'Example Labs')
    assert 'several' not in _mask_unshared_quantities(
        'several hundred customers', set(), 'Example Labs')
    part = MemoPartA.model_validate({key: draft()[key] for key in (
        'recommendation', 'recommendation_reason', 'recommendation_claims',
        'investment_thesis', 'business_and_market', 'unknowns')})
    candidate = {'sentences': [
        'The reported pilot has thirty million users, which would require dated buyer records to verify.',
        'Diligence should seek several hundred customer contracts before treating this as demand.']}
    with pytest.raises(ValueError, match='unparsed spelled quantity'):
        apply_single_claim_field(part, 'recommendation_reason', candidate,
                                 as_of_date='2026-10-03', company='Example Labs')


def test_shared_digit_and_scale_quantity_remains_available_to_isolated_prose():
    data = {key: draft()[key] for key in (
        'recommendation', 'recommendation_reason', 'recommendation_claims',
        'investment_thesis', 'business_and_market', 'unknowns')}
    data['recommendation_claims'][0] = {
        'source_id': 'S1',
        'quote': 'Example Labs reports a GBP 9 million funding entry.',
        'assertion': 'The publisher reports a GBP 9 million funding entry.'}
    part = MemoPartA.model_validate(data)
    payload = single_claim_payload('Example Labs', 'recommendation_reason', part,
        base_response_id='response_base', source_set_digest='snapshot',
        as_of_date='2026-10-03')
    assert 'GBP 9 million' in payload['claim']['quote']
    patch = {'sentences': [
        'The source reports a GBP 9 million entry, but the transaction status still requires primary closing evidence.',
        'Diligence should seek signed records before treating the GBP 9 million entry as received capital.']}
    assert 'GBP 9 million' in apply_single_claim_field(part, 'recommendation_reason',
        patch, as_of_date='2026-10-03', company='Example Labs').recommendation_reason


def test_numeric_context_mask_preserves_modal_may_but_masks_dated_may():
    from agents.research.staged_memo import _mask_unshared_quantities
    value = _mask_unshared_quantities(
        'The pilot may continue. A May 2026 funding entry is unconfirmed.',
        set(), 'Example Labs')
    assert 'pilot may continue' in value
    assert 'May' not in value
    assert '2026' not in value


def test_isolated_feedback_masks_numeric_json_keys_values_and_glued_tokens():
    from agents.research.staged_memo import _mask_task_feedback, _mask_unshared_quantities
    feedback = {'sentences': [6800000], '6800000 in 2026': 'source'}
    masked = _mask_task_feedback(feedback, set(), 'Example Labs')
    visible = json.dumps(masked)
    assert '6800000' not in visible
    assert '2026' not in visible
    assert '[quantity omitted]' in visible
    assert '6800000' not in _mask_unshared_quantities('GBP6800000', set(), 'Example Labs')
    assert '2026E' not in _mask_unshared_quantities('2026E', set(), 'Example Labs')
    assert _mask_unshared_quantities('GBP6800000', {'6800000'}, 'Example Labs') == 'GBP6800000'
    part = MemoPartA.model_validate({key: draft()[key] for key in (
        'recommendation', 'recommendation_reason', 'recommendation_claims',
        'investment_thesis', 'business_and_market', 'unknowns')})
    for token in ('GBP6800000', '2026E'):
        candidate = {'sentences': [
            f'The reported {token} entry requires checking signed primary records before any decision can rely on it.',
            'Diligence should seek dated evidence before treating the reported entry as a completed transaction.']}
        with pytest.raises(ValueError, match='glued numeric token'):
            apply_single_claim_field(part, 'recommendation_reason', candidate,
                                     as_of_date='2026-10-03', company='Example Labs')


def test_plural_magnitudes_and_mask_marker_cannot_enter_isolated_prose():
    from agents.research.staged_memo import _mask_unshared_quantities
    visible = _mask_unshared_quantities(
        'millions of users across hundreds of clinics', set(), 'Example Labs')
    assert 'millions' not in visible
    assert 'hundreds' not in visible
    part = MemoPartA.model_validate({key: draft()[key] for key in (
        'recommendation', 'recommendation_reason', 'recommendation_claims',
        'investment_thesis', 'business_and_market', 'unknowns')})
    for phrase, error in [
        ('millions of users across hundreds of clinics', 'unparsed spelled quantity'),
        ('[quantity omitted] users', 'masked task marker')]:
        candidate = {'sentences': [
            f'The reported pilot has {phrase}, which requires primary usage records before an investment decision.',
            'Diligence should seek dated buyer and usage evidence before treating this reported pilot as demand.']}
        with pytest.raises(ValueError, match=error):
            apply_single_claim_field(part, 'recommendation_reason', candidate,
                                     as_of_date='2026-10-03', company='Example Labs')


def test_schema_invalid_isolated_answer_resumes_with_recorded_candidate_and_error():
    part = MemoPartA.model_validate({key: draft()[key] for key in (
        'recommendation', 'recommendation_reason', 'recommendation_claims',
        'investment_thesis', 'business_and_market', 'unknowns')})
    invalid = {'sentences': ['Only one sentence was returned.']}
    corrected = {'sentences': [
        'The reported clinic pilot warrants checking dated use before treating it as repeatable demand.',
        'The source describes an initial pilot, so diligence should test buyer decisions and later product use.']}
    attempts = []
    model = FakeLocalModel([invalid, corrected])
    payload = single_claim_payload('Example Labs', 'recommendation_reason', part,
        base_response_id='response_base', source_set_digest='source_digest',
        as_of_date='2026-10-03')
    task = 'investment_memo_single_claim_recommendation_reason'
    options = dict(task=task, instruction=SINGLE_CLAIM_FIELD,
                   base_payload=payload, attempts=attempts, save=lambda: None,
                   model=model, as_of_date='2026-10-03', company='Example Labs')
    with preparation_budget(PreparationBudget(30, max_calls=1)) as budget:
        assert isolated_field_result(part, 'recommendation_reason',
                                     budget=budget, **options) is None
    assert attempts[0]['failure_kind'] == 'schema_validation'
    assert attempts[0]['answer'] == invalid
    assert attempts[0]['raw_response'] == json.dumps(invalid)
    with preparation_budget(PreparationBudget(30, max_calls=1)) as budget:
        changed, response_id = isolated_field_result(part,
            'recommendation_reason', budget=budget, **options)
    assert response_id == attempts[1]['id']
    assert attempts[1]['input']['previous_response_id'] == attempts[0]['id']
    assert attempts[1]['input']['previous_answer'] == invalid
    assert 'Schema validation:' in attempts[1]['input']['validation_issue']
    assert 'reported clinic pilot' in changed.recommendation_reason
    with preparation_budget(PreparationBudget(30, max_calls=1)) as budget:
        replayed, replay_id = isolated_field_result(part,
            'recommendation_reason', budget=budget, **options)
    assert replay_id == response_id
    assert replayed == changed
    assert len(attempts) == 2


def test_schema_invalid_isolated_answers_stop_at_three_recorded_responses():
    part = MemoPartA.model_validate({key: draft()[key] for key in (
        'recommendation', 'recommendation_reason', 'recommendation_claims',
        'investment_thesis', 'business_and_market', 'unknowns')})
    invalid = {'sentences': ['Only one sentence was returned.']}
    attempts = []
    payload = single_claim_payload('Example Labs', 'recommendation_reason', part,
        base_response_id='response_base', source_set_digest='source_digest',
        as_of_date='2026-10-03')
    with pytest.raises(ValueError, match='retry limit exhausted'):
        isolated_field_result(part, 'recommendation_reason',
            task='investment_memo_single_claim_recommendation_reason',
            instruction=SINGLE_CLAIM_FIELD, base_payload=payload,
            attempts=attempts, save=lambda: None,
            model=FakeLocalModel([invalid] * 3), as_of_date='2026-10-03',
            company='Example Labs')
    assert len(attempts) == 3
    assert all(row['failure_kind'] == 'schema_validation' and row['raw_response']
               for row in attempts)


def test_isolated_field_retry_stops_after_three_answered_failures():
    whole = draft()
    first_fields = ('recommendation', 'recommendation_reason', 'recommendation_claims',
                    'investment_thesis', 'business_and_market', 'unknowns')
    second_fields = ('differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')
    part_a = {key: whole[key] for key in first_fields}
    part_a['recommendation_reason'] = 'The company has 900 customers [S1]. ' + part_a['recommendation_reason']
    invalid = {'sentences': [
        'The reported clinic pilot has 900 customers, which would change the commercial diligence priority.',
        'The retained source describes a scheduling tool, so buyer records would be needed for confirmation.']}
    attempts = []
    draft_model = FakeLocalModel([part_a, {key: whole[key] for key in second_fields}])
    prose_model = FakeLocalModel([invalid] * 3)
    first = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=draft_model, prose_model=prose_model,
        review_model=FakeLocalModel([]), as_of_date='2026-10-03')
    assert first['state'] == 'needs_resume'
    with pytest.raises(ValueError, match='retry limit exhausted'):
        run_stage('Example Labs', [SOURCE], attempts, lambda: None,
            draft_model=draft_model, prose_model=prose_model,
            review_model=FakeLocalModel([]), as_of_date='2026-10-03')
    assert len([row for row in attempts if row['task'] ==
                'investment_memo_single_claim_recommendation_reason']) == 3
    assert all(row['raw_response'] for row in attempts[-3:])


def test_corrected_second_part_is_reused_on_resume_without_part_a_input():
    from agents.research.staged_memo import _latest_part
    from agents.inference.model_authorship import digest
    answer = {"differentiation_and_execution": {"analysis": "saved"}}
    raw = json.dumps(answer)
    correction = {"id": "response_3", "task": "investment_memo_part_b_correction",
                  "input": {"company": "Example Labs", "sources": [SOURCE.model_dump()],
                            "as_of_date": "2026-10-02", "part": {}, "issues": []},
                  "raw_response": raw, "response_hash": digest(raw), "answer": answer}
    payload = {"company": "Example Labs", "sources": [SOURCE.model_dump()],
               "as_of_date": "2026-10-02"}
    assert _latest_part([correction], {"investment_memo_part_b_correction"},
                        payload, bound_first=[{"recommendation": "defer"}]) is correction


def test_timed_out_draft_resumes_once_with_saved_input_and_no_previous_answer():
    from agents.research.staged_memo import draft_part_result, PART_A
    payload = {'company': 'Example Labs', 'sources': [SOURCE.model_dump()],
               'as_of_date': '2026-10-03'}
    attempts = [{'id': 'response_1', 'task': 'investment_memo_part_a',
                 'input': payload, 'model': 'offline-test-model',
                 'error': 'Preparation reached its time limit during inference.',
                 'raw_response': ''}]
    answer = {key: draft()[key] for key in (
        'recommendation', 'recommendation_reason', 'recommendation_claims',
        'investment_thesis', 'business_and_market', 'unknowns')}
    with preparation_budget(PreparationBudget(30, max_calls=1)) as budget:
        row = draft_part_result(FakeLocalModel([answer]), 'investment_memo_part_a',
            PART_A, payload, MemoPartA, attempts, lambda: None, budget)
    assert row['id'] == 'response_2'
    assert row['input']['previous_response_id'] == 'response_1'
    assert 'previous_answer' not in row['input']
    assert row['input']['sources'] == payload['sources']
    with preparation_budget(PreparationBudget(30, max_calls=1)) as budget:
        assert draft_part_result(FakeLocalModel([]), 'investment_memo_part_a',
            PART_A, payload, MemoPartA, attempts, lambda: None, budget)['id'] == 'response_2'
    assert len(attempts) == 2


def test_part_b_can_use_separately_frozen_local_draft_model():
    whole = draft()
    first = {key: whole[key] for key in (
        'recommendation', 'recommendation_reason', 'recommendation_claims',
        'investment_thesis', 'business_and_market', 'unknowns')}
    second = {key: whole[key] for key in (
        'differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')}
    primary = FakeLocalModel([first])
    primary.name = 'local-draft-a'
    secondary = FakeLocalModel([second])
    secondary.name = 'local-draft-b'
    attempts = []
    run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=primary, part_b_model=secondary,
        review_model=FakeLocalModel([]), as_of_date='2026-10-03',
        budget=PreparationBudget(30, max_calls=2))
    assert [(row['task'], row['model']) for row in attempts[:2]] == [
        ('investment_memo_part_a', 'local-draft-a'),
        ('investment_memo_part_b', 'local-draft-b')]


def test_compact_part_b_sections_replay_into_accepted_memo():
    whole = draft()
    first_fields = ('recommendation', 'recommendation_reason', 'recommendation_claims',
                    'investment_thesis', 'business_and_market', 'unknowns')
    fields = ('differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')
    attempts = []
    initial = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=FakeLocalModel([{key: whole[key] for key in first_fields}]),
        part_b_model=FakeLocalModel([{field: whole[field]} for field in fields]),
        review_model=FakeLocalModel([]), phase='draft_only', compact_part_b=True,
        as_of_date='2026-10-03', budget=PreparationBudget(105, max_calls=4))
    assert initial['state'] == 'draft_ready'
    ids = initial['draft']['part_b_section_response_ids']
    assert tuple(ids) == fields
    assert initial['draft']['part_b_response_id'].startswith('part_b_bundle_')
    assert [row['task'] for row in attempts[1:]] == [
        'investment_memo_part_b_' + field for field in fields]
    accepted = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=FakeLocalModel([]), review_model=FakeLocalModel([passing_review()]),
        phase='analysis_only', compact_part_b=True, as_of_date='2026-10-03',
        budget=PreparationBudget(105, max_calls=2))
    assert accepted['state'] == 'accepted'
    assert accepted['accepted']['part_b_section_response_ids'] == ids
    renderable_sections(accepted['accepted'], [SOURCE], attempts)


def test_compact_part_b_rejects_source_version_change_before_analysis():
    whole = draft()
    first_fields = ('recommendation', 'recommendation_reason', 'recommendation_claims',
                    'investment_thesis', 'business_and_market', 'unknowns')
    fields = ('differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')
    attempts = []
    run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=FakeLocalModel([{key: whole[key] for key in first_fields}]),
        part_b_model=FakeLocalModel([{field: whole[field]} for field in fields]),
        review_model=FakeLocalModel([]), phase='draft_only', compact_part_b=True,
        as_of_date='2026-10-03', budget=PreparationBudget(105, max_calls=4))
    changed = SOURCE.model_copy(update={'version': 'version456'})
    with pytest.raises(ValueError, match='Part A draft'):
        run_stage('Example Labs', [changed], attempts, lambda: None,
            draft_model=FakeLocalModel([]), review_model=FakeLocalModel([]),
            phase='analysis_only', compact_part_b=True, as_of_date='2026-10-03')


def test_compact_parts_checkpoint_and_replay_exact_model_components():
    whole = draft()
    fields_b = ('differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')
    first_model = FakeLocalModel([{key: whole[key] for key in (
        'recommendation', 'recommendation_reason', 'recommendation_claims', 'unknowns')},
        whole['investment_thesis'], whole['business_and_market']])
    second_model = FakeLocalModel([{field: whole[field]} for field in fields_b])
    attempts = []
    kwargs = dict(draft_model=first_model, part_b_model=second_model,
                  review_model=FakeLocalModel([]), phase='draft_only',
                  compact_part_a=True, compact_part_b=True, as_of_date='2026-10-03')
    pending = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        budget=PreparationBudget(105, max_calls=5), **kwargs)
    assert pending == {'state': 'needs_resume', 'phase': 'part_b_section_pending'}
    assert len(attempts) == 5
    ready = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        budget=PreparationBudget(105, max_calls=5), **kwargs)
    assert ready['state'] == 'draft_ready'
    assert ready['draft']['part_a_response_id'].startswith('part_a_bundle_')
    assert len(ready['draft']['part_a_component_ids']) == 3
    assert len(ready['draft']['part_b_section_response_ids']) == 3
    accepted = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=FakeLocalModel([]), review_model=FakeLocalModel([passing_review()]),
        phase='analysis_only', compact_part_a=True, compact_part_b=True,
        as_of_date='2026-10-03', budget=PreparationBudget(105, max_calls=2))
    assert accepted['state'] == 'accepted'
    renderable_sections(accepted['accepted'], [SOURCE], attempts)
    tampered = dict(accepted['accepted'])
    tampered['part_b_section_response_ids'] = dict(
        accepted['accepted']['part_b_section_response_ids'])
    tampered['part_b_section_response_ids']['diligence_plan'] = (
        accepted['accepted']['part_b_section_response_ids']['risks_and_countercase'])
    with pytest.raises(ValueError, match='bundle identifier changed'):
        renderable_sections(tampered, [SOURCE], attempts)
    changed = SOURCE.model_copy(update={'version': 'version456'})
    with pytest.raises(ValueError, match='Part A draft'):
        run_stage('Example Labs', [changed], attempts, lambda: None,
            draft_model=FakeLocalModel([]), review_model=FakeLocalModel([]),
            phase='analysis_only', compact_part_a=True, compact_part_b=True,
            as_of_date='2026-10-03')


def test_compact_components_survive_finite_correction_ledger_review_phases():
    from tests.research.test_memo_challenge import evidence_review

    whole = draft()
    fields_b = ('differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')
    attempts = []
    shared = {'compact_part_a': True, 'compact_part_b': True,
              'as_of_date': '2026-10-03'}
    ready = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=FakeLocalModel([{key: whole[key] for key in (
            'recommendation', 'recommendation_reason', 'recommendation_claims', 'unknowns')},
            whole['investment_thesis'], whole['business_and_market']]),
        part_b_model=FakeLocalModel([{field: whole[field]} for field in fields_b]),
        review_model=FakeLocalModel([]), phase='draft_only',
        budget=PreparationBudget(105, max_calls=6), **shared)
    assert ready['state'] == 'draft_ready'
    corrected = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=FakeLocalModel([]), review_model=FakeLocalModel([]),
        phase='correction_only', **shared)
    assert corrected['state'] == 'correction_ready'
    ledger = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=FakeLocalModel([]), challenge_model=FakeLocalModel([]),
        review_model=FakeLocalModel([]), phase='ledger_only',
        phase_checkpoint=corrected, **shared)
    assert ledger['state'] == 'ledger_ready'
    accepted = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=FakeLocalModel([]), challenge_model=FakeLocalModel([]),
        review_model=FakeLocalModel([evidence_review()]), phase='review_only',
        phase_checkpoint=ledger, **shared)
    assert accepted['state'] == 'accepted'
    assert accepted['accepted']['part_a_component_ids'] == ready['draft']['part_a_component_ids']
    assert accepted['accepted']['part_b_section_response_ids'] == ready['draft']['part_b_section_response_ids']
    renderable_sections(accepted['accepted'], [SOURCE], attempts)


def test_compact_part_b_schema_retry_remains_replayable():
    whole = draft()
    first_fields = ('recommendation', 'recommendation_reason', 'recommendation_claims',
                    'investment_thesis', 'business_and_market', 'unknowns')
    fields = ('differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')
    attempts = []
    part_b_model = FakeLocalModel([{}, *({field: whole[field]} for field in fields)])
    base = dict(draft_model=FakeLocalModel([{key: whole[key] for key in first_fields}]),
                part_b_model=part_b_model, review_model=FakeLocalModel([]),
                phase='draft_only', compact_part_b=True, as_of_date='2026-10-03')
    pending = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        budget=PreparationBudget(105, max_calls=5), **base)
    assert pending['phase'] == 'part_b_section_pending'
    ready = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        budget=PreparationBudget(105, max_calls=5), **base)
    assert ready['state'] == 'draft_ready'
    retry_id = ready['draft']['part_b_section_response_ids'][fields[0]]
    assert next(row for row in attempts if row['id'] == retry_id)['input']['retry_index'] == 1
    accepted = run_stage('Example Labs', [SOURCE], attempts, lambda: None,
        draft_model=FakeLocalModel([]), review_model=FakeLocalModel([passing_review()]),
        phase='analysis_only', compact_part_b=True, as_of_date='2026-10-03',
        budget=PreparationBudget(105, max_calls=2))
    assert accepted['state'] == 'accepted'
    renderable_sections(accepted['accepted'], [SOURCE], attempts)
    changed_attempts = json.loads(json.dumps(attempts))
    retry = next(row for row in changed_attempts if row['id'] == retry_id)
    retry['input']['retry_base_digest'] = '0' * 64
    with pytest.raises(ValueError, match='bound to the exact draft'):
        renderable_sections(accepted['accepted'], [SOURCE], changed_attempts)


def test_compact_draft_defers_call_with_insufficient_pass_time():
    from agents.research.part_a_components import compact_call_has_time
    model = FakeLocalModel([])
    budget = PreparationBudget(105, max_calls=5)
    budget.started -= 90
    payload = {'company': 'Example Labs', 'sources': [SOURCE.model_dump()],
               'as_of_date': '2026-10-03'}
    assert compact_call_has_time([], payload, budget, model) is False
    budget.started += 40
    measured = [{'task': 'investment_memo_part_a_recommendation',
                 'input': payload, 'model': model.name, 'elapsed_seconds': 65}]
    assert compact_call_has_time(measured, payload, budget, model) is False
