"""Narrow font capabilities; real boundary probe is in test_private_runtime."""
from pathlib import Path
from delivery import isolation


def test_only_exact_nonsymlink_font_resource_gets_read_capability(tmp_path,monkeypatch):
    font=tmp_path/'font.ttf';font.write_bytes(b'synthetic-font-resource')
    link=tmp_path/'linked.ttf';link.symlink_to(font)
    monkeypatch.setattr(isolation,'READONLY_RENDER_FONTS',(font,link,tmp_path/'missing.ttf'))
    assert isolation._render_font_literals()==[str(font)]


def test_sandbox_profile_grants_literal_font_without_app_directory_or_write_access(tmp_path,monkeypatch):
    font=tmp_path/'font.ttf';font.write_bytes(b'synthetic-font-resource')
    job=tmp_path/'job';job.mkdir()
    monkeypatch.setattr(isolation,'READONLY_RENDER_FONTS',(font,))
    monkeypatch.setattr(isolation.platform,'system',lambda:'Darwin')
    class Process:
        returncode=0
        def communicate(self,timeout):return b'',b''
    monkeypatch.setattr(isolation.subprocess,'Popen',lambda *args,**kwargs:Process())
    isolation.run_private(['/usr/bin/true'],job)
    profile=(job/'worker.sb').read_text()
    assert f'(literal "{font}")' in profile
    assert f'(subpath "{font}")' not in profile
    assert '(subpath "/Applications")' not in profile
    assert '(deny network*)' in profile
    writes=next(line for line in profile.splitlines()if 'deny file-write' in line)
    assert str(font) not in writes
