"""Draft slot idempotence and release-manifest separation."""
import hashlib

import pytest

from api.routers.rooms import revision_for
from delivery.artifacts import get_artifact, register_draft
from delivery.contracts import REQUIRED_MATERIAL_KINDS
from delivery.release import load_package
from delivery.rendering import render_intro, render_research_pdf
from store import Store
from tests.api.test_authentication import secured, sign_in


def _room(client, store, tenant):
    created = client.post('/api/rooms', json={
        'name': 'Synthetic company', 'website': 'https://synthetic.example'}).json()
    room = store.get_workspace(tenant, workspace_id=created['workspace_id'])
    return room, revision_for(store, room)


def test_same_revision_slot_reuses_identical_bytes_and_rejects_changed_bytes(
        secured, tmp_path, monkeypatch):
    client, db, users = secured
    monkeypatch.setenv('PRIVATE_ARTIFACT_ROOT', str(tmp_path / 'artifacts'))
    sign_in(client, users[0])
    with Store(db) as store:
        room, revision = _room(client, store, users[0][1])
        first = render_intro('Synthetic company', [('Intro', 'Original text', 'Fixture')])
        changed = render_intro('Synthetic company', [('Intro', 'Changed text', 'Fixture')])
        artifact_id = register_draft(store.conn, users[0][1], room.id,
                                     'intro_deck', 'pptx', revision, first)
        assert register_draft(store.conn, users[0][1], room.id,
                              'intro_deck', 'pptx', revision, first) == artifact_id
        with pytest.raises(ValueError, match='different bytes'):
            register_draft(store.conn, users[0][1], room.id,
                           'intro_deck', 'pptx', revision, changed)
        assert get_artifact(store.conn, users[0][1], artifact_id)['sha256'] == hashlib.sha256(first).hexdigest()


def test_internal_research_pdf_stays_preview_only_and_validation_reports_missing_formats(
        secured, tmp_path, monkeypatch):
    client, db, users = secured
    monkeypatch.setenv('PRIVATE_ARTIFACT_ROOT', str(tmp_path / 'artifacts'))
    sign_in(client, users[0])
    with Store(db) as store:
        room, revision = _room(client, store, users[0][1])
        draft = render_research_pdf('Synthetic company', [
            ('Research', 'Synthetic fixture analysis.', 'Synthetic fixture source')])
        preview_id = register_draft(store.conn, users[0][1], room.id,
                                    'research_brief', 'pdf', revision, draft)
    response = client.post(f'/api/rooms/{room.id}/validate')
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['eligible_for_release'] is False
    assert 'missing_file:investment_memorandum:pdf' in result['blockers']
    with Store(db) as store:
        manifest, _, _, _ = load_package(store, users[0][1], result['package_id'])
        assert manifest.requested == REQUIRED_MATERIAL_KINDS
        assert 'financial_projection' not in manifest.requested
        assert preview_id not in {file.artifact_id for file in manifest.files}
        assert get_artifact(store.conn, users[0][1], preview_id)['state'] == 'draft'


def test_unsupported_artifact_kind_or_format_cannot_enter_release_registry(
        secured, tmp_path, monkeypatch):
    client, db, users = secured
    monkeypatch.setenv('PRIVATE_ARTIFACT_ROOT', str(tmp_path / 'artifacts'))
    sign_in(client, users[0])
    with Store(db) as store:
        room, revision = _room(client, store, users[0][1])
        for kind, fmt in [('unknown_preview', 'pdf'), ('research_brief', 'pptx'),
                          ('investment_memorandum', 'xlsx')]:
            with pytest.raises(ValueError, match='Unsupported artifact kind or format'):
                register_draft(store.conn, users[0][1], room.id, kind, fmt,
                               revision, b'not-an-artifact')
        assert store.conn.execute('SELECT COUNT(*) FROM room_artifacts').fetchone()[0] == 0


def test_validation_blocks_mismatched_exact_pptx_pdf_pair(secured, tmp_path, monkeypatch):
    from io import BytesIO
    from reportlab.pdfgen import canvas

    client, db, users = secured
    monkeypatch.setenv('PRIVATE_ARTIFACT_ROOT', str(tmp_path / 'artifacts'))
    sign_in(client, users[0])
    output = BytesIO()
    pdf = canvas.Canvas(output)
    pdf.drawString(72, 720, 'Synthetic fixture page')
    pdf.showPage()
    pdf.save()
    with Store(db) as store:
        room, revision = _room(client, store, users[0][1])
        pptx = render_intro('Synthetic company', [
            ('First', 'First source-bound fixture section.', 'Fixture'),
            ('Second', 'Second source-bound fixture section.', 'Fixture')])
        register_draft(store.conn, users[0][1], room.id, 'intro_deck', 'pptx', revision, pptx)
        pdf_id = register_draft(store.conn, users[0][1], room.id, 'intro_deck',
                                'pdf', revision, output.getvalue())
    response = client.post(f'/api/rooms/{room.id}/validate')
    assert response.status_code == 200, response.text
    with Store(db) as store:
        _, checks, _, _ = load_package(store, users[0][1], response.json()['package_id'])
    pair_checks = [check for check in checks if check.target == pdf_id
                   and check.check_id == 'file_compatibility']
    assert len(pair_checks) == 1
    assert pair_checks[0].status == 'fail'
    assert not response.json()['eligible_for_release']


def test_recorded_text_exports_form_three_exact_structural_pairs(tmp_path, monkeypatch):
    from delivery.inspection import inspect_export_pair
    from scripts.private_document_worker import main

    sections = [('Synthetic finding',
                 'Recorded synthetic analysis cites [S1]; ₹20 million is illustrative.',
                 '[S1] Synthetic fixture, exact version')]
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'request.json').write_text(__import__('json').dumps({
        'operation': 'render', 'title': 'Synthetic company',
        'memo_sections': sections,
        'intro_sections': [(*sections[0], 'evidence')],
        'pitch_sections': [(*sections[0], 'comparison'),
                           ('Synthetic risk', 'Recorded synthetic 2024 uncertainty cites [S1].',
                            '[S1] Synthetic fixture, exact version', 'timeline')]}))
    main()
    for stem, editable_format in (('intro', 'pptx'), ('pitch', 'pptx'), ('memo', 'docx')):
        pair = inspect_export_pair((tmp_path / f'{stem}.{editable_format}').read_bytes(),
            editable_format, (tmp_path / f'{stem}.pdf').read_bytes())
        assert pair['pair_status'] == pair['editable_text_status'] == 'pass'
    assert (tmp_path / 'research.pdf').is_file()
