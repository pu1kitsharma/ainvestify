"""Explicit live loopback acceptance with retained synthetic fixtures only.

Uses temporary production-factory sessions for two existing verified Google
identities. Browser callbacks are a separate acceptance result. No model call,
worker execution, public enabling, data deletion or service change is performed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
import uuid


class AcceptanceFailure(RuntimeError):
    pass


def sha(body):
    return hashlib.sha256(body).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resume-fixtures-from', type=Path)
    parser.add_argument('--acknowledge-live-synthetic-writes', action='store_true')
    args = parser.parse_args()
    if not args.acknowledge_live_synthetic_writes:
        parser.error('Explicit live synthetic-write acknowledgement is required')
    runtime, output = args.runtime_root.resolve(), args.output.absolute()
    repository = Path(__file__).resolve().parents[1]
    if (not runtime.is_dir() or output.exists() or output.resolve() != output
            or output.is_relative_to(runtime) or output.is_relative_to(repository)):
        parser.error('Use a fresh canonical output directory outside the runtime and Git checkout')
    output.mkdir(mode=0o700, parents=True)
    os.umask(0o077)
    prior, prior_hash = None, None
    if args.resume_fixtures_from:
        previous = args.resume_fixtures_from.absolute()
        if previous.resolve() != previous or previous.is_relative_to(repository) or previous.is_relative_to(runtime):
            parser.error('The retained fixture report must be canonical and outside Git/runtime code')
        raw = previous.read_bytes(); prior = json.loads(raw); prior_hash = sha(raw)
        if (prior.get('contract') != 'live-loopback-http-isolation-v1'
                or prior.get('failed_http_checks') != 0 or len(prior.get('fixtures', [])) != 2
                or len(prior.get('actors', [])) != 2):
            parser.error('Resume requires the exact two-fixture acceptance report without HTTP failures')
    sys.path.insert(0, str(runtime))
    from scripts.local_hosting import read_env_file, database_path, database_inventory
    config = read_env_file(args.env_file)
    database = database_path(config, root=runtime)
    os.environ['INVESTIFY_DB_PATH'] = str(database)
    # Use the production paths/model revision inputs without copying OIDC secrets
    # into this process environment or any worker.
    for key, value in config.items():
        if key.startswith(('LOCAL_MEMO_', 'PRIVATE_', 'PREPARATION_')) or key in (
                'SOURCING_MODEL', 'REASONING_MODEL', 'LOCAL_OLLAMA_HARDWARE_PROFILE'):
            os.environ[key] = value
    del config
    from security.identity import create_session, revoke_session, token_hash, COOKIE
    from store import Store
    from delivery import jobs
    from delivery.artifacts import register_draft
    from api.routers.rooms import revision_for
    import httpx
    from openpyxl import Workbook
    from reportlab.pdfgen.canvas import Canvas

    run_id = prior['run_id'] if prior else uuid.uuid4().hex[:12]
    label = 'SYNTHETIC HTTP isolation acceptance ' + run_id
    checks, actors, sessions, fixtures = [], [], [], []
    report = {'contract': 'live-loopback-http-isolation-v1', 'run_id': run_id,
        'started_utc': datetime.now(timezone.utc).isoformat(), 'state': 'started',
        'http_origin': 'http://127.0.0.1:8080', 'synthetic_only': True,
        'session_scope': 'Server-issued acceptance sessions for two existing numeric-subject Google identities; browser Google callbacks were checked separately.',
        'new_browser_login_performed': False, 'identities_created': 0,
        'model_calls_requested': 0, 'room_worker_execution_exercised': False,
        'public_routes_changed': False, 'service_changes': False,
        'substantive_company_answers_or_final_artifacts_created': False,
        'fixture_cleanup_policy': 'Retain every fixture and original; cancel only fixture jobs and revoke only acceptance sessions.',
        'checks': checks, 'fixtures': fixtures}
    if prior:
        report['resumed_from'] = {'report': str(args.resume_fixtures_from), 'sha256': prior_hash,
                                 'prior_http_checks': prior['http_checks'],
                                 'explanation': 'The earlier checker incorrectly required historical jobs to remain queued. inputs_superseded cancellations are expected; all earlier HTTP statuses passed.'}
        report['duplicate_rooms_or_uploads_created'] = 0
    client = httpx.Client(base_url='http://127.0.0.1:8080', timeout=55,
                         trust_env=False, follow_redirects=False)
    current = 'preflight'
    source_files = ('security/identity.py', 'api/routers/rooms.py', 'api/routers/deals.py',
                    'delivery/ingestion.py', 'delivery/artifacts.py', 'delivery/private_inspection.py')
    code_hashes = {name: sha((runtime/name).read_bytes()) for name in source_files}
    report['production_code_sha256'] = code_hashes
    manifest_bytes = (runtime/'.hosting-code-manifest.json').read_bytes()
    manifest = {row['path']: row['sha256'] for row in json.loads(manifest_bytes)['files']}
    if any(manifest.get(name) != value for name,value in code_hashes.items()):
        raise AcceptanceFailure('Production factory/boundary source differs from checked runtime manifest')
    report['runtime_manifest_sha256_at_start'] = sha(manifest_bytes)

    def verify(condition, name):
        if not condition:
            raise AcceptanceFailure(name)

    def request(actor, method, path, expected, *, payload=None, headers=None, files=None, name=None):
        nonlocal current
        current = name or method + ' ' + path
        sent = {'Origin': 'https://investify.fyi'}
        if actor is not None:
            sent.update({'Cookie': COOKIE + '=' + actor['token'], 'X-CSRF-Token': actor['csrf']})
        sent.update(headers or {})
        response = client.request(method, path, json=payload, files=files, headers=sent)
        checks.append({'name': current, 'method': method, 'path': path,
                       'expected_status': expected, 'actual_status': response.status_code})
        verify(response.status_code == expected, current)
        verify(response.headers.get('cache-control') == 'no-store', current + ' private cache header')
        return response

    def actor_meta(actor):
        return {'alias': actor['alias'], 'user_id_sha256': sha(actor['user'].encode()),
                'sandbox_id_sha256': sha(actor['tenant'].encode()), 'role': 'owner'}

    def fixture_jobs(fixture):
        with Store(database) as store:
            return jobs.list_jobs(store.conn, fixture['actor']['tenant'], fixture['workspace_id'])

    def session_metadata(connection, excluded=()):
        # Raw tokens never enter SQLite. Exclude ordinary touched timestamps
        # because unrelated public users may legitimately use their sessions.
        return {row[0]: tuple(row[1:]) for row in connection.execute(
            'SELECT token_hash,user_id,tenant_id,created,expires,revoked FROM auth_sessions')
                if row[0] not in excluded}

    try:
        activity = database_inventory(database)
        verify(activity['running_jobs'] == 0 and activity['active_leases'] == 0, 'no active room jobs before acceptance')
        pid = subprocess.check_output(['systemctl', 'show', 'investify-api.service',
                                      '--property=MainPID', '--value'], text=True).strip()
        verify(pid.isdecimal() and int(pid) > 0, 'active production API process')
        verify(b'--without-worker' in Path('/proc', pid, 'cmdline').read_bytes(), 'room worker remains disabled')
        report['api_pid_at_start'] = pid
        backup = output / 'before.sqlite3'
        original = sqlite3.connect(database.resolve().as_uri()+'?mode=ro', uri=True)
        saved = sqlite3.connect(backup)
        try:
            original.execute('PRAGMA query_only=ON')
            original.backup(saved)
            verify(saved.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'online backup integrity')
            tables = [row[0] for row in saved.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            counts = {table: saved.execute('SELECT count(*) FROM "'+table.replace('"','""')+'"').fetchone()[0]
                      for table in tables}
            report['backup'] = {'path': str(backup), 'sha256': sha(backup.read_bytes()),
                                'integrity': 'ok', 'table_count': len(tables), 'table_counts': counts}
        finally:
            saved.close(); original.close()
        os.chmod(backup, 0o600)
        with Store(database) as store:
            baseline_sessions = session_metadata(store.conn)
            report['preexisting_session_rows'] = len(baseline_sessions)
            report['preexisting_active_sessions'] = sum(not row[-1] for row in baseline_sessions.values())
            rows = store.conn.execute('''SELECT i.subject,i.user_id,s.id FROM auth_identities i
                JOIN auth_users u ON u.id=i.user_id JOIN auth_sandboxes s ON s.owner_id=i.user_id
                JOIN auth_memberships m ON m.user_id=i.user_id AND m.tenant_id=s.id
                WHERE i.issuer='https://accounts.google.com' AND u.disabled=0 AND m.active=1 AND m.role='owner'
                ORDER BY i.subject,i.user_id''').fetchall()
            rows = [row for row in rows if re.fullmatch('[0-9]+', row[0])]
            if prior:
                by_hash = {sha(row[1].encode()): row for row in rows}
                rows = [by_hash[actor['user_id_sha256']] for actor in prior['actors']]
            verify(len(rows) >= 2 and rows[0][1] != rows[1][1] and rows[0][2] != rows[1][2], 'two distinct existing Google owners')
            for index, (_, user, tenant) in enumerate(rows[:2]):
                token, csrf = create_session(store.conn, user, tenant)
                actor = {'alias': chr(65+index), 'user': user, 'tenant': tenant,
                         'token': token, 'csrf': csrf}
                actors.append(actor); sessions.append((token, token_hash(token)))
        report['actors'] = [actor_meta(actor) for actor in actors]
        report['temporary_sessions_created'] = 2
        request(None, 'GET', '/api/deals', 401, headers={'X-Tenant-ID': actors[0]['tenant'], 'X-Reviewer': 'owner'}, name='anonymous spoofed headers do not authenticate')
        if prior is None:
            for actor in actors:
                me = request(actor, 'GET', '/api/auth/me', 200, name=actor['alias']+' acceptance session identity').json()
                verify((me['user_id'], me['tenant_id'], me['csrf_token'], me['role']) ==
                       (actor['user'], actor['tenant'], actor['csrf'], 'owner'), 'server-derived owner and sandbox')
                created = request(actor, 'POST', '/api/rooms', 201, payload={
                    'name': label+' '+actor['alias'], 'website': 'https://synthetic-'+run_id+'-'+actor['alias'].lower()+'.invalid',
                    'mandate_type': 'fundraising_advisory',
                    'terms_summary': 'SYNTHETIC TECHNICAL ACCEPTANCE ONLY. Not a real engagement, agreement, fundraising mandate or outreach authorization.'},
                    name=actor['alias']+' create labelled synthetic room').json()
                fixture = {'actor': actor, 'workspace_id': created['workspace_id'], 'lead_id': created['lead_id']}
                with Store(database) as store:
                    workspace = store.get_workspace(actor['tenant'], workspace_id=fixture['workspace_id'])
                    verify(workspace is not None, 'room persisted in correct sandbox')
                    lead = store.get_lead(actor['tenant'], workspace.lead_id)
                    verify(lead.company_name == label+' '+actor['alias'], 'synthetic fixture identity')
                    fixture['deal_id'] = workspace.deal_id
                fixtures.append({'actor': actor['alias'], 'workspace_id': fixture['workspace_id'],
                                 'lead_id': fixture['lead_id'], 'deal_id': fixture['deal_id']})
                actor['fixture'] = fixture
                before = request(actor, 'GET', '/api/rooms/'+fixture['workspace_id'], 200).json()
                verify(before['deal_id'] == fixture['deal_id'] and all(j['state']=='queued' for j in before['jobs']), 'new room queues work without model execution')
                request(actor, 'POST', '/api/rooms', 403, payload={'name': label+' forbidden', 'website': 'https://synthetic.invalid'},
                        headers={'X-CSRF-Token': ''}, name=actor['alias']+' missing CSRF blocks writes')
                request(actor, 'POST', '/api/rooms', 403, payload={'name': label+' forbidden', 'website': 'https://synthetic.invalid'},
                        headers={'Origin': 'https://untrusted.invalid'}, name=actor['alias']+' foreign origin blocks writes')
                originals = []
                for fmt in ('pdf', 'xlsx'):
                    content = BytesIO()
                    if fmt == 'pdf':
                        canvas = Canvas(content)
                        canvas.drawString(50, 750, 'SYNTHETIC TECHNICAL ISOLATION FIXTURE ONLY')
                        canvas.drawString(50, 720, 'Run '+run_id+' / actor '+actor['alias'])
                        canvas.drawString(50, 690, 'No company claims, investor materials or financial projections.')
                        canvas.save()
                    else:
                        workbook = Workbook(); sheet = workbook.active; sheet.title = 'Synthetic'
                        sheet.append(['SYNTHETIC TECHNICAL FIXTURE '+actor['alias'], 'Value'])
                        sheet.append(['Technical integer input', 17]); sheet.append(['Technical formula', '=B2+1'])
                        hidden = workbook.create_sheet('HiddenTechnical'); hidden.sheet_state = 'hidden'
                        hidden['A1'] = 'SYNTHETIC hidden lineage fixture'; hidden['B2'] = '=Synthetic!B2+1'
                        workbook.save(content); workbook.close()
                    raw = content.getvalue(); local = output/(actor['alias']+'-original.'+fmt); local.write_bytes(raw)
                    request(actor, 'POST', '/api/deals/'+fixture['deal_id']+'/documents', 200,
                            files={'file': ('technical-fixture.'+fmt, raw)}, name=actor['alias']+' real isolated '+fmt+' upload')
                    originals.append({'format': fmt, 'sha256': sha(raw), 'local_original': str(local)})
                documents = request(actor, 'GET', '/api/deals/'+fixture['deal_id']+'/source-documents', 200).json()
                verify(len(documents) == 2, 'exactly two uploaded fixture documents')
                for original in originals:
                    document = next(item for item in documents if item['type'] == original['format'])
                    verify((document['tenant_id'], document['deal_id']) == (actor['tenant'], fixture['deal_id']), 'trusted upload tenant/deal binding')
                    verify(document['blocks'] and all(block['document_id']==document['id'] and block['page']>0 for block in document['blocks']), 'source-block lineage binding')
                    stored = Path(document['storage_uri'])
                    verify(stored.resolve() == stored and not stored.is_symlink() and sha(stored.read_bytes())==original['sha256'], 'immutable uploaded original hash')
                    verify(not stored.is_relative_to(runtime) and not stored.is_relative_to(repository), 'uploaded originals outside Git/runtime code')
                    if original['format'] == 'xlsx':
                        inventory = document['workbook_inventory']
                        verify(inventory['formula_count']==2 and any(sheet['state']=='hidden' for sheet in inventory['sheets']), 'visible and hidden formula inventory retained')
                    original.update(document_id=document['id'], block_count=len(document['blocks']))
                fixtures[-1]['uploads'] = originals
                workspaces = request(actor, 'GET', '/api/operations/workspaces?lead_id='+fixture['lead_id'], 200).json()
                workspace = next(item for item in workspaces if item['id']==fixture['workspace_id'])
                payload = {'expected_revision': workspace['revision'], 'update': {'month': '2026-09', 'currency': 'USD',
                    'orders': 0, 'source_note': label+' TECHNICAL ZERO ONLY; not real company financial data.'}}
                updated = request(actor, 'POST', '/api/operations/workspaces/'+fixture['workspace_id']+'/metrics', 200,
                                  payload=payload, name=actor['alias']+' actual revision-checked technical write').json()
                verify(len(updated['metric_updates'])==1, 'one explicit synthetic metric submission')
                request(actor, 'POST', '/api/operations/workspaces/'+fixture['workspace_id']+'/metrics', 409,
                        payload=payload, name=actor['alias']+' stale revision cannot overwrite records')

        else:
            for actor, metadata in zip(actors, prior['fixtures']):
                verify(actor['alias']==metadata['actor'], 'retained fixture actor order')
                fixture = {'actor': actor, **{key: metadata[key] for key in ('workspace_id','lead_id','deal_id')}}
                actor['fixture'] = fixture
                fixtures.append(json.loads(json.dumps(metadata)))
                with Store(database) as store:
                    workspace = store.get_workspace(actor['tenant'], workspace_id=fixture['workspace_id'])
                    verify(workspace is not None and workspace.deal_id==fixture['deal_id'], 'retained fixture sandbox/deal association')
                    lead = store.get_lead(actor['tenant'], fixture['lead_id'])
                    verify(lead is not None and lead.company_name==label+' '+actor['alias'], 'retained synthetic fixture label')
                me = request(actor, 'GET', '/api/auth/me', 200, name=actor['alias']+' reissued acceptance session identity').json()
                verify((me['user_id'],me['tenant_id'],me['role'])==(actor['user'],actor['tenant'],'owner'), 'same verified owner on resume')
                documents = request(actor, 'GET', '/api/deals/'+fixture['deal_id']+'/source-documents', 200,
                                    name=actor['alias']+' retained original upload lineage').json()
                verify(len(documents)==2, 'no duplicate source uploads on resume')
                for original in metadata['uploads']:
                    document = next(item for item in documents if item['id']==original['document_id'])
                    verify((document['tenant_id'],document['deal_id'])==(actor['tenant'],fixture['deal_id']), 'retained source scope')
                    verify(sha(Path(document['storage_uri']).read_bytes())==original['sha256']
                           and sha(Path(original['local_original']).read_bytes())==original['sha256'], 'retained uploaded/original bytes unchanged')
                workspace = next(item for item in request(actor, 'GET', '/api/operations/workspaces?lead_id='+fixture['lead_id'], 200).json()
                                 if item['id']==fixture['workspace_id'])
                previous_count = len(workspace['metric_updates'])
                payload = {'expected_revision': workspace['revision'], 'update': {'month':'2026-08','currency':'USD','orders':0,
                    'source_note':label+' RESUME TECHNICAL ZERO ONLY; not real company financial data.'}}
                updated = request(actor, 'POST', '/api/operations/workspaces/'+fixture['workspace_id']+'/metrics', 200,
                                  payload=payload, name=actor['alias']+' new labelled technical revision for actual queued-job cancellation').json()
                verify(len(updated['metric_updates'])==previous_count+1, 'append-only technical revision; earlier submissions preserved')

        for actor, other in ((actors[0], actors[1]), (actors[1], actors[0])):
            own, foreign = actor['fixture'], other['fixture']
            spoof = {'X-Tenant-ID': other['tenant'], 'X-Reviewer': other['user']}
            for path in ('/api/rooms/'+foreign['workspace_id'], '/api/deals/'+foreign['deal_id'],
                         '/api/deals/'+foreign['deal_id']+'/source-documents',
                         '/api/operations/workspaces/'+foreign['workspace_id']+'/metrics'):
                request(actor, 'GET', path, 404, headers=spoof, name=actor['alias']+' cross-sandbox read/header spoof denial')
            history = request(other, 'GET', '/api/rooms/'+foreign['workspace_id'], 200).json()['jobs']
            queued = [item for item in history if item['state']=='queued']
            verify(len(queued)==1 and all(item['state'] in ('queued','cancelled') and item['attempt']==0
                   for item in history), 'one current queued job; historical revisions are cancelled without worker execution')
            target = queued[0]['id']
            request(actor, 'POST', '/api/rooms/'+foreign['workspace_id']+'/jobs/'+target+'/cancel', 404,
                    headers=spoof, name=actor['alias']+' cross-sandbox cancellation denied')
            request(other, 'POST', '/api/rooms/'+foreign['workspace_id']+'/jobs/'+target+'/cancel', 403,
                    headers={'X-CSRF-Token': 'invalid-technical-token'}, name=other['alias']+' cancellation requires CSRF')
            verify(next(item for item in fixture_jobs(foreign) if item['id']==target)['state']=='queued', 'denied cancellation changes nothing')
            request(other, 'POST', '/api/rooms/'+foreign['workspace_id']+'/jobs/'+target+'/cancel', 200,
                    name=other['alias']+' actual owned fixture cancellation')
            verify(next(item for item in fixture_jobs(foreign) if item['id']==target)['state']=='cancelled', 'owned cancellation persists')
            before = {item['id'] for item in fixture_jobs(own)}
            request(actor, 'GET', '/api/rooms/'+own['workspace_id'], 200)
            verify(before == {item['id'] for item in fixture_jobs(own)}, 'reopening unchanged room does not requeue work')

        for actor in actors:
            fixture = actor['fixture']; data = BytesIO(); canvas = Canvas(data)
            canvas.drawString(50, 750, 'DRAFT - SYNTHETIC TECHNICAL PREVIEW ONLY')
            canvas.drawString(50, 720, 'Run '+run_id+' / actor '+actor['alias'])
            canvas.drawString(50, 690, 'Not investor material, company analysis, a recommendation or an approved release.')
            canvas.save(); raw = data.getvalue(); (output/(actor['alias']+'-technical-preview.pdf')).write_bytes(raw)
            with Store(database) as store:
                room = store.get_workspace(actor['tenant'], workspace_id=fixture['workspace_id'])
                artifact = register_draft(store.conn, actor['tenant'], room.id, 'research_brief', 'pdf',
                                          revision_for(store, room), raw)
            fixture['artifact_id'] = artifact
            next(row for row in fixtures if row['actor']==actor['alias'])['technical_preview'] = {
                'artifact_id': artifact, 'sha256': sha(raw), 'kind': 'research_brief',
                'seeded_via_register_draft': True, 'model_authored_investor_content': False}
            base = '/api/rooms/'+fixture['workspace_id']+'/artifacts/'+artifact
            for suffix, disposition in (('/preview?inline=true', 'inline;'), ('/preview', 'attachment;')):
                result = request(actor, 'GET', base+suffix, 200, name=actor['alias']+' exact technical draft '+disposition)
                verify(sha(result.content)==sha(raw) and result.headers.get('content-disposition','').startswith(disposition)
                       and 'DRAFT-' in result.headers['content-disposition'] and result.headers.get('x-artifact-state')=='draft',
                       'draft bytes and inline/attachment state are exact')
            request(actor, 'GET', base+'/download', 409, name=actor['alias']+' final download remains blocked')
            assessment = request(actor, 'POST', '/api/rooms/'+fixture['workspace_id']+'/validate', 200,
                                 name=actor['alias']+' missing investor package remains ineligible').json()
            verify(assessment.get('eligible_for_release') is False, 'missing reviews/materials block release eligibility')
            fixture['package_id'] = assessment['package_id']
            request(actor, 'POST', '/api/rooms/'+fixture['workspace_id']+'/packages/'+assessment['package_id']+'/release', 409,
                    name=actor['alias']+' actual release request blocked without mandatory checks/reviews')
        for actor, other in ((actors[0], actors[1]), (actors[1], actors[0])):
            own, foreign = actor['fixture'], other['fixture']
            for room in (own['workspace_id'], foreign['workspace_id']):
                request(actor, 'GET', '/api/rooms/'+room+'/artifacts/'+foreign['artifact_id']+'/preview?inline=true', 404,
                        headers={'X-Tenant-ID': other['tenant']}, name=actor['alias']+' foreign artifact bytes never returned')
            request(actor, 'POST', '/api/rooms/'+own['workspace_id']+'/packages/'+foreign['package_id']+'/release', 404,
                    name=actor['alias']+' foreign package release denied')
        for actor in actors:
            request(actor, 'POST', '/api/auth/logout', 204, name=actor['alias']+' actual acceptance session logout')
            request(actor, 'GET', '/api/auth/me', 401, name=actor['alias']+' revoked acceptance token cannot authenticate')
        report['state'] = 'pass'
    except Exception as exc:
        report.update(state='fail', failed_stage=current, error_type=type(exc).__name__)
        if type(exc) is AcceptanceFailure:
            report['failed_assertion'] = exc.args[0]
    finally:
        cleanup = {'fixture_jobs_cancelled': 0, 'acceptance_sessions_revoked': 0,
                   'rows_deleted': 0, 'errors': []}
        try:
            with Store(database) as store:
                for actor in actors:
                    fixture = actor.get('fixture')
                    if fixture:
                        for job in jobs.list_jobs(store.conn, actor['tenant'], fixture['workspace_id']):
                            verify(job['tenant_id']==actor['tenant'] and job['workspace_id']==fixture['workspace_id'], 'cleanup remains in fixture scope')
                            if job['state'] in ('queued', 'running'):
                                jobs.cancel(store.conn, actor['tenant'], job['id']); cleanup['fixture_jobs_cancelled'] += 1
                for token, hashed in sessions:
                    # This production helper updates only the exact token hash.
                    revoke_session(store.conn, token)
                    row = store.conn.execute('SELECT revoked FROM auth_sessions WHERE token_hash=?', (hashed,)).fetchone()
                    verify(row is not None and row[0]==1, 'temporary acceptance session revoked')
                    cleanup['acceptance_sessions_revoked'] += 1
                ours = {hashed for _, hashed in sessions}
                remaining = store.conn.execute('SELECT token_hash FROM auth_sessions WHERE revoked=0').fetchall()
                cleanup['acceptance_sessions_still_active'] = sum(row[0] in ours for row in remaining)
                current_others = session_metadata(store.conn, ours)
                baseline = locals().get('baseline_sessions', {})
                cleanup['preexisting_session_rows_deleted'] = sum(key not in current_others for key in baseline)
                cleanup['preexisting_session_rows_changed_except_touched'] = sum(
                    key in current_others and current_others[key] != value for key,value in baseline.items())
                cleanup['concurrent_other_session_changes_are_never_restored'] = True
                cleanup['only_issued_session_hashes_targeted_for_revocation'] = True
                cleanup['fixture_jobs_remaining_queued_or_running'] = sum(
                    job['state'] in ('queued','running') for actor in actors if actor.get('fixture')
                    for job in jobs.list_jobs(store.conn, actor['tenant'], actor['fixture']['workspace_id']))
        except Exception as exc:
            cleanup['errors'].append(type(exc).__name__); report['state'] = 'fail'
        client.close()
        report['cleanup'] = cleanup
        report['http_checks'] = len(checks)
        report['failed_http_checks'] = sum(row['actual_status'] != row['expected_status'] for row in checks)
        report['production_code_unchanged'] = all(sha((runtime/name).read_bytes())==value for name,value in code_hashes.items())
        if prior:
            report['prior_report_bytes_unchanged'] = sha(args.resume_fixtures_from.read_bytes()) == prior_hash
        report['completed_utc'] = datetime.now(timezone.utc).isoformat()
        report['limits'] = ['Loopback HTTP with production-factory acceptance sessions, not a new browser OAuth flow.',
            'No model generation, public private-route enabling or room-worker processing was exercised.',
            'The seeded research_brief PDFs are technical previews, not company answers or investor artifacts.',
            'Parsing/lineage and transport isolation do not establish financial, visual, compliance or investor quality.']
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        for actor in actors:
            actor.pop('token', None); actor.pop('csrf', None)
        sessions.clear()
        print(json.dumps({'state': report['state'], 'http_checks': len(checks),
                          'failed_stage': report.get('failed_stage'), 'report': str(output/'report.json'),
                          'cleanup': cleanup}, indent=2))
    return 0 if report['state']=='pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
