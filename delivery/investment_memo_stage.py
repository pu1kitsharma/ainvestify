"""Bind existing room evidence to a private, resumable local memo attempt."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
from urllib.error import URLError

from agents.inference.model_authorship import digest as model_digest
from agents.research.investment_memo import (FRESH_SECTION_PROJECTION, Source,
                                             renderable_sections)
from delivery.artifacts import artifact_root
from delivery.isolation import run_private
from delivery.storage import scope_component


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class LocalModelInventoryUnavailable(ValueError):
    """The installed loopback model inventory could not be frozen yet."""


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


def memo_base_directory(job):
    """Stable source-selection and original memo root for this leased room job."""
    return (artifact_root() / scope_component(job["tenant_id"]) /
            scope_component(job["workspace_id"]) / "jobs" /
            scope_component(job["id"]) / "investment_memo")


def memo_directory(job):
    base = memo_base_directory(job)
    revision = job.get('checkpoint', {}).get('memo_revision')
    if revision is None:
        return base
    if revision not in {'causal_v1', 'causal_v2', 'causal_v3',
                        'causal_v4', 'causal_v5', 'field_v1', 'stable_v1', 'field_v2'}:
        raise ValueError('Unknown memo revision root')
    return base / revision


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
    root = memo_base_directory(job)
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
    except LocalModelInventoryUnavailable:
        return {'state': 'needs_resume', 'reason': 'local_model_inventory_unavailable'}
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
            if profile.get('memo_final_review_contract') not in {None, 'field_v1', 'field_v2', 'field_v3', 'field_v4'} or (
                    profile.get('memo_final_review_contract') and
                    profile.get('memo_draft_contract') != 'memo-cards-v13'):
                raise ValueError('Unknown saved final memo review contract')
            if set(roles) - {'draft_b', 'challenge', 'author'} != {
                    'draft', 'review', 'corrector', 'prose'}:
                raise ValueError('Saved memo model profile is incomplete')
            author_digest = profile.get('memo_author_model_digest')
            if profile.get('memo_draft_contract') in {'memo-cards-v12',
                                                      'memo-cards-v13'}:
                if (not isinstance(roles.get('author'), str) or
                        not isinstance(author_digest, str) or len(author_digest) != 64):
                    raise ValueError('Saved memo author role/digest is incomplete')
                role_digests = profile.get('memo_role_model_digests')
                if (profile.get('memo_draft_contract') == 'memo-cards-v13' and
                        role_digests is not None):
                    if (not isinstance(role_digests, dict) or
                            set(role_digests) != set(roles) or
                            any(not isinstance(value, str) or len(value) != 64
                                for value in role_digests.values()) or
                            role_digests['author'] != author_digest or
                            role_digests['review'] !=
                            profile.get('memo_causal_review_model_digest') or
                            profile.get('memo_causal_review_contract') not in
                            {'memo-causal-v2', 'memo-causal-v3'}):
                        raise ValueError('Saved v13 memo role digests are incomplete')
            elif 'author' in roles or author_digest is not None:
                raise ValueError('Saved memo author role has the wrong draft contract')
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
    # Frozen with the run: a profile saved before section projections were
    # versioned has no entry and keeps its original memo layout.
    profile = {'model': selected_model, 'profiles': roles, 'profile_version': 4,
               'section_projection': FRESH_SECTION_PROJECTION,
               'memo_draft_contract': 'memo-cards-v2'}
    requested_contract = os.environ.get('LOCAL_MEMO_DRAFT_CONTRACT', 'memo-cards-v2')
    if requested_contract not in {'memo-cards-v2', 'memo-cards-v13'}:
        raise ValueError('Unknown fresh memo draft contract')
    if requested_contract == 'memo-cards-v13':
        # This is an explicit local pilot opt-in, frozen before the first model
        # attempt. Every role is pinned to the installed loopback model digest.
        author = os.environ.get('LOCAL_MEMO_AUTHOR_MODEL', 'qwen3:14b')
        roles['review'] = os.environ.get('LOCAL_MEMO_REVIEW_MODEL', 'qwen3:14b')
        validate_local_model_name(author)
        validate_local_model_name(roles['review'])
        roles['author'] = author
        try:
            with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=5) as response:
                installed = {item['name']: item.get('digest') for item in
                             json.load(response)['models']}
        except (OSError, TimeoutError, URLError, ValueError, KeyError, TypeError) as exc:
            raise LocalModelInventoryUnavailable('Local model inventory is unavailable') from exc
        digests = {role: installed.get(name) for role, name in roles.items()}
        if any(not isinstance(value, str) or len(value) != 64
               for value in digests.values()):
            raise ValueError('Fresh v13 memo requires every frozen local model installed')
        profile.update({'memo_draft_contract': requested_contract,
                        'memo_final_review_contract': 'field_v4',
                        'memo_author_model_digest': digests['author'],
                        'memo_causal_review_contract': 'memo-causal-v2',
                        'memo_causal_review_model_digest': digests['review'],
                        'memo_role_model_digests': digests})
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(profile))
    temporary.replace(path)
    return profile


def _causal_review_summary(result):
    review = result.get('causal_review')
    if not isinstance(review, dict):
        return None
    findings = review.get('review', {}).get('findings', [])
    fields = ('field', 'sentence_id', 'relation', 'challenged_clause',
              'reason', 'premise_source_ids')
    return {'state': review.get('state'), 'reason': review.get('reason'),
            'review': {'findings': [
                {key: finding.get(key) for key in fields} for finding in findings[:36]
                if isinstance(finding, dict)]},
            'batches_recorded': len(review.get('response_ids', []))}


def _prepare_causal_shape_revision(job, root, result, attempts, profile):
    """One final schema-correction branch for a multi-sentence v2 repair only."""
    if (job.get('checkpoint', {}).get('memo_revision') != 'causal_v2' or
            result.get('state') != 'blocked' or
            result.get('reason') != 'CausalRepairSentenceShapeError' or
            profile.get('memo_draft_contract') != 'memo-cards-v13' or
            profile.get('profiles', {}).get('author') != 'qwen3:14b' or
            profile.get('profiles', {}).get('review') != 'qwen3:14b' or
            profile.get('memo_author_model_digest') !=
            profile.get('memo_causal_review_model_digest') or
            not attempts or attempts[-1].get('task') !=
            'investment_memo_causal_repair_v2'):
        return None
    failed = attempts[-1]
    if (failed.get('error') or not failed.get('raw_response') or
            not isinstance(failed.get('response_hash'), str) or
            len(failed['response_hash']) != 64):
        return None
    second_packet = json.loads((root / 'causal_repair_v2.json').read_text())
    if (second_packet.get('contract') != 'memo-causal-repair-v2' or
            failed.get('input', {}).get('contract') != 'memo-causal-repair-v2' or
            failed.get('input', {}).get('prior_repair_response_hash') !=
            second_packet.get('prior_repair_response_hash')):
        return None
    packet = {**second_packet, 'contract': 'memo-causal-repair-v3',
              'failed_v2_response_id': failed['id'],
              'failed_v2_response_hash': failed['response_hash']}
    branch = root.parent / 'causal_v3'
    prefix = attempts[:-1]
    if branch.exists():
        saved_prefix = json.loads((branch / 'attempts.json').read_text())
        if (json.loads((branch / 'causal_repair_v3.json').read_text()) != packet or
                (branch / 'request.json').read_bytes() != (root / 'request.json').read_bytes() or
                (branch / 'model.json').read_bytes() != (root / 'model.json').read_bytes() or
                saved_prefix[:len(prefix)] != prefix):
            raise ValueError('Saved constrained causal revision changed')
        return 'causal_v3'
    temporary = Path(tempfile.mkdtemp(prefix='.causal_v3_', dir=branch.parent))
    try:
        for name in ('request.json', 'model.json', 'causal_repair.json'):
            shutil.copyfile(root / name, temporary / name)
        (temporary / 'attempts.json').write_text(json.dumps(prefix, ensure_ascii=False))
        (temporary / 'causal_repair_v3.json').write_text(json.dumps(packet,
                                                               ensure_ascii=False))
        manifest = {'contract': 'memo-causal-revision-v3',
                    'failed_v2_response_id': failed['id'],
                    'failed_v2_response_hash': failed['response_hash'],
                    'failed_v2_result_sha256': _digest((root / 'result.json').read_text()),
                    'copied_attempt_row_digests': [
                        _digest(json.dumps(row, sort_keys=True, ensure_ascii=False))
                        for row in prefix]}
        (temporary / 'revision_manifest.json').write_text(json.dumps(manifest))
        temporary.rename(branch)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return 'causal_v3'


def _prepare_typed_causal_revision(job, root, result, attempts, profile):
    """Freeze one typed-list call, then one replay-only label correction."""
    prior = job.get('checkpoint', {}).get('memo_revision')
    cases = {'causal_v3': ('CausalRepairSingleSentenceSchemaError',
                           'investment_memo_causal_repair_v3',
                           'causal_repair_v3.json', 'causal_v4',
                           'causal_repair_v4.json', 'memo-causal-repair-v4'),
             'causal_v4': ('CausalRepairCitationLayoutError',
                           'investment_memo_causal_repair_v4',
                           'causal_repair_v4.json', 'causal_v5',
                           'causal_repair_v5.json', 'memo-causal-repair-v5')}
    if prior not in cases or not attempts:
        return None
    reason, task, old_name, revision, packet_name, contract = cases[prior]
    if (result.get('state') != 'blocked' or result.get('reason') != reason or
            profile.get('memo_draft_contract') != 'memo-cards-v13' or
            profile.get('profiles', {}).get('author') != 'qwen3:14b' or
            profile.get('profiles', {}).get('review') != 'qwen3:14b' or
            profile.get('memo_author_model_digest') !=
            profile.get('memo_causal_review_model_digest') or
            attempts[-1].get('task') != task or
            not attempts[-1].get('raw_response') or
            not isinstance(attempts[-1].get('response_hash'), str) or
            len(attempts[-1]['response_hash']) != 64):
        return None
    failed = attempts[-1]
    if prior == 'causal_v4' and failed.get('error'):
        return None
    if prior == 'causal_v3' and (
            failed.get('failure_kind') != 'schema_validation' or
            'string_pattern_mismatch' not in str(failed.get('error', ''))):
        return None
    old_packet = json.loads((root / old_name).read_text())
    if old_packet.get('contract') != ('memo-causal-repair-v3' if prior == 'causal_v3'
                                       else 'memo-causal-repair-v4'):
        return None
    packet = {**old_packet, 'contract': contract}
    if prior == 'causal_v3':
        packet.update({'failed_v3_response_id': failed['id'],
                       'failed_v3_response_hash': failed['response_hash']})
    else:
        packet.update({'prior_v4_response_id': failed['id'],
                       'prior_v4_response_hash': failed['response_hash']})
    branch = root.parent / revision
    prefix = attempts[:-1] if prior == 'causal_v3' else attempts
    if branch.exists():
        saved = json.loads((branch / 'attempts.json').read_text())
        if (json.loads((branch / packet_name).read_text()) != packet or
                (branch / 'request.json').read_bytes() != (root / 'request.json').read_bytes() or
                (branch / 'model.json').read_bytes() != (root / 'model.json').read_bytes() or
                saved[:len(prefix)] != prefix):
            raise ValueError('Saved typed causal revision changed')
        return revision
    temporary = Path(tempfile.mkdtemp(prefix=f'.{revision}_', dir=branch.parent))
    try:
        for name in ('request.json', 'model.json', 'causal_repair.json'):
            shutil.copyfile(root / name, temporary / name)
        (temporary / 'attempts.json').write_text(json.dumps(prefix, ensure_ascii=False))
        (temporary / packet_name).write_text(json.dumps(packet, ensure_ascii=False))
        (temporary / 'revision_manifest.json').write_text(json.dumps({
            'contract': f'memo-causal-revision-{revision}',
            'prior_result_sha256': _digest((root / 'result.json').read_text()),
            'trigger_response_id': failed['id'],
            'trigger_response_hash': failed['response_hash'],
            'copied_attempt_row_digests': [
                _digest(json.dumps(row, sort_keys=True, ensure_ascii=False))
                for row in prefix]}))
        temporary.rename(branch)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return revision


def _prepare_causal_revision(job, root, result, attempts, profile):
    """Atomically freeze one model-authored repair branch after a single finding.

    The original blocked result and raw review rows remain in ``root``. A job
    checkpoint selects the sibling root on its next leased review pass.
    """
    prior_revision = job.get('checkpoint', {}).get('memo_revision')
    if prior_revision not in {None, 'causal_v1'}:
        return None
    if (profile.get('memo_draft_contract') != 'memo-cards-v13' or
            profile.get('memo_causal_review_contract') != 'memo-causal-v2' or
            profile.get('profiles', {}).get('author') != 'qwen3:14b' or
            profile.get('profiles', {}).get('review') != 'qwen3:14b' or
            profile.get('memo_author_model_digest') !=
            profile.get('memo_causal_review_model_digest')):
        return None
    review = result.get('causal_review', {})
    findings = review.get('review', {}).get('findings', [])
    if (result.get('reason') != 'memo_causal_review_rejected' or
            review.get('review_contract') != 'memo-causal-v2' or
            len(findings) != 1 or
            findings[0].get('relation') != 'unsupported_consequence'):
        return None
    finding = findings[0]
    premise_ids = finding.get('premise_ids')
    evidence = finding.get('source_evidence')
    if (not isinstance(premise_ids, list) or len(premise_ids) != 1 or
            not isinstance(evidence, list) or len(evidence) != 1 or
            evidence[0].get('source_id') != premise_ids[0] or
            len(evidence[0].get('exact_quotes', [])) != 1 or
            not isinstance(finding.get('challenged_clause'), str) or
            finding['challenged_clause'] not in finding.get('sentence', '')):
        return None
    checkpoint = job.get('checkpoint', {}).get('memo_phase_checkpoint', {})
    if checkpoint.get('state') != 'ledger_ready':
        return None
    review_id = finding.get('response_id')
    reviewed = [row for row in attempts if row.get('id') == review_id and
                row.get('task') == 'investment_memo_causal_review_v2']
    if len(reviewed) != 1 or reviewed[0].get('error') or not reviewed[0].get('raw_response'):
        return None
    causal_rows = [row for row in attempts
                   if row.get('task') == 'investment_memo_causal_review_v2']
    if (not causal_rows or attempts[-len(causal_rows):] != causal_rows or
            any(row.get('task') == 'investment_memo_review' for row in attempts)):
        return None
    pre_review = attempts[:-len(causal_rows)]
    first_repair = [row for row in pre_review
                    if row.get('task') == 'investment_memo_causal_repair_v1']
    if ((prior_revision is None and first_repair) or
            (prior_revision == 'causal_v1' and
             (len(first_repair) != 1 or first_repair[0].get('error') or
              not first_repair[0].get('raw_response')))):
        return None
    original = json.loads((root / 'request.json').read_text())
    if (checkpoint.get('source_set_digest') != model_digest(original['sources']) or
            checkpoint.get('as_of_date') != original.get('as_of_date')):
        return None
    packet = {'contract': ('memo-causal-repair-v1' if prior_revision is None
                           else 'memo-causal-repair-v2'),
              'base_memo_digest': (checkpoint['final_memo_digest'] if prior_revision is None
                                   else reviewed[0].get('input', {}).get('memo_digest')),
              'review_response_id': review_id,
              'review_response_hash': reviewed[0]['response_hash'],
              'model_name': profile['profiles']['author'],
              'model_digest': profile['memo_author_model_digest'],
              'sentence_id': finding['sentence_id'], 'field': finding['field'],
              'challenged_clause': finding['challenged_clause'],
              'source_id': premise_ids[0]}
    if (not isinstance(packet['base_memo_digest'], str) or
            len(packet['base_memo_digest']) != 64):
        return None
    if prior_revision == 'causal_v1':
        packet.update({'prior_repair_response_id': first_repair[0]['id'],
                       'prior_repair_response_hash': first_repair[0]['response_hash']})
    revision = 'causal_v1' if prior_revision is None else 'causal_v2'
    branch = (root if prior_revision is None else root.parent) / revision
    packet_name = ('causal_repair.json' if prior_revision is None
                   else 'causal_repair_v2.json')
    if branch.exists():
        branch_attempts = json.loads((branch / 'attempts.json').read_text())
        if (json.loads((branch / packet_name).read_text()) != packet or
                (branch / 'request.json').read_bytes() != (root / 'request.json').read_bytes() or
                (branch / 'model.json').read_bytes() != (root / 'model.json').read_bytes() or
                branch_attempts[:len(pre_review)] != pre_review):
            raise ValueError('Saved causal revision packet changed')
        return revision
    temporary = Path(tempfile.mkdtemp(prefix=f'.{revision}_', dir=branch.parent))
    try:
        for name in ('request.json', 'model.json'):
            shutil.copyfile(root / name, temporary / name)
        (temporary / 'attempts.json').write_text(json.dumps(pre_review, ensure_ascii=False))
        if prior_revision == 'causal_v1':
            shutil.copyfile(root / 'causal_repair.json', temporary / 'causal_repair.json')
        (temporary / packet_name).write_text(json.dumps(packet, ensure_ascii=False))
        manifest = {'contract': 'memo-causal-revision-v1',
                    'revision': revision,
                    'original_result_sha256': _digest((root / 'result.json').read_text()),
                    'original_attempt_row_digests': [
                        _digest(json.dumps(row, sort_keys=True, ensure_ascii=False))
                        for row in attempts],
                    'copied_attempt_count': len(pre_review),
                    'omitted_review_response_ids': [row['id'] for row in causal_rows],
                    'ledger_checkpoint_digest': _digest(json.dumps(
                        checkpoint, sort_keys=True, ensure_ascii=False))}
        (temporary / 'revision_manifest.json').write_text(json.dumps(manifest))
        temporary.rename(branch)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return revision


def _prepare_field_revision(job, root, result, attempts, profile):
    """Freeze one source-bound field rewrite after an exact final-review finding."""
    if (job.get('checkpoint', {}).get('memo_revision') != 'causal_v5' or
            result.get('state') != 'blocked' or
            result.get('reason') not in {'field_v4_bridge_blocking_finding',
                                         'field_v4_blocking_finding'} or
            profile.get('memo_draft_contract') != 'memo-cards-v13' or
            profile.get('memo_final_review_contract') != 'field_v4' or
            profile.get('profiles', {}).get('author') != 'qwen3:14b' or
            profile.get('profiles', {}).get('review') != 'qwen3:14b'):
        return None
    final = result.get('final_field_review') or {}
    finding = final.get('finding') or {}
    field = final.get('field')
    if (field not in {'investment_thesis', 'business_and_market',
                      'differentiation_and_execution', 'risks_and_countercase',
                      'diligence_plan'} or
            finding.get('verdict') == 'supported_or_conditional' or
            finding.get('response_id') is None):
        return None
    review_rows = [row for row in attempts if row.get('id') == finding['response_id']
                   and row.get('task') in {'investment_memo_final_review_field_v3',
                                           'investment_memo_final_review_field_v4'}]
    if (len(review_rows) != 1 or not review_rows[0].get('raw_response') or
            model_digest(review_rows[0]['raw_response']) !=
            review_rows[0].get('response_hash')):
        return None
    reviewed = review_rows[0]
    bridge = result['reason'] == 'field_v4_bridge_blocking_finding'
    if bridge:
        if (reviewed.get('task') != 'investment_memo_final_review_field_v3' or
                reviewed.get('failure_kind') != 'schema_validation' or
                'string_too_long' not in str(reviewed.get('error', ''))):
            return None
    elif reviewed.get('error') or reviewed.get('task') != 'investment_memo_final_review_field_v4':
        return None
    base_digest = reviewed.get('input', {}).get('memo_digest')
    if not isinstance(base_digest, str) or len(base_digest) != 64:
        return None
    checkpoint = job.get('checkpoint', {}).get('memo_phase_checkpoint') or {}
    request = json.loads((root / 'request.json').read_text())
    if (checkpoint.get('state') != 'ledger_ready' or
            checkpoint.get('source_set_digest') != model_digest(request['sources']) or
            checkpoint.get('as_of_date') != request.get('as_of_date')):
        return None
    first_review = next((index for index, row in enumerate(attempts)
                         if row.get('task') == 'investment_memo_causal_review_v2'), None)
    if first_review is None:
        return None
    prefix = attempts[:first_review]
    if (not any(row.get('task') == 'investment_memo_causal_repair_v4' for row in prefix) or
            any(row.get('task') == 'investment_memo_field_repair_v1' for row in attempts) or
            any(row.get('task') not in {
                'investment_memo_causal_review_v2',
                'investment_memo_final_review_field_v1',
                'investment_memo_final_review_field_v2',
                'investment_memo_final_review_field_v3',
                'investment_memo_final_review_field_v4',
                'investment_memo_review'} for row in attempts[first_review:])):
        return None
    packet = {'contract': 'memo-field-repair-v1', 'field': field,
              'base_memo_digest': base_digest,
              'model_name': profile['profiles']['author'],
              'model_digest': profile['memo_author_model_digest'],
              'review_response_id': reviewed['id'],
              'review_response_hash': reviewed['response_hash']}
    branch = root.parent / 'field_v1'
    names = ('request.json', 'model.json', 'causal_repair.json',
             'causal_repair_v5.json')
    if branch.exists():
        if (json.loads((branch / 'memo_field_repair.json').read_text()) != packet or
                json.loads((branch / 'attempts.json').read_text())[:len(prefix)] != prefix or
                any((branch / name).read_bytes() != (root / name).read_bytes()
                    for name in names)):
            raise ValueError('Saved field revision packet changed')
        return 'field_v1'
    temporary = Path(tempfile.mkdtemp(prefix='.field_v1_', dir=branch.parent))
    try:
        for name in names:
            shutil.copyfile(root / name, temporary / name)
        (temporary / 'attempts.json').write_text(json.dumps(prefix, ensure_ascii=False))
        (temporary / 'memo_field_repair.json').write_text(json.dumps(packet, ensure_ascii=False))
        (temporary / 'revision_manifest.json').write_text(json.dumps({
            'contract': 'memo-field-revision-v1',
            'blocked_result_sha256': _digest((root / 'result.json').read_text()),
            'review_response_id': reviewed['id'],
            'review_response_hash': reviewed['response_hash'],
            'copied_attempt_row_digests': [
                _digest(json.dumps(row, sort_keys=True, ensure_ascii=False))
                for row in prefix]}))
        temporary.rename(branch)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return 'field_v1'


def _prepare_stable_revision(job, root, result, attempts, profile):
    """Carry exact prior model judgments for unchanged rows into isolated review."""
    if (job.get('checkpoint', {}).get('memo_revision') != 'field_v1' or
            result.get('state') != 'blocked' or
            result.get('reason') != 'memo_causal_review_rejected' or
            profile.get('memo_draft_contract') != 'memo-cards-v13' or
            profile.get('memo_causal_review_contract') != 'memo-causal-v2' or
            profile.get('profiles', {}).get('author') != 'qwen3:14b' or
            profile.get('profiles', {}).get('review') != 'qwen3:14b'):
        return None
    review = result.get('causal_review') or {}
    findings = (review.get('review') or {}).get('findings') or []
    if (len(findings) != 1 or
            findings[0].get('relation') != 'unsupported_consequence'):
        return None
    from agents.research.memo_causal_review import (
        CONTRACT_V3, _clauses, _prior_v2_judgments, _stable_key)
    prior_root = root.parent / 'causal_v5'
    if not all((prior_root / name).is_file() for name in
               ('request.json', 'model.json', 'attempts.json', 'result.json')):
        return None
    prior_profile = json.loads((prior_root / 'model.json').read_text())
    frozen_keys = ('model', 'profiles', 'memo_draft_contract',
                   'memo_author_model_digest', 'memo_causal_review_contract',
                   'memo_causal_review_model_digest', 'memo_role_model_digests',
                   'section_projection')
    if ((root / 'request.json').read_bytes() != (prior_root / 'request.json').read_bytes() or
            any(profile.get(key) != prior_profile.get(key) for key in frozen_keys)):
        return None
    prior_attempts = json.loads((prior_root / 'attempts.json').read_text())
    originals = [row for row in prior_attempts if row.get('task') ==
                 'investment_memo_causal_review_v2']
    if len(originals) < 1 or any(row.get('error') for row in originals):
        return None
    old_rows = [{**row, 'original_response_id': row['id'],
                 'id': 'prior_v2_' + row['id']} for row in originals]
    memo_digests = {row.get('input', {}).get('memo_digest') for row in old_rows}
    if len(memo_digests) != 1 or len(next(iter(memo_digests)) or '') != 64:
        return None
    lineage = {'prior_memo_digest': next(iter(memo_digests)),
               'prior_response_ids': [row['id'] for row in old_rows],
               'original_response_ids': [row['id'] for row in originals],
               'prior_response_hashes': [row['response_hash'] for row in old_rows],
               'prior_result_sha256': _digest((prior_root / 'result.json').read_text())}
    original = json.loads((root / 'request.json').read_text())
    contract = {'version': CONTRACT_V3, 'model_name': profile['profiles']['review'],
                'model_digest': profile['memo_causal_review_model_digest'],
                'prior_lineage': lineage}
    old, old_ids = _prior_v2_judgments(original['sources'], old_rows, contract)
    if len(old_ids) != len(old_rows):
        return None
    finding = findings[0]
    evidence = finding.get('source_evidence') or []
    if not evidence or not all(isinstance(item, dict) for item in evidence):
        return None
    projected = {'field': finding.get('field'),
                 'sentence_id': finding.get('sentence_id'),
                 'sentence': finding.get('sentence'),
                 'premise_ids': finding.get('premise_ids'),
                 'claim_quotes': [{'source_id': item.get('source_id'),
                                   'exact_quotes': item.get('exact_quotes')}
                                  for item in evidence],
                 'clauses': _clauses(finding.get('sentence') or '')}
    table = {item['source_id']: {'source_version': item.get('source_version'),
                                  'full_passage': item.get('full_passage')}
             for item in evidence}
    match = old.get(_stable_key(projected, table))
    if match is None or match[0]['relation'] != 'no_unsupported_consequence':
        return None
    first_new = next((index for index, row in enumerate(attempts)
                      if row.get('task') == 'investment_memo_causal_review_v2'), None)
    if first_new is None:
        return None
    prefix = attempts[:first_new]
    if (len([row for row in prefix if row.get('task') ==
             'investment_memo_field_repair_v1']) != 1 or
            any(row.get('task') != 'investment_memo_causal_review_v2'
                for row in attempts[first_new:])):
        return None
    branch = root.parent / 'stable_v1'
    active = prefix + old_rows
    if len({row['id'] for row in active}) != len(active):
        raise ValueError('Stable causal branch has duplicate response IDs')
    next_profile = {**profile, 'memo_causal_review_contract': CONTRACT_V3}
    files = ('request.json', 'causal_repair.json', 'causal_repair_v5.json',
             'memo_field_repair.json')
    if branch.exists():
        if (json.loads((branch / 'memo_causal_review_lineage.json').read_text()) != lineage or
                json.loads((branch / 'model.json').read_text()) != next_profile or
                json.loads((branch / 'attempts.json').read_text())[:len(active)] != active or
                any((branch / name).read_bytes() != (root / name).read_bytes()
                    for name in files)):
            raise ValueError('Saved stable causal revision changed')
        return 'stable_v1'
    temporary = Path(tempfile.mkdtemp(prefix='.stable_v1_', dir=branch.parent))
    try:
        for name in files:
            shutil.copyfile(root / name, temporary / name)
        (temporary / 'model.json').write_text(json.dumps(next_profile))
        (temporary / 'attempts.json').write_text(json.dumps(active, ensure_ascii=False))
        (temporary / 'memo_causal_review_lineage.json').write_text(json.dumps(lineage))
        (temporary / 'revision_manifest.json').write_text(json.dumps({
            'contract': 'memo-stable-causal-revision-v1',
            'blocked_result_sha256': _digest((root / 'result.json').read_text()),
            'prior_result_sha256': lineage['prior_result_sha256'],
            'prior_original_row_digests': [
                _digest(json.dumps(row, sort_keys=True, ensure_ascii=False))
                for row in originals],
            'prior_response_id_map': [
                {'original': original['id'], 'active': copied['id']}
                for original, copied in zip(originals, old_rows)],
            'copied_attempt_row_digests': [
                _digest(json.dumps(row, sort_keys=True, ensure_ascii=False))
                for row in active],
            'omitted_blocked_response_hashes': [row.get('response_hash')
                                                for row in attempts[first_new:]]}))
        temporary.rename(branch)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return 'stable_v1'


def _prepare_second_field_revision(job, root, result, attempts, profile):
    """Freeze one further local author call for a distinct final-review field."""
    if (job.get('checkpoint', {}).get('memo_revision') != 'stable_v1' or
            result.get('state') != 'blocked' or
            result.get('reason') != 'field_v4_blocking_finding' or
            profile.get('memo_draft_contract') != 'memo-cards-v13' or
            profile.get('memo_causal_review_contract') != 'memo-causal-v3' or
            profile.get('memo_final_review_contract') != 'field_v4'):
        return None
    final = result.get('final_field_review') or {}
    finding = final.get('finding') or {}
    field = final.get('field')
    if (field not in {'investment_thesis', 'business_and_market',
                      'differentiation_and_execution', 'risks_and_countercase',
                      'diligence_plan'} or
            finding.get('verdict') == 'supported_or_conditional' or
            not finding.get('response_id')):
        return None
    reviews = [row for row in attempts if row.get('id') == finding['response_id'] and
               row.get('task') == 'investment_memo_final_review_field_v4']
    first_repairs = [row for row in attempts if row.get('task') ==
                     'investment_memo_field_repair_v1']
    if (len(reviews) != 1 or len(first_repairs) != 1 or
            any(row.get('error') or not row.get('raw_response') or
                model_digest(row['raw_response']) != row.get('response_hash')
                for row in reviews + first_repairs)):
        return None
    review_row, first_repair = reviews[0], first_repairs[0]
    base_digest = review_row.get('input', {}).get('memo_digest')
    if not isinstance(base_digest, str) or len(base_digest) != 64:
        return None
    first_new = next((index for index, row in enumerate(attempts)
                      if row.get('task') == 'investment_memo_causal_review_v3'), None)
    if first_new is None:
        return None
    prefix = attempts[:first_new]
    if (first_repair not in prefix or
            any(row.get('task') not in {'investment_memo_causal_review_v3',
                                        'investment_memo_final_review_field_v4'}
                for row in attempts[first_new:]) or
            not (root / 'memo_causal_review_lineage.json').is_file()):
        return None
    packet = {'contract': 'memo-field-repair-v2', 'field': field,
              'base_memo_digest': base_digest,
              'model_name': profile['profiles']['author'],
              'model_digest': profile['memo_author_model_digest'],
              'review_response_id': review_row['id'],
              'review_response_hash': review_row['response_hash'],
              'prior_field_repair_response_id': first_repair['id'],
              'prior_field_repair_response_hash': first_repair['response_hash']}
    branch = root.parent / 'field_v2'
    files = ('request.json', 'model.json', 'causal_repair.json',
             'causal_repair_v5.json', 'memo_field_repair.json',
             'memo_causal_review_lineage.json')
    if branch.exists():
        if (json.loads((branch / 'memo_field_repair_v2.json').read_text()) != packet or
                json.loads((branch / 'attempts.json').read_text())[:len(prefix)] != prefix or
                any((branch / name).read_bytes() != (root / name).read_bytes()
                    for name in files)):
            raise ValueError('Saved second field revision changed')
        return 'field_v2'
    temporary = Path(tempfile.mkdtemp(prefix='.field_v2_', dir=branch.parent))
    try:
        for name in files:
            shutil.copyfile(root / name, temporary / name)
        (temporary / 'attempts.json').write_text(json.dumps(prefix, ensure_ascii=False))
        (temporary / 'memo_field_repair_v2.json').write_text(json.dumps(packet,
                                                               ensure_ascii=False))
        (temporary / 'revision_manifest.json').write_text(json.dumps({
            'contract': 'memo-field-revision-v2',
            'blocked_result_sha256': _digest((root / 'result.json').read_text()),
            'review_response_id': review_row['id'],
            'review_response_hash': review_row['response_hash'],
            'prior_repair_response_id': first_repair['id'],
            'prior_repair_response_hash': first_repair['response_hash'],
            'copied_attempt_row_digests': [
                _digest(json.dumps(row, sort_keys=True, ensure_ascii=False))
                for row in prefix]}))
        temporary.rename(branch)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return 'field_v2'


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
            if phase == 'review_only' and model_file.exists():
                profile = json.loads(model_file.read_text())
                revision = (_prepare_second_field_revision(job, root, previous,
                                                           attempts, profile) or
                            _prepare_stable_revision(job, root, previous,
                                                     attempts, profile) or
                            _prepare_field_revision(job, root, previous,
                                                    attempts, profile) or
                            _prepare_typed_causal_revision(job, root, previous,
                                                            attempts, profile) or
                            _prepare_causal_shape_revision(job, root, previous,
                                                            attempts, profile) or
                            _prepare_causal_revision(job, root, previous,
                                                     attempts, profile))
                if revision is not None:
                    return {'state': 'needs_resume',
                            'phase': ('memo_stable_review_pending' if revision == 'stable_v1'
                                      else 'memo_field_repair_pending' if revision in
                                      {'field_v1', 'field_v2'}
                                      else 'memo_causal_repair_pending'),
                            'reason': ('memo_revision_branch_frozen' if revision in
                                       {'field_v1', 'stable_v1', 'field_v2'} else
                                       'causal_revision_branch_frozen'),
                            'memo_revision': revision,
                            'causal_review': _causal_review_summary(previous),
                            'attempt_count': len(attempts),
                            'private_attempts_path': str(root / 'attempts.json')}
            return {"state": "blocked", "reason": previous.get("reason", "local_memo_rejected"),
                    "attempt_count": len(attempts), "private_attempts_path": str(root / "attempts.json")}
    if not accepted_before:
        try:
            frozen_memo_model_profile(model_file, model_name)
        except LocalModelInventoryUnavailable:
            return {'state': 'needs_resume', 'reason': 'local_model_inventory_unavailable',
                    'attempt_count': 0, 'private_attempts_path': str(root / 'attempts.json')}
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
    if result.get('state') == 'blocked' and phase == 'review_only':
        profile = json.loads(model_file.read_text())
        revision = (_prepare_second_field_revision(job, root, result, attempts, profile) or
                    _prepare_stable_revision(job, root, result, attempts, profile) or
                    _prepare_field_revision(job, root, result, attempts, profile) or
                    _prepare_typed_causal_revision(job, root, result, attempts, profile) or
                    _prepare_causal_shape_revision(job, root, result, attempts, profile) or
                    _prepare_causal_revision(job, root, result, attempts, profile))
        if revision is not None:
            return {'state': 'needs_resume',
                    'phase': ('memo_stable_review_pending' if revision == 'stable_v1'
                              else 'memo_field_repair_pending' if revision in
                              {'field_v1', 'field_v2'}
                              else 'memo_causal_repair_pending'),
                    'reason': ('memo_revision_branch_frozen' if revision in
                               {'field_v1', 'stable_v1', 'field_v2'} else
                               'causal_revision_branch_frozen'),
                    'memo_revision': revision,
                    'causal_review': _causal_review_summary(result),
                    'attempt_count': len(attempts),
                    'private_attempts_path': str(root / 'attempts.json')}
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
        if not isinstance(roles, dict) or set(roles) - {'draft_b', 'challenge', 'author'} != {
                'draft', 'review', 'corrector', 'prose'}:
            raise ValueError('Accepted memo lacks frozen local model roles')
        author_digest = profile.get('memo_author_model_digest')
        if profile.get('memo_draft_contract') in {'memo-cards-v12',
                                                  'memo-cards-v13'}:
            if (not isinstance(roles.get('author'), str) or
                    not isinstance(author_digest, str) or len(author_digest) != 64):
                raise ValueError('Accepted memo lacks frozen author role/digest')
        elif 'author' in roles or author_digest is not None:
            raise ValueError('Accepted memo author role has the wrong draft contract')
        for name in roles.values():
            validate_local_model_name(name)
        validate_saved_model_roles(attempts, roles)
        sections = renderable_sections(result["accepted"], sources, attempts,
                                       projection=profile.get('section_projection'))
        return {"state": "accepted", "sections": sections,
                "section_projection": profile.get('section_projection'),
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
    summary = _causal_review_summary(result)
    return {"state": result["state"], "reason": result.get("reason", "local_memo_incomplete"),
            **({'phase': result['phase']} if result.get('phase') else {}),
            **({'causal_review': summary} if summary is not None else {}),
            "attempt_count": len(attempts), "private_attempts_path": str(root / "attempts.json")}
