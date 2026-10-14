"""Persist real-file inspection and enforce exact package checks at release/download."""
from __future__ import annotations
import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from delivery.artifacts import artifact_bytes, get_artifact
from delivery.contracts import (POLICY, REQUIRED_MATERIAL_KINDS, ArtifactFile, ArtifactManifest, CheckResult,
    ReviewDecision, assess_release)
from delivery.inspection import inspect_bytes, inspect_export_pair
from delivery.compliance import (assess_compliance, official_source_hosts,
    qualified_compliance_owners)
from delivery.review_integrity import (financial_reviewer_grants,
    retained_official_sources, room_evidence_inventory)


def validate_room(store, tenant, room):
    from api.routers.rooms import revision_for
    revision=revision_for(store,room)
    rows=store.conn.execute("SELECT id FROM room_artifacts WHERE tenant_id=? AND workspace_id=? AND input_revision=?",
        (tenant,room.id,revision)).fetchall()
    # Multiple revisions of one kind/format require explicit selection, not an
    # arbitrary 'latest'. Current worker emits one immutable candidate per job.
    files=[];reports={};contents={}
    for row in rows:
        artifact=get_artifact(store.conn,tenant,row[0])
        # This private research preview is not an investor-package artifact.
        # Keep it inspectable in the room, but never treat it as a substitute
        # for the required PDF converted from the investment memorandum.
        if artifact['kind'] == 'research_brief' or artifact['kind'].endswith('_preview'):
            continue
        content=artifact_bytes(tenant,artifact)
        contents[artifact['id']]=content
        reports[artifact['id']]=inspect_bytes(content,artifact['format'])
        files.append(ArtifactFile(artifact_id=artifact['id'],kind=artifact['kind'],format=artifact['format'],
            sha256=artifact['sha256'],size_bytes=len(content)))
    by_kind_format = {(file.kind, file.format): file for file in files}
    if len(by_kind_format) != len(files):
        raise ValueError('Multiple artifacts occupy one kind/format slot; select an exact version')
    for kind, editable_format in (('intro_deck', 'pptx'), ('pitch_deck', 'pptx'),
                                  ('investment_memorandum', 'docx')):
        editable = by_kind_format.get((kind, editable_format))
        distribution = by_kind_format.get((kind, 'pdf'))
        if editable and distribution:
            pair = inspect_export_pair(contents[editable.artifact_id], editable_format,
                                       contents[distribution.artifact_id])
            reports[distribution.artifact_id]['export_pair'] = pair
            reports[distribution.artifact_id]['findings'].extend(pair['findings'])
    # A projection is an optional requested artifact. Its presence requires the
    # full XLSX contract; absent reviewed inputs never force a generated file.
    requested = (*REQUIRED_MATERIAL_KINDS,
                 *(("financial_projection",) if any(
                     file.kind == "financial_projection" for file in files) else ()))
    manifest=ArtifactManifest(tenant_id=tenant,workspace_id=room.id,audience='investor',policy_version=POLICY.version,
        evidence_revision=revision,model_revision=hashlib.sha256(json.dumps(room.analyst_pack,sort_keys=True).encode()).hexdigest(),
        assumption_revision=hashlib.sha256(json.dumps(room.metric_updates,sort_keys=True).encode()).hexdigest(),
        material_revision=revision,renderer_version='draft-templates-v1',calculation_version='not_qualified',
        template_version='draft-v1',requested=requested,files=tuple(files))
    if room.compliance_review is not None:
        manifest = manifest.model_copy(update={
            'compliance_revision': room.compliance_review.content_revision()})
    checks=[]
    for file in files:
        report=reports[file.artifact_id]
        for name in next(c for c in POLICY.artifacts if c.kind==file.kind).checks:
            status='not_run'
            reason='Full mandatory validator not yet qualified'
            if name=='formula_execution_all_sheets' and report['findings']:
                status='fail';reason='Workbook inspection found blocking stored errors or unsupported features'
            if name in {'file_compatibility','confidentiality'} and report['structural_status']=='fail':
                status='fail';reason='Exported file inspection found blocking structure or embedded-content findings'
            if name == 'file_compatibility' and report.get('export_pair', {}).get('pair_status') == 'fail':
                status='fail';reason='Editable export and exact PDF bytes failed pair inspection'
            checks.append(CheckResult(check_id=name,target=file.artifact_id,manifest_digest=manifest.digest(),
                status=status,coverage_complete=False,validator_version='ooxml-pdf-v2',
                report_id=secrets.token_hex(16),reason=reason))
    for name in POLICY.package_checks:
        checks.append(CheckResult(check_id=name,target='package',manifest_digest=manifest.digest(),
            status='not_run',coverage_complete=False,validator_version='ooxml-pdf-v2',
            report_id=secrets.token_hex(16),reason='Package-wide evidence and consistency validation is incomplete'))
    package_id='package_'+secrets.token_hex(16)
    store.conn.execute("INSERT INTO room_packages VALUES (?,?,?,?,?,?,'blocked')",
        (package_id,tenant,room.id,manifest.model_dump_json(),json.dumps([c.model_dump() for c in checks]),'[]'))
    store.conn.commit()
    return package_id, evaluate_package(store,tenant,package_id)


