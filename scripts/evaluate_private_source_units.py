"""Private checkpointed source-unit workflow; local checks are not release approval."""
import argparse
import json
from pathlib import Path
import sys
import time
from agents.inference.model_authorship import digest
from delivery.isolation import run_private
from scripts.evaluate_private_memo_content import _memo_inputs, OUTPUT_ROOT, PROJECT
from scripts.evaluate_private_material_acceptance import _installed_digest, _write_new, _replace
from scripts.private_source_unit_worker import FLOW, FLOW_V2, FLOW_V3, FLOW_V4, FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12, PHASES, phases_for, load_source_unit_revision, replay_source_unit_revision


def run(memo_root, output, phase, model='qwen3.5:9b', section_author_model=None, section_review_model=None,
        *, flow=FLOW_V4, structures=None, financial_scope=None, coverage_contract=None,
        coverage_model=None, adjudication_model=None, coverage_batching_contract=None):
    memo_dir, original, _, accepted = _memo_inputs(Path(memo_root))
    root = Path(output).resolve()
    if (not root.is_relative_to(OUTPUT_ROOT.resolve()) or root.parent != memo_dir.parent or root == memo_dir):
        raise ValueError('Source-unit diagnostic must be beside the private memo')
    if phase == 'prepare':
        pin = {'name':model,'digest':_installed_digest(model)}
        if flow not in {FLOW_V4, FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12}:
            raise ValueError('Unknown fresh source-unit diagnostic contract')
        body = {'flow_contract':flow,'memo':accepted['memo'],'sources':original['sources'],
                'characterizer_pin':pin,'author_pin':pin,'reviewer_pin':pin,
                'author_contract':'memo-source-unit-author-v7',
                'section_author_contract':'memo-section-units-author-v8', 'section_review_contract':'memo-section-units-review-v7',
                'core_reviewer_pin':{'name':section_review_model or model,'digest':_installed_digest(section_review_model or model)},
                'core_author_pin':{'name':section_author_model or model,'digest':_installed_digest(section_author_model or model)}}
        if flow == FLOW_V11:
            body['coverage_batching_contract'] = coverage_batching_contract or 'source-interpretation-evidence-first-v2'
        elif flow == FLOW_V12:
            body['coverage_batching_contract'] = coverage_batching_contract or 'source-interpretation-pair-v1'
        elif coverage_batching_contract is not None:
            raise ValueError('Source interpretation version requires FLOW11')
        if flow in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12}:
            from agents.research import diligence_coverage
            if ((flow == FLOW_V12 and coverage_contract not in (None, diligence_coverage.CONTRACT_V20)) or
                    (flow == FLOW_V11 and coverage_contract not in (None, diligence_coverage.CONTRACT_V19)) or
                    (flow == FLOW_V10 and coverage_contract not in (None, diligence_coverage.CONTRACT_V18)) or
                    (flow == FLOW_V9 and coverage_contract not in (None, diligence_coverage.CONTRACT_V17)) or
                    (flow == FLOW_V8 and coverage_contract not in (None, diligence_coverage.CONTRACT_V16)) or
                    (flow == FLOW_V7 and coverage_contract not in (None, diligence_coverage.CONTRACT_V15)) or
                    (flow == FLOW_V6 and coverage_contract not in (None, diligence_coverage.CONTRACT_V12, diligence_coverage.CONTRACT_V13, diligence_coverage.CONTRACT_V14)) or
                    (flow == FLOW_V5 and coverage_contract in {diligence_coverage.CONTRACT_V12, diligence_coverage.CONTRACT_V13, diligence_coverage.CONTRACT_V14, diligence_coverage.CONTRACT_V15, diligence_coverage.CONTRACT_V16, diligence_coverage.CONTRACT_V17, diligence_coverage.CONTRACT_V18, diligence_coverage.CONTRACT_V19, diligence_coverage.CONTRACT_V20})):
                raise ValueError('Split source adjudication requires its exact fresh flow')
            coverage_pin = ({'name':coverage_model,'digest':_installed_digest(coverage_model)}
                            if coverage_model is not None else dict(body['core_author_pin']))
            body.update(section_author_contract='memo-section-units-author-v13',
                        section_review_contract='memo-section-units-review-v12',
                        coverage_contract=coverage_contract or (diligence_coverage.CONTRACT_V20 if flow == FLOW_V12 else diligence_coverage.CONTRACT_V19 if flow == FLOW_V11 else diligence_coverage.CONTRACT_V18 if flow == FLOW_V10 else diligence_coverage.CONTRACT_V17 if flow == FLOW_V9 else diligence_coverage.CONTRACT_V16 if flow == FLOW_V8 else diligence_coverage.CONTRACT_V15 if flow == FLOW_V7 else diligence_coverage.CONTRACT_V14 if flow == FLOW_V6 else diligence_coverage.CONTRACT_V11),
                        coverage_pin=coverage_pin,
                        coverage_structures={} if structures is None else structures)
            if body['coverage_contract'] in {diligence_coverage.CONTRACT_V14, diligence_coverage.CONTRACT_V15, diligence_coverage.CONTRACT_V16, diligence_coverage.CONTRACT_V17, diligence_coverage.CONTRACT_V18, diligence_coverage.CONTRACT_V19, diligence_coverage.CONTRACT_V20}:
                adjudicator = adjudication_model or (model if flow in {FLOW_V11, FLOW_V12} else section_author_model or model)
                body['coverage_adjudicator_pin'] = {'name': adjudicator, 'digest': _installed_digest(adjudicator)}
                body['coverage_adjudicator_role'] = 'adjudicator'
            elif adjudication_model is not None:
                raise ValueError('Adjudication role cannot enter a historical coverage contract')
            frozen = diligence_coverage.frozen_coverage_requests(body['sources'], body['coverage_pin'],
                structures=body['coverage_structures'], financial_scope=financial_scope, contract=body['coverage_contract'],
                **({'adjudicator_pin': body['coverage_adjudicator_pin']} if 'coverage_adjudicator_pin' in body else {}),
                **({'interpretation_contract': body['coverage_batching_contract']} if flow in {FLOW_V11, FLOW_V12} else {}))
            body['coverage_financial_scope'] = frozen[0][2]['financial_evidence_scope']
        elif structures is not None or financial_scope is not None or coverage_model is not None or adjudication_model is not None:
            raise ValueError('Coverage metadata cannot enter a historical flow')
        root.mkdir(mode=0o700,parents=True,exist_ok=False)
        _write_new(root/'content_request.json',{**body,'digest':digest(body)})
        return {'state':'prepared','diagnostic_path':str(root)}
    request = json.loads((root/'content_request.json').read_text())
    if request['memo'] != accepted['memo'] or request['sources'] != original['sources']:
        raise ValueError('Source-unit original memo/source inputs changed')
    if coverage_model is not None and request.get('coverage_pin', {}).get('name') != coverage_model:
        raise ValueError('Coverage model cannot change after the request is frozen')
    if adjudication_model is not None and request.get('coverage_adjudicator_pin', {}).get('name') != adjudication_model:
        raise ValueError('Adjudication model cannot change after the request is frozen')
    if coverage_batching_contract is not None and request.get('coverage_batching_contract') != coverage_batching_contract:
        raise ValueError('Source interpretation version cannot change after freeze')
    phases = phases_for(request['flow_contract'])
    if phase == 'advance':
        history_file = root/'content_passes.json'
        history = json.loads(history_file.read_text()) if history_file.exists() else []
        result_path = root/'content_result.json'
        previous = json.loads(result_path.read_text()) if result_path.exists() else {}
        if previous.get('state') in {'accepted','blocked'}:
            return {'state':previous['state'],'reason':previous.get('reason'),'passes':len(history),'diagnostic_path':str(root)}
        recovering = request['flow_contract'] == FLOW_V12 and previous.get('reason') == 'interrupted_between_committed_calls'
        prior_history = history[:-1] if recovering else history
        if (len(history)>=len(phases) and not recovering or any(row['state']!='needs_resume' for row in prior_history)
                or recovering and history[-1]['state'] != 'interrupted_between_committed_calls'):
            raise ValueError('Source-unit diagnostic exhausted its ordered checkpoints')
        expected = phases[len(history) - 1 if recovering else len(history)]
        if previous.get('next_phase',phases[0]) != expected:
            raise ValueError('Previous bounded phase did not complete')
        for key in ('characterizer_pin','author_pin','reviewer_pin',
                    *(key for key in ('core_author_pin', 'core_reviewer_pin', 'coverage_pin', 'coverage_adjudicator_pin') if key in request)):
            pin=request[key]
            if _installed_digest(pin['name'])!=pin['digest']:
                raise ValueError('Installed local source-unit role changed')
        if not recovering:
            history.append({'pass':len(history)+1,'phase':expected,'state':'started'})
        (_replace if history_file.exists() else _write_new)(history_file,history)
        budget_file=root/'content_budget.json'
        seconds = 105
        if recovering:
            from scripts.private_source_unit_worker import source_pair_recovery_budget
            seconds = source_pair_recovery_budget(root, request, previous)
        (_replace if budget_file.exists() else _write_new)(budget_file,{'seconds':seconds,'max_calls':6})
        child_started = time.monotonic()
        try:
            run_private([sys.executable,PROJECT/'scripts/private_source_unit_worker.py'],root,
                        timeout=118,extra_read=(PROJECT/'agents',PROJECT/'schemas.py'),local_model=True)
            result=json.loads(result_path.read_text())
        except RuntimeError:
            if request['flow_contract'] == FLOW_V12:
                from scripts.private_source_unit_worker import record_source_pair_interruption
                result = record_source_pair_interruption(root, request, expected, time.monotonic() - child_started)
            else:
                result={'state':'blocked','reason':'source_unit_worker_interrupted'}
            (_replace if result_path.exists() else _write_new)(result_path,result)
        history[-1]['state']=('interrupted_between_committed_calls' if result.get('reason') == 'interrupted_between_committed_calls' else result['state']);_replace(history_file,history)
        return {'state':result['state'],'reason':result.get('reason'),'next_phase':result.get('next_phase'),
                'passes':len(history),'diagnostic_path':str(root),'independent_review':'pending'}
    if phase == 'verify':
        history=json.loads((root/'content_passes.json').read_text())
        if history != [{'pass':i+1,'phase':p,'state':'accepted' if i==len(phases)-1 else 'needs_resume'} for i,p in enumerate(phases)]:
            raise ValueError('Source-unit diagnostic lacks its exact completed checkpoints')
        memo,gate=replay_source_unit_revision(request['memo'],request['sources'],load_source_unit_revision(root))
        result=json.loads((root/'content_result.json').read_text())
        if result.get('content_review')!=gate or result.get('final_memo_digest')!=digest(memo):
            raise ValueError('Recorded source-unit result changed')
        return {'state':'accepted','final_memo_digest':digest(memo),'acceptance_scope':'local_model_checks_only',
                'independent_review':'pending','diagnostic_path':str(root)}
    raise ValueError('Unknown source-unit phase')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('memo_root',type=Path);p.add_argument('output',type=Path)
    p.add_argument('phase',choices=('prepare','advance','verify'));p.add_argument('--model',default='qwen3.5:9b')
    p.add_argument('--section-author-model',help='Installed local model for independent core writer checkpoints')
    p.add_argument('--section-review-model',help='Installed local model for independent core review checkpoints')
    p.add_argument('--coverage-model',help='Installed local source-coverage model; defaults to the core author model')
    p.add_argument('--adjudication-model', help='Installed source-adjudication model for coverage14/15/16/17/18/19; defaults to source model for19, core author otherwise')
    p.add_argument('--flow', choices=(FLOW_V4, FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12), default=FLOW_V10)
    p.add_argument('--coverage-batching-contract', choices=('source-interpretation-evidence-first-v2', 'source-interpretation-evidence-first-v3', 'source-interpretation-evidence-first-v4', 'source-interpretation-evidence-first-v5', 'source-interpretation-pair-v1', 'source-interpretation-pair-v2'))
    p.add_argument('--coverage-contract', choices=('diligence-source-coverage-v1', 'diligence-source-coverage-v2', 'diligence-source-coverage-v3', 'diligence-source-coverage-v4', 'diligence-source-coverage-v5', 'diligence-source-coverage-v6', 'diligence-source-coverage-v7', 'diligence-source-coverage-v8', 'diligence-source-coverage-v9', 'diligence-source-coverage-v10', 'diligence-source-coverage-v11', 'diligence-source-coverage-v12', 'diligence-source-coverage-v13', 'diligence-source-coverage-v14', 'diligence-source-coverage-v15', 'diligence-source-coverage-v16', 'diligence-source-coverage-v17', 'diligence-source-coverage-v18', 'diligence-source-coverage-v19', 'diligence-source-coverage-v20'))
    p.add_argument('--coverage-structures', type=Path, help='Private source-ID structure JSON')
    p.add_argument('--coverage-financial-scope', type=Path, help='Private unassessed workbook scope JSON')
    a=p.parse_args();print(json.dumps(run(a.memo_root,a.output,a.phase,a.model,a.section_author_model,a.section_review_model,
        flow=a.flow, structures=json.loads(a.coverage_structures.read_text()) if a.coverage_structures else None,
        financial_scope=json.loads(a.coverage_financial_scope.read_text()) if a.coverage_financial_scope else None,
        coverage_contract=a.coverage_contract, coverage_model=a.coverage_model, adjudication_model=a.adjudication_model, coverage_batching_contract=a.coverage_batching_contract)))
