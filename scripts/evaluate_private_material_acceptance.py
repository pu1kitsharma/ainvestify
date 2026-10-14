"""Continue an accepted private memo into local deck drafts and export pairs.

This is an isolated diagnostic. It does not create a room, publish artifacts, or
mark investor materials accepted. Invoke once per bounded draft/review pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.request

from agents.inference.model_authorship import digest
from agents.research.investment_memo import Source, renderable_sections
from agents.research.material_relation_review import _BATCH_CONTRACT, BATCH_OPTIONS, _SENTENCE_CONTRACT, SENTENCE_OPTIONS
from agents.research.material_slides import replay_material_rows, render_sections
from agents.research.material_narrative_review import options_for as narrative_review_options
from delivery.inspection import inspect_export_pair
from delivery.isolation import run_private
from delivery.material_review_stage import (FRESH_REVIEW_CONTRACT,
                                             require_supported_contract)
from agents.research.material_purpose_draft import (financial_unknown_candidates,
                                                    memo_sentence_candidates)
from scripts.evaluate_private_acceptance import OUTPUT_ROOT
from scripts.private_material_worker import draft_materials
from scripts.private_material_review_worker import review_materials

PROJECT = Path(__file__).resolve().parents[1]
KINDS = ('intro_deck', 'pitch_deck')
MAX_DRAFT_PASSES = 15
MAX_REVIEW_PASSES = 15  # Twelve semantic batches plus bounded no-call yields.


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_new(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
        json.dump(value, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())


def _replace(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    _write_new(temporary, value)
    temporary.replace(path)


def _installed_digest(name: str) -> str:
    with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=5) as stream:
        rows = json.load(stream)['models']
    pin = next((row.get('digest') for row in rows if row.get('name') == name), None)
    if not isinstance(pin, str) or len(pin) != 64:
        raise ValueError('Frozen local model is unavailable')
    return pin


def _memo_projection(memo_root: Path, *, material_draft_model: str | None = None,
                     content_root: Path | None = None, assertion_candidates=False, temporal_candidates=False, temporal_contract="purpose_v16") -> dict:
    """Replay the accepted response IDs and reviewer against its original sources."""
    root = memo_root.resolve()
    if not root.is_relative_to(OUTPUT_ROOT.resolve()) or root == OUTPUT_ROOT.resolve():
        raise ValueError('Memo is outside private acceptance diagnostics')
    ancestors = [root]
    for _ in range(4):
        ancestors.append(ancestors[-1].parent)
    parent = next((candidate for candidate in ancestors[1:]
                   if candidate.is_relative_to(OUTPUT_ROOT.resolve()) and
                   (candidate / 'ingest_result.json').is_file()), None)
    if parent is None:
        raise ValueError('Memo has no matching private ingestion checkpoint')
    ingest = json.loads((parent / 'ingest_result.json').read_text())
    request = json.loads((root / 'request.json').read_text())
    profile = json.loads((root / 'model.json').read_text())
    result = json.loads((root / 'result.json').read_text())
    attempts = json.loads((root / 'attempts.json').read_text())
    if (ingest.get('state') != 'parsed' or result.get('state') != 'accepted' or
            result.get('acceptance_scope') != 'local_model_checks_only' or
            result.get('independent_review') != 'pending' or
            request.get('input_revision') != ingest.get('memo_source_sha256')):
        raise ValueError('Exact locally accepted private memo is required')
    if profile.get('memo_draft_contract') != 'memo-cards-v13':
        raise ValueError('The private material pilot requires the frozen v13 memo')
    pins = profile.get('memo_role_model_digests')
    if pins is not None and (not isinstance(pins, dict) or
                             any(_installed_digest(profile['profiles'][role]) != pins.get(role)
                                 for role in ('draft', 'review'))):
        raise ValueError('Installed local memo model digest changed')
    review_pin = (pins['review'] if pins is not None else
                  profile.get('memo_causal_review_model_digest'))
    if (not isinstance(review_pin, str) or len(review_pin) != 64 or
            _installed_digest(profile['profiles']['review']) != review_pin):
        raise ValueError('Frozen local memo reviewer digest changed')
    # Historical v13 attempts already bind their model name and raw response.
    # Only the new material phase freezes the current installed draft digest.
    selected_draft = material_draft_model or profile['profiles']['draft']
    from agents.inference.model_routing import validate_local_model_name
    validate_local_model_name(selected_draft)
    material_draft_pin = (pins['draft'] if pins is not None and
                          selected_draft == profile['profiles']['draft'] else
                          _installed_digest(selected_draft))
    sources = [Source.model_validate(row) for row in request['sources']]
    if result['accepted'].get('challenge', {}).get('source_set_digest') not in (None, digest(request['sources'])):
        raise ValueError('Accepted memo source set changed')
    accepted, content = result['accepted'], None
    if content_root is not None:
        # A model-authored content repair, replayed from raw responses. The
        # original memo stays untouched; materials bind to the revised digest.
        from agents.research.memo_content_repair import replay_content_revision
        from scripts.evaluate_private_memo_content import load_revision
        croot = content_root.resolve()
        if croot.parent != root.parent or not croot.is_relative_to(OUTPUT_ROOT.resolve()):
            raise ValueError('Content revision must sit beside its private memo')
        content_request = json.loads((croot / 'content_request.json').read_text())
        if content_request.get('flow_contract') is not None:
            from scripts.private_source_unit_worker import (
                FLOW, load_source_unit_revision, replay_source_unit_revision)
            from delivery.source_unit_content_stage import _history, FLOW_V2, FLOW_V3, FLOW_V4, FLOW_V5
            if content_request['flow_contract'] not in (FLOW, FLOW_V2, FLOW_V3, FLOW_V4, FLOW_V5):
                raise ValueError('Unknown source-unit content flow')
            if content_request['flow_contract'] in {FLOW_V4, FLOW_V5}:
                # This diagnostic can select a separately pinned core writer.
                # The original memo's historical role profile stays untouched.
                core_pin = content_request.get('core_author_pin')
                if (not isinstance(core_pin, dict) or set(core_pin) != {'name', 'digest'} or
                        not isinstance(core_pin['digest'], str) or len(core_pin['digest']) != 64):
                    raise ValueError('Source-unit core author requires an exact local role pin')
                validate_local_model_name(core_pin['name'])
                if _installed_digest(core_pin['name']) != core_pin['digest']:
                    raise ValueError('Installed source-unit core author digest changed')
            if content_request.get('section_author_contract') in {'memo-section-units-author-v7', 'memo-section-units-author-v8', 'memo-section-units-author-v9', 'memo-section-units-author-v10', 'memo-section-units-author-v11', 'memo-section-units-author-v12', 'memo-section-units-author-v13'}:
                core_review_pin = content_request.get('core_reviewer_pin')
                if (not isinstance(core_review_pin, dict) or set(core_review_pin) != {'name', 'digest'} or
                        not isinstance(core_review_pin['digest'], str) or len(core_review_pin['digest']) != 64):
                    raise ValueError('Source-unit core reviewer requires an exact local role pin')
                validate_local_model_name(core_review_pin['name'])
                if _installed_digest(core_review_pin['name']) != core_review_pin['digest']:
                    raise ValueError('Installed source-unit core reviewer digest changed')
            _history(croot, accepted=True, flow_contract=content_request['flow_contract'])
            revision = load_source_unit_revision(croot)
            revised_json, record = replay_source_unit_revision(accepted['memo'], sources, revision)
            from agents.research.investment_memo import Memo
            revised = Memo.model_validate(revised_json)
            if content_request['flow_contract'] in {FLOW_V4, FLOW_V5} and record.get('core_author_pin') != content_request.get('core_author_pin'):
                raise ValueError('Source-unit core author role differs from exact replay')
            if content_request.get('section_author_contract') in {'memo-section-units-author-v7', 'memo-section-units-author-v8', 'memo-section-units-author-v9', 'memo-section-units-author-v10', 'memo-section-units-author-v11', 'memo-section-units-author-v12', 'memo-section-units-author-v13'} and record.get('core_reviewer_pin') != content_request['core_reviewer_pin']:
                raise ValueError('Source-unit core reviewer role differs from exact replay')
            if content_request.get('section_review_contract') is not None and record.get('section_review_contract') != content_request['section_review_contract']:
                raise ValueError('Source-unit section reviewer contract differs from exact replay')
            section_contract = content_request.get('section_author_contract')
            if section_contract is not None and record.get('section_author_contract') != section_contract:
                raise ValueError('Source-unit section author contract differs from exact replay')
            content_result = json.loads((croot / 'content_result.json').read_text())
            if (content_result.get('state') != 'accepted' or
                    content_result.get('final_memo_digest') != digest(revised.model_dump(mode='json')) or
                    content_result.get('content_review') != record):
                raise ValueError('Source-unit content result differs from exact replay')
        else:
            revision = load_revision(croot)
            revised, record = replay_content_revision(accepted['memo'], sources, revision)
        if record['state'] != 'accepted':
            raise ValueError('Content revision is not accepted')
        content = {'root': str(croot), 'record': record, 'revision': revision}
        accepted = {**accepted, 'memo': revised.model_dump(mode='json')}
    sections = renderable_sections(result['accepted'], sources, attempts,
                                   projection=profile.get('section_projection'),
                                   content_revision=content['revision'] if content else None)
    if temporal_candidates:
        from delivery.material_stage import _material_as_of
        from agents.research.material_purpose_draft import memo_assertion_candidates_v16, financial_unknown_candidates_v16
        if temporal_contract == "purpose_v18":
            from agents.research.material_purpose_draft import financial_unknown_candidates_v18, memo_assertion_candidates_v18
            financial_unknown_candidates_v16, memo_assertion_candidates_v16 = financial_unknown_candidates_v18, memo_assertion_candidates_v18
        elif temporal_contract == "purpose_v17":
            from agents.research.material_purpose_draft import financial_unknown_candidates_v17, memo_assertion_candidates_v17
            financial_unknown_candidates_v16, memo_assertion_candidates_v16 = financial_unknown_candidates_v17, memo_assertion_candidates_v17
        elif temporal_contract != "purpose_v16":
            raise ValueError("Unsupported temporal material contract")
        financial_packet = financial_unknown_candidates_v16(accepted)
        narrative_packet = {'memo_assertion_candidates': {**memo_assertion_candidates_v16(accepted), 'as_of_date': _material_as_of(root)}}
    elif assertion_candidates:
        from agents.research.material_purpose_draft import memo_assertion_candidates, financial_unknown_candidates_v15
        financial_packet = financial_unknown_candidates_v15(accepted)
        narrative_packet = {'memo_assertion_candidates': memo_assertion_candidates(accepted)}
    else:
        financial_packet = financial_unknown_candidates(accepted)
        narrative_packet = {'memo_sentence_candidates': memo_sentence_candidates(accepted)}
    return {'company': request['company'], 'input_revision': request['input_revision'],
            'source_hash': digest(request['sources']), 'sections': sections,
            'memo_digest': digest(accepted),
            'content_revision': (None if content is None else
                                 {'root': content['root'], 'record': content['record']}),
            'financial_unknown_candidates': financial_packet,
            **narrative_packet,
            'section_projection': profile.get('section_projection'),
            'draft_model': selected_draft,
            'review_model': profile['profiles']['review'],
            'draft_pin': material_draft_pin, 'review_pin': review_pin,
            'draft_pin_origin': ('memo_role_profile' if pins is not None and
                                 selected_draft == profile['profiles']['draft'] else
                                 'new_material_stage_inventory'),
            'memo_files': {name: _sha(root / name) for name in
                           ('request.json', 'model.json', 'result.json', 'attempts.json')},
            'memo_root': str(root), 'acceptance_root': str(parent)}



def _material_base(manifest):
    base = {key: manifest[key] for key in ('input_revision','source_hash','memo_digest','sections',
        'financial_unknown_candidates', 'memo_assertion_candidates' if manifest['draft_contract'] in {'purpose_v15','purpose_v16','purpose_v17','purpose_v18'} else 'memo_sentence_candidates')}
    if 'author_options_contract' in manifest:
        from delivery.material_stage import COMPACT_MATERIAL_AUTHOR_OPTIONS
        base.update(author_options_contract=manifest['author_options_contract'],
                    as_of_date=manifest['memo_assertion_candidates']['as_of_date'],
                    draft_model={'name':manifest['draft_model'],'digest':manifest['draft_pin'],
                                 'options':COMPACT_MATERIAL_AUTHOR_OPTIONS})
    return base

def _frozen(memo_root: Path, output: Path, *, create: bool,
            draft_model: str | None = None, content_root: Path | None = None) -> dict:
    root = output.resolve()
    if not create:
        saved = json.loads((root / 'manifest.json').read_text())
        if draft_model is not None and draft_model != saved['draft_model']:
            raise ValueError('Frozen material draft model changed')
        draft_model = saved['draft_model']
        saved_content = (saved.get('content_revision') or {}).get('root')
        content_root = Path(saved_content) if saved_content else None
    projection = _memo_projection(memo_root, material_draft_model=draft_model,
                                  content_root=content_root, **({'temporal_candidates':True, 'temporal_contract':'purpose_v18' if create else saved['draft_contract']} if (create and content_root is not None) or (not create and saved['draft_contract'] in {'purpose_v16','purpose_v17','purpose_v18'}) else {'assertion_candidates':True} if not create and saved['draft_contract']=='purpose_v15' else {}))
    if (not root.is_relative_to(OUTPUT_ROOT.resolve()) or
            root == OUTPUT_ROOT.resolve() or root == memo_root.resolve() or
            root.parent != Path(projection['acceptance_root'])):
        raise ValueError('Material output must be beside its private memo diagnostic')
    manifest = json.loads(json.dumps({**projection,
        'contract': 'private-material-continuation-v1',
        # purpose_v14 (distinct slide sentences) is used only on a memo whose
        # rationales passed the content review; older branches replay as v13.
        'draft_contract': ('purpose_v18' if projection.get('content_revision') else 'purpose_v13') if create else saved['draft_contract'],
        'review_contract': ('semantic_v20' if projection.get('content_revision') else 'semantic_v12') if create else saved['review_contract']}, ensure_ascii=False))
    if (create and projection.get('content_revision')) or (not create and 'author_options_contract' in saved):
        from delivery.material_stage import COMPACT_AUTHOR_OPTIONS_CONTRACT
        manifest['author_options_contract'] = COMPACT_AUTHOR_OPTIONS_CONTRACT if create else saved['author_options_contract']
    require_supported_contract(manifest['review_contract'])
    if create:
        root.mkdir(parents=True, exist_ok=False, mode=0o700)
        _write_new(root / 'manifest.json', manifest)
        base = _material_base(manifest)
        base['replay_contracts'] = {kind: manifest['draft_contract'] for kind in KINDS}
        _write_new(root / 'material_request.json', {**base, 'digest': digest(base)})
        _write_new(root / 'model.json', {'profiles': {'draft': projection['draft_model']}})
    elif json.loads((root / 'manifest.json').read_text()) != manifest:
        raise ValueError('Frozen private memo or model changed')
    return manifest


def _material_replay(root: Path, manifest: dict) -> dict:
    request = json.loads((root / 'material_request.json').read_text())
    base = _material_base(manifest)
    base['replay_contracts'] = {kind: manifest['draft_contract'] for kind in KINDS}
    if (request != {**base, 'digest': digest(base)} or
            json.loads((root / 'model.json').read_text()) !=
            {'profiles': {'draft': manifest['draft_model']}}):
        raise ValueError('Material request differs from frozen memo')
    rows = json.loads((root / 'material_attempts.json').read_text())
    from delivery.material_stage import _validate_draft_routes
    _validate_draft_routes(request, rows)
    saved = json.loads((root / 'material_result.json').read_text())
    if saved.get('state') != 'accepted':
        raise ValueError('Model-authored decks are incomplete')
    decks = {}
    for kind in KINDS:
        payload = {**{key: base[key] for key in
                      ('input_revision', 'source_hash', 'memo_digest', 'sections',
                       'financial_unknown_candidates', 'memo_assertion_candidates' if manifest['draft_contract'] in {'purpose_v15','purpose_v16','purpose_v17','purpose_v18'} else 'memo_sentence_candidates')},
                   'kind': kind}
        if 'as_of_date' in base: payload['as_of_date'] = base['as_of_date']
        replayed = replay_material_rows(kind, payload, rows, manifest['sections'],
                                        model_name=manifest['draft_model'],
                                        contract_version=manifest['draft_contract'])
        if replayed['state'] != 'accepted':
            raise ValueError('Deck model response does not replay')
        rendered = render_sections(replayed['spec'], manifest['sections'])
        if (replayed['response_ids'] != saved['decks'][kind]['response_ids'] or
                [list(row) for row in rendered] != saved['decks'][kind]['sections']):
            raise ValueError('Deck sections differ from exact model response')
        decks[kind] = saved['decks'][kind]['sections']
    if decks[KINDS[0]] == decks[KINDS[1]]:
        raise ValueError('Intro and pitch decks are identical')
    return decks



def _reuse_material_draft(root: Path, source: Path, manifest: dict) -> dict:
    """Fork accepted author evidence byte-for-byte; never import review state."""
    source = source.resolve()
    if (source == root or source.parent != root.parent or
            not source.is_relative_to(OUTPUT_ROOT.resolve())):
        raise ValueError('Reusable material draft must be a distinct private sibling')
    names = ('manifest.json','material_request.json','model.json',
             'material_attempts.json','material_result.json','draft_passes.json')
    snapshots = {}
    for name in names:
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Reusable material draft evidence is incomplete')
        snapshots[name] = path.read_bytes()
    original = {name: json.loads(raw) for name, raw in snapshots.items()}
    old = original['manifest.json']
    keys = ('input_revision','source_hash','memo_digest','sections','content_revision',
            'draft_contract','draft_model','draft_pin','author_options_contract')
    if any(old.get(key) != manifest.get(key) for key in keys):
        raise ValueError('Reusable material author or memo contract changed')
    if (original['material_request.json'] != json.loads((root/'material_request.json').read_text()) or
            original['model.json'] != json.loads((root/'model.json').read_text())):
        raise ValueError('Reusable frozen author inputs or model pin changed')
    history = original['draft_passes.json']
    if (not isinstance(history, list) or not 1 <= len(history) <= MAX_DRAFT_PASSES or
            any(row != {'pass': index+1, 'state': 'accepted' if index == len(history)-1 else 'needs_resume'}
                for index,row in enumerate(history))):
        raise ValueError('Reusable author history is not terminal accepted')
    saved, attempts = original['material_result.json'], original['material_attempts.json']
    if (saved.get('state') != 'accepted' or saved.get('attempt_count') != len(attempts) or
            saved.get('source_hash') != manifest['source_hash'] or
            saved.get('memo_digest') != manifest['memo_digest'] or len(attempts) > 12):
        raise ValueError('Reusable author result is not complete')
    accepted_ids = [rid for kind in KINDS for rid in saved['decks'][kind]['response_ids']]
    if (len(accepted_ids) != len(set(accepted_ids)) or
            set(accepted_ids) != {row.get('id') for row in attempts} or
            len(attempts) != len(accepted_ids) or
            any('error' in row or not any(row.get('task','').startswith('material_'+kind+'_') for kind in KINDS)
                for row in attempts)):
        raise ValueError('Reusable evidence contains failed or non-author responses')
    # Recompute routes, frozen prompts/schemas, raw answer equality, selected
    # response IDs and every rendered section before copying anything.
    _material_replay(source, old)
    for name, raw in snapshots.items():
        if (source/name).read_bytes() != raw:
            raise ValueError('Reusable material evidence changed during replay')
    imported = ('material_attempts.json','material_result.json','draft_passes.json')
    for name in imported:
        with os.fdopen(os.open(root/name, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600),'wb') as stream:
            stream.write(snapshots[name]); stream.flush(); os.fsync(stream.fileno())
    _material_replay(root, manifest)
    provenance = {'contract':'private-material-author-fork-v1','source_root':str(source),
        'source_files':{name:hashlib.sha256(raw).hexdigest() for name,raw in snapshots.items()},
        'imported_files':list(imported),'author_response_ids':accepted_ids,
        'author_attempt_count':len(attempts),'author_pass_count':len(history),
        'review_state_imported':False,'replayed_state':'accepted'}
    _write_new(root/'material_draft_fork.json',provenance)
    return provenance

def run(memo_root: Path, output: Path, phase: str, *, draft_model: str | None = None,
        content_root: Path | None = None, reuse_material_draft: Path | None = None) -> dict:
    if reuse_material_draft is not None and phase != 'prepare':
        raise ValueError('Material author reuse is allowed only during fresh prepare')
    root = output.resolve()
    manifest = _frozen(memo_root, root, create=phase == 'prepare',
                       draft_model=draft_model, content_root=content_root)
    if phase == 'prepare':
        if reuse_material_draft is not None:
            provenance = _reuse_material_draft(root, reuse_material_draft, manifest)
            return {'state':'prepared','diagnostic_path':str(root),'draft_state':'accepted',
                    'reused_author_responses':provenance['author_attempt_count']}
        return {'state': 'prepared', 'diagnostic_path': str(root)}
    if phase == 'draft':
        if _installed_digest(manifest['draft_model']) != manifest['draft_pin']:
            raise ValueError('Installed local draft model changed')
        history_file = root / 'draft_passes.json'
        history = json.loads(history_file.read_text()) if history_file.exists() else []
        if len(history) >= MAX_DRAFT_PASSES or any(row['state'] == 'started' for row in history):
            raise ValueError('Bounded material draft cannot continue')
        if history and history[-1]['state'] != 'needs_resume':
            raise ValueError('Material draft already ended')
        history.append({'pass': len(history) + 1, 'state': 'started'})
        (_replace if history_file.exists() else _write_new)(history_file, history)
        budget_file = root / 'material_budget.json'
        (_replace if budget_file.exists() else _write_new)(budget_file, {'seconds': 105})
        run_private([sys.executable, PROJECT / 'scripts/private_material_worker.py'],
                    root, timeout=118, extra_read=(PROJECT / 'agents', PROJECT / 'schemas.py'),
                    local_model=True)
        result = json.loads((root / 'material_result.json').read_text())
        history[-1]['state'] = result['state']
        _replace(history_file, history)
        if result['state'] == 'accepted':
            _material_replay(root, manifest)
        return {'state': result['state'], 'reason': result.get('reason'),
                'passes': len(history), 'diagnostic_path': str(root),
                'release_status': 'diagnostic_only_no_release'}
    decks = _material_replay(root, manifest)
    if phase == 'review':
        if _installed_digest(manifest['review_model']) != manifest['review_pin']:
            raise ValueError('Installed local review model changed')
        request_file = root / 'material_review_request.json'
        base = {'input_revision': manifest['input_revision'],
                'source_hash': manifest['source_hash'],
                'memo_digest': manifest['memo_digest'],
                'material_digest': digest(json.loads((root / 'material_result.json').read_text())),
                'memo_sections': manifest['sections'], 'decks': decks,
                'review_model': {'name': manifest['review_model'],
                    'digest': manifest['review_pin'], 'options': (
                    narrative_review_options(manifest['review_contract'])
                    if manifest['review_contract'] in {'semantic_v18','semantic_v19','semantic_v20'} else BATCH_OPTIONS if manifest['review_contract'] in {_BATCH_CONTRACT, 'semantic_v14', 'semantic_v15', 'semantic_v16', 'semantic_v17', 'semantic_v18'} else
                        SENTENCE_OPTIONS if manifest['review_contract'] == _SENTENCE_CONTRACT else
                        {'thinking': False, 'max_tokens': 1200, 'context_tokens': 16384, 'temperature': 0})},
                'review_contract': manifest['review_contract']}
        if manifest['review_contract'] in {'semantic_v14', 'semantic_v15', 'semantic_v16', 'semantic_v17', 'semantic_v18', 'semantic_v19', 'semantic_v20'}:
            base['financial_unknown_candidates'] = manifest['financial_unknown_candidates']
            base['memo_assertion_candidates'] = manifest['memo_assertion_candidates']
        if manifest['section_projection'] in ('reader_v1', 'reader_v2'):
            base['memo_section_projection'] = manifest['section_projection']
        if manifest['section_projection'] == 'reader_v2':
            base['evidence_extraction'] = 'reader_v2_claim_pair_v1'
        request = {**base, 'digest': digest(base)}
        if request_file.exists():
            if json.loads(request_file.read_text()) != request:
                raise ValueError('Frozen material review input changed')
        else:
            _write_new(request_file, request)
        history_file = root / 'review_passes.json'
        history = json.loads(history_file.read_text()) if history_file.exists() else []
        if len(history) >= MAX_REVIEW_PASSES or any(row['state'] == 'started' for row in history):
            raise ValueError('Bounded material review cannot continue')
        if history and history[-1]['state'] != 'needs_resume':
            raise ValueError('Material review already ended')
        history.append({'pass': len(history) + 1, 'state': 'started'})
        (_replace if history_file.exists() else _write_new)(history_file, history)
        budget_file = root / 'material_review_budget.json'
        (_replace if budget_file.exists() else _write_new)(budget_file, {'seconds': 105})
        run_private([sys.executable, PROJECT / 'scripts/private_material_review_worker.py'],
                    root, timeout=118, extra_read=(PROJECT / 'agents', PROJECT / 'schemas.py'),
                    local_model=True)
        result = json.loads((root / 'material_review_result.json').read_text())
        history[-1]['state'] = result['state']
        _replace(history_file, history)
        return {'state': result['state'], 'reason': result.get('reason'),
                'passes': len(history), 'diagnostic_path': str(root),
                'release_status': 'diagnostic_only_no_release'}
    if phase == 'render':
        review = json.loads((root / 'material_review_result.json').read_text())
        if review.get('state') != 'accepted':
            raise ValueError('Local material review has not accepted both decks')
        class NoInference:
            name = manifest['review_model']
            def generate_for_task(self, *args, **kwargs):
                raise AssertionError('Recorded material review cannot infer during replay')
        if review_materials(root, NoInference()) != review:
            raise ValueError('Material reviewer response did not replay')
        render_root = root / 'render'
        render_root.mkdir(mode=0o700, exist_ok=False)
        _write_new(render_root / 'request.json', {'operation': 'render',
            'title': manifest['company'], 'memo_sections': manifest['sections'],
            'intro_sections': decks['intro_deck'], 'pitch_sections': decks['pitch_deck']})
        run_private([sys.executable, PROJECT / 'scripts/private_document_worker.py'],
                    render_root, timeout=118, extra_read=(PROJECT / 'agents', PROJECT / 'schemas.py'))
        pairs = {}
        for stem, editable in (('intro', 'pptx'), ('pitch', 'pptx'), ('memo', 'docx')):
            pair = inspect_export_pair((render_root / f'{stem}.{editable}').read_bytes(),
                                       editable, (render_root / f'{stem}.pdf').read_bytes())
            pairs[stem] = {'pair_status': pair['pair_status'],
                           'editable_text_status': pair['editable_text_status']}
        _write_new(root / 'render_result.json', {'state': 'rendered', 'pairs': pairs,
            'files': {path.name: _sha(path) for path in render_root.iterdir()
                      if path.is_file() and path.suffix in {'.pptx', '.pdf', '.docx'}},
            'release_status': 'diagnostic_only_no_release'})
        return {'state': 'rendered', 'pairs': pairs, 'diagnostic_path': str(render_root),
                'release_status': 'diagnostic_only_no_release'}
    raise ValueError('Unknown private material phase')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('memo_root', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('phase', choices=('prepare', 'draft', 'review', 'render'))
    parser.add_argument('--draft-model', help='Installed local model for a new material branch')
    parser.add_argument('--content-revision', type=Path,
                        help='Accepted memo content-revision diagnostic beside the memo')
    parser.add_argument('--reuse-material-draft', type=Path,
                        help='Fork exact accepted author responses from a private sibling; no review reuse')
    args = parser.parse_args()
    result = run(args.memo_root, args.output, args.phase,
                 draft_model=args.draft_model, content_root=args.content_revision,
                 reuse_material_draft=args.reuse_material_draft)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