def load_package(store,tenant,package_id):
    row=store.conn.execute("SELECT manifest,checks,reviews,state FROM room_packages WHERE tenant_id=? AND id=?",
        (tenant,package_id)).fetchone()
    if not row:raise LookupError('Package not found')
    return (ArtifactManifest.model_validate_json(row[0]),
        tuple(CheckResult.model_validate(c) for c in json.loads(row[1])),
        tuple(ReviewDecision.model_validate(r) for r in json.loads(row[2])),row[3])


def evaluate_package(store,tenant,package_id):
    from api.routers.rooms import revision_for
    manifest,checks,reviews,_=load_package(store,tenant,package_id)
    room=store.get_workspace(tenant,workspace_id=manifest.workspace_id)
    if room is None or manifest.tenant_id!=tenant or revision_for(store,room)!=manifest.material_revision:
        raise ValueError('Package inputs changed; validate the new revision')
    if manifest.model_revision!=hashlib.sha256(json.dumps(room.analyst_pack,sort_keys=True).encode()).hexdigest():
        raise ValueError('Model output changed; validate the new revision')
    hashes={}
    for file in manifest.files:
        artifact=get_artifact(store.conn,tenant,file.artifact_id)
        if not artifact or artifact['workspace_id']!=room.id or artifact['input_revision']!=manifest.material_revision:
            raise ValueError('Artifact scope or revision mismatch')
        content=artifact_bytes(tenant,artifact)
        if len(content)!=file.size_bytes:raise ValueError('Artifact size mismatch')
        hashes[file.artifact_id]=hashlib.sha256(content).hexdigest()
    grants={role:set() for role in ('financial','compliance')}
    for user,role in store.conn.execute("""SELECT m.user_id,m.role FROM auth_memberships m JOIN auth_users u ON u.id=m.user_id
        WHERE m.tenant_id=? AND m.active=1 AND u.disabled=0""",(tenant,)):
        if role in grants:grants[role].add(user)
    record = room.compliance_review
    as_of = datetime.now(timezone.utc).date()
    # Financial membership alone never establishes professional qualification.
    grants['financial'] = set()
    financial_date_blockers = []
    for review in reviews:
        if review.role != 'financial':
            continue
        if review.reviewed_on is None or review.reviewed_on > as_of:
            financial_date_blockers.append('financial_review_date_missing_or_invalid')
            continue
        qualified = financial_reviewer_grants(store.conn, tenant,
            record.scope if record else None, as_of, reviewed_on=review.reviewed_on)
        if review.reviewer_id in qualified:
            grants['financial'].add(review.reviewer_id)
    assessment = assess_release(manifest,checks,reviews,observed_hashes=hashes,authorized_reviewers=grants)
    content_revision = record.content_revision() if record is not None else None
    project = Path(__file__).resolve().parents[1]
    source_register = project / 'deployment' / 'regulatory_sources.json'
    compliance = assess_compliance(manifest_digest=manifest.digest(),
        evidence_revision=manifest.evidence_revision,
        scope=record.scope if record else None, matrix=record.matrix if record else None,
        signoff=record.signoff if record else None,
        qualified_owners=qualified_compliance_owners(store.conn, tenant),
        official_source_hosts=official_source_hosts(source_register),
        official_source_snapshots=retained_official_sources(source_register, project),
        evidence_inventory=room_evidence_inventory(store, tenant, room, manifest.evidence_revision),
        as_of=as_of)
    blockers = (*assessment.blockers, *compliance.blockers, *financial_date_blockers)
    for review in reviews:
        if review.role == 'financial' and review.reviewer_id not in grants['financial']:
            blockers = (*blockers, 'financial_owner_unqualified_for_scope')
    if manifest.compliance_revision != content_revision:
        blockers = (*blockers, 'compliance_content_revision_changed')
    return assessment.model_copy(update={
        'eligible_for_release': not blockers, 'blockers': blockers})


def publish_package(store,tenant,package_id):
    store.conn.execute('BEGIN IMMEDIATE')
    try:
        assessment=evaluate_package(store,tenant,package_id)
        if not assessment.eligible_for_release:
            raise ValueError('Mandatory validation or exact-version reviews block release')
        store.conn.execute("UPDATE room_packages SET state='released' WHERE tenant_id=? AND id=?",(tenant,package_id))
        store.conn.commit()
        return assessment
    except Exception:
        store.conn.rollback();raise
