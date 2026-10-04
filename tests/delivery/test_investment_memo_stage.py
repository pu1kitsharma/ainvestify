from types import SimpleNamespace
import json

from delivery.investment_memo_stage import (room_sources, source_fingerprint,
                                             run_memo_pass, frozen_memo_model_profile)
from delivery.worker import memo_coverage_issue
from agents.research.investment_memo import Source
import pytest
from scripts.private_investment_memo_worker import validate_saved_model_roles
from scripts.private_investment_memo_worker import evaluate_source_selection, SourceSelection
from agents.inference.model_authorship import digest
from delivery.investment_memo_stage import resolve_memo_sources
from delivery.investment_memo_stage import _prepare_causal_revision
from delivery.investment_memo_stage import memo_base_directory, memo_directory


def test_new_memo_uses_9b_draft_default(tmp_path, monkeypatch):
    monkeypatch.delenv('LOCAL_MEMO_DRAFT_MODEL', raising=False)
    monkeypatch.delenv('LOCAL_MEMO_PART_B_MODEL', raising=False)
    monkeypatch.delenv('LOCAL_MEMO_DRAFT_CONTRACT', raising=False)
    profile = frozen_memo_model_profile(tmp_path / 'model.json', 'qwen3.5:9b')
    assert profile['profiles']['draft'] == 'qwen3.5:9b'
    assert profile['profiles']['draft_b'] == 'qwen3.5:9b'
    assert profile['profiles']['challenge'] == 'qwen3.5:9b'


def test_fresh_v13_opt_in_pins_all_installed_local_roles(tmp_path, monkeypatch):
    from io import BytesIO
    monkeypatch.setenv('LOCAL_MEMO_DRAFT_CONTRACT', 'memo-cards-v13')
    monkeypatch.setenv('LOCAL_MEMO_AUTHOR_MODEL', 'qwen3:14b')
    monkeypatch.delenv('LOCAL_MEMO_DRAFT_MODEL', raising=False)
    monkeypatch.delenv('LOCAL_MEMO_PART_B_MODEL', raising=False)
    monkeypatch.delenv('LOCAL_MEMO_REVIEW_MODEL', raising=False)
    monkeypatch.delenv('LOCAL_MEMO_CHALLENGE_MODEL', raising=False)
    tags = {'models': [{'name': 'qwen3.5:9b', 'digest': 'a' * 64},
                       {'name': 'qwen3:14b', 'digest': 'b' * 64}]}
    stream = lambda: BytesIO(json.dumps(tags).encode())
    monkeypatch.setattr('delivery.investment_memo_stage.urllib.request.urlopen',
                        lambda *_args, **_kwargs: stream())
    path = tmp_path / 'model.json'
    profile = frozen_memo_model_profile(path, 'qwen3.5:9b')
    assert profile['memo_draft_contract'] == 'memo-cards-v13'
    assert profile['memo_causal_review_contract'] == 'memo-causal-v2'
    assert profile['memo_author_model_digest'] == 'b' * 64
    assert profile['memo_causal_review_model_digest'] == 'b' * 64
    assert profile['memo_role_model_digests']['draft'] == 'a' * 64
    assert profile['memo_role_model_digests']['author'] == 'b' * 64
    assert profile['memo_role_model_digests']['review'] == 'b' * 64
    monkeypatch.setenv('LOCAL_MEMO_DRAFT_CONTRACT', 'memo-cards-v2')
    assert frozen_memo_model_profile(path, 'qwen3.5:9b') == profile


