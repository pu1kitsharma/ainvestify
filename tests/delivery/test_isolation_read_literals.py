"""Exact private lineage reads cannot become sibling or write capabilities."""
import platform
from pathlib import Path
import sys

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


@pytest.mark.skipif(platform.system()!='Darwin' or not Path('/usr/bin/sandbox-exec').exists(),
                    reason='The native private boundary is macOS Seatbelt')
def test_exact_parent_row_read_allows_listing_but_denies_sibling_contents_and_writes(tmp_path):
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
