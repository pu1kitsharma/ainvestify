"""Bind existing room evidence to a private, resumable local memo attempt."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from agents.research.investment_memo import Source, renderable_sections
from delivery.artifacts import artifact_root
from delivery.isolation import run_private
from delivery.storage import scope_component


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def room_sources(store, lead, room, *, full_inventory=False):
    """Use retained public KB passages and already-extracted private room blocks.

    The only public lookup is the source-supported public company name. Private
    notes, thesis and uploaded text never become public queries or KB writes.
    """
    rows = []
    oversized = 0
    if lead.company_profile.provenance.get("origin") == "public_kb":
        bound_source = lead.company_profile.provenance.get("source_id")
        bound_version = lead.company_profile.provenance.get("source_version")
        for evidence in lead.company_profile.evidence:
            if (evidence.origin == "public_page_claim" and evidence.dataset_id == bound_source
                    and (evidence.row_key or "").startswith(str(bound_version) + ":")):
                passage = evidence.quote.strip()
                if 30 <= len(passage) <= 4000:
                    rows.append((evidence.source_url, "Indexed company record", passage,
                                 bound_version, lead.company_profile.provenance.get("attribution") or
                                 "Rights-cleared public KB source"))
                elif len(passage) > 4000:
                    oversized += 1
    # Current rendered public pages were retained in this private lead profile
    # by the research worker. They remain room-scoped and are never put in ES.
    for evidence in lead.company_profile.evidence:
        if (evidence.origin == "preparation_public_page"
                and (evidence.row_key or "").startswith(("preparation_context_v3:", "preparation_context_v4:"))):
            passage = evidence.quote.strip()
            if 30 <= len(passage) <= 4000:
                rows.append((evidence.source_url, evidence.source_url, passage,
                             _digest(evidence.source_url + passage),
                             "Public page retained in this private room; source-reported"))
            elif len(passage) > 4000:
                oversized += 1
    if lead.company_profile.provenance.get("origin") == "public_kb" and os.environ.get("ELASTICSEARCH_URL"):
        from public_kb.ingestion import PublicIngestion
        from public_kb.elasticsearch import ElasticsearchPublicKB
        kb_root = Path(__file__).resolve().parents[1] / "runtime_public_kb"
        if not (kb_root / "kb.db").is_file():
            raise RuntimeError("Bound public KB registry is unavailable")
        kb = PublicIngestion(kb_root / "kb.db", kb_root / "archive")
        try:
            # Retained versions are historical evidence even when today's fetch
            # has not run. Keep their fetched_at visible so the model can label
            # currency; never treat an older passage as a fresh observation.
            records = ElasticsearchPublicKB(kb).search(lead.company_name[:160], limit=8,
                                                       max_age_seconds=30 * 86400)
        finally:
            kb.close()
        for page in records:
            # The ES search path rechecks the rights registry per hit. A
            # publisher with no usable attribution still cannot enter a memo.
            if not page.get("attribution"):
                continue
            blocks = page.get("passages") or [page.get("text", "")]
            for block in blocks:
                passage = (block.get("text", "") if isinstance(block, dict) else block).strip()
                if not 30 <= len(passage) <= 4000:
                    if len(passage) > 4000:
                        oversized += 1
                    continue
                url = page["url"]
                rows.append((url, page.get("title") or url, passage,
                             page["sha256"], page["attribution"]))
    if room.deal_id:
        for document in store.get_documents_for_deal(lead.tenant_id, room.deal_id):
            for block in document.blocks:
                content = block.content if isinstance(block.content, str) else json.dumps(block.content, ensure_ascii=False)
                content = content.strip()
                if not 30 <= len(content) <= 4000:
                    if len(content) > 4000:
                        oversized += 1
                    continue
                rows.append((f"private://{document.id}/{block.id}", document.filename, content,
                             _digest(document.id + block.id + content),
                             "Private room upload; source-reported and unverified"))
    # Preserve the rights-bound indexed record when the bounded context fills.
    # The source-coverage gate still blocks drafting until omitted passages
    # receive a separate model-authored selection pass.
    rows.sort(key=lambda row: row[1] != "Indexed company record")
    sources = []
    size = 0
    seen = set()
    omitted = 0
    inventory_ids = []
    selected_ids = []
    omitted_ids = []
    for url, title, passage, version, attribution in rows:
        key = (url, passage, version)
        if key in seen:
            continue
        seen.add(key)
        passage_id = _digest(json.dumps(key, ensure_ascii=False))
        inventory_ids.append(passage_id)
        if not full_inventory and (len(sources) >= 30 or size + len(passage) > 24000):
            omitted += 1
            omitted_ids.append(passage_id)
            continue
        size += len(passage)
        selected_ids.append(passage_id)
        sources.append(Source(id=f"S{len(sources) + 1}", url=url, title=title[:300],
                              passage=passage, version=version, attribution=attribution))
    public_urls = {source.url for source in sources
                   if urlsplit(source.url).scheme in {"http", "https"}
                   and urlsplit(source.url).hostname}
    private_docs = {source.url.split("/")[2] for source in sources if source.url.startswith("private://")}
    coverage = {"source_count": len(sources), "public_publishers": len({urlsplit(url).hostname for url in public_urls}),
                "public_urls": len(public_urls), "private_documents": len(private_docs),
                "available_passages": len(seen), "omitted_passages": omitted,
                "oversized_passages": oversized,
                "inventory_passage_ids": inventory_ids,
                "selected_passage_ids": selected_ids,
                "omitted_passage_ids": omitted_ids,
                "coverage_complete": omitted == 0 and oversized == 0}
    coverage['inventory_digest'] = _digest(json.dumps(
        [source.model_dump() for source in sources] if full_inventory else inventory_ids,
        sort_keys=True, ensure_ascii=False))
    return sources, coverage


def memo_directory(job):
    return (artifact_root() / scope_component(job["tenant_id"]) /
            scope_component(job["workspace_id"]) / "jobs" /
            scope_component(job["id"]) / "investment_memo")


def source_fingerprint(job, lead, sources, inventory_digest=None):
    payload = {"company": lead.company_name, "sources": [source.model_dump() for source in sources],
               "input_revision": job["input_revision"]}
    if inventory_digest is not None:
        payload['inventory_digest'] = inventory_digest
    return _digest(json.dumps(payload, sort_keys=True, ensure_ascii=False))


def _inventory_manifest(job, lead, inventory):
    rows = []
    for source in inventory:
        source_data = source.model_dump()
        rows.append({'passage_id': _digest(json.dumps(source_data, sort_keys=True,
            ensure_ascii=False)), 'source': source_data})
    base = {'company': lead.company_name, 'input_revision': job['input_revision'],
            'passages': rows, 'selection_revision': 'memo-source-selection-v1'}
    return {**base, 'inventory_digest': _digest(json.dumps(base, sort_keys=True,
        ensure_ascii=False))}


def resolve_memo_sources(job, lead, inventory, coverage, *, timeout):
    """Privately adjudicate every passage before the bounded memo context is built.

    The full inventory and raw model decisions are retained in the room job. A
    changed source or revision cannot replay an older selection.
    """
    if coverage.get('oversized_passages', 0):
        return {'state': 'blocked', 'reason': 'source_passage_oversized'}
    if (coverage.get('coverage_complete') and coverage.get('omitted_passages') == 0
            and len(inventory) <= 30 and sum(len(source.passage) for source in inventory) <= 24000):
        return {'state': 'complete', 'sources': inventory, 'coverage': coverage}
    manifest = _inventory_manifest(job, lead, inventory)
    root = memo_directory(job)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    inventory_file = root / 'inventory.json'
    if inventory_file.exists():
        if json.loads(inventory_file.read_text()) != manifest:
            return {'state': 'blocked', 'reason': 'source_inventory_changed'}
    else:
        temporary = inventory_file.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(manifest, ensure_ascii=False))
        temporary.replace(inventory_file)
    from agents.inference.local_models import PreparationModel, shared_model_name
    model_name = shared_model_name(PreparationModel())
    try:
        frozen_memo_model_profile(root / 'model.json', model_name)
    except ValueError:
        return {'state': 'blocked', 'reason': 'memo_model_profile_changed'}
    (root / 'selection_budget.json').write_text(json.dumps(
        {'seconds': max(1, min(105, timeout - 8))}))
    project = Path(__file__).resolve().parents[1]
    try:
        run_private([__import__('sys').executable,
            project / 'scripts/private_investment_memo_worker.py', '--select-sources'],
            root, timeout=timeout, extra_read=[project / 'agents', project / 'schemas.py'],
            local_model=True)
    except TimeoutError:
        return {'state': 'needs_resume', 'reason': 'source_selection_timeout'}
    result = json.loads((root / 'selection_result.json').read_text())
    context_exceeded = result.get('reason') == 'selected_source_context_exceeded'
    if result.get('state') != 'complete' and not context_exceeded:
        return result
    selected_ids = result.get('selected_passage_ids')
    excluded_ids = result.get('excluded_passage_ids')
    all_ids = [row['passage_id'] for row in manifest['passages']]
    if (not isinstance(selected_ids, list) or not isinstance(excluded_ids, list) or
            any(not isinstance(value, str) for value in selected_ids + excluded_ids) or
            len(set(selected_ids)) != len(selected_ids) or
            len(set(excluded_ids)) != len(excluded_ids) or
            set(selected_ids) & set(excluded_ids) or
            set(selected_ids) | set(excluded_ids) != set(all_ids) or
            result.get('inventory_digest') != manifest['inventory_digest']):
        return {'state': 'blocked', 'reason': 'source_selection_incomplete'}
    if excluded_ids:
        from agents.inference.model_authorship import digest
        packet_file = root / 'excluded_source_review.json'
        try:
            packet = json.loads(packet_file.read_text())
            expected = {row['passage_id']: row['source'] for row in manifest['passages']}
            excluded_rows = packet['excluded']
            actual = {row['passage_id']: row['source'] for row in excluded_rows}
            valid = (packet['packet_digest'] == digest({key: value for key, value in packet.items()
                                                       if key != 'packet_digest'})
                     and packet['inventory_digest'] == manifest['inventory_digest']
                     and packet['review_status'] == 'pending_independent_review'
                     and packet['selected_passage_ids'] == selected_ids
                     and [row['passage_id'] for row in excluded_rows] == excluded_ids
                     and actual == {key: expected[key] for key in excluded_ids}
                     and all(row['model_reason'].strip() for row in excluded_rows))
        except (OSError, ValueError, KeyError, TypeError):
            valid = False
        if not valid:
            return {'state': 'blocked', 'reason': 'excluded_source_review_packet_invalid'}
    if context_exceeded:
        result['coverage'] = {**coverage, 'coverage_complete': False,
            'omitted_passages': len(excluded_ids), 'selected_passage_ids': selected_ids,
            'excluded_passage_ids': excluded_ids, 'omitted_passage_ids': excluded_ids,
            'excluded_passages': len(excluded_ids),
            'excluded_source_review_path': str(root / 'excluded_source_review.json') if excluded_ids else None,
            'inventory_digest': manifest['inventory_digest']}
        return result
    by_id = {row['passage_id']: row['source'] for row in manifest['passages']}
    selected = [Source.model_validate({**by_id[passage_id], 'id': f'S{index}'})
                for index, passage_id in enumerate(selected_ids, 1)]
    if len(selected) > 30 or sum(len(source.passage) for source in selected) > 24000:
        return {'state': 'awaiting_input', 'reason': 'selected_source_context_exceeded',
                'coverage': {**coverage, 'coverage_complete': False,
                             'omitted_passages': len(excluded_ids),
                             'omitted_passage_ids': excluded_ids,
                             'excluded_passages': len(excluded_ids),
                             'inventory_digest': manifest['inventory_digest']}}
    public_urls = {source.url for source in selected if
                   urlsplit(source.url).scheme in {'http', 'https'} and
                   urlsplit(source.url).hostname}
    private_docs = {source.url.split('/')[2] for source in selected
                    if source.url.startswith('private://')}
    selected_coverage = {**coverage, 'source_count': len(selected),
        'public_publishers': len({urlsplit(url).hostname for url in public_urls}),
        'public_urls': len(public_urls), 'private_documents': len(private_docs),
        'available_passages': len(all_ids), 'omitted_passages': len(excluded_ids),
        'inventory_passage_ids': all_ids, 'selected_passage_ids': selected_ids,
        'excluded_passage_ids': excluded_ids, 'omitted_passage_ids': excluded_ids,
        'excluded_passages': len(excluded_ids), 'coverage_complete': not excluded_ids,
        'selection_applied': True,
        'inventory_digest': manifest['inventory_digest'],
        'excluded_source_review_path': str(root / 'excluded_source_review.json') if excluded_ids else None,
        'selection_attempts_path': str(root / 'selection_attempts.json')}
    if excluded_ids:
        return {'state': 'awaiting_input',
                'reason': 'excluded_source_review_required',
                'coverage': selected_coverage}
    return {'state': 'complete', 'sources': selected, 'coverage': selected_coverage}


def frozen_memo_model_profile(path, selected_model):
    """Pin every local model role before the first saved memo response."""
    from agents.inference.model_routing import validate_local_model_name
    if path.exists():
        profile = json.loads(path.read_text())
        if profile.get('model') != selected_model:
            raise ValueError('Memo model changed during a saved attempt')
        if 'profiles' in profile:
            roles = profile['profiles']
            if set(roles) - {'draft_b', 'challenge'} != {
                    'draft', 'review', 'corrector', 'prose'}:
                raise ValueError('Saved memo model profile is incomplete')
            for name in roles.values():
                validate_local_model_name(name)
            return profile
        if (path.parent / 'attempts.json').exists():
            raise ValueError('Saved memo lacks frozen role models; historical attempts require migration review')
    draft = os.environ.get('LOCAL_MEMO_DRAFT_MODEL', 'qwen3.5:9b')
    roles = {'draft': draft,
             'draft_b': os.environ.get('LOCAL_MEMO_PART_B_MODEL', draft),
             'review': os.environ.get('LOCAL_MEMO_REVIEW_MODEL', selected_model),
             'challenge': os.environ.get('LOCAL_MEMO_CHALLENGE_MODEL', selected_model),
             'corrector': selected_model, 'prose': selected_model}
    for name in roles.values():
        validate_local_model_name(name)
    profile = {'model': selected_model, 'profiles': roles, 'profile_version': 3}
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(profile))
    temporary.replace(path)
    return profile


def run_memo_pass(job, lead, sources, *, timeout, inventory_digest=None, phase='all',
                  phase_checkpoint=None):
    """Run local inference inside the room sandbox; keep attempts across passes."""
    if phase not in {'all', 'draft_only', 'analysis_only', 'correction_only',
                     'ledger_only', 'review_only'}:
        raise ValueError('Unknown memo phase')
    if phase in {'ledger_only', 'review_only'} and not isinstance(phase_checkpoint, dict):
        raise ValueError('Saved memo phase checkpoint required')
    root = memo_directory(job)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    base = {"company": lead.company_name, "sources": [source.model_dump() for source in sources],
            "input_revision": job["input_revision"]}
    if inventory_digest is not None:
        base['inventory_digest'] = inventory_digest
    request = root / "request.json"
    if request.exists():
        payload = json.loads(request.read_text())
        if any(payload.get(key) != value for key, value in base.items()):
            raise ValueError("Memo source or room revision changed during a saved attempt")
    else:
        payload = {**base, "as_of_date": date.today().isoformat()}
        request.write_text(json.dumps(payload, ensure_ascii=False))
    from agents.inference.local_models import PreparationModel, shared_model_name
    model_name = shared_model_name(PreparationModel())
    model_file = root / "model.json"
    if model_file.exists() and json.loads(model_file.read_text()).get('model') != model_name:
        raise ValueError('Memo model changed during a saved attempt')
    project = Path(__file__).resolve().parents[1]
    accepted_before = False
    if (root / "result.json").exists():
        previous = json.loads((root / "result.json").read_text())
        accepted_before = previous.get("state") == "accepted"
        if previous.get("state") == "blocked":
            # A substantively rejected draft is terminal for this exact job.
            # Repeating a stochastic review could incorrectly approve it.
            attempts = json.loads((root / "attempts.json").read_text())
            return {"state": "blocked", "reason": previous.get("reason", "local_memo_rejected"),
                    "attempt_count": len(attempts), "private_attempts_path": str(root / "attempts.json")}
    if not accepted_before:
        try:
            frozen_memo_model_profile(model_file, model_name)
        except ValueError as exc:
            if 'historical attempts require migration review' not in str(exc):
                raise
            attempts_file = root / 'attempts.json'
            attempts = json.loads(attempts_file.read_text())
            return {'state': 'blocked', 'reason': 'legacy_model_profile_unfrozen',
                    'attempt_count': len(attempts),
                    'private_attempts_path': str(attempts_file)}
        # The child must stop and save before the outer private-runtime kill.
        # This file is per pass; it is not part of the immutable source request.
        (root / "budget.json").write_text(json.dumps({
            "seconds": max(1, min(105, timeout - 8)), "phase": phase,
            "phase_checkpoint": phase_checkpoint}))
        run_private([__import__("sys").executable, project / "scripts/private_investment_memo_worker.py"],
                    root, timeout=timeout, extra_read=[project / "agents", project / "schemas.py"], local_model=True)
    result = json.loads((root / "result.json").read_text())
    attempts = json.loads((root / "attempts.json").read_text())
    if result['state'] == 'draft_ready':
        if phase != 'draft_only':
            raise ValueError('Draft phase result returned during analysis')
        return {'state': 'draft_ready', 'draft': result['draft'],
                'source_hash': source_fingerprint(job, lead, sources, inventory_digest),
                'attempt_count': len(attempts),
                'private_attempts_path': str(root / 'attempts.json')}
    if result['state'] in {'correction_ready', 'ledger_ready'}:
        expected = {'correction_only': 'correction_ready', 'ledger_only': 'ledger_ready'}
        if expected.get(phase) != result['state']:
            raise ValueError('Memo phase result returned during another phase')
        required = ({'corrected_memo_digest', 'source_set_digest', 'as_of_date'}
                    if result['state'] == 'correction_ready' else
                    {'corrected_memo_digest', 'source_set_digest', 'as_of_date',
                     'ledger_binding_digest', 'final_memo_digest'})
        if not required <= result.keys() or any(not result[key] for key in required):
            raise ValueError('Memo phase result lacks source-bound digest')
        return {**{key: result[key] for key in required}, 'state': result['state'],
                'source_hash': source_fingerprint(job, lead, sources, inventory_digest),
                'attempt_count': len(attempts),
                'private_attempts_path': str(root / 'attempts.json')}
    if result["state"] == "accepted":
        from agents.inference.model_routing import validate_local_model_name
        from scripts.private_investment_memo_worker import validate_saved_model_roles
        profile = json.loads(model_file.read_text())
        roles = profile.get('profiles')
        if not isinstance(roles, dict) or set(roles) - {'draft_b', 'challenge'} != {
                'draft', 'review', 'corrector', 'prose'}:
            raise ValueError('Accepted memo lacks frozen local model roles')
        for name in roles.values():
            validate_local_model_name(name)
        validate_saved_model_roles(attempts, roles)
        sections = renderable_sections(result["accepted"], sources, attempts)
        return {"state": "accepted", "sections": sections,
                "recommendation": result["accepted"]["memo"]["recommendation"],
                "source_hash": source_fingerprint(job, lead, sources, inventory_digest),
                "part_a_response_id": result["accepted"]["part_a_response_id"],
                "part_b_response_id": result["accepted"]["part_b_response_id"],
                "part_a_component_ids": result["accepted"].get("part_a_component_ids"),
                "part_b_section_response_ids": result["accepted"].get("part_b_section_response_ids"),
                "part_a_patch_id": result["accepted"].get("part_a_patch_id"),
                "part_b_patch_id": result["accepted"].get("part_b_patch_id"),
                "part_a_quote_patch_id": result["accepted"].get("part_a_quote_patch_id"),
                "part_b_quote_patch_id": result["accepted"].get("part_b_quote_patch_id"),
                "field_patch_ids": result["accepted"].get("field_patch_ids", {}),
                "review_response_id": result["accepted"]["review_response_id"],
                "attempt_count": len(attempts), "private_attempts_path": str(root / "attempts.json")}
    return {"state": result["state"], "reason": result.get("reason", "local_memo_incomplete"),
            "attempt_count": len(attempts), "private_attempts_path": str(root / "attempts.json")}