def test_one_causal_revision_branch_preserves_blocked_result_and_replays(tmp_path):
    source = Source(id='S1', url='https://example.invalid/report', title='Report',
                    passage='Example Labs reports a pilot while commercial outcomes remain unverified.',
                    version='report-v1', attribution='Synthetic report')
    checkpoint = {'state': 'ledger_ready',
                  'source_set_digest': digest([source.model_dump()]),
                  'as_of_date': '2026-10-05', 'final_memo_digest': 'm' * 64}
    job = {'checkpoint': {'memo_phase_checkpoint': checkpoint}}
    profile = {'memo_draft_contract': 'memo-cards-v13',
               'memo_causal_review_contract': 'memo-causal-v2',
               'profiles': {'author': 'qwen3:14b', 'review': 'qwen3:14b'},
               'memo_author_model_digest': 'a' * 64,
               'memo_causal_review_model_digest': 'a' * 64}
    request = {'company': 'Example Labs', 'sources': [source.model_dump()],
               'as_of_date': '2026-10-05'}
    (tmp_path / 'request.json').write_text(json.dumps(request))
    (tmp_path / 'model.json').write_text(json.dumps(profile))
    base = {'id': 'r1', 'task': 'investment_memo_part_a_recommendation_select_v7'}
    review = {'id': 'r2', 'task': 'investment_memo_causal_review_v2',
              'response_hash': 'b' * 64, 'raw_response': {'r01': {'relation':
                'unsupported_consequence'}}, 'error': None}
    attempts = [base, review]
    finding = {'field': 'investment_thesis',
               'sentence_id': 'investment_thesis.sentence_2',
               'sentence': 'The pilot forces growth [S1].',
               'challenged_clause': 'forces growth', 'premise_ids': ['S1'],
               'source_evidence': [{'source_id': 'S1',
                                    'exact_quotes': ['Example Labs reports a pilot']}],
               'relation': 'unsupported_consequence', 'response_id': 'r2'}
    result = {'state': 'blocked', 'reason': 'memo_causal_review_rejected',
              'causal_review': {'review_contract': 'memo-causal-v2',
                                'review': {'findings': [finding]}}}
    (tmp_path / 'result.json').write_text(json.dumps(result))
    assert _prepare_causal_revision(job, tmp_path, result, attempts, profile) == 'causal_v1'
    branch = tmp_path / 'causal_v1'
    assert json.loads((branch / 'attempts.json').read_text()) == [base]
    assert json.loads((branch / 'causal_repair.json').read_text())['review_response_hash'] == 'b' * 64
    assert json.loads((tmp_path / 'result.json').read_text()) == result
    assert _prepare_causal_revision(job, tmp_path, result, attempts, profile) == 'causal_v1'
    repaired = {'id': 'r3', 'task': 'investment_memo_causal_repair_v1',
                'response_hash': 'c' * 64, 'raw_response': {'text': 'A bound sentence.'},
                'error': None}
    second_review = {**review, 'id': 'r4', 'response_hash': 'd' * 64,
                     'input': {'memo_digest': 'n' * 64}}
    second_finding = {**finding, 'response_id': 'r4',
                      'sentence_id': 'diligence_plan.sentence_3',
                      'field': 'diligence_plan'}
    second_result = {**result, 'causal_review': {
        'review_contract': 'memo-causal-v2',
        'review': {'findings': [second_finding]}}}
    (branch / 'result.json').write_text(json.dumps(second_result))
    second_job = {'checkpoint': {**job['checkpoint'], 'memo_revision': 'causal_v1'}}
    assert _prepare_causal_revision(second_job, branch, second_result,
                                    [base, repaired, second_review], profile) == 'causal_v2'
    second = tmp_path / 'causal_v2'
    assert json.loads((second / 'attempts.json').read_text()) == [base, repaired]
    assert json.loads((second / 'causal_repair_v2.json').read_text())[
        'prior_repair_response_hash'] == 'c' * 64
    assert json.loads((branch / 'result.json').read_text()) == second_result
    assert _prepare_causal_revision({**second_job, 'checkpoint': {
        **second_job['checkpoint'], 'memo_revision': 'causal_v2'}}, second,
        second_result, [base, repaired, second_review], profile) is None


def test_causal_revision_uses_child_memo_root_and_stable_source_selection_root():
    job = {'tenant_id': 'tenant-one', 'workspace_id': 'room-one', 'id': 'job-one',
           'checkpoint': {'memo_revision': 'causal_v1'}}
    assert memo_directory(job) == memo_base_directory(job) / 'causal_v1'
    assert memo_directory({**job, 'checkpoint': {}}) == memo_base_directory(job)
    assert memo_directory({**job, 'checkpoint': {'memo_revision': 'causal_v2'}}) == (
        memo_base_directory(job) / 'causal_v2')


