"""Page-copy checks using the real page writer, audits and compliance adapter."""
import pytest

from delivery.deal_documents import pages, pipeline
from delivery.deal_documents.llm import ModelResponseError


def _page(key='risks'):
    return {'key': key, 'kind': 'grid', 'brief': 'Investment evidence', 'topics': [], 'cells': [],
            'title': 'An unsupported conclusion persists', 'takeaways': [], 'schedule': False,
            'exhibits': {'grid': {'header': ['Concern', 'Response'], 'rows': [['Unsupported concern', 'Unsupported reassurance']]}}}


class AuditModel:
    def __init__(self, disagree=False):
        self.profiles = []
        self.disagree = disagree

    def json(self, name, profile, system, user, schema, **kwargs):
        self.profiles.append(profile)
        assert 'Unsupported reassurance' in user
        evidence = user.split('SENTENCES:')[0]
        assert 'Unsupported reassurance' not in evidence
        return {'sentences': [{'n': n, 'kind': 'inference', 'verdict': 'pass' if self.disagree and profile == 'analyse' else 'refuse',
                               'why': 'No evidence supports this claim.'}
                              for n in range(schema['properties']['sentences']['minItems'])]}


@pytest.mark.parametrize('key', ['risks', 'highlights'])
def test_both_readers_audit_grid_rows_and_remove_persistent_refusals(key):
    model = AuditModel()
    page = _page(key)
    rewrites = []
    final = pages.audit_copy(model, page, [], lambda notes: rewrites.append(notes) or page, full=True)
    assert set(model.profiles) == {'check', 'analyse'}
    assert len(model.profiles) == 4
    assert len(rewrites) == 1
    assert 'Unsupported reassurance' in rewrites[0]
    assert final['title'] == ''
    assert final['exhibits']['grid']['rows'] == []
    assert final['problems']
    assert pipeline._page_sections([final], {'facts': []})[0]['problems'] == final['problems']


def test_one_readers_refusal_is_preserved_for_review_without_rewriting():
    page = _page()
    def rewrite(notes):
        pytest.fail('One reader alone must not flatten a supported page')
    final = pages.audit_copy(AuditModel(disagree=True), page, [], rewrite, full=True)
    assert final['title'] == page['title']
    assert not final['audit']
    assert final['audit_noted']


def test_a_rewrite_cannot_pass_an_audit_by_removing_almost_all_the_copy():
    page = _page()
    model = AuditModel()
    empty = {**page, 'title': 'Operating evidence overview', 'exhibits': {'grid': {'header': ['Concern'], 'rows': []}}}
    final = pages.audit_copy(model, page, [], lambda notes: empty, full=True)
    assert len(model.profiles) == 2
    assert final['audit']
    assert final['problems']


def test_audit_cannot_silently_skip_a_line_by_repeating_an_index():
    class DuplicateModel:
        def json(self, *args):
            return {'sentences': [{'n': 0, 'verdict': 'pass'}, {'n': 0, 'verdict': 'pass'}]}
    with pytest.raises(ModelResponseError, match='every line exactly once'):
        pages._audit_lines(DuplicateModel(), _page(), ['One', 'Two'], '', 'audit')


def test_diligence_pages_require_relevant_source_facts_and_reach_the_writer():
    fact = {'id': 'source-claim', 'statement': 'The company operates under a stated authorization.', 'topic': 'regulatory',
            'value': '', 'metric': '', 'unit': '', 'basis': 'company_claim', 'period': '', 'segment': '',
            'document': 'Source', 'location': 'page 1'}
    base = {'facts': [fact], 'workbook_cells': []}
    plan = pipeline._page_plan(base, [])
    page = next(page for page in plan if page['key'] == 'regulatory')
    assert page['cells'] == ['source-claim']
    assert not any(page['key'] == 'regulatory' for page in pipeline._page_plan({'facts': [], 'workbook_cells': []}, []))
    class Writer:
        def json(self, name, profile, system, user, schema):
            assert fact['statement'] in user
            return {'title': 'The stated authorization defines the operating scope', 'takeaways': []}
    written = pages.write_copy(Writer(), page, base['facts'])
    assert not written['problems']


def test_the_gate_reads_merit_rows_and_keeps_every_page_problem():
    page = {**_page('highlights'), 'problems': ['audit unavailable']}
    sections = pipeline._page_sections([page], {'facts': []})
    assert 'Unsupported reassurance' in ' '.join(p['text'] for p in sections[0]['paragraphs'])
    assert sections[0]['problems'] == ['audit unavailable']


def test_preview_download_keeps_room_authorization_and_draft_headers(tmp_path, monkeypatch):
    from api.routers import deal_documents as api
    checked = []
    def authorized(store, identity, room_id):
        checked.append(room_id)
        return {'run_dir': str(tmp_path)}
    monkeypatch.setattr(api, '_run', authorized)
    (tmp_path / 'investment_memorandum.preview.pdf').write_bytes(b'synthetic preview bytes')
    response = api.file('room', 'investment_memorandum.preview.pdf', store=object(), identity=object())
    assert checked == ['room']
    assert response.body == b'synthetic preview bytes'
    assert response.headers['x-artifact-state'] == 'draft'
    assert response.headers['cache-control'] == 'no-store'
    assert response.media_type == 'application/pdf'
    with pytest.raises(api.HTTPException):
        api.file('room', 'pages.preview.json', store=object(), identity=object())


def test_unfinished_preview_is_not_presented_as_a_finished_earlier_version(tmp_path):
    import json
    from api.routers import deal_documents as api
    version = tmp_path / 'superseded' / '20250101T000000Z'
    version.mkdir(parents=True)
    (version / 'investment_memorandum.preview.pdf').write_bytes(b'synthetic preview')
    assert api.earlier_versions(tmp_path) == []
    (version / 'investment_memorandum.pdf').write_bytes(b'synthetic completed draft')
    rounds = [{'round': 0, 'scores': {'page': 80}, 'kept': ['page'], 'dropped': []}]
    (version / 'memo_review.json').write_text(json.dumps({'climb': rounds}))
    assert api.earlier_versions(tmp_path)[0]['rounds'] == rounds


def test_page_progress_can_be_read_before_any_review_copy_exists(tmp_path):
    import json
    from api.routers import deal_documents as api
    built = [{**_page('company'), 'title': 'Completed page', 'takeaways': ['An evidence-backed implication.'], 'page_status': 'written'},
             {**_page('market'), 'page_status': 'pending'}]
    (tmp_path / 'pages.preview.json').write_text(json.dumps({'generation': 1, 'pages': built}))
    assert api.draft_sections(tmp_path) == [{'title': 'Completed page', 'paragraphs': ['An evidence-backed implication.']}]
