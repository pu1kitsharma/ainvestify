"""Private, local-only attachment acceptance diagnostic outside deal/API state.

Parses two PDFs and one workbook in a fail-closed macOS sandbox. It never
creates a company, deal, tenant, mandate, job, public-KB record or artifact
release. Private passages remain only in the ignored mode-0700 output folder.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from delivery.isolation import run_private
from delivery.storage import read_source_bytes

OUTPUT_ROOT = Path(__file__).resolve().parents[1] / 'runtime_qualification/private_acceptance'
PROJECT = Path(__file__).resolve().parents[1]


def prepare(inputs: list[Path], output: Path) -> dict:
    if len(inputs) != 3 or sorted(path.suffix.lower() for path in inputs) != [
            '.pdf', '.pdf', '.xlsx']:
        raise ValueError('Exactly two PDFs and one XLSX are required')
    root = output.resolve()
    if not root.is_relative_to(OUTPUT_ROOT.resolve()) or root == OUTPUT_ROOT.resolve():
        raise ValueError('Private output must be under ignored acceptance diagnostics')
    checked = []
    for path in inputs:
        if path.is_symlink() or not path.is_file():
            raise ValueError('Input is unavailable or linked')
        # Fail before creating an output if a file exceeds the supported bound.
        read_source_bytes(path)
        checked.append(str(path.resolve()))
    root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.mkdir(mode=0o700, exist_ok=False)
    request = {'contract': 'private-acceptance-ingest-v1', 'files': checked,
               'scope': 'local_diagnostic_only_no_deal_or_release'}
    descriptor = os.open(root / 'request.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as output_file:
        json.dump(request, output_file)
    try:
        run_private([sys.executable, PROJECT / 'scripts/private_acceptance_ingest_worker.py'],
                    root, timeout=120,
                    extra_read=[PROJECT / 'agents', PROJECT / 'schemas.py', *inputs])
    except (RuntimeError, TimeoutError):
        return {'state': 'blocked', 'reason': 'isolated_ingestion_failed',
                'diagnostic_path': str(root),
                'release_status': 'diagnostic_only_no_release'}
    result = json.loads((root / 'ingest_result.json').read_text())
    return {'state': result['state'],
            'document_count': result['document_count'],
            'pdf_passage_count': result['pdf_passage_count'],
            'pdf_passage_characters': result['pdf_passage_characters'],
            'oversized_pdf_passages': result['oversized_pdf_passages'],
            'memo_source_count': result['memo_source_count'],
            'memo_source_complete': result['memo_source_complete'],
            'memo_source_sha256': result['memo_source_sha256'],
            'input_hashes': [item['sha256'] for item in result['documents']],
            'input_block_counts': [item['block_count'] for item in result['documents']],
            'inventory_sha256': result['inventory_sha256'],
            'diagnostic_path': str(root),
            'release_status': result['release_status']}


def _atomic_private(path: Path, payload) -> None:
    if path.exists():
        if json.loads(path.read_text()) != payload:
            raise ValueError('Frozen private diagnostic input changed')
        return
    temporary = path.with_suffix(path.suffix + '.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as output_file:
        json.dump(payload, output_file, ensure_ascii=False)
        output_file.flush()
        os.fsync(output_file.fileno())
    temporary.replace(path)


def _replace_private(path: Path, payload) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as output_file:
        json.dump(payload, output_file, ensure_ascii=False)
        output_file.flush()
        os.fsync(output_file.fileno())
    temporary.replace(path)


def _copy_exact_private(source: Path, destination: Path) -> None:
    """Preserve a frozen phase artifact byte-for-byte before the next phase."""
    if destination.exists():
        if destination.read_bytes() != source.read_bytes():
            raise ValueError('Frozen private phase snapshot changed')
        return
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as output_file:
        output_file.write(source.read_bytes())
        output_file.flush()
        os.fsync(output_file.fileno())


def _private_root(output: Path) -> Path:
    root = output.resolve()
    if not root.is_relative_to(OUTPUT_ROOT.resolve()) or root == OUTPUT_ROOT.resolve():
        raise ValueError('Private output must be under ignored acceptance diagnostics')
    if not (root / 'ingest_result.json').is_file():
        raise ValueError('Private inputs have not been isolated and parsed')
    return root


def _company_hint_from_input_names(paths: list[str]) -> str:
    """A filename label only; the model must establish identity from sources."""
    pdfs = [Path(path).stem.strip().split() for path in paths
            if Path(path).suffix.lower() == '.pdf']
    if len(pdfs) != 2:
        raise ValueError('Two PDF filenames required for the unverified label')
    common = []
    for left, right in zip(*pdfs):
        if left.casefold() != right.casefold():
            break
        common.append(left)
    label = ' '.join(common).strip(' -_')
    if len(label) < 2:
        raise ValueError('No common filename label; company identity must be supplied')
    return label


def _memo_draft_pass_cap(profile: dict) -> int:
    if profile.get('memo_draft_contract') in {'memo-cards-v8', 'memo-cards-v9',
                                              'memo-cards-v10', 'memo-cards-v11',
                                              'memo-cards-v12', 'memo-cards-v13'}:
        return 30
    return (8 if profile.get('memo_draft_contract') in {
        'memo-cards-v1', 'memo-cards-v2', 'memo-cards-v3', 'memo-cards-v4',
        'memo-cards-v5', 'memo-cards-v6', 'memo-cards-v7'} else 6)


def run_one_local_pass(output: Path, phase: str, *, resume=False) -> dict:
    """One private inference pass; no deal writes and no investor release."""
    if phase == 'memo_correction':
        return run_memo_correction_pass(output, resume=resume)
    if phase == 'memo_ledger':
        return run_memo_ledger_pass(output, resume=resume)
    if phase == 'memo_review':
        return run_memo_review_pass(output, resume=resume)
    if phase not in {'memo_draft', 'financial'}:
        raise ValueError('Unsupported local acceptance phase')
    root = _private_root(output)
    source = json.loads((root / 'ingest_result.json').read_text())
    if source.get('state') != 'parsed':
        raise ValueError('Private attachment parse is not complete')
    original_request = json.loads((root / 'request.json').read_text())
    draft_pass_cap = 6
    if phase == 'memo_draft':
        from agents.inference.local_models import PreparationModel, shared_model_name
        from delivery.investment_memo_stage import frozen_memo_model_profile
        bundle = json.loads((root / 'memo_sources.json').read_text())
        if not bundle.get('complete') or bundle.get('source_sha256') != source.get('memo_source_sha256'):
            return {'state': 'blocked', 'reason': 'complete_source_bundle_required',
                    'release_status': 'diagnostic_only_no_release'}
        memo = root / 'memo'
        memo.mkdir(mode=0o700, exist_ok=True)
        request_file = memo / 'request.json'
        saved_request = json.loads(request_file.read_text()) if request_file.exists() else None
        request = {'company': _company_hint_from_input_names(original_request['files']),
                   'company_hint_status': 'filename_only_unverified',
                   'sources': bundle['sources'],
                   'input_revision': source['memo_source_sha256'],
                   'as_of_date': (saved_request['as_of_date'] if saved_request
                                  else date.today().isoformat())}
        _atomic_private(request_file, request)
        profile = frozen_memo_model_profile(memo / 'model.json',
                                            shared_model_name(PreparationModel()))
        draft_pass_cap = _memo_draft_pass_cap(profile)
        _atomic_private(memo / 'budget.json', {'seconds': 105, 'phase': 'draft_only'})
        script = PROJECT / 'scripts/private_investment_memo_worker.py'
        extra_read = [PROJECT / 'agents', PROJECT / 'schemas.py']
        directory = memo
    else:
        from agents.inference.local_models import PreparationModel, shared_model_name
        workbook = root / 'financial'
        workbook.mkdir(mode=0o700, exist_ok=True)
        path = next(Path(path) for path in original_request['files']
                    if Path(path).suffix.lower() == '.xlsx')
        content = read_source_bytes(path)
        content_hash = hashlib.sha256(content).hexdigest()
        expected_hashes = {row['sha256'] for row in source['documents']}
        if content_hash not in expected_hashes:
            return {'state': 'blocked', 'reason': 'original_workbook_hash_changed',
                    'release_status': 'diagnostic_only_no_release'}
        copy = workbook / 'source.xlsx'
        if copy.exists():
            if hashlib.sha256(copy.read_bytes()).hexdigest() != content_hash:
                raise ValueError('Frozen private workbook copy changed')
        else:
            descriptor = os.open(copy, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'wb') as output_file:
                output_file.write(content)
                output_file.flush()
                os.fsync(output_file.fileno())
        _atomic_private(workbook / 'request.json',
                        {'workbook': 'source.xlsx', 'workbook_sha256': content_hash,
                         'as_of_date': date.today().isoformat()})
        _atomic_private(workbook / 'model.json',
                        {'profiles': {'financial': shared_model_name(PreparationModel())}})
        _atomic_private(workbook / 'budget.json', {'seconds': 105})
        script = PROJECT / 'scripts/private_financial_worker.py'
        extra_read = [PROJECT / 'agents', PROJECT / 'schemas.py']
        directory = workbook
    result_file = directory / 'result.json'
    if resume and phase != 'memo_draft':
        raise ValueError('Only the bounded memo draft can resume')
    if result_file.exists() and not resume:
        return {'state': 'blocked', 'reason': 'one_pass_already_recorded',
                'attempts_path': str(directory / 'attempts.json'),
                'release_status': 'diagnostic_only_no_release'}
    if resume:
        if not result_file.exists() or json.loads(result_file.read_text()).get('state') != 'needs_resume':
            return {'state': 'blocked', 'reason': 'saved_memo_pass_not_resumable',
                    'release_status': 'diagnostic_only_no_release'}
        journal = directory / 'pass_history.json'
        history = json.loads(journal.read_text()) if journal.exists() else [
            {'pass': 1, 'state': 'needs_resume', 'origin': 'first_recorded_pass'}]
        if len(history) >= draft_pass_cap or any(row['state'] == 'started' for row in history):
            return {'state': 'blocked', 'reason': 'memo_draft_cap_or_incomplete_pass',
                    'release_status': 'diagnostic_only_no_release'}
        history.append({'pass': len(history) + 1, 'state': 'started'})
        _replace_private(journal, history)
    try:
        run_private([sys.executable, script], directory, timeout=118,
                    extra_read=extra_read, local_model=True)
    except (RuntimeError, TimeoutError):
        return {'state': 'blocked', 'reason': 'isolated_local_model_pass_failed',
                'diagnostic_path': str(directory),
                'release_status': 'diagnostic_only_no_release'}
    result = json.loads(result_file.read_text())
    if resume:
        history[-1]['state'] = result.get('state', 'blocked')
        _replace_private(journal, history)
    attempts_path = directory / 'attempts.json'
    attempts = json.loads(attempts_path.read_text()) if attempts_path.is_file() else []
    reason = result.get('reason')
    if reason is not None and (not isinstance(reason, str) or
                               not re.fullmatch(r'[a-zA-Z0-9_:-]{1,100}', reason)):
        reason = 'private_reason_saved_in_diagnostic'
    terminal_cap = (phase == 'memo_draft' and resume and len(history) >= draft_pass_cap and
                    result.get('state') == 'needs_resume')
    return {'state': 'blocked' if terminal_cap else result.get('state', 'blocked'),
            'worker_state': result.get('state'),
            'reason': 'draft_pass_cap_exhausted' if terminal_cap else reason,
            'attempt_count': len(attempts),
            'pass_count': len(history) if resume else 1,
            'source_count': source['memo_source_count'] if phase == 'memo_draft' else 1,
            'diagnostic_path': str(directory),
            'attempts_path': str(attempts_path) if attempts_path.is_file() else None,
            'release_status': 'diagnostic_only_no_release',
            'financial_claim_status': 'unreconciled_no_validated_forecast'}


def run_memo_correction_pass(output: Path, *, resume=False) -> dict:
    """Advance a draft-ready private memo through at most three correction passes."""
    root = _private_root(output)
    memo = root / 'memo'
    result_file = memo / 'result.json'
    budget_file = memo / 'budget.json'
    draft_result_copy = memo / 'draft_ready_result.json'
    draft_budget_copy = memo / 'draft_only_budget.json'
    history_file = memo / 'correction_pass_history.json'
    attempts_file = memo / 'attempts.json'
    if not all(path.is_file() for path in (result_file, budget_file, attempts_file)):
        raise ValueError('Saved private memo draft is incomplete')
    current_result = json.loads(result_file.read_text())
    current_budget = json.loads(budget_file.read_text())
    if not resume:
        if history_file.exists() or draft_result_copy.exists() or draft_budget_copy.exists():
            return {'state': 'blocked', 'reason': 'correction_phase_already_started',
                    'release_status': 'diagnostic_only_no_release'}
        if current_result.get('state') != 'draft_ready' or current_budget != {
                'seconds': 105, 'phase': 'draft_only'}:
            return {'state': 'blocked', 'reason': 'draft_ready_checkpoint_required',
                    'release_status': 'diagnostic_only_no_release'}
        _copy_exact_private(result_file, draft_result_copy)
        _copy_exact_private(budget_file, draft_budget_copy)
        history = []
    else:
        if not all(path.is_file() for path in (
                history_file, draft_result_copy, draft_budget_copy)):
            raise ValueError('Frozen correction transition is missing')
        history = json.loads(history_file.read_text())
        if (not history or history[-1].get('state') != 'needs_resume' or
                current_result.get('state') != 'needs_resume' or
                current_budget != {'seconds': 105, 'phase': 'correction_only'}):
            return {'state': 'blocked', 'reason': 'saved_correction_not_resumable',
                    'release_status': 'diagnostic_only_no_release'}
    if len(history) >= 3 or any(row.get('state') == 'started' for row in history):
        return {'state': 'blocked', 'reason': 'correction_pass_cap_or_incomplete_pass',
                'release_status': 'diagnostic_only_no_release'}
    saved_draft = json.loads(draft_result_copy.read_text())
    saved_budget = json.loads(draft_budget_copy.read_text())
    if saved_draft.get('state') != 'draft_ready' or saved_budget != {
            'seconds': 105, 'phase': 'draft_only'}:
        raise ValueError('Frozen draft phase snapshot changed')
    from agents.research.investment_memo import Source
    from agents.research.part_a_components import (part_a_bundle_id,
                                                    replay_part_a_components)
    from agents.research.staged_memo import (
        _component_revision, _part_b_bundle_id, digest,
        funding_timeline_conflicts, saved_part_a_components,
        saved_part_b_sections)
    request = json.loads((memo / 'request.json').read_text())
    attempts = json.loads(attempts_file.read_text())
    sources = [Source.model_validate(row) for row in request['sources']]
    payload = {key: request[key] for key in ('company', 'sources', 'as_of_date')}
    conflicts = funding_timeline_conflicts(sources)
    if conflicts:
        payload['reported_stage_date_discrepancies'] = conflicts
    part_a_ids = saved_part_a_components(attempts, payload)
    if part_a_ids is None:
        raise ValueError('Frozen Part A draft cannot be replayed')
    part_a = replay_part_a_components(attempts, payload, part_a_ids)
    first_id = part_a_bundle_id(part_a_ids, revision=_component_revision(attempts))
    part_b_ids = saved_part_b_sections(attempts, payload, first_id, part_a)
    if part_b_ids is None:
        raise ValueError('Frozen Part B draft cannot be replayed')
    saved_ids = saved_draft['draft']
    if (saved_ids.get('source_set_digest') != digest(payload['sources']) or
            saved_ids.get('as_of_date') != request['as_of_date'] or
            saved_ids.get('part_a_component_ids') != part_a_ids or
            saved_ids.get('part_a_response_id') != first_id or
            saved_ids.get('part_b_section_response_ids') != part_b_ids or
            saved_ids.get('part_b_response_id') != _part_b_bundle_id(part_b_ids)):
        raise ValueError('Frozen draft checkpoint differs from exact saved replay')
    history.append({'pass': len(history) + 1, 'state': 'started',
                    'draft_result_sha256': hashlib.sha256(
                        draft_result_copy.read_bytes()).hexdigest(),
                    'draft_budget_sha256': hashlib.sha256(
                        draft_budget_copy.read_bytes()).hexdigest()})
    if history_file.exists():
        _replace_private(history_file, history)
    else:
        _atomic_private(history_file, history)
    if current_budget['phase'] == 'draft_only':
        _replace_private(budget_file, {'seconds': 105, 'phase': 'correction_only'})
    try:
        run_private([sys.executable, PROJECT / 'scripts/private_investment_memo_worker.py'],
                    memo, timeout=118,
                    extra_read=[PROJECT / 'agents', PROJECT / 'schemas.py'],
                    local_model=True)
    except (RuntimeError, TimeoutError):
        return {'state': 'blocked', 'reason': 'isolated_local_model_pass_failed',
                'diagnostic_path': str(memo),
                'release_status': 'diagnostic_only_no_release'}
    result = json.loads(result_file.read_text())
    history[-1]['state'] = result.get('state', 'blocked')
    _replace_private(history_file, history)
    attempts = json.loads(attempts_file.read_text())
    reason = result.get('reason')
    if reason is not None and (not isinstance(reason, str) or
                               not re.fullmatch(r'[a-zA-Z0-9_:-]{1,100}', reason)):
        reason = 'private_reason_saved_in_diagnostic'
    terminal_cap = len(history) >= 3 and result.get('state') == 'needs_resume'
    return {'state': 'blocked' if terminal_cap else result.get('state', 'blocked'),
            'worker_state': result.get('state'),
            'reason': 'correction_pass_cap_exhausted' if terminal_cap else reason,
            'attempt_count': len(attempts), 'correction_pass_count': len(history),
            'diagnostic_path': str(memo), 'attempts_path': str(attempts_file),
            'release_status': 'diagnostic_only_no_release',
            'financial_claim_status': 'unreconciled_no_validated_forecast'}


def run_memo_ledger_pass(output: Path, *, resume=False) -> dict:
    """Replay the corrected memo, then run at most five local ledger passes."""
    root = _private_root(output)
    memo = root / 'memo'
    result_file = memo / 'result.json'
    budget_file = memo / 'budget.json'
    attempts_file = memo / 'attempts.json'
    correction_result_copy = memo / 'correction_ready_result.json'
    correction_budget_copy = memo / 'correction_only_budget.json'
    history_file = memo / 'ledger_pass_history.json'
    if not all(path.is_file() for path in (
            result_file, budget_file, attempts_file, memo / 'draft_ready_result.json',
            memo / 'correction_pass_history.json')):
        raise ValueError('Saved private correction checkpoint is incomplete')
    current_result = json.loads(result_file.read_text())
    current_budget = json.loads(budget_file.read_text())
    if not resume:
        if history_file.exists() or correction_result_copy.exists() != correction_budget_copy.exists():
            return {'state': 'blocked', 'reason': 'ledger_phase_already_started',
                    'release_status': 'diagnostic_only_no_release'}
        if current_result.get('state') != 'correction_ready' or current_budget != {
                'seconds': 105, 'phase': 'correction_only'}:
            return {'state': 'blocked', 'reason': 'correction_ready_checkpoint_required',
                    'release_status': 'diagnostic_only_no_release'}
        correction_history = json.loads((memo / 'correction_pass_history.json').read_text())
        if not correction_history or correction_history[-1].get('state') != 'correction_ready':
            raise ValueError('Frozen correction pass did not complete')
        _copy_exact_private(result_file, correction_result_copy)
        _copy_exact_private(budget_file, correction_budget_copy)
        history = []
    else:
        if not all(path.is_file() for path in (
                history_file, correction_result_copy, correction_budget_copy)):
            raise ValueError('Frozen ledger transition is missing')
        history = json.loads(history_file.read_text())
        if (not history or history[-1].get('state') != 'needs_resume' or
                current_result.get('state') != 'needs_resume'):
            return {'state': 'blocked', 'reason': 'saved_ledger_not_resumable',
                    'release_status': 'diagnostic_only_no_release'}
    checkpoint = json.loads(correction_result_copy.read_text())
    if checkpoint.get('state') != 'correction_ready' or json.loads(
            correction_budget_copy.read_text()) != {'seconds': 105, 'phase': 'correction_only'}:
        raise ValueError('Frozen correction phase snapshot changed')
    request = json.loads((memo / 'request.json').read_text())
    profile = json.loads((memo / 'model.json').read_text())
    attempts = json.loads(attempts_file.read_text())
    from agents.research.investment_memo import Source
    from agents.research.staged_memo import digest, run_stage
    if (checkpoint.get('source_set_digest') != digest(request['sources']) or
            checkpoint.get('as_of_date') != request['as_of_date'] or
            not checkpoint.get('corrected_memo_digest')):
        raise ValueError('Saved correction checkpoint source or date changed')
    # No model is provided; any unexpected save raises. This is a private
    # in-memory replay of the exact correction, before ledger inference.
    replay = run_stage(request['company'],
        [Source.model_validate(row) for row in request['sources']],
        json.loads(json.dumps(attempts)),
        lambda: (_ for _ in ()).throw(ValueError('Read-only ledger preflight tried to save')),
        draft_model=None, review_model=None, as_of_date=request['as_of_date'],
        phase='correction_only', compact_part_a=True, compact_part_b=True,
        memo_draft_contract=profile['memo_draft_contract'],
        memo_causal_review_contract=profile.get('memo_causal_review_contract'))
    if replay != checkpoint:
        raise ValueError('Saved correction does not replay to the exact ledger checkpoint')
    expected_budget = {'seconds': 105, 'phase': 'ledger_only',
                       'phase_checkpoint': checkpoint}
    if resume and current_budget != expected_budget:
        raise ValueError('Frozen ledger phase budget changed')
    if len(history) >= 5 or any(row.get('state') == 'started' for row in history):
        return {'state': 'blocked', 'reason': 'ledger_pass_cap_or_incomplete_pass',
                'release_status': 'diagnostic_only_no_release'}
    history.append({'pass': len(history) + 1, 'state': 'started',
                    'correction_result_sha256': hashlib.sha256(
                        correction_result_copy.read_bytes()).hexdigest(),
                    'correction_budget_sha256': hashlib.sha256(
                        correction_budget_copy.read_bytes()).hexdigest()})
    if history_file.exists():
        _replace_private(history_file, history)
    else:
        _atomic_private(history_file, history)
    if not resume:
        _replace_private(budget_file, expected_budget)
    try:
        run_private([sys.executable, PROJECT / 'scripts/private_investment_memo_worker.py'],
                    memo, timeout=118,
                    extra_read=[PROJECT / 'agents', PROJECT / 'schemas.py'],
                    local_model=True)
    except (RuntimeError, TimeoutError):
        return {'state': 'blocked', 'reason': 'isolated_local_model_pass_failed',
                'diagnostic_path': str(memo),
                'release_status': 'diagnostic_only_no_release'}
    result = json.loads(result_file.read_text())
    history[-1]['state'] = result.get('state', 'blocked')
    _replace_private(history_file, history)
    attempts = json.loads(attempts_file.read_text())
    reason = result.get('reason')
    if reason is not None and (not isinstance(reason, str) or
                               not re.fullmatch(r'[a-zA-Z0-9_:-]{1,100}', reason)):
        reason = 'private_reason_saved_in_diagnostic'
    terminal_cap = len(history) >= 5 and result.get('state') == 'needs_resume'
    return {'state': 'blocked' if terminal_cap else result.get('state', 'blocked'),
            'worker_state': result.get('state'),
            'reason': 'ledger_pass_cap_exhausted' if terminal_cap else reason,
            'attempt_count': len(attempts), 'ledger_pass_count': len(history),
            'diagnostic_path': str(memo), 'attempts_path': str(attempts_file),
            'release_status': 'diagnostic_only_no_release',
            'financial_claim_status': 'unreconciled_no_validated_forecast'}


def run_memo_review_pass(output: Path, *, resume=False) -> dict:
    """Review the exact ledger-ready memo in at most fourteen local passes."""
    root = _private_root(output)
    memo = root / 'memo'
    result_file = memo / 'result.json'
    budget_file = memo / 'budget.json'
    attempts_file = memo / 'attempts.json'
    ledger_result_copy = memo / 'ledger_ready_result.json'
    ledger_budget_copy = memo / 'ledger_only_budget.json'
    history_file = memo / 'review_pass_history.json'
    if not all(path.is_file() for path in (
            result_file, budget_file, attempts_file, memo / 'ledger_pass_history.json',
            memo / 'correction_ready_result.json')):
        raise ValueError('Saved private ledger checkpoint is incomplete')
    current_result = json.loads(result_file.read_text())
    current_budget = json.loads(budget_file.read_text())
    if not resume:
        if history_file.exists() or ledger_result_copy.exists() != ledger_budget_copy.exists():
            return {'state': 'blocked', 'reason': 'review_phase_already_started',
                    'release_status': 'diagnostic_only_no_release'}
        if (current_result.get('state') != 'ledger_ready' or
                current_budget.get('seconds') != 105 or
                current_budget.get('phase') != 'ledger_only' or
                current_budget.get('phase_checkpoint') != json.loads(
                    (memo / 'correction_ready_result.json').read_text())):
            return {'state': 'blocked', 'reason': 'ledger_ready_checkpoint_required',
                    'release_status': 'diagnostic_only_no_release'}
        ledger_history = json.loads((memo / 'ledger_pass_history.json').read_text())
        if not ledger_history or ledger_history[-1].get('state') != 'ledger_ready':
            raise ValueError('Frozen ledger pass did not complete')
        _copy_exact_private(result_file, ledger_result_copy)
        _copy_exact_private(budget_file, ledger_budget_copy)
        history = []
    else:
        if not all(path.is_file() for path in (
                history_file, ledger_result_copy, ledger_budget_copy)):
            raise ValueError('Frozen review transition is missing')
        history = json.loads(history_file.read_text())
        if (not history or history[-1].get('state') != 'needs_resume' or
                current_result.get('state') != 'needs_resume'):
            return {'state': 'blocked', 'reason': 'saved_review_not_resumable',
                    'release_status': 'diagnostic_only_no_release'}
    checkpoint = json.loads(ledger_result_copy.read_text())
    if checkpoint.get('state') != 'ledger_ready' or not all(
            checkpoint.get(key) for key in ('corrected_memo_digest',
                'ledger_binding_digest', 'final_memo_digest',
                'source_set_digest', 'as_of_date')):
        raise ValueError('Frozen ledger phase snapshot changed')
    request = json.loads((memo / 'request.json').read_text())
    profile = json.loads((memo / 'model.json').read_text())
    attempts = json.loads(attempts_file.read_text())
    from agents.research.investment_memo import Source
    from agents.research.staged_memo import digest, run_stage
    causal_contract = profile.get('memo_causal_review_contract')
    lineage_file = memo / 'memo_causal_review_lineage.json'
    if (checkpoint['source_set_digest'] != digest(request['sources']) or
            checkpoint['as_of_date'] != request['as_of_date'] or
            causal_contract not in {'memo-causal-v2', 'memo-causal-v3'} or
            lineage_file.is_file() != (causal_contract == 'memo-causal-v3')):
        raise ValueError('Saved review checkpoint source, date, or reviewer changed')
    causal_lineage = (json.loads(lineage_file.read_text())
                      if causal_contract == 'memo-causal-v3' else None)

    class _TrapChallenge:
        name = 'read_only_trap'

        def generate(self, *args, **kwargs):
            raise RuntimeError('Read-only review preflight tried to infer')

    replay = run_stage(request['company'],
        [Source.model_validate(row) for row in request['sources']],
        json.loads(json.dumps(attempts)),
        lambda: (_ for _ in ()).throw(ValueError('Read-only review preflight tried to save')),
        draft_model=None, review_model=None, challenge_model=_TrapChallenge(),
        as_of_date=request['as_of_date'], phase='ledger_only',
        phase_checkpoint=json.loads((memo / 'correction_ready_result.json').read_text()),
        compact_part_a=True, compact_part_b=True,
        memo_draft_contract=profile['memo_draft_contract'],
        memo_causal_review_contract=causal_contract,
        memo_causal_review_lineage=causal_lineage)
    if replay != checkpoint:
        raise ValueError('Saved ledger does not replay to the exact review checkpoint')
    expected_budget = {'seconds': 105, 'phase': 'review_only',
                       'phase_checkpoint': checkpoint}
    if resume and current_budget != expected_budget:
        raise ValueError('Frozen review phase budget changed')
    if len(history) >= 14 or any(row.get('state') == 'started' for row in history):
        return {'state': 'blocked', 'reason': 'review_pass_cap_or_incomplete_pass',
                'release_status': 'diagnostic_only_no_release'}
    history.append({'pass': len(history) + 1, 'state': 'started',
                    'ledger_result_sha256': hashlib.sha256(
                        ledger_result_copy.read_bytes()).hexdigest(),
                    'ledger_budget_sha256': hashlib.sha256(
                        ledger_budget_copy.read_bytes()).hexdigest()})
    if history_file.exists():
        _replace_private(history_file, history)
    else:
        _atomic_private(history_file, history)
    if not resume:
        _replace_private(budget_file, expected_budget)
    try:
        run_private([sys.executable, PROJECT / 'scripts/private_investment_memo_worker.py'],
                    memo, timeout=118,
                    extra_read=[PROJECT / 'agents', PROJECT / 'schemas.py'],
                    local_model=True)
    except (RuntimeError, TimeoutError):
        return {'state': 'blocked', 'reason': 'isolated_local_model_pass_failed',
                'diagnostic_path': str(memo),
                'release_status': 'diagnostic_only_no_release'}
    result = json.loads(result_file.read_text())
    history[-1]['state'] = result.get('state', 'blocked')
    _replace_private(history_file, history)
    attempts = json.loads(attempts_file.read_text())
    reason = result.get('reason')
    if reason is not None and (not isinstance(reason, str) or
                               not re.fullmatch(r'[a-zA-Z0-9_:-]{1,100}', reason)):
        reason = 'private_reason_saved_in_diagnostic'
    terminal_cap = len(history) >= 14 and result.get('state') == 'needs_resume'
    return {'state': 'blocked' if terminal_cap else result.get('state', 'blocked'),
            'worker_state': result.get('state'),
            'reason': 'review_pass_cap_exhausted' if terminal_cap else reason,
            'attempt_count': len(attempts), 'review_pass_count': len(history),
            'diagnostic_path': str(memo), 'attempts_path': str(attempts_file),
            'release_status': 'diagnostic_only_no_release',
            'financial_claim_status': 'unreconciled_no_validated_forecast'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest='command', required=True)
    ingest = subcommands.add_parser('prepare')
    ingest.add_argument('intro_pdf', type=Path)
    ingest.add_argument('pitch_pdf', type=Path)
    ingest.add_argument('workbook', type=Path)
    ingest.add_argument('output', type=Path)
    run = subcommands.add_parser('run-one-pass')
    run.add_argument('phase', choices=('memo_draft', 'memo_correction',
                                       'memo_ledger', 'memo_review', 'financial'))
    run.add_argument('output', type=Path)
    resume = subcommands.add_parser('resume')
    resume.add_argument('phase', choices=('memo_draft', 'memo_correction',
                                          'memo_ledger', 'memo_review'))
    resume.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        result = (prepare([args.intro_pdf, args.pitch_pdf, args.workbook], args.output)
                  if args.command == 'prepare' else run_one_local_pass(
                      args.output, args.phase, resume=args.command == 'resume'))
    except (OSError, ValueError, RuntimeError) as exc:
        result = {'state': 'blocked', 'reason': type(exc).__name__,
                  'release_status': 'diagnostic_only_no_release'}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