def test_new_memo_can_freeze_distinct_part_b_model(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCAL_MEMO_DRAFT_MODEL', 'qwen3.5:9b')
    monkeypatch.setenv('LOCAL_MEMO_PART_B_MODEL', 'qwen3.5:4b')
    path = tmp_path / 'model.json'
    frozen = frozen_memo_model_profile(path, 'qwen3.5:9b')
    assert frozen['profiles']['draft_b'] == 'qwen3.5:4b'
    assert frozen['profile_version'] == 4
    assert frozen['memo_draft_contract'] == 'memo-cards-v2'
    monkeypatch.setenv('LOCAL_MEMO_PART_B_MODEL', 'qwen3:14b')
    assert frozen_memo_model_profile(path, 'qwen3.5:9b') == frozen


def test_distinct_part_b_role_rejects_saved_wrong_model():
    roles = {'draft': 'qwen3.5:9b', 'draft_b': 'qwen3.5:4b',
             'review': 'qwen3.5:9b', 'corrector': 'qwen3.5:9b',
             'prose': 'qwen3.5:9b'}
    validate_saved_model_roles([
        {'task': 'investment_memo_part_a', 'model': 'qwen3.5:9b'},
        {'task': 'investment_memo_part_b', 'model': 'qwen3.5:4b'},
        {'task': 'investment_memo_part_b_quote_patch', 'model': 'qwen3.5:4b'}], roles)
    with pytest.raises(ValueError, match='differs from its frozen role'):
        validate_saved_model_roles([
            {'task': 'investment_memo_part_b', 'model': 'qwen3.5:9b'}], roles)


def test_v12_saved_author_role_is_distinct_and_frozen(tmp_path):
    roles = {'draft': 'qwen3.5:9b', 'draft_b': 'qwen3.5:9b',
             'author': 'qwen3:14b', 'review': 'qwen3.5:9b',
             'corrector': 'qwen3.5:9b', 'prose': 'qwen3.5:9b'}
    path = tmp_path / 'model.json'
    path.write_text(json.dumps({'model': 'qwen3.5:9b', 'profiles': roles,
        'memo_draft_contract': 'memo-cards-v12',
        'memo_author_model_digest': 'a' * 64}))
    assert frozen_memo_model_profile(path, 'qwen3.5:9b')['profiles']['author'] == 'qwen3:14b'
    rows = [
        {'task': 'investment_memo_part_a_recommendation_select_v7', 'model': 'qwen3.5:9b'},
        {'task': 'investment_memo_part_a_recommendation_decision_source_1_v7', 'model': 'qwen3:14b'},
        {'task': 'investment_memo_part_b_v13_diligence_plan_select', 'model': 'qwen3.5:9b'},
        {'task': 'investment_memo_part_b_v13_diligence_plan_author_0', 'model': 'qwen3:14b'}]
    validate_saved_model_roles(rows, roles)
    with pytest.raises(ValueError, match='differs from its frozen role'):
        validate_saved_model_roles([{**rows[-1], 'model': 'qwen3.5:9b'}], roles)


def test_distinct_challenge_role_is_frozen_and_replay_checked(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCAL_MEMO_CHALLENGE_MODEL', 'qwen3.5:4b')
    path = tmp_path / 'model.json'
    frozen = frozen_memo_model_profile(path, 'qwen3.5:9b')
    assert frozen['profiles']['challenge'] == 'qwen3.5:4b'
    monkeypatch.setenv('LOCAL_MEMO_CHALLENGE_MODEL', 'qwen3.5:9b')
    assert frozen_memo_model_profile(path, 'qwen3.5:9b') == frozen
    with pytest.raises(ValueError, match='differs from its frozen role'):
        validate_saved_model_roles([
            {'task': 'investment_memo_challenge', 'model': 'qwen3.5:9b'}], frozen['profiles'])


def test_memo_models_are_frozen_across_environment_changes(tmp_path, monkeypatch):
    path = tmp_path / 'model.json'
    monkeypatch.setenv('LOCAL_MEMO_DRAFT_MODEL', 'qwen3.5:4b')
    monkeypatch.setenv('LOCAL_MEMO_REVIEW_MODEL', 'qwen3.5:9b')
    first = frozen_memo_model_profile(path, 'qwen3.5:9b')
    monkeypatch.setenv('LOCAL_MEMO_DRAFT_MODEL', 'qwen3:14b')
    assert frozen_memo_model_profile(path, 'qwen3.5:9b') == first
    assert first['profiles']['draft'] == 'qwen3.5:4b'
    with pytest.raises(ValueError, match='Memo model changed'):
        frozen_memo_model_profile(path, 'qwen3:14b')


def test_old_memo_with_attempts_requires_profile_review(tmp_path):
    path = tmp_path / 'model.json'
    path.write_text(json.dumps({'model': 'qwen3.5:9b'}))
    (tmp_path / 'attempts.json').write_text('[]')
    with pytest.raises(ValueError, match='historical attempts require migration review'):
        frozen_memo_model_profile(path, 'qwen3.5:9b')
    assert json.loads(path.read_text()) == {'model': 'qwen3.5:9b'}


def test_saved_memo_attempts_must_match_each_frozen_model_role():
    roles = {'draft': 'qwen3.5:4b', 'review': 'qwen3.5:9b',
             'corrector': 'qwen3.5:9b', 'prose': 'qwen3.5:9b'}
    rows = [{'task': 'investment_memo_part_a', 'model': 'qwen3.5:4b'},
            {'task': 'investment_memo_single_claim_investment_thesis', 'model': 'qwen3.5:9b'},
            {'task': 'investment_memo_review', 'model': 'qwen3.5:9b'}]
    validate_saved_model_roles(rows, roles)
    validate_saved_model_roles(rows + [
        {'task': 'investment_memo_review_field_business_and_market', 'model': 'qwen3.5:9b'},
        {'task': 'investment_memo_source_selection', 'model': 'qwen3.5:4b'},
        {'task': 'investment_memo_part_a_claim_patch', 'model': 'qwen3.5:9b'},
        {'task': 'investment_memo_part_b_claim_patch', 'model': 'qwen3.5:9b'},
        {'task': 'investment_memo_timeline_patch', 'model': 'qwen3.5:9b'}], roles)
    compact_roles = {**roles, 'draft_b': 'qwen3.5:9b'}
    validate_saved_model_roles([
        *({'task': task, 'model': 'qwen3.5:4b'} for task in (
            'investment_memo_part_a_recommendation', 'investment_memo_part_a_thesis',
            'investment_memo_part_a_market')),
        *({'task': task, 'model': 'qwen3.5:9b'} for task in (
            'investment_memo_part_b_differentiation_and_execution',
            'investment_memo_part_b_risks_and_countercase',
            'investment_memo_part_b_diligence_plan'))], compact_roles)
    with pytest.raises(ValueError, match='differs from its frozen role'):
        validate_saved_model_roles(rows[:-1] + [
            {'task': 'investment_memo_review', 'model': 'qwen3:14b'}], roles)


def test_accepted_memo_rechecks_frozen_roles_before_rendering(tmp_path, monkeypatch):
    monkeypatch.setenv('PREPARATION_MODEL', 'qwen3.5:9b')
    monkeypatch.setattr('delivery.investment_memo_stage.memo_directory', lambda job: tmp_path)
    source = Source(id='S1', url='https://source.example/company', title='Company record',
                    passage='A retained public source passage with sufficient text for this test.',
                    version='version-1', attribution='Public source')
    job = {'tenant_id': 'tenant', 'workspace_id': 'room', 'id': 'job',
           'input_revision': 'a' * 64}
    lead = SimpleNamespace(company_name='Synthetic company')
    (tmp_path / 'request.json').write_text(json.dumps({
        'company': lead.company_name, 'sources': [source.model_dump()],
        'input_revision': job['input_revision'], 'as_of_date': '2026-10-03'}))
    (tmp_path / 'model.json').write_text(json.dumps({
        'model': 'qwen3.5:9b', 'profiles': {'draft': 'qwen3.5:4b',
        'review': 'qwen3.5:9b', 'corrector': 'qwen3.5:9b', 'prose': 'qwen3.5:9b'}}))
    (tmp_path / 'result.json').write_text(json.dumps({'state': 'accepted', 'accepted': {}}))
    (tmp_path / 'attempts.json').write_text(json.dumps([
        {'task': 'investment_memo_review', 'model': 'qwen3:14b'}]))
    with pytest.raises(ValueError, match='differs from its frozen role'):
        run_memo_pass(job, lead, [source], timeout=20)


def test_accepted_memo_accepts_new_frozen_challenge_role(tmp_path, monkeypatch):
    monkeypatch.setenv('PREPARATION_MODEL', 'qwen3.5:9b')
    monkeypatch.setattr('delivery.investment_memo_stage.memo_directory', lambda job: tmp_path)
    monkeypatch.setattr('delivery.investment_memo_stage.renderable_sections',
                        lambda accepted, sources, attempts, projection=None: [('Investment thesis', 'Model text', [])])
    source = Source(id='S1', url='https://source.example/company', title='Company record',
                    passage='A retained public source passage with enough text for the test.',
                    version='version-1', attribution='Public source')
    job = {'tenant_id': 'tenant', 'workspace_id': 'room', 'id': 'job',
           'input_revision': 'a' * 64}
    lead = SimpleNamespace(company_name='Synthetic company')
    (tmp_path / 'request.json').write_text(json.dumps({
        'company': lead.company_name, 'sources': [source.model_dump()],
        'input_revision': job['input_revision'], 'as_of_date': '2026-10-03'}))
    (tmp_path / 'model.json').write_text(json.dumps({
        'model': 'qwen3.5:9b', 'profiles': {
            'draft': 'qwen3.5:9b', 'draft_b': 'qwen3.5:9b',
            'review': 'qwen3.5:9b', 'challenge': 'qwen3.5:9b',
            'corrector': 'qwen3.5:9b', 'prose': 'qwen3.5:9b'}}))
    (tmp_path / 'result.json').write_text(json.dumps({'state': 'accepted', 'accepted': {
        'memo': {'recommendation': 'defer_pending_evidence'},
        'part_a_response_id': 'response_1', 'part_b_response_id': 'response_2',
        'review_response_id': 'response_3'}}))
    (tmp_path / 'attempts.json').write_text('[]')
    result = run_memo_pass(job, lead, [source], timeout=20)
    assert result['state'] == 'accepted'
    assert result['sections'] == [('Investment thesis', 'Model text', [])]


class PrivateStore:
    def get_documents_for_deal(self, tenant_id, deal_id):
        assert (tenant_id, deal_id) == ("tenant", "deal")
        return [SimpleNamespace(id="document_a", filename="uploaded.pdf", blocks=[
            SimpleNamespace(id="block_a", content="A sufficiently long private source passage for local research only."),
            SimpleNamespace(id="block_b", content="A separate company record that remains within the private room.")])]


def test_private_room_blocks_are_version_bound_without_public_lookup():
    lead = SimpleNamespace(tenant_id="tenant", company_name="Synthetic company",
                           company_profile=SimpleNamespace(provenance={}, evidence=[]))
    room = SimpleNamespace(deal_id="deal")
    sources, coverage = room_sources(PrivateStore(), lead, room)
    assert len(sources) == 2
    assert coverage["private_documents"] == 1
    assert coverage["public_publishers"] == 0
    assert coverage["coverage_complete"]
    assert all(source.url.startswith("private://") for source in sources)
    job = {"input_revision": "a" * 64}
    first = source_fingerprint(job, lead, sources)
    changed = sources[0].model_copy(update={"passage": sources[0].passage + " Changed."})
    assert source_fingerprint(job, lead, [changed, sources[1]]) != first


def test_bound_public_record_and_private_room_captured_page_are_both_used(monkeypatch):
    monkeypatch.delenv("ELASTICSEARCH_URL", raising=False)
    version = "a" * 64
    record = SimpleNamespace(origin="public_page_claim", dataset_id="source_a",
        row_key=version + ":company.headquarters_location", source_url="https://directory.example/company",
        quote='{"headquarters_location":"Mumbai","name":"Synthetic company"}')
    page = SimpleNamespace(origin="preparation_public_page", dataset_id=None,
        row_key="preparation_context_v4:abc", source_url="https://synthetic.example/about",
        quote="The company website describes a product and the customers it intends to serve.")
    lead = SimpleNamespace(tenant_id="tenant", company_name="Synthetic company",
        company_profile=SimpleNamespace(provenance={"origin":"public_kb", "source_id":"source_a",
            "source_version":version, "attribution":"Licensed directory"}, evidence=[record, page]))
    sources, coverage = room_sources(PrivateStore(), lead, SimpleNamespace(deal_id=None))
    assert len(sources) == 2
    assert {source.url for source in sources} == {record.source_url, page.source_url}
    assert coverage["public_publishers"] == 2
    assert any(source.version == version for source in sources)


def test_long_source_inventory_reports_omissions_for_model_selection(monkeypatch):
    monkeypatch.delenv("ELASTICSEARCH_URL", raising=False)
    pages = [SimpleNamespace(origin="preparation_public_page", dataset_id=None,
        row_key=f"preparation_context_v4:{index}", source_url=f"https://source{index}.example/about",
        quote=(f"Public source passage {index} " + "evidence " * 110)) for index in range(31)]
    lead = SimpleNamespace(tenant_id="tenant", company_name="Synthetic company",
        company_profile=SimpleNamespace(provenance={}, evidence=pages))
    sources, coverage = room_sources(PrivateStore(), lead, SimpleNamespace(deal_id=None))
    assert len(sources) < len(pages)
    assert coverage["source_count"] + coverage["omitted_passages"] == coverage["available_passages"] == 31
    assert not coverage["coverage_complete"]
    assert memo_coverage_issue(coverage) == "source_coverage_incomplete"
    assert len(coverage['inventory_passage_ids']) == 31
    assert len(coverage['omitted_passage_ids']) == coverage['omitted_passages']
    assert set(coverage['selected_passage_ids']).isdisjoint(coverage['omitted_passage_ids'])


def test_oversized_retained_passage_blocks_instead_of_disappearing(monkeypatch, tmp_path):
    monkeypatch.delenv('ELASTICSEARCH_URL', raising=False)
    page = SimpleNamespace(origin='preparation_public_page', dataset_id=None,
        row_key='preparation_context_v4:large', source_url='https://source.example/about',
        quote='Evidence text. ' * 400)
    lead = SimpleNamespace(tenant_id='tenant', company_name='Synthetic company',
        company_profile=SimpleNamespace(provenance={}, evidence=[page]))
    inventory, coverage = room_sources(PrivateStore(), lead, SimpleNamespace(deal_id=None),
                                       full_inventory=True)
    assert not inventory
    assert coverage['oversized_passages'] == 1
    assert not coverage['coverage_complete']
    assert resolve_memo_sources({'input_revision': 'a' * 64}, lead, inventory, coverage,
                                timeout=20) == {'state': 'blocked', 'reason': 'source_passage_oversized'}


def test_indexed_company_record_survives_bounded_source_inventory(monkeypatch):
    monkeypatch.delenv('ELASTICSEARCH_URL', raising=False)
    version = 'a' * 64
    indexed = SimpleNamespace(origin='public_page_claim', dataset_id='source_a',
        row_key=version + ':company.stage', source_url='https://directory.example/company',
        quote='{"name":"Synthetic company","stage":"seed","status":"source-reported"}')
    pages = [SimpleNamespace(origin='preparation_public_page', dataset_id=None,
        row_key=f'preparation_context_v4:{index}', source_url=f'https://page{index}.example/about',
        quote=f'This retained public page reports source passage {index} for the company.')
        for index in range(30)]
    lead = SimpleNamespace(tenant_id='tenant', company_name='Synthetic company',
        company_profile=SimpleNamespace(provenance={'origin': 'public_kb',
            'source_id': 'source_a', 'source_version': version}, evidence=pages + [indexed]))
    sources, coverage = room_sources(PrivateStore(), lead, SimpleNamespace(deal_id=None))
    assert len(sources) == 30
    assert sources[0].title == 'Indexed company record'
    assert coverage['omitted_passages'] == 1
    assert len(coverage['inventory_passage_ids']) == 31


class SelectionModel:
    name = 'qwen3.5:4b'
    last_response_text = ''
    last_route = {}

    def __init__(self):
        self.calls = []

    def generate(self, instruction, evidence, schema):
        payload = json.loads(evidence)
        self.calls.append(payload)
        answer = {'dispositions': [
            {'passage_id': row['passage_id'], 'include': index == 0,
             'reason': 'This passage is material to the company decision.' if index == 0
                       else 'This passage repeats immaterial general website text.'}
            for index, row in enumerate(payload['passages'])]}
        self.last_response_text = json.dumps(answer)
        return schema.model_validate(answer)


def selection_inventory(tmp_path, count=3, repeats=35):
    rows = []
    for index in range(count):
        source = Source(id=f'S{index + 1}', url=f'https://source{index}.example/about',
            title=f'Source {index}', passage='A retained and attributable passage about this company. ' * repeats,
            version=f'version-{index}', attribution='Publisher')
        data = source.model_dump()
        rows.append({'passage_id': digest(data), 'source': data})
    base = {'company': 'Synthetic company', 'input_revision': 'a' * 64,
            'passages': rows, 'selection_revision': 'memo-source-selection-v1'}
    manifest = {**base, 'inventory_digest': digest(base)}
    (tmp_path / 'inventory.json').write_text(json.dumps(manifest))
    (tmp_path / 'model.json').write_text(json.dumps({'model': 'qwen3.5:9b', 'profiles': {
        'draft': 'qwen3.5:4b', 'review': 'qwen3.5:9b',
        'corrector': 'qwen3.5:9b', 'prose': 'qwen3.5:9b'}}))
    (tmp_path / 'selection_budget.json').write_text(json.dumps({'seconds': 30}))
    return manifest


def test_private_selection_sees_every_passage_and_replays_exact_raw_answers(tmp_path):
    manifest = selection_inventory(tmp_path, 3)
    model = SelectionModel()
    first = evaluate_source_selection(tmp_path, model)
    assert first['state'] == 'complete'
    assert set(first['selected_passage_ids'] + first['excluded_passage_ids']) == {
        row['passage_id'] for row in manifest['passages']}
    assert len(model.calls) == 1
    assert [row['passage_id'] for row in model.calls[0]['passages']] == [
        row['passage_id'] for row in manifest['passages']]
    assert evaluate_source_selection(tmp_path, model) == first
    assert len(model.calls) == 1
    attempts = json.loads((tmp_path / 'selection_attempts.json').read_text())
    assert attempts[0]['raw_response'] and attempts[0]['response_hash']
    packet = json.loads((tmp_path / 'excluded_source_review.json').read_text())
    assert packet['review_status'] == 'pending_independent_review'
    assert packet['packet_digest'] == digest({k: v for k, v in packet.items()
                                              if k != 'packet_digest'})
    assert [row['passage_id'] for row in packet['excluded']] == first['excluded_passage_ids']
    assert all(row['source']['passage'] and row['model_reason'] for row in packet['excluded'])
    assert first['excluded_source_review_path'] == str(tmp_path / 'excluded_source_review.json')


def test_changed_excluded_review_packet_blocks_saved_selection(tmp_path):
    selection_inventory(tmp_path, 3)
    model = SelectionModel()
    assert evaluate_source_selection(tmp_path, model)['state'] == 'complete'
    packet_file = tmp_path / 'excluded_source_review.json'
    packet = json.loads(packet_file.read_text())
    packet['excluded'][0]['source']['passage'] = 'Altered evidence'
    packet_file.write_text(json.dumps(packet))
    assert evaluate_source_selection(tmp_path, model) == {
        'state': 'blocked', 'reason': 'excluded_source_review_packet_changed'}
    assert len(model.calls) == 1


def test_private_selection_rejects_changed_inventory_and_missing_decision(tmp_path):
    manifest = selection_inventory(tmp_path, 2)
    manifest['passages'][0]['source']['passage'] += ' Changed.'
    (tmp_path / 'inventory.json').write_text(json.dumps(manifest))
    assert evaluate_source_selection(tmp_path, SelectionModel()) == {
        'state': 'blocked', 'reason': 'source_inventory_digest_invalid'}
    selection_inventory(tmp_path, 2)
    class Incomplete(SelectionModel):
        def generate(self, instruction, evidence, schema):
            payload = json.loads(evidence)
            answer = {'dispositions': [{'passage_id': payload['passages'][0]['passage_id'],
                'include': True, 'reason': 'This passage is useful for company analysis.'}]}
            self.last_response_text = json.dumps(answer)
            return schema.model_validate(answer)
    assert evaluate_source_selection(tmp_path, Incomplete()) == {
        'state': 'blocked', 'reason': 'source_selection_incomplete'}


def test_schema_invalid_source_selection_gets_bounded_feedback(tmp_path):
    selection_inventory(tmp_path, 2)
    class CorrectingSelection(SelectionModel):
        def generate(self, instruction, evidence, schema):
            payload = json.loads(evidence)
            self.calls.append(payload)
            answer = {'dispositions': [
                {'passage_id': row['passage_id'], 'include': index == 0,
                 'reason': (' ' * 25 if len(self.calls) == 1
                            else 'This exact source is relevant to the company decision.')}
                for index, row in enumerate(payload['passages'])]}
            self.last_response_text = json.dumps(answer)
            return schema.model_validate(answer)
    model = CorrectingSelection()
    first = evaluate_source_selection(tmp_path, model)
    assert first == {'state': 'needs_resume', 'reason': 'source_selection_local_model_failed'}
    second = evaluate_source_selection(tmp_path, model)
    assert second['state'] == 'complete'
    assert len(model.calls) == 2
    assert model.calls[1]['previous_response_id'] == 'response_1'
    assert model.calls[1]['previous_answer']['dispositions']
    assert 'reason' in model.calls[1]['validation_issue']
    attempts = json.loads((tmp_path / 'selection_attempts.json').read_text())
    assert attempts[0]['raw_response'] and attempts[0]['error']
    assert attempts[1]['input']['inventory_digest'] == attempts[0]['input']['inventory_digest']
    assert evaluate_source_selection(tmp_path, model) == second
    assert len(model.calls) == 2


def test_private_selection_resumes_bounded_batches_without_repeat_calls(tmp_path):
    selection_inventory(tmp_path, 12)
    model = SelectionModel()
    first = evaluate_source_selection(tmp_path, model)
    assert first == {'state': 'needs_resume', 'reason': 'bounded_source_selection_calls'}
    assert len(model.calls) == 2
    second = evaluate_source_selection(tmp_path, model)
    assert second['state'] == 'complete'
    assert len(model.calls) == 4
    assert [payload['batch_index'] for payload in model.calls] == [0, 1, 2, 3]


def test_all_included_sources_over_memo_context_await_input(tmp_path):
    selection_inventory(tmp_path, 31, repeats=3)
    class IncludeAll(SelectionModel):
        def generate(self, instruction, evidence, schema):
            payload = json.loads(evidence)
            answer = {'dispositions': [{'passage_id': row['passage_id'],
                'include': True, 'reason': 'This source may affect the company decision.'}
                for row in payload['passages']]}
            self.last_response_text = json.dumps(answer)
            self.calls.append(payload)
            return schema.model_validate(answer)
    model = IncludeAll()
    result = evaluate_source_selection(tmp_path, model)
    while result['state'] == 'needs_resume':
        result = evaluate_source_selection(tmp_path, model)
    assert result['state'] == 'awaiting_input'
    assert result['reason'] == 'selected_source_context_exceeded'
    assert len(result['selected_passage_ids']) == 31


def test_selected_memo_sources_bind_full_inventory_and_changed_exclusion_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr('delivery.investment_memo_stage.memo_base_directory', lambda job: tmp_path)
    monkeypatch.setenv('PREPARATION_MODEL', 'qwen3.5:9b')
    monkeypatch.setenv('LOCAL_MEMO_DRAFT_MODEL', 'qwen3.5:4b')
    model = SelectionModel()
    def local_selection_worker(*args, **kwargs):
        result = evaluate_source_selection(tmp_path, model)
        (tmp_path / 'selection_result.json').write_text(json.dumps(result))
    monkeypatch.setattr('delivery.investment_memo_stage.run_private', local_selection_worker)
    job = {'input_revision': 'a' * 64, 'tenant_id': 'tenant', 'workspace_id': 'room', 'id': 'job'}
    lead = SimpleNamespace(company_name='Synthetic company')
    inventory = [Source(id=f'S{index + 1}', url=f'https://source{index}.example/about',
        title=f'Source {index}', passage='A retained attributable company source passage. ' * 12,
        version=f'version-{index}', attribution='Publisher') for index in range(31)]
    coverage = {'coverage_complete': False, 'omitted_passages': 1}
    first = resolve_memo_sources(job, lead, inventory, coverage, timeout=40)
    assert first['state'] == 'needs_resume'
    second = resolve_memo_sources(job, lead, inventory, coverage, timeout=40)
    assert second['state'] == 'awaiting_input'
    assert second['reason'] == 'excluded_source_review_required'
    assert not second['coverage']['coverage_complete']
    assert second['coverage']['omitted_passages'] == 27
    assert second['coverage']['excluded_passages'] == 27
    assert len(second['coverage']['selected_passage_ids']) == 4
    assert second['coverage']['omitted_passage_ids'] == second['coverage']['excluded_passage_ids']
    assert second['coverage']['excluded_source_review_path'] == str(
        tmp_path / 'excluded_source_review.json')
    assert memo_coverage_issue(second['coverage']) == 'source_coverage_incomplete'
    original_digest = second['coverage']['inventory_digest']
    assert resolve_memo_sources(job, lead, inventory, coverage, timeout=40) == second
    changed = list(inventory)
    changed[-1] = changed[-1].model_copy(update={'passage': changed[-1].passage + ' Changed.'})
    blocked = resolve_memo_sources(job, lead, changed, coverage, timeout=40)
    assert blocked == {'state': 'blocked', 'reason': 'source_inventory_changed'}
    assert original_digest != digest(
        [source.model_dump() for source in changed])


def test_excluded_source_packet_must_match_retained_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr('delivery.investment_memo_stage.memo_base_directory', lambda job: tmp_path)
    monkeypatch.setenv('PREPARATION_MODEL', 'qwen3.5:9b')
    model = SelectionModel()
    def local_selection_worker(*args, **kwargs):
        result = evaluate_source_selection(tmp_path, model)
        (tmp_path / 'selection_result.json').write_text(json.dumps(result))
    monkeypatch.setattr('delivery.investment_memo_stage.run_private', local_selection_worker)
    job = {'input_revision': 'a' * 64, 'tenant_id': 'tenant', 'workspace_id': 'room', 'id': 'job'}
    lead = SimpleNamespace(company_name='Synthetic company')
    inventory = [Source(id=f'S{index + 1}', url=f'https://source{index}.example/about',
        title=f'Source {index}', passage='A retained attributable company source passage. ' * 12,
        version=f'version-{index}', attribution='Publisher') for index in range(2)]
    coverage = {'coverage_complete': False, 'omitted_passages': 1}
    assert resolve_memo_sources(job, lead, inventory, coverage, timeout=40)['reason'] == (
        'excluded_source_review_required')
    packet_file = tmp_path / 'excluded_source_review.json'
    packet = json.loads(packet_file.read_text())
    packet['excluded'][0]['source']['passage'] = 'Changed after selection'
    packet['packet_digest'] = digest({key: value for key, value in packet.items()
                                      if key != 'packet_digest'})
    packet_file.write_text(json.dumps(packet))
    # The private worker also rejects tampering on replay; the parent checks
    # the packet against the immutable inventory even if a worker misreports.
    monkeypatch.setattr('delivery.investment_memo_stage.run_private', lambda *args, **kwargs: None)
    (tmp_path / 'selection_result.json').write_text(json.dumps({
        'state': 'complete',
        'selected_passage_ids': [json.loads((tmp_path / 'inventory.json').read_text())['passages'][0]['passage_id']],
        'excluded_passage_ids': [json.loads((tmp_path / 'inventory.json').read_text())['passages'][1]['passage_id']],
        'inventory_digest': json.loads((tmp_path / 'inventory.json').read_text())['inventory_digest']}))
    assert resolve_memo_sources(job, lead, inventory, coverage, timeout=40) == {
        'state': 'blocked', 'reason': 'excluded_source_review_packet_invalid'}


def test_duplicate_excluded_rows_cannot_hide_in_review_packet(tmp_path, monkeypatch):
    monkeypatch.setattr('delivery.investment_memo_stage.memo_base_directory', lambda job: tmp_path)
    monkeypatch.setenv('PREPARATION_MODEL', 'qwen3.5:9b')
    model = SelectionModel()
    def worker(*args, **kwargs):
        result = evaluate_source_selection(tmp_path, model)
        (tmp_path / 'selection_result.json').write_text(json.dumps(result))
    monkeypatch.setattr('delivery.investment_memo_stage.run_private', worker)
    job = {'input_revision': 'a' * 64, 'tenant_id': 'tenant', 'workspace_id': 'room', 'id': 'job'}
    lead = SimpleNamespace(company_name='Synthetic company')
    inventory = [Source(id=f'S{index + 1}', url=f'https://source{index}.example/about',
        title=f'Source {index}', passage='A retained attributable company source passage. ' * 12,
        version=f'version-{index}', attribution='Publisher') for index in range(3)]
    coverage = {'coverage_complete': False, 'omitted_passages': 1}
    assert resolve_memo_sources(job, lead, inventory, coverage, timeout=40)['reason'] == (
        'excluded_source_review_required')
    packet_file = tmp_path / 'excluded_source_review.json'
    packet = json.loads(packet_file.read_text())
    packet['excluded'].append(packet['excluded'][-1])
    packet['packet_digest'] = digest({key: value for key, value in packet.items()
                                      if key != 'packet_digest'})
    packet_file.write_text(json.dumps(packet))
    monkeypatch.setattr('delivery.investment_memo_stage.run_private', lambda *args, **kwargs: None)
    assert resolve_memo_sources(job, lead, inventory, coverage, timeout=40) == {
        'state': 'blocked', 'reason': 'excluded_source_review_packet_invalid'}


def test_oversized_selection_result_requires_exact_partition_and_digest(tmp_path, monkeypatch):
    monkeypatch.setattr('delivery.investment_memo_stage.memo_base_directory', lambda job: tmp_path)
    monkeypatch.setenv('PREPARATION_MODEL', 'qwen3.5:9b')
    def forged_worker(*args, **kwargs):
        (tmp_path / 'selection_result.json').write_text(json.dumps({
            'state': 'awaiting_input', 'reason': 'selected_source_context_exceeded',
            'inventory_digest': 'stale', 'selected_passage_ids': ['a' * 64],
            'excluded_passage_ids': []}))
    monkeypatch.setattr('delivery.investment_memo_stage.run_private', forged_worker)
    job = {'input_revision': 'a' * 64, 'tenant_id': 'tenant', 'workspace_id': 'room', 'id': 'job'}
    lead = SimpleNamespace(company_name='Synthetic company')
    inventory = [Source(id='S1', url='https://source.example/about', title='Source',
        passage='A retained attributable company source passage. ' * 12,
        version='version-1', attribution='Publisher')]
    assert resolve_memo_sources(job, lead, inventory,
        {'coverage_complete': False, 'omitted_passages': 1}, timeout=40) == {
        'state': 'blocked', 'reason': 'source_selection_incomplete'}


def test_public_http_page_is_counted_as_source_host(monkeypatch):
    monkeypatch.delenv("ELASTICSEARCH_URL", raising=False)
    page = SimpleNamespace(origin="preparation_public_page", dataset_id=None,
        row_key="preparation_context_v4:http", source_url="http://publisher.example/about",
        quote="A retained public page has enough content to be an evidence passage.")
    lead = SimpleNamespace(tenant_id="tenant", company_name="Synthetic company",
        company_profile=SimpleNamespace(provenance={}, evidence=[page]))
    _, coverage = room_sources(PrivateStore(), lead, SimpleNamespace(deal_id=None))
    assert coverage["public_publishers"] == 1


def test_rejected_memo_is_terminal_for_same_job_and_sources(tmp_path, monkeypatch):
    monkeypatch.setattr('delivery.investment_memo_stage.memo_directory', lambda job: tmp_path)
    monkeypatch.setattr('delivery.investment_memo_stage.run_private',
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('reran rejected memo')))
    job = {'input_revision': 'a' * 64, 'tenant_id': 'tenant', 'workspace_id': 'room', 'id': 'job'}
    lead = SimpleNamespace(company_name='Synthetic company')
    sources = [Source(id='S1', url='https://example.org/', title='Source',
        passage='A sufficiently long public source passage about the company.',
        version='version123', attribution='Publisher')]
    payload = {'company': lead.company_name, 'sources': [source.model_dump() for source in sources],
               'input_revision': job['input_revision']}
    (tmp_path / 'request.json').write_text(json.dumps(payload))
    (tmp_path / 'result.json').write_text(json.dumps({'state': 'blocked', 'reason': 'review_rejected'}))
    (tmp_path / 'attempts.json').write_text(json.dumps([{'task': 'investment_memo_review'}]))
    assert run_memo_pass(job, lead, sources, timeout=20)['state'] == 'blocked'


def test_unfrozen_historical_memo_attempts_fail_clearly_without_rerun(tmp_path, monkeypatch):
    monkeypatch.setattr('delivery.investment_memo_stage.memo_directory', lambda job: tmp_path)
    monkeypatch.setattr('delivery.investment_memo_stage.run_private',
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('reran old attempt')))
    monkeypatch.setenv('PREPARATION_MODEL', 'qwen3.5:9b')
    job = {'input_revision': 'a' * 64, 'tenant_id': 'tenant', 'workspace_id': 'room', 'id': 'job'}
    lead = SimpleNamespace(company_name='Synthetic company')
    sources = [Source(id='S1', url='https://example.org/', title='Source',
        passage='A sufficiently long public source passage about the company.',
        version='version123', attribution='Publisher')]
    (tmp_path / 'request.json').write_text(json.dumps({
        'company': lead.company_name, 'sources': [source.model_dump() for source in sources],
        'input_revision': job['input_revision'], 'as_of_date': '2026-10-02'}))
    (tmp_path / 'model.json').write_text(json.dumps({'model': 'qwen3.5:9b'}))
    (tmp_path / 'attempts.json').write_text(json.dumps([{'task': 'investment_memo_part_a'}]))
    (tmp_path / 'result.json').write_text(json.dumps({'state': 'needs_resume'}))
    result = run_memo_pass(job, lead, sources, timeout=20)
    assert result['state'] == 'blocked'
    assert result['reason'] == 'legacy_model_profile_unfrozen'
    assert len(json.loads((tmp_path / 'attempts.json').read_text())) == 1
