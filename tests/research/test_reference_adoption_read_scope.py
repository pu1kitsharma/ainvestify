"""Checked source-map lineage gets individual files, never private subtrees."""
import hashlib
from pathlib import Path

import pytest

from delivery import document_generation_stage as stage
from scripts import evaluate_reference_generation as cli
from tests.delivery.test_document_generation_stage_source_maps import adoption_fixture,new_adoption_target


def lineage(tmp_path,monkeypatch):
    monkeypatch.setattr(cli,'PRIVATE_ROOT',tmp_path)
    parent,value,proof=adoption_fixture(tmp_path,monkeypatch)
    manifest=Path(proof['sources'][0]['manifest_path'])
    stage._write_new(manifest.parent/'document_manifest_receipt.json',{
        'binding':value['binding'],'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),
        'manifest_digest':value['manifest_digest']})
    child=new_adoption_target(tmp_path,value,proof,budgets=[900,900,1600],
                              profiles=['quoted-v1','quoted-v1','unit-ids-v2'])
    stage.adopt_source_map_prefix(child,parent,count=2)
    return child,parent,proof


def test_cli_adoption_worker_gets_checked_exact_files_and_never_parent_subpath(tmp_path,monkeypatch):
    child,parent,proof=lineage(tmp_path,monkeypatch)
    private_sibling=parent/'unrelated-private-data.json'
    private_sibling.write_bytes(b'never granted synthetic private bytes')
    expected={parent,parent/'request.json',parent/'source_provenance.json'}
    expected.update(Path(item[field]) for item in proof['sources'] for field in ('manifest_path','original_path'))
    for number in (1,2,3):
        expected.update((parent/f'response_{number}.json',parent/f'call_{number}.started.json'))
    assert set(cli._adoption_read_literals(child))==expected
    def isolated(command,job,*,timeout,extra_read,extra_read_literals,local_model):
        assert job==child and timeout==118 and local_model is False
        assert command[-1]=='verify'
        assert set(extra_read_literals)==expected
        assert parent not in extra_read and tmp_path not in extra_read
        assert private_sibling not in extra_read_literals
        return b'{"state":"needs_call","phase":"document_source_map"}'
    monkeypatch.setattr(cli,'run_private',isolated)
    monkeypatch.setattr(cli,'installed_digest',lambda *a:pytest.fail('Verification must not access model inventory'))
    assert cli.run(child,'verify')['phase']=='document_source_map'


def test_changed_adoption_parent_blocks_before_private_worker_and_grants(tmp_path,monkeypatch):
    child,parent,_=lineage(tmp_path,monkeypatch)
    row=parent/'response_1.json';row.write_bytes(row.read_bytes()+b' ')
    monkeypatch.setattr(cli,'run_private',lambda *a,**k:pytest.fail('Changed lineage must not launch'))
    with pytest.raises(ValueError):cli.run(child,'verify')
