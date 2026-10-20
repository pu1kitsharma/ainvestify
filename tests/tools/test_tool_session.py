import hashlib
import json
from zipfile import ZipFile

import pytest

from scripts.qualify_agentic_tool_session import run_session, replay_session


def test_scripted_session_has_two_slides_live_formula_and_replays_without_effects(tmp_path):
    from openpyxl import load_workbook
    root = tmp_path / 'session'
    result = run_session(root)
    assert result['actual_model_calls'] == 0
    assert result['scripted_transport_calls'] == 6
    assert result['release'] == 'blocked'
    assert load_workbook(root / 'model.xlsx')['Historicals']['D3'].value == '=C3/C2-1'
    with ZipFile(root / 'synthetic-v1.pack/synthetic-v1.pptx') as archive:
        slides = [n for n in archive.namelist() if n.startswith('ppt/slides/slide') and n.endswith('.xml')]
        assert len(slides) == 2
        assert len([n for n in archive.namelist() if n.startswith('ppt/embeddings/')]) == 1
    before = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    assert replay_session(root, expected_sha256=result['session_sha256'])['rerendered'] is False
    after = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    assert before == after
    with pytest.raises(FileExistsError):
        run_session(root)


def test_replay_rejects_changed_workbook_and_export_bytes(tmp_path):
    root = tmp_path / 'session'
    result = run_session(root)
    workbook = root / 'model.xlsx'
    original = workbook.read_bytes()
    workbook.write_bytes(original + b'changed')
    with pytest.raises(ValueError, match='evidence changed'):
        replay_session(root, expected_sha256=result['session_sha256'])
    workbook.write_bytes(original)
    authoring_log = root / 'workbook.trajectory.jsonl'
    log_original = authoring_log.read_bytes()
    authoring_log.write_bytes(log_original + b'changed')
    with pytest.raises(ValueError, match='evidence changed'):
        replay_session(root, expected_sha256=result['session_sha256'])
    authoring_log.write_bytes(log_original)
    (root / 'synthetic-v1.pack/synthetic-v1.docx').write_bytes(b'changed')
    with pytest.raises(ValueError):
        replay_session(root, expected_sha256=result['session_sha256'])
