import pytest
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from public_kb.ingestion import PublicIngestion


def source(kb, **changes):
    settings = dict(source_id='approved-feed', url='https://publisher.example/feed',
        terms_url='https://publisher.example/terms', reviewed_at='2026-09-30',
        automated_access=True, retention=True, inference_processing=True,
        investor_reuse=True, enabled=True)
    settings.update(changes)
    kb.register_source(**settings)


def test_disabled_or_incomplete_rights_cannot_stage(tmp_path):
    kb=PublicIngestion(tmp_path/'kb.sqlite',tmp_path/'archive')
    with pytest.raises(ValueError): source(kb,investor_reuse=False)
    source(kb,enabled=False,investor_reuse=False)
    with pytest.raises(PermissionError): kb.stage('approved-feed',b'public fixture')
    assert kb.pending()==[]
    kb.close()


def test_unchanged_version_indexes_once_and_changed_version_is_retained(tmp_path):
    kb=PublicIngestion(tmp_path/'kb.sqlite',tmp_path/'archive');source(kb)
    first=kb.stage('approved-feed',b'public version one')
    assert kb.stage('approved-feed',b'public version one')==first
    calls=[]
    kb.publish_pending(lambda source_id,digest,content:calls.append((source_id,digest,content)))
    kb.publish_pending(lambda *args:calls.append(args))
    assert len(calls)==1
    second=kb.stage('approved-feed',b'public version two')
    assert second!=first
    kb.publish_pending(lambda *args:calls.append(args))
    assert len(calls)==2
    assert (tmp_path/'archive'/'approved-feed'/first).read_bytes()==b'public version one'
    kb.close()


def test_failed_sink_resumes_and_revoked_rights_pause_pending(tmp_path):
    kb=PublicIngestion(tmp_path/'kb.sqlite',tmp_path/'archive');source(kb)
    digest=kb.stage('approved-feed',b'public version')
    def fails(*args): raise RuntimeError('index unavailable')
    with pytest.raises(RuntimeError): kb.publish_pending(fails)
    assert kb.pending()==[('approved-feed',digest)]
    source(kb,enabled=False)
    assert kb.pending()==[]
    source(kb)
    seen=[];kb.publish_pending(lambda *args:seen.append(args))
    assert len(seen)==1 and kb.pending()==[]
    kb.close()


def test_overlapping_stagers_share_one_version(tmp_path):
    db, archive = tmp_path/'kb.sqlite', tmp_path/'archive'
    setup=PublicIngestion(db,archive);source(setup);setup.close()
    def stage():
        kb=PublicIngestion(db,archive)
        try: return kb.stage('approved-feed',b'same public version')
        finally: kb.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        hashes=list(pool.map(lambda _:stage(),range(2)))
    assert hashes[0]==hashes[1]
    kb=PublicIngestion(db,archive)
    assert kb.pending()==[('approved-feed',hashes[0])]
    kb.close()


def test_overlapping_publishers_do_not_call_sink_twice(tmp_path):
    db, archive = tmp_path/'kb.sqlite', tmp_path/'archive'
    setup=PublicIngestion(db,archive);source(setup)
    setup.stage('approved-feed',b'public record');setup.close()
    entered, release = Event(), Event()
    calls=[]
    def slow_sink(*args):
        calls.append(args);entered.set();assert release.wait(5)
    def publish(sink):
        kb=PublicIngestion(db,archive)
        try: kb.publish_pending(sink)
        finally: kb.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(publish,slow_sink)
        assert entered.wait(5)
        second=pool.submit(publish,lambda *args:calls.append(args))
        second.result(timeout=5)
        release.set();first.result(timeout=5)
    assert len(calls)==1


def test_source_version_keeps_original_attribution_after_registry_edit(tmp_path):
    kb=PublicIngestion(tmp_path/'kb.sqlite',tmp_path/'archive');source(kb)
    digest=kb.stage('approved-feed',b'first public item',source_url='https://publisher.example/first',content_type='text/html')
    source(kb,terms_url='https://publisher.example/new-terms')
    with pytest.raises(ValueError,match='immutable'):
        source(kb,url='https://publisher.example/new-feed')
    kb.stage('approved-feed',b'first public item',source_url='https://publisher.example/other')
    assert kb.conn.execute('SELECT source_url,terms_url,content_type FROM version_metadata WHERE source_id=? AND sha256=?',
                           ('approved-feed',digest)).fetchone() == (
                               'https://publisher.example/first','https://publisher.example/terms','text/html')
    with pytest.raises(ValueError):
        kb.stage('approved-feed',b'poison',source_url='https://other.example/private')
    kb.close()
