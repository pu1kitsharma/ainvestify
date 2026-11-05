"""Explicit public HTTPS read/cancel-denial smoke over retained technical fixtures.

No browser login, fixture creation, queue activation, model call, service change
or public-mode change. Temporary production-factory sessions remain in memory.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys


class SmokeFailure(RuntimeError):
    pass


def sha(value):
    return hashlib.sha256(value).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--fixture-report', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--acknowledge-public-acceptance-sessions', action='store_true')
    args = parser.parse_args()
    runtime, output = args.runtime_root.resolve(), args.output.absolute()
    repository = Path(__file__).resolve().parents[1]
    if (not args.acknowledge_public_acceptance_sessions or output.exists() or output.resolve()!=output
            or output.is_relative_to(runtime) or output.is_relative_to(repository)):
        parser.error('Use an explicitly acknowledged fresh outside-Git private output directory')
    os.umask(0o077); output.mkdir(mode=0o700, parents=True)
    source = Path(__file__).read_bytes(); (output/'qualified-invoker.py').write_bytes(source)
    sys.path.insert(0, str(runtime))
    from scripts.local_hosting import read_env_file, database_path
    config = read_env_file(args.env_file); database = database_path(config, root=runtime); del config
    from store import Store
    from security.identity import create_session, revoke_session, token_hash, COOKIE
    import httpx

    retained = json.loads(args.fixture_report.read_text())
    report = {'contract':'public-authenticated-technical-smoke-v1', 'started_utc':datetime.now(timezone.utc).isoformat(),
        'state':'started', 'origin':'https://investify.fyi', 'tls_verification_enabled':True,
        'normal_os_dns_without_overrides':True, 'follow_redirects':False,
        'session_scope':'Two temporary production-factory sessions for the same existing verified Google owners. Google browser callbacks were qualified separately; this is not a new browser sign-in.',
        'new_browser_login':False, 'fixtures_created':0, 'uploads_created':0, 'activations_requested':0,
        'model_calls_requested':0, 'service_changes':False, 'public_mode_changes':False,
        'all_other_user_activity_left_running':True, 'fixture_report':str(args.fixture_report),
        'fixture_report_sha256':sha(args.fixture_report.read_bytes()), 'invoker_sha256':sha(source), 'checks':[]}
    actors, sessions = [], []
    current = 'preflight'
    client = httpx.Client(base_url='https://investify.fyi', verify=True, trust_env=False,
                         follow_redirects=False, timeout=35, headers={'Accept-Encoding':'identity'})

    def check(condition, label):
        if not condition: raise SmokeFailure(label)

    def request(actor, method, path, status, label, headers=None):
        nonlocal current
        current = label
        sent = {'Origin':'https://investify.fyi'}
        if actor:
            sent.update({'Cookie':COOKIE+'='+actor['token'], 'X-CSRF-Token':actor['csrf']})
        sent.update(headers or {})
        response = client.request(method, path, headers=sent)
        cache = response.headers.get('cf-cache-status')
        entry = {'name':label, 'method':method, 'path':path, 'expected_status':status,
                 'actual_status':response.status_code, 'cache_control':response.headers.get('cache-control'),
                 'cf_cache_status':cache, 'cf_ray_present':bool(response.headers.get('cf-ray')),
                 'content_type':response.headers.get('content-type')}
        report['checks'].append(entry)
        check(response.status_code==status, label+' HTTP status')
        check(response.headers.get('cache-control')=='no-store', label+' no-store')
        check(bool(response.headers.get('cf-ray')), label+' Cloudflare path')
        if method=='GET':check(cache=='DYNAMIC', label+' private response remains DYNAMIC')
        elif cache:check(cache in ('DYNAMIC','BYPASS'), label+' write/error is not cached')
        stream = response.extensions.get('network_stream')
        if stream:
            ssl = stream.get_extra_info('ssl_object')
            if ssl:entry['tls_version'] = ssl.version()
        return response

    def snapshot(store, actor):
        fixture = actor['fixture']; tenant = actor['tenant']; room = fixture['workspace_id']
        tables = {
            'workspace':store.conn.execute('SELECT data FROM operating_workspaces WHERE tenant_id=? AND id=?',(tenant,room)).fetchall(),
            'documents':store.conn.execute('SELECT id,data FROM documents WHERE tenant_id=? AND deal_id=? ORDER BY id',(tenant,fixture['deal_id'])).fetchall(),
            'artifacts':store.conn.execute('SELECT id,sha256,state FROM room_artifacts WHERE tenant_id=? AND workspace_id=? ORDER BY id',(tenant,room)).fetchall(),
            'packages':store.conn.execute('SELECT id,manifest,checks,reviews,state FROM room_packages WHERE tenant_id=? AND workspace_id=? ORDER BY id',(tenant,room)).fetchall(),
            'cancel_target':store.conn.execute('SELECT id,state,lease_token,lease_until FROM room_jobs WHERE id=? AND tenant_id=?',(actor['cancel_job'],tenant)).fetchall()}
        return sha(json.dumps(tables,sort_keys=True,separators=(',',':')).encode())

    try:
        check(retained['state']=='pass' and len(retained['actors'])==len(retained['fixtures'])==2, 'retained two-owner fixture proof')
        identity_file = runtime/'security/identity.py'
        manifest = {r['path']:r['sha256'] for r in json.loads((runtime/'.hosting-code-manifest.json').read_text())['files']}
        check(sha(identity_file.read_bytes())==manifest['security/identity.py'], 'production session factory matches checked manifest')
        backup = output/'before.sqlite3'; source_db = sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True); target_db = sqlite3.connect(backup)
        try:
            source_db.execute('PRAGMA query_only=ON'); source_db.backup(target_db)
            check(target_db.execute('PRAGMA integrity_check').fetchone()[0]=='ok', 'checked live backup')
        finally:target_db.close();source_db.close()
        report['backup'] = {'path':str(backup),'sha256':sha(backup.read_bytes()),'integrity':'ok'}
        with Store(database) as store:
            before_sessions = {r[0]:tuple(r[1:]) for r in store.conn.execute(
                'SELECT token_hash,user_id,tenant_id,created,expires,revoked FROM auth_sessions')}
            report['other_active_sessions_before'] = sum(not value[-1] for value in before_sessions.values())
            owners = {sha(user.encode()):(user,tenant) for user,tenant in store.conn.execute('SELECT owner_id,id FROM auth_sandboxes')}
            for expected,fixture in zip(retained['actors'],retained['fixtures']):
                user,tenant = owners[expected['user_id_sha256']]
                check(sha(tenant.encode())==expected['sandbox_id_sha256'], 'same retained sandbox')
                check(store.conn.execute("SELECT 1 FROM auth_identities WHERE user_id=? AND issuer='https://accounts.google.com'",(user,)).fetchone() is not None, 'existing Google identity')
                workspace = store.get_workspace(tenant,workspace_id=fixture['workspace_id'])
                lead = store.get_lead(tenant,fixture['lead_id'])
                check(workspace is not None and workspace.deal_id==fixture['deal_id'] and lead.company_name.startswith('SYNTHETIC HTTP isolation acceptance '+retained['run_id']), 'retained technical fixture association')
                row = store.conn.execute("SELECT id FROM room_jobs WHERE tenant_id=? AND workspace_id=? AND state='cancelled' AND lease_token IS NULL ORDER BY created LIMIT 1",(tenant,workspace.id)).fetchone()
                check(row is not None, 'historical already-cancelled fixture job')
                package = store.conn.execute("SELECT id FROM room_packages WHERE tenant_id=? AND workspace_id=? AND state='blocked' ORDER BY id LIMIT 1",(tenant,workspace.id)).fetchone()
                check(package is not None, 'existing blocked technical package')
                token,csrf = create_session(store.conn,user,tenant)
                actor = {'alias':expected['alias'],'user':user,'tenant':tenant,'fixture':fixture,
                         'token':token,'csrf':csrf,'cancel_job':row[0],'package':package[0]}
                actors.append(actor);sessions.append((token,token_hash(token)))
                actor['before'] = snapshot(store,actor)
        report['acceptance_sessions_created'] = len(sessions)
        for actor in actors:
            alias,fixture = actor['alias'],actor['fixture']
            me = request(actor,'GET','/api/auth/me',200,alias+' public owner identity').json()
            check((me['user_id'],me['tenant_id'],me['role'])==(actor['user'],actor['tenant'],'owner'), 'server identity and private sandbox')
            status = request(actor,'GET','/api/rooms/'+fixture['workspace_id'],200,alias+' public own room').json()
            check(status['id']==fixture['workspace_id'] and status['deal_id']==fixture['deal_id'], 'room identity')
            documents = request(actor,'GET','/api/deals/'+fixture['deal_id']+'/source-documents',200,alias+' public retained source lineage').json()
            check(len(documents)==2 and {r['id'] for r in documents}=={r['document_id'] for r in fixture['uploads']}, 'same two retained source documents')
            check(all(r['tenant_id']==actor['tenant'] and r['deal_id']==fixture['deal_id'] for r in documents), 'same owner source document scope')
            artifact = fixture['technical_preview']; base = '/api/rooms/'+fixture['workspace_id']+'/artifacts/'+artifact['artifact_id']
            for suffix,disposition in (('/preview?inline=true','inline;'),('/preview','attachment;')):
                result = request(actor,'GET',base+suffix,200,alias+' public exact draft '+disposition)
                check(sha(result.content)==artifact['sha256'] and result.headers.get('x-artifact-state')=='draft'
                      and result.headers.get('content-disposition','').startswith(disposition)
                      and 'DRAFT-' in result.headers['content-disposition'], 'exact technical draft bytes and disposition')
            request(actor,'GET',base+'/download',409,alias+' final download remains blocked')
            cancel = '/api/rooms/'+fixture['workspace_id']+'/jobs/'+actor['cancel_job']+'/cancel'
            request(actor,'POST',cancel,403,alias+' public negative CSRF cancellation',{'X-CSRF-Token':'invalid-technical-token'})
            with Store(database) as store:
                check(store.conn.execute('SELECT state FROM room_jobs WHERE id=? AND tenant_id=?',(actor['cancel_job'],actor['tenant'])).fetchone()[0]=='cancelled', 'positive write only targets already-cancelled job')
            result = request(actor,'POST',cancel,200,alias+' public idempotent owned cancellation').json()
            check(result['state']=='cancelled', 'cancelled job remains cancelled')
            release = '/api/rooms/'+fixture['workspace_id']+'/packages/'+actor['package']+'/release'
            request(actor,'POST',release,403,alias+' release requires CSRF',{'X-CSRF-Token':'invalid-technical-token'})
            request(actor,'POST',release,409,alias+' missing or stale reviews block public release')
        for actor,other in ((actors[0],actors[1]),(actors[1],actors[0])):
            own,foreign = actor['fixture'],other['fixture']; spoof={'X-Tenant-ID':other['tenant'],'X-Reviewer':other['user']}
            for path in ('/api/rooms/'+foreign['workspace_id'],'/api/deals/'+foreign['deal_id']+'/source-documents',
                         '/api/rooms/'+foreign['workspace_id']+'/artifacts/'+foreign['technical_preview']['artifact_id']+'/preview?inline=true',
                         '/api/rooms/'+own['workspace_id']+'/artifacts/'+foreign['technical_preview']['artifact_id']+'/preview?inline=true'):
                request(actor,'GET',path,404,actor['alias']+' public cross-owner/header-spoof denial',spoof)
            request(actor,'POST','/api/rooms/'+own['workspace_id']+'/packages/'+other['package']+'/release',404,
                    actor['alias']+' foreign package release denied',spoof)
        request(None,'GET','/api/rooms/'+actors[0]['fixture']['workspace_id'],401,'anonymous spoofed identity remains unauthenticated',{'X-Tenant-ID':actors[0]['tenant']})
        with Store(database) as store:
            check(all(snapshot(store,actor)==actor['before'] for actor in actors), 'retained fixture business rows unchanged')
        for actor in actors:
            request(actor,'POST','/api/auth/logout',204,actor['alias']+' public temporary session logout')
            request(actor,'GET','/api/auth/me',401,actor['alias']+' revoked temporary cookie cannot authenticate')
        report['state'] = 'pass'
    except Exception as exc:
        report.update(state='fail',failed_check=current,error_type=type(exc).__name__)
        if type(exc) is SmokeFailure:report['failed_assertion']=exc.args[0]
    finally:
        cleanup={'temporary_sessions_revoked':0,'temporary_sessions_active':0,'rows_deleted':0,
                 'other_sessions_targeted':0,'jobs_enqueued':0,'models_called':0,'errors':[]}
        try:
            with Store(database) as store:
                for token,hashed in sessions:
                    revoke_session(store.conn,token)
                    check(store.conn.execute('SELECT revoked FROM auth_sessions WHERE token_hash=?',(hashed,)).fetchone()[0]==1, 'our temporary session revoked')
                    cleanup['temporary_sessions_revoked'] += 1
                ours={hashed for _,hashed in sessions}
                cleanup['temporary_sessions_active']=sum(r[0] in ours for r in store.conn.execute('SELECT token_hash FROM auth_sessions WHERE revoked=0'))
                after={r[0]:tuple(r[1:]) for r in store.conn.execute('SELECT token_hash,user_id,tenant_id,created,expires,revoked FROM auth_sessions') if r[0] not in ours}
                baseline=locals().get('before_sessions',{})
                cleanup['preexisting_sessions_deleted']=sum(key not in after for key in baseline)
                cleanup['preexisting_sessions_changed_excluding_touched']=sum(key in after and after[key]!=value for key,value in baseline.items())
                cleanup['concurrent_other_user_changes_never_restored']=True
        except Exception as exc:cleanup['errors'].append(type(exc).__name__);report['state']='fail'
        client.close();report['cleanup']=cleanup;report['http_checks']=len(report['checks'])
        report['failed_status_checks']=sum(r['actual_status']!=r['expected_status'] for r in report['checks'])
        report['completed_utc']=datetime.now(timezone.utc).isoformat()
        report['limitations']=['Factory-session public HTTPS proof, not a new Google browser callback.',
            'Retained synthetic technical drafts only; no company answers or investor qualification.',
            'No worker/model pass, activation, upload, global queue assertion or public/service change.']
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        for actor in actors:actor.pop('token',None);actor.pop('csrf',None)
        sessions.clear()
        print(json.dumps({'state':report['state'],'http_checks':report['http_checks'],
                          'failed_check':report.get('failed_check'),'report':str(output/'report.json'),'cleanup':cleanup},indent=2))
    return 0 if report['state']=='pass' else 1


if __name__=='__main__':raise SystemExit(main())
