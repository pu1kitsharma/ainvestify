"""Exact private lineage reads cannot become sibling or write capabilities."""
import platform
from pathlib import Path
import sys
import subprocess
from types import SimpleNamespace

import pytest

from delivery import isolation


def test_literal_capability_rejects_links_and_absent_paths_before_starting_worker(tmp_path,monkeypatch):
    job=tmp_path/'job';job.mkdir(mode=0o700)
    parent=tmp_path/'parent';parent.mkdir(mode=0o700)
    original=parent/'response_1.json';original.write_bytes(b'synthetic immutable row')
    link=tmp_path/'linked-row';link.symlink_to(original)
    monkeypatch.setattr(isolation.subprocess,'Popen',lambda *a,**kw:pytest.fail('Unsafe capability must fail before launch'))
    for capability in (link,tmp_path/'missing-row'):
        with pytest.raises(ValueError,match='canonical and present'):
            isolation.run_private(['/usr/bin/true'],job,extra_read_literals=[capability])
    assert not (job/'worker.sb').exists()


def _require_native_seatbelt():
    # Probe the host's ability to APPLY an independent minimal policy. Merely
    # having the executable is insufficient inside an enclosing macOS sandbox.
    probe = subprocess.run(['/usr/bin/sandbox-exec', '-p',
        '(version 1)(allow default)(deny network*)', '/usr/bin/true'],
        capture_output=True, timeout=5)
    if probe.returncode == 71 and probe.stderr.strip() == b'sandbox-exec: sandbox_apply: Operation not permitted':
        pytest.skip('Mandatory native private-isolation check UNRUN: enclosing sandbox forbids Seatbelt sandbox_apply; rerun in a qualified native host')
    assert probe.returncode == 0, 'Independent native Seatbelt capability probe failed unexpectedly'


def test_native_probe_only_skips_exact_host_capability_denial(monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=71, stderr=b'sandbox-exec: sandbox_apply: Operation not permitted\n'))
    with pytest.raises(pytest.skip.Exception, match='Mandatory native private-isolation check UNRUN'):
        _require_native_seatbelt()
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=65, stderr=b'sandbox-exec: invalid profile'))
    with pytest.raises(AssertionError, match='unexpectedly'):
        _require_native_seatbelt()
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stderr=b''))
    _require_native_seatbelt()


@pytest.mark.skipif(platform.system()!='Darwin' or not Path('/usr/bin/sandbox-exec').exists(),
                    reason='The native private boundary is macOS Seatbelt')
def test_exact_parent_row_read_allows_listing_but_denies_sibling_contents_and_writes(tmp_path):
    _require_native_seatbelt()
    job=tmp_path/'job';job.mkdir(mode=0o700)
    parent=tmp_path/'parent';parent.mkdir(mode=0o700)
    allowed=parent/'response_1.json';allowed.write_bytes(b'synthetic immutable row')
    sibling=parent/'unrelated-private-note.json';sibling.write_bytes(b'ungranted synthetic private bytes')
    code='''
import os,sys
from pathlib import Path
allowed,sibling,parent=map(Path,sys.argv[1:])
assert allowed.read_bytes()==b'synthetic immutable row'
assert sibling.name in os.listdir(parent)
try:
    sibling.read_bytes()
except PermissionError:
    pass
else:
    raise AssertionError('A directory literal granted its descendant contents')
try:
    allowed.write_bytes(b'forbidden replacement')
except PermissionError:
    pass
else:
    raise AssertionError('A read literal granted private writes')
print('exact_private_capabilities_pass')
'''
    raw=isolation.run_private([sys.executable,'-B','-c',code,allowed,sibling,parent],job,
                              timeout=10,extra_read_literals=[parent,allowed])
    assert raw.strip()==b'exact_private_capabilities_pass'
    profile=(job/'worker.sb').read_text()
    assert f'(literal "{parent}")' in profile and f'(literal "{allowed}")' in profile
    assert f'(subpath "{parent}")' not in profile and f'(subpath "{allowed}")' not in profile
    assert str(sibling) not in profile
    assert '(deny network*)' in profile
    write_rule=next(line for line in profile.splitlines() if 'deny file-write*' in line)
    assert str(parent) not in write_rule and str(allowed) not in write_rule
    assert allowed.read_bytes()==b'synthetic immutable row'
    assert sibling.read_bytes()==b'ungranted synthetic private bytes'
