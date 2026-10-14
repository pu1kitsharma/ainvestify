"""Three checkpointed source-only phases, one bounded phase per invocation."""
from __future__ import annotations
import json
from pathlib import Path
from types import SimpleNamespace
from agents.inference.model_authorship import digest
from agents.inference.model_authorship import recorded_call
from agents.inference.local_models import LocalModel
from agents.inference.model_routing import validate_local_model_name
from agents.preparation.preparation_budget import PreparationBudget, PreparationBudgetExceeded, preparation_budget
from agents.research import rationale_evidence as evidence
from agents.research import memo_source_unit_author as author_engine
from agents.research import memo_source_unit_review as review_engine
from agents.research.memo_content_review_v2 import frozen_calls, SCOPE_CONTRACT
from agents.research.investment_memo import Memo, Source

FLOW = 'memo-source-unit-flow-v1'
FLOW_V2 = 'memo-source-unit-flow-v2'
FLOW_V3 = 'memo-source-unit-flow-v3'
FLOW_V4 = 'memo-source-unit-flow-v4'
FLOW_V5 = 'memo-source-unit-flow-v5'
FLOW_V6 = 'memo-source-unit-flow-v6'
FLOW_V7 = 'memo-source-unit-flow-v7'
FLOW_V8 = 'memo-source-unit-flow-v8'
FLOW_V9 = 'memo-source-unit-flow-v9'
FLOW_V10 = 'memo-source-unit-flow-v10'
FLOW_V11 = 'memo-source-unit-flow-v11'
FLOW_V12 = 'memo-source-unit-flow-v12'
CORE_PAIRS_V6 = {('memo-section-units-author-v13', 'memo-section-units-review-v12')}
CORE_PAIRS_V5 = {('memo-section-units-author-v9', 'memo-section-units-review-v8'),
                 ('memo-section-units-author-v10', 'memo-section-units-review-v9'),
                 ('memo-section-units-author-v11', 'memo-section-units-review-v10'),
                 ('memo-section-units-author-v12', 'memo-section-units-review-v11'),
                 ('memo-section-units-author-v13', 'memo-section-units-review-v12')}
PHASES = ('source_characterization', 'source_unit_author', 'source_unit_review')
PHASES_V2 = (*PHASES, 'memo_section_author', 'memo_section_review')
PHASES_V3 = ('source_characterization', 'source_unit_author',
    'source_unit_review_recommendation','source_unit_review_u0','source_unit_review_u1',
    'memo_section_author','memo_section_review_investment_thesis',
    'memo_section_review_business_and_market','memo_section_review_differentiation_and_execution',
    'memo_section_review_risks_and_countercase','memo_section_review_diligence_plan')
PHASES_V4 = (*PHASES_V3[:5],
    *('memo_section_author_'+field for field in ('investment_thesis','business_and_market','differentiation_and_execution','risks_and_countercase','diligence_plan')),
    *PHASES_V3[6:])
COVERAGE_PHASES_V5 = tuple('diligence_coverage_' + str(number) for number in range(1, 6)) + ('diligence_field_selection',)
PHASES_V5 = COVERAGE_PHASES_V5 + PHASES_V4
COVERAGE_PHASES_V6 = COVERAGE_PHASES_V5[:5] + ('diligence_source_adjudication', 'diligence_field_selection')
PHASES_V6 = COVERAGE_PHASES_V6 + PHASES_V4
COVERAGE_PHASES_V7 = COVERAGE_PHASES_V5[:5] + tuple(
    'diligence_source_adjudication_' + str(number) for number in range(1, 6)) + ('diligence_field_selection',)
PHASES_V7 = COVERAGE_PHASES_V7 + PHASES_V4
COVERAGE_PHASES_V8 = COVERAGE_PHASES_V7
PHASES_V8 = COVERAGE_PHASES_V8 + PHASES_V4
COVERAGE_PHASES_V9 = COVERAGE_PHASES_V8
PHASES_V9 = COVERAGE_PHASES_V9 + PHASES_V4
COVERAGE_PHASES_V10 = COVERAGE_PHASES_V9[5:]
PHASES_V10 = COVERAGE_PHASES_V10 + PHASES_V4
COVERAGE_PHASES_V11 = COVERAGE_PHASES_V10
PHASES_V11 = COVERAGE_PHASES_V11 + PHASES_V4
COVERAGE_PHASES_V12 = tuple('diligence_source_pair_' + str(number) for number in range(1, 26)) + ('diligence_field_selection',)
PHASES_V12 = COVERAGE_PHASES_V12 + PHASES_V4
COVERAGE_FILES = {'diligence_coverage_attempts': 'diligence_coverage_attempts.json'}
FILES = {'source_characterization_attempts': 'source_characterization_attempts.json',
         'source_unit_author_attempts': 'source_unit_author_attempts.json',
         'source_unit_review_attempts': 'source_unit_review_attempts.json'}
RECORD_KEYS = {'contract', 'request_digest', 'base_memo_digest', 'source_set_digest',
               'characterizer_pin', 'author_pin', 'reviewer_pin', *FILES}
CORE_FILES = {'memo_section_author_attempts': 'memo_section_author_attempts.json',
              'memo_section_review_attempts': 'memo_section_review_attempts.json'}

def phases_for(flow):
    if flow == FLOW: return PHASES
    if flow == FLOW_V2: return PHASES_V2
    if flow == FLOW_V3: return PHASES_V3
    if flow == FLOW_V4: return PHASES_V4
    if flow == FLOW_V5: return PHASES_V5
    if flow == FLOW_V6: return PHASES_V6
    if flow == FLOW_V7: return PHASES_V7
    if flow == FLOW_V8: return PHASES_V8
    if flow == FLOW_V9: return PHASES_V9
    if flow == FLOW_V10: return PHASES_V10
    if flow == FLOW_V11: return PHASES_V11
    if flow == FLOW_V12: return PHASES_V12
    raise ValueError('Unknown source flow')

def files_for(flow):
    return {**FILES, **(CORE_FILES if flow in {FLOW_V2,FLOW_V3,FLOW_V4,FLOW_V5,FLOW_V6,FLOW_V7,FLOW_V8,FLOW_V9,FLOW_V10, FLOW_V11, FLOW_V12} else {}),
            **(COVERAGE_FILES if flow in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12} else {})}

EMPTY_BUDGET = SimpleNamespace(calls=0, max_calls=0, remaining=lambda: 0)


def _load(root, filename, default=None):
    path = root / filename
    return json.loads(path.read_text()) if path.exists() else default


def _write(root, filename, value):
    path = root / filename
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False))
    temporary.chmod(0o600)
    temporary.replace(path)


def _request(root):
    request = _load(root, 'content_request.json')
    if isinstance(request, dict) and request.get('flow_contract') in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12}:
        _validate_flow5_request(request)
        return request
    keys = {'flow_contract', 'memo', 'sources', 'characterizer_pin', 'author_pin', 'reviewer_pin', 'digest'}
    if (not isinstance(request, dict) or set(request) not in (keys, keys | {'author_contract'}, keys | {'author_contract','section_author_contract'}, keys | {'author_contract','section_author_contract','core_author_pin'}, keys | {'author_contract','section_author_contract','core_author_pin','core_reviewer_pin'}, keys | {'author_contract','section_author_contract','core_author_pin','core_reviewer_pin','section_review_contract'}) or
        ('author_contract' in request and request['author_contract'] not in {'memo-source-unit-author-v2', 'memo-source-unit-author-v3', 'memo-source-unit-author-v4', 'memo-source-unit-author-v5', 'memo-source-unit-author-v6', 'memo-source-unit-author-v7'}) or request['flow_contract'] not in {FLOW,FLOW_V2,FLOW_V3,FLOW_V4} or
        request['digest'] != digest({k:v for k,v in request.items() if k != 'digest'})):
        raise ValueError('Frozen source-unit request changed')
    if (request['flow_contract'] in {FLOW_V2,FLOW_V3,FLOW_V4}) != (request.get('author_contract') == 'memo-source-unit-author-v7'):
        raise ValueError('Full memo flow requires exact v7 author; legacy flow cannot substitute it')
    if 'section_author_contract' in request and (request['flow_contract'] not in {FLOW_V3,FLOW_V4} or request['section_author_contract'] not in {'memo-section-units-author-v2','memo-section-units-author-v3','memo-section-units-author-v4','memo-section-units-author-v5','memo-section-units-author-v6','memo-section-units-author-v7','memo-section-units-author-v8'}):
        raise ValueError('Unknown full memo section author contract')
    if request['flow_contract'] == FLOW_V4 and (request.get('section_author_contract') not in {'memo-section-units-author-v3','memo-section-units-author-v4','memo-section-units-author-v5','memo-section-units-author-v6','memo-section-units-author-v7','memo-section-units-author-v8'} or 'core_author_pin' not in request):
        raise ValueError('Independent author checkpoints need their own frozen core role')
    if request['flow_contract'] != FLOW_V4 and ('core_author_pin' in request or request.get('section_author_contract') in {'memo-section-units-author-v4','memo-section-units-author-v5','memo-section-units-author-v6','memo-section-units-author-v7','memo-section-units-author-v8'}):
        raise ValueError('Core role/bounded writer cannot downgrade its flow')
    if (request.get('section_author_contract') in {'memo-section-units-author-v7','memo-section-units-author-v8'}) != ('core_reviewer_pin' in request):
        raise ValueError('Structured core decisions require their exact independent reviewer role')
    if 'section_review_contract' in request and (request['flow_contract'] != FLOW_V4 or request.get('section_author_contract') != 'memo-section-units-author-v8' or request['section_review_contract'] != 'memo-section-units-review-v7'):
        raise ValueError('Unknown independent section reviewer contract')
    Memo.model_validate(request['memo'])
    for row in request['sources']: Source.model_validate(row)
    for key in ('characterizer_pin','author_pin','reviewer_pin', *(('core_author_pin',) if request['flow_contract']==FLOW_V4 else ()), *(('core_reviewer_pin',) if 'core_reviewer_pin' in request else ())):
        pin = request[key]
        if (not isinstance(pin, dict) or set(pin) != {'name','digest'} or
            not isinstance(pin['digest'], str) or len(pin['digest']) != 64):
            raise ValueError('Source-unit request requires exact local role pins')
        validate_local_model_name(pin['name'])
    return request


def _validate_flow5_request(request):
    from agents.research import diligence_coverage
    flow = request.get('flow_contract')
    historical_coverage = {diligence_coverage.CONTRACT, diligence_coverage.CONTRACT_V2,
                          diligence_coverage.CONTRACT_V3, diligence_coverage.CONTRACT_V4,
                          diligence_coverage.CONTRACT_V5, diligence_coverage.CONTRACT_V6,
                          diligence_coverage.CONTRACT_V7, diligence_coverage.CONTRACT_V8,
                          diligence_coverage.CONTRACT_V9, 'diligence-source-coverage-v10',
                          'diligence-source-coverage-v11'}
    allowed_coverage = ({'diligence-source-coverage-v20'} if flow == FLOW_V12 else
                        {'diligence-source-coverage-v19'} if flow == FLOW_V11 else
                        {'diligence-source-coverage-v18'} if flow == FLOW_V10 else
                        {'diligence-source-coverage-v17'} if flow == FLOW_V9 else
                        {'diligence-source-coverage-v16'} if flow == FLOW_V8 else
                        {'diligence-source-coverage-v15'} if flow == FLOW_V7 else
                        {'diligence-source-coverage-v12', 'diligence-source-coverage-v13', 'diligence-source-coverage-v14'}
                        if flow == FLOW_V6 else historical_coverage)
    allowed_pairs = CORE_PAIRS_V6 if flow in {FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12} else CORE_PAIRS_V5
    keys = {'flow_contract', 'memo', 'sources', 'characterizer_pin', 'author_pin', 'reviewer_pin',
            'author_contract', 'section_author_contract', 'section_review_contract',
            'core_author_pin', 'core_reviewer_pin', 'coverage_pin', 'coverage_contract',
            'coverage_structures', 'coverage_financial_scope', 'digest'}
    if flow == FLOW_V12:
        keys.add('coverage_batching_contract')
        if request.get('coverage_batching_contract') not in {'source-interpretation-pair-v1', 'source-interpretation-pair-v2'}:
            raise ValueError('Separate source tasks require their exact pair contract')
    if flow == FLOW_V11:
        keys.add('coverage_batching_contract')
        if request.get('coverage_batching_contract') not in {'source-interpretation-evidence-first-v2', 'source-interpretation-evidence-first-v3', 'source-interpretation-evidence-first-v4', 'source-interpretation-evidence-first-v5'}:
            raise ValueError('Atomic coverage19 requires its exact versioned batching contract')
    if 'coverage_role' in request:
        keys.add('coverage_role')
    independent_adjudicator = request.get('coverage_contract') in {'diligence-source-coverage-v14', 'diligence-source-coverage-v15', 'diligence-source-coverage-v16', 'diligence-source-coverage-v17', 'diligence-source-coverage-v18', 'diligence-source-coverage-v19', 'diligence-source-coverage-v20'}
    if independent_adjudicator:
        keys.update({'coverage_adjudicator_pin', 'coverage_adjudicator_role'})
    if (set(request) != keys or flow not in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12}
            or request.get('digest') != digest({k: v for k, v in request.items() if k != 'digest'})
            or request.get('author_contract') != 'memo-source-unit-author-v7'
            or (request.get('section_author_contract'), request.get('section_review_contract')) not in allowed_pairs
            or request.get('coverage_contract') not in allowed_coverage):
        raise ValueError('All-source coverage flow requires its exact frozen v5/v7/v9/v8 contracts')
    Memo.model_validate(request['memo'])
    for row in request['sources']:
        Source.model_validate(row)
    for key in ('characterizer_pin', 'author_pin', 'reviewer_pin', 'core_author_pin', 'core_reviewer_pin', 'coverage_pin',
                *(('coverage_adjudicator_pin',) if independent_adjudicator else ())):
        pin = request[key]
        if (not isinstance(pin, dict) or set(pin) != {'name', 'digest'}
                or not isinstance(pin['digest'], str) or len(pin['digest']) != 64):
            raise ValueError('All-source coverage requires exact local role pins')
        validate_local_model_name(pin['name'])
    if 'coverage_role' in request and (not isinstance(request['coverage_role'], str)
            or not request['coverage_role'] or len(request['coverage_role']) > 64):
        raise ValueError('All-source coverage requires an explicit frozen local profile role')
    if independent_adjudicator and (not isinstance(request['coverage_adjudicator_role'], str)
            or not request['coverage_adjudicator_role'] or len(request['coverage_adjudicator_role']) > 64):
        raise ValueError('Independent coverage adjudication requires its frozen local role')
    diligence_coverage.frozen_coverage_requests(request['sources'], request['coverage_pin'],
                                               structures=request['coverage_structures'],
                                               financial_scope=request['coverage_financial_scope'], contract=request['coverage_contract'],
                                               **_adjudicator_kwargs(request))


def _adjudicator_kwargs(request):
    return ({'adjudicator_pin': request['coverage_adjudicator_pin'],
             **({'interpretation_contract': request['coverage_batching_contract']}
                if request.get('coverage_contract') in {'diligence-source-coverage-v19', 'diligence-source-coverage-v20'} else {})}
            if request.get('coverage_contract') in {'diligence-source-coverage-v14', 'diligence-source-coverage-v15', 'diligence-source-coverage-v16', 'diligence-source-coverage-v17', 'diligence-source-coverage-v18', 'diligence-source-coverage-v19', 'diligence-source-coverage-v20'} else {})


def _coverage_bundle(request, attempts):
    return {'model_pin': request['coverage_pin'],
            'attempts': attempts['diligence_coverage_attempts'],
            'structures': request['coverage_structures'],
            'financial_scope': request['coverage_financial_scope'],
            **_adjudicator_kwargs(request),
            **({'contract': request['coverage_contract']} if request['coverage_contract'] != 'diligence-source-coverage-v1' else {})}


def _coverage_result(request, attempts):
    from agents.research.diligence_coverage import evaluate_coverage
    return evaluate_coverage(request['sources'], request['coverage_pin'],
                             attempts['diligence_coverage_attempts'],
                             structures=request['coverage_structures'],
                             financial_scope=request['coverage_financial_scope'], contract=request['coverage_contract'],
                             **_adjudicator_kwargs(request))


def _selected(request):
    contract = {'version': SCOPE_CONTRACT, 'model_name': request['characterizer_pin']['name'],
                'model_digest': request['characterizer_pin']['digest']}
    calls = frozen_calls(request['memo'], request['sources'], contract)
    ids = {sid for _, payload, _ in calls for sid in payload['selected_source_ids']}
    return [Source.model_validate(s) for s in request['sources'] if s['id'] in ids]


def load_source_unit_revision(root):
    root = Path(root)
    request = _request(root)
    return {'contract': request['flow_contract'], 'request_digest': request['digest'],
            'base_memo_digest': digest(request['memo']), 'source_set_digest': digest(request['sources']),
            **({k:request[k] for k in ('author_contract','section_author_contract','core_author_pin','core_reviewer_pin','section_review_contract',
                                    'coverage_contract', 'coverage_pin', 'coverage_structures', 'coverage_financial_scope', 'coverage_role',
                                    'coverage_adjudicator_pin', 'coverage_adjudicator_role', 'coverage_batching_contract') if k in request}),
            **{k:request[k] for k in ('characterizer_pin','author_pin','reviewer_pin')},
            **{k:_load(root,filename,[]) for k,filename in files_for(request['flow_contract']).items()}}


def _proof(request, rows):
    result = evidence.characterize_sources(_selected(request), request['characterizer_pin'],
        rows, lambda: None, None, EMPTY_BUDGET)
    if result['state'] != 'accepted' or result['contract'] != evidence.CONTRACT:
        raise ValueError('Source-unit flow requires complete current blind source proof')
    return {'attempts':rows, 'result':result}


def _gate(request, proof, authored, reviewed):
    if reviewed['state'] != 'accepted': raise ValueError('Source-unit final review is not accepted')
    return {'state':'accepted', 'contract':FLOW, 'base_memo_digest':digest(request['memo']),
            'final_memo_digest':digest(authored['memo']),
            'source_response_hash':proof['result']['response_hash'],
            'source_request_digest':proof['result']['request_digest'],
            'author_response_hash':authored['response_hash'],
            'author_request_digest':authored['request_digest'],
            'review_response_hash':reviewed['response_hash'],
            'review_request_digest':reviewed['request_digest'],
            'review':reviewed, 'independent_review':'pending', 'investment_approval':False}


def replay_source_unit_revision(memo, sources, record):
    memo = Memo.model_validate(memo).model_dump(mode='json')
    sources = [Source.model_validate(s).model_dump(mode='json') for s in sources]
    flow = record.get('contract')
    phases_for(flow)
    if flow in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12}:
        return _replay_flow5(memo, sources, record)
    keys = RECORD_KEYS | (set(CORE_FILES) if flow in {FLOW_V2,FLOW_V3,FLOW_V4} else set())
    if set(record) not in (keys, keys | {'author_contract'}, keys | {'author_contract','section_author_contract'}, keys | {'author_contract','section_author_contract','core_author_pin'}, keys | {'author_contract','section_author_contract','core_author_pin','core_reviewer_pin'}, keys | {'author_contract','section_author_contract','core_author_pin','core_reviewer_pin','section_review_contract'}):
        raise ValueError('Unknown source-unit revision contract')
    if (flow in {FLOW_V2,FLOW_V3,FLOW_V4}) != (record.get('author_contract') == 'memo-source-unit-author-v7'):
        raise ValueError('Full memo flow requires exact v7 author')
    request = {'flow_contract':flow, 'memo':memo, 'sources':sources,
               **({k:record[k] for k in ('author_contract','section_author_contract','core_author_pin','core_reviewer_pin','section_review_contract') if k in record}),
               **{k:record[k] for k in ('characterizer_pin','author_pin','reviewer_pin')}}
    if (record['base_memo_digest'] != digest(memo) or record['source_set_digest'] != digest(sources) or
        record['request_digest'] != digest(request)):
        raise ValueError('Source-unit revision does not bind its original inputs')
    if 'section_author_contract' in record and (flow not in {FLOW_V3,FLOW_V4} or record['section_author_contract'] not in {'memo-section-units-author-v2','memo-section-units-author-v3','memo-section-units-author-v4','memo-section-units-author-v5','memo-section-units-author-v6','memo-section-units-author-v7','memo-section-units-author-v8'}):
        raise ValueError('Unknown full memo section author contract')
    if flow == FLOW_V4 and ('core_author_pin' not in record or record.get('section_author_contract') not in {'memo-section-units-author-v3','memo-section-units-author-v4','memo-section-units-author-v5','memo-section-units-author-v6','memo-section-units-author-v7','memo-section-units-author-v8'}):
        raise ValueError('Independent core author role is missing')
    if flow != FLOW_V4 and ('core_author_pin' in record or record.get('section_author_contract') in {'memo-section-units-author-v4','memo-section-units-author-v5','memo-section-units-author-v6','memo-section-units-author-v7','memo-section-units-author-v8'}):
        raise ValueError('Core role/bounded writer cannot downgrade flow')
    if (record.get('section_author_contract') in {'memo-section-units-author-v7','memo-section-units-author-v8'}) != ('core_reviewer_pin' in record):
        raise ValueError('Structured core revision requires its exact independent reviewer role')
    if 'section_review_contract' in record and (flow != FLOW_V4 or record.get('section_author_contract') != 'memo-section-units-author-v8' or record['section_review_contract'] != 'memo-section-units-review-v7'):
        raise ValueError('Unknown independent section reviewer contract')
    proof = _proof(request, record['source_characterization_attempts'])
    authored = author_engine.run_author(memo,sources,proof,request['author_pin'],
        record['source_unit_author_attempts'], lambda:None,None,EMPTY_BUDGET,
        contract=request.get('author_contract', 'memo-source-unit-author-v1'))
    if authored['state'] != 'accepted': raise ValueError('Source-unit author is incomplete')
    reviewed = review_engine.run_review(memo,sources,proof,authored,request['author_pin'],
        request['reviewer_pin'],record['source_unit_review_attempts'],lambda:None,None,EMPTY_BUDGET)
    gate = _gate(request,proof,authored,reviewed)
    if flow == FLOW:
        return authored['memo'], gate
    from agents.research import memo_section_units, memo_section_review
    core_pin = request.get('core_author_pin', request['author_pin'])
    core = memo_section_units.run_author(authored['memo'],sources,core_pin,
        record['memo_section_author_attempts'],lambda:None,None,EMPTY_BUDGET,
        contract=request.get('section_author_contract','memo-section-units-author-v1'))
    if core['state'] != 'accepted': raise ValueError('Core memo author is incomplete')
    core_review = memo_section_review.run_review(authored['memo'],sources,core,core_pin,
        request.get('core_reviewer_pin',request['reviewer_pin']),record['memo_section_review_attempts'],lambda:None,None,EMPTY_BUDGET,
        **({'contract':request['section_review_contract']} if 'section_review_contract' in request else {}))
    return core['memo'], _full_gate(gate, core, core_review, flow=flow, core_pin=core_pin if flow==FLOW_V4 else None, core_reviewer_pin=request.get('core_reviewer_pin'), section_review_contract=request.get('section_review_contract'))


def _full_gate(source_gate, core, review, *, flow=FLOW_V2, core_pin=None, core_reviewer_pin=None, section_review_contract=None):
    from agents.research.memo_section_units import FIELDS
    if review['state'] != 'accepted' or review.get('coverage') != list(FIELDS):
        raise ValueError('Full memo review requires all five core fields')
    if flow in {FLOW_V4,FLOW_V5,FLOW_V6,FLOW_V7,FLOW_V8,FLOW_V9,FLOW_V10, FLOW_V11, FLOW_V12} and core_pin is None: raise ValueError('Final gate requires exact core author role')
    if core.get('contract') in {'memo-section-units-author-v7','memo-section-units-author-v8','memo-section-units-author-v9', 'memo-section-units-author-v10', 'memo-section-units-author-v11', 'memo-section-units-author-v12', 'memo-section-units-author-v13'} and core_reviewer_pin is None:
        raise ValueError('Final gate requires exact independent core reviewer role')
    if section_review_contract is not None and review.get('contract') != section_review_contract:
        raise ValueError('Final gate requires exact section reviewer contract')
    return {**source_gate, **({'section_review_contract':section_review_contract} if section_review_contract is not None else {}), **({'core_reviewer_pin':core_reviewer_pin} if core.get('contract') in {'memo-section-units-author-v7','memo-section-units-author-v8','memo-section-units-author-v9', 'memo-section-units-author-v10', 'memo-section-units-author-v11', 'memo-section-units-author-v12', 'memo-section-units-author-v13'} else {}), **({'core_author_pin':core_pin} if flow in {FLOW_V4,FLOW_V5,FLOW_V6,FLOW_V7,FLOW_V8,FLOW_V9,FLOW_V10, FLOW_V11, FLOW_V12} else {}), 'contract':flow, 'final_memo_digest':digest(core['memo']),
        'coverage':['recommendation_reason','unknowns', *FIELDS],
        **({'section_author_contract':core['contract']} if core.get('contract') in {'memo-section-units-author-v2','memo-section-units-author-v3','memo-section-units-author-v4','memo-section-units-author-v5','memo-section-units-author-v6','memo-section-units-author-v7','memo-section-units-author-v8','memo-section-units-author-v9', 'memo-section-units-author-v10', 'memo-section-units-author-v11', 'memo-section-units-author-v12', 'memo-section-units-author-v13'} else {}),
        'section_author_response_hash':core['response_hash'],
        'section_author_request_digest':core['request_digest'],
        'section_review_response_hash':review['response_hash'],
        'section_review_request_digest':review['request_digest'], 'section_review':review}


def _flow5_final_gate(request, source_gate, core, review, coverage):
    allowed_split = ({'diligence-source-coverage-v20'} if request['flow_contract'] == FLOW_V12
                     else {'diligence-source-coverage-v19'} if request['flow_contract'] == FLOW_V11
                     else {'diligence-source-coverage-v18'} if request['flow_contract'] == FLOW_V10
                     else {'diligence-source-coverage-v17'} if request['flow_contract'] == FLOW_V9
                     else {'diligence-source-coverage-v16'} if request['flow_contract'] == FLOW_V8
                     else {'diligence-source-coverage-v15'} if request['flow_contract'] == FLOW_V7
                     else {'diligence-source-coverage-v12', 'diligence-source-coverage-v13', 'diligence-source-coverage-v14'})
    if request['flow_contract'] in {FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12} and (
            (core.get('contract'), review.get('contract')) not in CORE_PAIRS_V6
            or request['coverage_contract'] not in allowed_split
            or coverage.get('contract') != request['coverage_contract']):
        raise ValueError('Split adjudication gate requires exact coverage12/13/14/15/16/17/18/core13/reviewer12 contracts')
    if request['coverage_contract'] in {'diligence-source-coverage-v14', 'diligence-source-coverage-v15', 'diligence-source-coverage-v16', 'diligence-source-coverage-v17', 'diligence-source-coverage-v18', 'diligence-source-coverage-v19', 'diligence-source-coverage-v20'} and (
            coverage.get('adjudicator_pin') != request['coverage_adjudicator_pin']
            or core.get('coverage_binding', {}).get('adjudicator_pin') != request['coverage_adjudicator_pin']):
        raise ValueError('Split adjudication gate changed its exact adjudicator model pin')
    if (coverage.get('state') != 'accepted' or coverage.get('coverage_complete') is not True
            or (core.get('contract'), review.get('contract')) not in CORE_PAIRS_V5
            or core.get('contract') != request['section_author_contract']
            or review.get('contract') != request['section_review_contract']):
        raise ValueError('All-source core gate requires complete exact coverage and clarity review')
    gate = _full_gate(source_gate, core, review, flow=request['flow_contract'],
                      core_pin=request['core_author_pin'], core_reviewer_pin=request['core_reviewer_pin'],
                      section_review_contract=request['section_review_contract'])
    return {**gate, 'coverage_contract': request['coverage_contract'], 'coverage_pin': request['coverage_pin'],
            **({'coverage_batching_contract': request['coverage_batching_contract']} if request['flow_contract'] in {FLOW_V11, FLOW_V12} else {}),
            **({key: request[key] for key in ('coverage_adjudicator_pin', 'coverage_adjudicator_role')}
               if 'coverage_adjudicator_pin' in request else {}),
            **({'coverage_role': request['coverage_role']} if 'coverage_role' in request else {}),
            'coverage_binding': core['coverage_binding'], 'diligence_coverage': coverage,
            'coverage_scope': 'five_core_sections',
            'recommendation_and_unknown_source_scope': 'legacy_frozen_source_scope',
            'financial_validation': 'not_established', 'investment_approval': False}


def _replay_flow5(memo, sources, record):
    extras = {'author_contract', 'section_author_contract', 'section_review_contract', 'core_author_pin',
              'core_reviewer_pin', 'coverage_contract', 'coverage_pin', 'coverage_structures', 'coverage_financial_scope'}
    if record.get('contract') in {FLOW_V11, FLOW_V12}:
        extras.add('coverage_batching_contract')
    if 'coverage_role' in record:
        extras.add('coverage_role')
    if record.get('coverage_contract') in {'diligence-source-coverage-v14', 'diligence-source-coverage-v15', 'diligence-source-coverage-v16', 'diligence-source-coverage-v17', 'diligence-source-coverage-v18', 'diligence-source-coverage-v19', 'diligence-source-coverage-v20'}:
        extras.update({'coverage_adjudicator_pin', 'coverage_adjudicator_role'})
    if set(record) != RECORD_KEYS | set(CORE_FILES) | set(COVERAGE_FILES) | extras:
        raise ValueError('Unknown all-source revision contract')
    request = {'flow_contract': record['contract'], 'memo': memo, 'sources': sources,
               **{key: record[key] for key in extras | {'characterizer_pin', 'author_pin', 'reviewer_pin'}}}
    request['digest'] = digest(request)
    _validate_flow5_request(request)
    if (record['request_digest'] != request['digest'] or record['base_memo_digest'] != digest(memo)
            or record['source_set_digest'] != digest(sources)):
        raise ValueError('All-source revision does not bind its original inputs')
    coverage = _coverage_result(request, record)
    if coverage['state'] != 'accepted':
        raise ValueError('All-source revision coverage is incomplete or changed')
    proof = _proof(request, record['source_characterization_attempts'])
    authored = author_engine.run_author(memo, sources, proof, request['author_pin'],
        record['source_unit_author_attempts'], lambda: None, None, EMPTY_BUDGET, contract=request['author_contract'])
    if authored['state'] != 'accepted':
        raise ValueError('Legacy recommendation and unknown author is incomplete')
    reviewed = review_engine.run_review(memo, sources, proof, authored, request['author_pin'], request['reviewer_pin'],
                                        record['source_unit_review_attempts'], lambda: None, None, EMPTY_BUDGET)
    source_gate = _gate(request, proof, authored, reviewed)
    from agents.research import memo_section_units, memo_section_review
    bundle = _coverage_bundle(request, record)
    core = memo_section_units.run_author(authored['memo'], sources, request['core_author_pin'],
        record['memo_section_author_attempts'], lambda: None, None, EMPTY_BUDGET,
        contract=request['section_author_contract'], coverage=bundle)
    if core['state'] != 'accepted':
        raise ValueError('All-source core memo author is incomplete')
    core_review = memo_section_review.run_review(authored['memo'], sources, core, request['core_author_pin'],
        request['core_reviewer_pin'], record['memo_section_review_attempts'], lambda: None, None, EMPTY_BUDGET,
        contract=request['section_review_contract'], coverage=bundle)
    return core['memo'], _flow5_final_gate(request, source_gate, core, core_review, coverage)


def advance(root, phase, budget, *, models=None):
    request = _request(root)
    phases = phases_for(request['flow_contract'])
    files = files_for(request['flow_contract'])
    if phase not in phases: raise ValueError('Unknown source-unit phase')
    attempts = {k:_load(root,filename,[]) for k,filename in files.items()}
    models = models or {}
    if request['flow_contract'] in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12}:
        return _advance_flow5(root, request, phase, budget, attempts, models)
    if request['flow_contract'] in {FLOW_V3,FLOW_V4}:
        return _advance_checkpointed(root,request,phase,budget,attempts,models)
    def save(key): return lambda: _write(root,files[key],attempts[key])
    def model(key, options): return models.get(key) or LocalModel(request[key]['name'],**options)
    try:
        if phase == PHASES[0]:
            if any(attempts[k] for k in files if k != 'source_characterization_attempts'):
                raise ValueError('Source-unit phases cannot move backwards')
            result = evidence.characterize_sources(_selected(request), request['characterizer_pin'],
                attempts['source_characterization_attempts'],save('source_characterization_attempts'),
                model('characterizer_pin',evidence.OPTIONS),budget)
            if result['state'] == 'accepted':
                return {'state':'needs_resume','reason':'source_characterization_complete',
                        'next_phase':PHASES[1]}
            return {**result,'next_phase':phase}
        proof = _proof(request,attempts['source_characterization_attempts'])
        if phase == PHASES[1]:
            if any(attempts[k] for k in files if k not in {'source_characterization_attempts','source_unit_author_attempts'}):
                raise ValueError('Authorship cannot continue after final review')
            result = author_engine.run_author(request['memo'],request['sources'],proof,request['author_pin'],
                attempts['source_unit_author_attempts'],save('source_unit_author_attempts'),
                model('author_pin', author_engine.OPTIONS_V2 if request.get('author_contract') in
                      {'memo-source-unit-author-v2', 'memo-source-unit-author-v3', 'memo-source-unit-author-v4', 'memo-source-unit-author-v5', 'memo-source-unit-author-v6', 'memo-source-unit-author-v7'} else author_engine.OPTIONS),budget,
                contract=request.get('author_contract', 'memo-source-unit-author-v1'))
            if result['state'] == 'accepted':
                return {'state':'needs_resume','reason':'source_unit_author_complete', 'next_phase':PHASES[2]}
            return {**result,'next_phase':phase}
        authored = author_engine.run_author(request['memo'],request['sources'],proof,request['author_pin'],
            attempts['source_unit_author_attempts'],lambda:None,None,EMPTY_BUDGET,
            contract=request.get('author_contract', 'memo-source-unit-author-v1'))
        if authored['state'] != 'accepted': raise ValueError('Final review requires complete authored units')
        if (phase == PHASES[2] and request['flow_contract'] in {FLOW_V2,FLOW_V3,FLOW_V4} and
                any(attempts[key] for key in CORE_FILES)):
            raise ValueError('Core phases cannot move backwards')
        if authored.get('contract') in {'memo-source-unit-author-v3', 'memo-source-unit-author-v4', 'memo-source-unit-author-v5', 'memo-source-unit-author-v6', 'memo-source-unit-author-v7'}:
            from agents.research.memo_source_unit_review_v3 import OPTIONS as review_options
        else:
            review_options = review_engine.OPTIONS_V2 if authored.get('contract') == 'memo-source-unit-author-v2' else review_engine.OPTIONS
        result = review_engine.run_review(request['memo'],request['sources'],proof,authored,request['author_pin'],
            request['reviewer_pin'],attempts['source_unit_review_attempts'],
            save('source_unit_review_attempts') if phase == PHASES[2] else lambda:None,
            model('reviewer_pin',review_options) if phase == PHASES[2] else None,
            budget if phase == PHASES[2] else EMPTY_BUDGET)
        if result['state'] == 'accepted':
            gate = _gate(request,proof,authored,result)
            if request['flow_contract'] == FLOW:
                return {'state':'accepted','final_memo_digest':gate['final_memo_digest'],'content_review':gate}
            if phase == PHASES[2]:
                return {'state':'needs_resume','reason':'source_unit_review_complete','next_phase':PHASES_V2[3]}
            from agents.research import memo_section_units, memo_section_review
            if phase == PHASES_V2[3] and attempts['memo_section_review_attempts']:
                raise ValueError('Core author cannot continue after review')
            core = memo_section_units.run_author(authored['memo'],request['sources'],request['author_pin'],
                attempts['memo_section_author_attempts'],save('memo_section_author_attempts') if phase == PHASES_V2[3] else lambda:None,
                model('author_pin',memo_section_units.OPTIONS) if phase == PHASES_V2[3] else None,
                budget if phase == PHASES_V2[3] else EMPTY_BUDGET)
            if core['state'] != 'accepted': return {**core,'next_phase':phase}
            if phase == PHASES_V2[3]:
                return {'state':'needs_resume','reason':'memo_section_author_complete','next_phase':PHASES_V2[4]}
            core_review = memo_section_review.run_review(authored['memo'],request['sources'],core,
                request['author_pin'],request['reviewer_pin'],attempts['memo_section_review_attempts'],
                save('memo_section_review_attempts'),model('core_reviewer_pin' if 'core_reviewer_pin' in request else 'reviewer_pin',memo_section_review.options_for(request.get('section_author_contract','memo-section-units-author-v1'))),budget,
                    **({'contract':request['section_review_contract']} if 'section_review_contract' in request else {}))
            if core_review['state'] != 'accepted': return {**core_review,'next_phase':phase}
            gate = _full_gate(gate,core,core_review)
            return {'state':'accepted','final_memo_digest':gate['final_memo_digest'],'content_review':gate}
        return {**result,'next_phase':phase}
    except PreparationBudgetExceeded:
        return {'state':'blocked','reason':'source_unit_phase_time_limit','phase':phase}
    except (ValueError,RuntimeError) as exc:
        return {'state':'blocked','reason':'source_unit_phase_failed','phase':phase,'detail':str(exc)[:500]}


def main():
    root = Path.cwd()
    limits = _load(root,'content_budget.json')
    if (type(limits['max_calls']) is not int or not 1 <= limits['max_calls'] <= 6 or
        not isinstance(limits['seconds'],(int,float)) or not 0 < limits['seconds'] <= 105):
        raise ValueError('Source-unit pass exceeds its fixed limits')
    previous = _load(root,'content_result.json',{})
    if previous.get('state') in {'accepted','blocked'}:
        return  # Terminal records never start another inference.
    request = _load(root, 'content_request.json', {})
    fresh = request.get('flow_contract') in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12}
    coverage_phases = (COVERAGE_PHASES_V12 if request.get('flow_contract') == FLOW_V12 else
                       COVERAGE_PHASES_V10 if request.get('flow_contract') in {FLOW_V10, FLOW_V11, FLOW_V12} else
                       COVERAGE_PHASES_V7 if request.get('flow_contract') in {FLOW_V7, FLOW_V8, FLOW_V9} else
                       COVERAGE_PHASES_V6 if request.get('flow_contract') == FLOW_V6 else COVERAGE_PHASES_V5)
    phase = previous.get('next_phase',coverage_phases[0] if fresh else PHASES[0])
    budget = PreparationBudget(limits['seconds'],max_calls=limits['max_calls'],max_requests=limits['max_calls'])
    with preparation_budget(budget):
        # Coverage is one recorded judgment per checkpoint. Core engines already
        # enforce their shared six-record cap and sole validation correction;
        # that correction must finish inside this same bounded checkpoint.
        single_call = fresh and phase in coverage_phases
        for _ in range(1 if single_call else budget.max_calls):
            before = budget.calls
            result = advance(root,phase,budget)
            if (result['state'] != 'needs_resume' or result.get('next_phase') != phase or
                budget.calls == before or budget.calls >= budget.max_calls): break
        if (fresh and phase.startswith('memo_section_') and result['state'] == 'needs_resume'
                and result.get('next_phase') == phase):
            if budget.calls >= budget.max_calls:
                reason = 'source_unit_phase_call_limit'
            else:
                try:
                    reason = ('source_unit_phase_time_limit' if budget.remaining() < 18
                              else 'source_unit_phase_incomplete')
                except PreparationBudgetExceeded:
                    reason = 'source_unit_phase_time_limit'
            result = {**result, 'state': 'blocked', 'reason': reason, 'phase': phase}
    _write(root,'content_result.json',result)


# Generic receipt-order guard authored by Claude Code from synthetic coding context.
def should_call_shard(shards, target_batch_id, completed_batch_ids, pending_batch_id):
    """Pure ordering guard. True only for the exact pending nonempty shard."""
    if not isinstance(shards, (list, tuple)) or len(shards) != 5:
        raise ValueError("inventory must contain exactly five shards")
    order, nonempty, seen_sources = [], [], set()
    for shard in shards:
        if not isinstance(shard, dict):
            raise ValueError("shard must be a dict")
        bid, srcs = shard.get("batch_id"), shard.get("source_ids")
        if not isinstance(bid, str) or not bid or bid in order:
            raise ValueError("invalid or duplicate batch_id")
        if not isinstance(srcs, list) or len(srcs) > 5:
            raise ValueError("source_ids must be a list of at most five")
        for sid in srcs:
            if not isinstance(sid, str) or not sid or sid in seen_sources:
                raise ValueError("invalid or duplicate source id")
            seen_sources.add(sid)
        order.append(bid)
        if srcs:
            nonempty.append(bid)
    if not isinstance(completed_batch_ids, (list, tuple)):
        raise ValueError("receipts must be an ordered sequence")
    done = list(completed_batch_ids)
    # Rejects unknown, reordered, duplicated, and empty-checkpoint receipts.
    if done != nonempty[: len(done)]:
        raise ValueError("receipts must be an ordered prefix of nonempty shards")
    expected = nonempty[len(done)] if len(done) < len(nonempty) else None
    if pending_batch_id != expected:
        raise ValueError("pending batch identity mismatch")
    if not isinstance(target_batch_id, str) or target_batch_id not in order:
        raise ValueError("unknown target checkpoint")
    idx = order.index(target_batch_id)
    if any(b not in done for b in nonempty if order.index(b) < idx):
        raise ValueError("prior nonempty checkpoint lacks a receipt")
    if target_batch_id not in nonempty:
        return False  # empty checkpoint: no call, no fabricated receipt
    if target_batch_id in done:
        return False  # cached replay
    return target_batch_id == pending_batch_id





def _advance_flow10(root, request, phase, budget, attempts, models):
    """Fresh blind source assessment: no classifier baseline or response reuse."""
    from agents.research import diligence_coverage
    phases = phases_for(request['flow_contract'])
    index = phases.index(phase)
    def status(result):
        coverage = _coverage_result(request, attempts)
        _write(root, 'diligence_coverage_result.json', coverage)
        return {**result, 'diligence_coverage': coverage}
    try:
        coverage = _coverage_result(request, attempts)
        if coverage['state'] == 'blocked':
            return status({'state': 'blocked', 'reason': coverage['reason'], 'next_phase': phase})
        if phase not in COVERAGE_PHASES_V10:
            if coverage['state'] != 'accepted':
                raise ValueError('Core/source phases require complete fresh blind source assessment and selection')
            return status(_advance_checkpointed(root, request, phase, budget, attempts, models))
        if any(attempts[key] for key in CORE_FILES):
            raise ValueError('Blind coverage cannot move backwards after core authorship')
        rows = attempts['diligence_coverage_attempts']
        pending = diligence_coverage.pending_coverage_request(request['sources'], request['coverage_pin'], rows,
            structures=request['coverage_structures'], financial_scope=request['coverage_financial_scope'],
            contract=request['coverage_contract'], **_adjudicator_kwargs(request))
        stage = 'field_source_selection' if phase == 'diligence_field_selection' else 'source_adjudication'
        inventory = diligence_coverage.frozen_adjudication_shards(request['sources'])
        completed = [row['input']['batch_id'] for row in rows
                     if row['input'].get('stage') == 'source_adjudication']
        pending_batch = (pending[2]['batch_id'] if pending is not None
                         and pending[2].get('stage') == 'source_adjudication' else None)
        empty_shard = False
        if stage == 'source_adjudication':
            target = phase.removeprefix('diligence_')
            should_call = should_call_shard(inventory, target, completed, pending_batch)
            empty_shard = not next(item['source_ids'] for item in inventory if item['batch_id'] == target)
            expected = pending if should_call else None
        else:
            if completed != [item['batch_id'] for item in inventory if item['source_ids']]:
                raise ValueError('Blind field selection skipped required source assessments')
            expected = pending if pending is not None and pending[2].get('stage') == stage else None
        if expected is not None:
            if len(rows) >= 6:
                raise ValueError('Blind source coverage exhausted its six recorded-call cap')
            options = diligence_coverage.options_for(request['coverage_contract'], stage)
            task, instruction, payload, schema = expected
            role_key = 'coverage_adjudicator_pin' if stage == 'source_adjudication' else 'coverage_pin'
            if payload.get('model_pin') != request[role_key]:
                raise ValueError('Blind source checkpoint differs from its frozen stage role')
            role = models.get(role_key) or LocalModel(request[role_key]['name'], **options)
            try:
                recorded_call(role, task, instruction, payload, schema, rows,
                    lambda: _write(root, COVERAGE_FILES['diligence_coverage_attempts'], rows))
            except Exception as exc:
                return status({'state': 'blocked', 'reason': 'diligence_coverage_inference_failed',
                               'next_phase': phase, 'detail': str(exc)[:500]})
        after = _coverage_result(request, attempts)
        if after['state'] == 'blocked':
            return status({'state': 'blocked', 'reason': after['reason'], 'next_phase': phase})
        if stage == 'field_source_selection' and after['state'] != 'accepted':
            raise ValueError('Fresh blind field selection is incomplete')
        if stage == 'source_adjudication' and not empty_shard and target not in [
                row['input'].get('batch_id') for row in rows if row['input'].get('stage') == stage]:
            raise ValueError('Fresh blind source shard is incomplete')
        return status({'state': 'needs_resume', 'reason':
            'diligence_field_selection_complete' if stage == 'field_source_selection' else
            'diligence_source_adjudication_empty' if empty_shard else 'diligence_source_adjudication_complete',
            'next_phase': phases[index + 1]})
    except PreparationBudgetExceeded:
        return status({'state': 'blocked', 'reason': 'blind_source_checkpoint_budget_exhausted', 'next_phase': phase})
    except Exception as exc:
        return status({'state': 'blocked', 'reason': str(exc), 'next_phase': phase})

def _advance_flow11(root, request, phase, budget, attempts, models):
    """One durable stage: at most five unread unique-source calls, one budget."""
    from agents.research import diligence_coverage
    phases = phases_for(request['flow_contract'])
    index = phases.index(phase)
    def status(result):
        coverage = _coverage_result(request, attempts)
        _write(root, 'diligence_coverage_result.json', coverage)
        return {**result, 'diligence_coverage': coverage}
    try:
        coverage = _coverage_result(request, attempts)
        if coverage['state'] == 'blocked':
            return status({'state': 'blocked', 'reason': coverage['reason'], 'next_phase': phase})
        if phase not in COVERAGE_PHASES_V11:
            if coverage['state'] != 'accepted':
                raise ValueError('Core/source phases require complete atomic source assessments and selection')
            return status(_advance_checkpointed(root, request, phase, budget, attempts, models))
        if any(attempts[key] for key in CORE_FILES):
            raise ValueError('Atomic coverage cannot move backwards after core authorship')
        rows = attempts['diligence_coverage_attempts']
        inventory = diligence_coverage.frozen_adjudication_shards(request['sources'])
        stage = 'field_source_selection' if phase == 'diligence_field_selection' else 'source_adjudication'
        target = phase.removeprefix('diligence_') if stage == 'source_adjudication' else None
        empty_shard = False
        for call_index in range(5 if stage == 'source_adjudication' else 1):
            coverage = _coverage_result(request, attempts)
            if coverage['state'] == 'blocked':
                return status({'state': 'blocked', 'reason': coverage['reason'], 'next_phase': phase})
            pending = diligence_coverage.pending_coverage_request(request['sources'], request['coverage_pin'], rows,
                structures=request['coverage_structures'], financial_scope=request['coverage_financial_scope'],
                contract=request['coverage_contract'], **_adjudicator_kwargs(request))
            completed = coverage['completed_adjudication_shards']
            if stage == 'source_adjudication':
                pending_batch = pending[2]['batch_id'] if pending is not None and pending[2].get('stage') == stage else None
                should_call = should_call_shard(inventory, target, completed, pending_batch)
                empty_shard = not next(item['source_ids'] for item in inventory if item['batch_id'] == target)
                expected = pending if should_call else None
            else:
                if completed != [item['batch_id'] for item in inventory if item['source_ids']]:
                    raise ValueError('Atomic field selection skipped retained source groups')
                expected = pending if pending is not None and pending[2].get('stage') == stage else None
            if expected is None:
                break
            if len(rows) >= diligence_coverage.MAX_CALLS_V19:
                raise ValueError('Atomic source coverage exhausted twenty-six distinct recorded calls')
            # The same active PreparationBudget charges every request. A partial
            # successful prefix is retained; no failed source gets another call.
            if budget.remaining() <= 0:
                raise PreparationBudgetExceeded('atomic_source_stage_time_limit')
            options = diligence_coverage.options_for(request['coverage_contract'], stage)
            task, instruction, payload, schema = expected
            role_key = 'coverage_adjudicator_pin' if stage == 'source_adjudication' else 'coverage_pin'
            if payload.get('model_pin') != request[role_key]:
                raise ValueError('Atomic source call differs from its frozen independent role')
            role = models.get(role_key) or LocalModel(request[role_key]['name'], **options)
            try:
                recorded_call(role, task, instruction, payload, schema, rows,
                    lambda: _write(root, COVERAGE_FILES['diligence_coverage_attempts'], rows))
            except Exception as exc:
                return status({'state': 'blocked', 'reason': 'diligence_coverage_inference_failed',
                    'next_phase': phase, 'detail': str(exc)[:500]})
        after = _coverage_result(request, attempts)
        if after['state'] == 'blocked':
            return status({'state': 'blocked', 'reason': after['reason'], 'next_phase': phase})
        if stage == 'field_source_selection' and after['state'] != 'accepted':
            raise ValueError('Atomic field selection is incomplete')
        if stage == 'source_adjudication' and not empty_shard and target not in after['completed_adjudication_shards']:
            raise ValueError('Atomic source checkpoint did not complete within its five-call budget')
        return status({'state': 'needs_resume', 'reason':
            'diligence_field_selection_complete' if stage == 'field_source_selection' else
            'diligence_source_adjudication_empty' if empty_shard else 'diligence_source_adjudication_complete',
            'next_phase': phases[index + 1]})
    except PreparationBudgetExceeded:
        return status({'state': 'blocked', 'reason': 'atomic_source_checkpoint_budget_exhausted', 'next_phase': phase})
    except Exception as exc:
        return status({'state': 'blocked', 'reason': str(exc), 'next_phase': phase})


PAIR_INTENT_FILE = 'source_pair_intent.json'


def source_pair_resume_state(root, request, phase):
    """Prove an interruption left committed answers and no unresolved request."""
    if request.get('flow_contract') != FLOW_V12 or phase not in COVERAGE_PHASES_V12:
        return {'state': 'blocked', 'reason': 'source_pair_recovery_not_applicable'}
    rows = _load(Path(root), COVERAGE_FILES['diligence_coverage_attempts'], [])
    intent = _load(Path(root), PAIR_INTENT_FILE, {})
    if (intent.get('source_request_digest') != request['digest'] or intent.get('phase') != phase
            or type(intent.get('record_count_before')) is not int):
        return {'state': 'blocked', 'reason': 'source_pair_recovery_intent_missing_or_changed'}
    position = intent['record_count_before']
    if (not 0 <= position < len(rows) or rows[position].get('error') or
            digest(rows[position].get('input')) != intent.get('request_digest')):
        return {'state': 'blocked', 'reason': 'source_pair_unresolved_inflight_request'}
    attempts = {key: _load(Path(root), filename, []) for key, filename in files_for(FLOW_V12).items()}
    coverage = _coverage_result(request, attempts)
    if coverage['state'] == 'blocked':
        return {'state': 'blocked', 'reason': 'source_pair_failed_response_cannot_retry'}
    matching = [row for row in rows if (row['input'].get('pair_index') ==
        (int(phase.removeprefix('diligence_source_pair_')) if phase != 'diligence_field_selection' else None))
        and (phase != 'diligence_field_selection' or row['input'].get('stage') == 'field_source_selection')]
    if len(matching) > (2 if phase != 'diligence_field_selection' else 1):
        return {'state': 'blocked', 'reason': 'source_pair_recovery_exceeds_distinct_call_bound'}
    return {'state': 'interrupted_between_committed_calls', 'phase': phase,
        'response_prefix_digest': digest(rows), 'committed_call_count': len(matching),
        'cumulative_model_seconds': sum(max(0, row.get('elapsed_seconds', 0)) for row in matching),
        'source_request_digest': request['digest']}


PAIR_RECOVERY_EVENTS = 'source_pair_recovery_events.json'


def record_source_pair_interruption(root, request, phase, elapsed_seconds):
    """Append proof of an interruption; never reopen a failed model response."""
    proof = source_pair_resume_state(root, request, phase)
    if proof['state'] == 'blocked':
        return proof
    limits = _load(Path(root), 'content_budget.json', {})
    allocation = limits.get('seconds')
    if (type(allocation) not in {int, float} or not 0 < allocation <= 105 or
            type(elapsed_seconds) not in {int, float} or elapsed_seconds < 0):
        return {'state': 'blocked', 'reason': 'source_pair_recovery_budget_invalid'}
    remaining = allocation - elapsed_seconds
    if remaining <= 0:
        return {'state': 'blocked', 'reason': 'source_pair_checkpoint_budget_exhausted'}
    events = _load(Path(root), PAIR_RECOVERY_EVENTS, [])
    prior = [event for event in events if event['phase'] == phase]
    event = {**proof, 'event': len(events) + 1, 'allocation_seconds': allocation,
        'elapsed_seconds': elapsed_seconds, 'remaining_seconds': remaining,
        'cumulative_elapsed_seconds': sum(event['elapsed_seconds'] for event in prior) + elapsed_seconds}
    events.append(event)
    _write(Path(root), PAIR_RECOVERY_EVENTS, events)
    return {'state': 'needs_resume', 'reason': 'interrupted_between_committed_calls',
        'next_phase': phase, 'recovery_event_digest': digest(event), 'remaining_seconds': remaining,
        'response_prefix_digest': event['response_prefix_digest']}


def source_pair_recovery_budget(root, request, result):
    """Replay exact interruption evidence before spending only unused time."""
    if result.get('reason') != 'interrupted_between_committed_calls':
        raise ValueError('Source-pair recovery requires its explicit interruption state')
    events = _load(Path(root), PAIR_RECOVERY_EVENTS, [])
    if not events or digest(events[-1]) != result.get('recovery_event_digest'):
        raise ValueError('Source-pair interruption event changed')
    event = events[-1]
    proof = source_pair_resume_state(root, request, event['phase'])
    if proof['state'] == 'blocked' or event['source_request_digest'] != request['digest']:
        raise ValueError('Source-pair interruption prefix no longer replays')
    rows = _load(Path(root), COVERAGE_FILES['diligence_coverage_attempts'], [])
    # Recovery may have committed its second answer before another crash. It
    # must preserve the original exact prefix; no previous event is rewritten.
    prefix_count = next((count for count in range(1, len(rows) + 1)
        if digest(rows[:count]) == event['response_prefix_digest']), None)
    if prefix_count is None or event['remaining_seconds'] != result.get('remaining_seconds'):
        raise ValueError('Source-pair recovery response prefix or allocation changed')
    return event['remaining_seconds']


def _advance_flow12(root, request, phase, budget, attempts, models):
    """One source pair per checkpoint, two genuine calls under one budget."""
    from agents.research import diligence_coverage
    phases = phases_for(FLOW_V12)
    index = phases.index(phase)
    def status(result):
        coverage = _coverage_result(request, attempts)
        _write(root, 'diligence_coverage_result.json', coverage)
        return {**result, 'diligence_coverage': coverage}
    try:
        coverage = _coverage_result(request, attempts)
        if coverage['state'] == 'blocked':
            return status({'state': 'blocked', 'reason': coverage['reason'], 'next_phase': phase})
        if phase not in COVERAGE_PHASES_V12:
            if coverage['state'] != 'accepted':
                raise ValueError('Core phases require all complete source pairs and exact field selection')
            return status(_advance_checkpointed(root, request, phase, budget, attempts, models))
        if any(attempts[key] for key in CORE_FILES):
            raise ValueError('Source pairs cannot move backwards after core authorship')
        rows = attempts['diligence_coverage_attempts']
        previous_intent = _load(root, PAIR_INTENT_FILE, {})
        if previous_intent.get('state') == 'started':
            recovery = source_pair_resume_state(root, request, previous_intent.get('phase'))
            if recovery['state'] == 'blocked':
                return status({'state': 'blocked', 'reason': recovery['reason'], 'next_phase': phase})
        pair_phase = phase != 'diligence_field_selection'
        target = int(phase.removeprefix('diligence_source_pair_')) if pair_phase else None
        pair_count = coverage['unique_source_pair_count']
        empty = bool(pair_phase and target > pair_count)
        for _ in range(2 if pair_phase else 1):
            coverage = _coverage_result(request, attempts)
            if coverage['state'] == 'blocked':
                return status({'state': 'blocked', 'reason': coverage['reason'], 'next_phase': phase})
            completed = coverage['completed_source_pairs']
            required = [f'source_pair_{number}' for number in range(1, min(target or pair_count + 1, pair_count + 1))]
            if not set(required) <= set(completed):
                raise ValueError('Source-pair checkpoint skipped an unread earlier pair')
            pending = diligence_coverage.pending_coverage_request(request['sources'], request['coverage_pin'], rows,
                structures=request['coverage_structures'], financial_scope=request['coverage_financial_scope'],
                contract=request['coverage_contract'], **_adjudicator_kwargs(request))
            if pair_phase:
                if empty or f'source_pair_{target}' in completed:
                    expected = None
                elif pending is not None and pending[2].get('pair_index') == target:
                    expected = pending
                else:
                    raise ValueError('Source-pair checkpoint differs from exact pending original source')
            else:
                if len(completed) != pair_count:
                    raise ValueError('Field selection cannot precede every retained source pair')
                expected = pending if pending is not None and pending[2].get('stage') == 'field_source_selection' else None
            if expected is None:
                break
            if len(rows) >= diligence_coverage.MAX_CALLS_V20:
                raise ValueError('Separate source tasks exhausted fifty-one distinct recorded calls')
            budget.remaining()
            task, instruction, payload, schema = expected
            role_key = 'coverage_adjudicator_pin' if pair_phase else 'coverage_pin'
            if payload.get('model_pin') != request[role_key]:
                raise ValueError('Separate source task differs from its frozen model role')
            role = models.get(role_key) or LocalModel(request[role_key]['name'], **payload['options'])
            intent = {'state': 'started', 'phase': phase, 'source_request_digest': request['digest'],
                'request_digest': digest(payload), 'record_count_before': len(rows)}
            _write(root, PAIR_INTENT_FILE, intent)
            try:
                recorded_call(role, task, instruction, payload, schema, rows,
                    lambda: _write(root, COVERAGE_FILES['diligence_coverage_attempts'], rows))
                _write(root, PAIR_INTENT_FILE, {**intent, 'state': 'recorded',
                    'response_id': rows[-1]['id'], 'response_hash': rows[-1]['response_hash']})
            except Exception as exc:
                return status({'state': 'blocked', 'reason': 'diligence_coverage_inference_failed',
                    'next_phase': phase, 'detail': str(exc)[:500]})
        after = _coverage_result(request, attempts)
        if after['state'] == 'blocked':
            return status({'state': 'blocked', 'reason': after['reason'], 'next_phase': phase})
        if pair_phase and not empty and f'source_pair_{target}' not in after['completed_source_pairs']:
            raise ValueError('Source pair did not complete in its bounded two-call checkpoint')
        if not pair_phase and after['state'] != 'accepted':
            raise ValueError('Source-pair field selection is incomplete')
        return status({'state': 'needs_resume', 'reason': 'diligence_source_pair_empty' if empty else
            'diligence_source_pair_complete' if pair_phase else 'diligence_field_selection_complete',
            'next_phase': phases[index + 1]})
    except PreparationBudgetExceeded:
        return status({'state': 'blocked', 'reason': 'source_pair_checkpoint_budget_exhausted', 'next_phase': phase})
    except Exception as exc:
        return status({'state': 'blocked', 'reason': str(exc), 'next_phase': phase})


def _advance_flow5(root, request, phase, budget, attempts, models):
    if request['flow_contract'] == FLOW_V12:
        return _advance_flow12(root, request, phase, budget, attempts, models)
    if request['flow_contract'] == FLOW_V11:
        return _advance_flow11(root, request, phase, budget, attempts, models)
    if request['flow_contract'] == FLOW_V10:
        return _advance_flow10(root, request, phase, budget, attempts, models)
    from agents.research import diligence_coverage
    phases = phases_for(request['flow_contract'])
    sharded = request['flow_contract'] in {FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12}
    split = request['flow_contract'] in {FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12}
    coverage_phases = COVERAGE_PHASES_V7 if sharded else COVERAGE_PHASES_V6 if split else COVERAGE_PHASES_V5
    index = phases.index(phase)
    def status(result):
        coverage = _coverage_result(request, attempts)
        _write(root, 'diligence_coverage_result.json', coverage)
        return {**result, 'diligence_coverage': coverage}
    try:
        coverage = _coverage_result(request, attempts)
        if coverage['state'] == 'blocked':
            return status({'state': 'blocked', 'reason': coverage['reason'], 'next_phase': phase})
        if phase in coverage_phases:
            if any(attempts[key] for key in CORE_FILES):
                raise ValueError('All-source coverage cannot move backwards after core authorship')
            requests = diligence_coverage.frozen_coverage_requests(request['sources'], request['coverage_pin'],
                structures=request['coverage_structures'], financial_scope=request['coverage_financial_scope'], contract=request['coverage_contract'],
                **_adjudicator_kwargs(request))
            rows = attempts['diligence_coverage_attempts']
            required_before = (len(requests) if sharded and index >= 5 else len(requests) + 1 if split and phase == 'diligence_field_selection'
                               else min(index, len(requests)))
            if len(rows) < required_before:
                raise ValueError('Coverage checkpoint skipped unassessed retained sources')
            pending = diligence_coverage.pending_coverage_request(request['sources'], request['coverage_pin'], rows,
                structures=request['coverage_structures'], financial_scope=request['coverage_financial_scope'], contract=request['coverage_contract'],
                **_adjudicator_kwargs(request))
            stage = ('source_adjudication' if phase.startswith('diligence_source_adjudication')
                     else 'field_source_selection' if phase == 'diligence_field_selection' else 'classification')
            empty_shard = False
            if sharded and stage == 'source_adjudication':
                inventory = diligence_coverage.frozen_adjudication_shards(request['sources'])
                target = phase.removeprefix('diligence_')
                completed = [row['input']['batch_id'] for row in rows
                             if row['input'].get('stage') == 'source_adjudication']
                pending_batch = (pending[2]['batch_id'] if pending is not None
                                 and pending[2].get('stage') == 'source_adjudication' else None)
                should_call = should_call_shard(inventory, target, completed, pending_batch)
                empty_shard = not next(item['source_ids'] for item in inventory if item['batch_id'] == target)
                expected = pending if should_call else None
            elif split:
                expected = (requests[index] if index < len(requests) else pending
                            if pending is not None and pending[2].get('stage') == stage else None)
            else:
                expected = requests[index] if index < len(requests) else pending if phase == 'diligence_field_selection' else None
            if expected is not None and (index < len(requests) and len(rows) == index or
                                         stage != 'classification' and pending is not None):
                if len(rows) >= (diligence_coverage.MAX_CALLS_V15 if sharded else diligence_coverage.MAX_CALLS_V12 if split else diligence_coverage.MAX_CALLS):
                    raise ValueError('All-source coverage exhausted its fixed recorded-call cap')
                coverage_options = diligence_coverage.options_for(request['coverage_contract'], stage)
                task, instruction, payload, schema = expected
                role_key = ('coverage_adjudicator_pin' if stage == 'source_adjudication'
                            and 'coverage_adjudicator_pin' in request else 'coverage_pin')
                if payload.get('model_pin') != request[role_key]:
                    raise ValueError('Coverage checkpoint model pin differs from its frozen stage role')
                role = models.get(role_key) or LocalModel(request[role_key]['name'], **coverage_options)
                try:
                    recorded_call(role, task, instruction, payload, schema, rows,
                                  lambda: _write(root, COVERAGE_FILES['diligence_coverage_attempts'], rows))
                except Exception as exc:
                    return status({'state': 'blocked', 'reason': 'diligence_coverage_inference_failed',
                                   'next_phase': phase, 'detail': str(exc)[:500]})
            after = _coverage_result(request, attempts)
            if after['state'] == 'blocked':
                return status({'state': 'blocked', 'reason': after['reason'], 'next_phase': phase})
            if phase == 'diligence_field_selection' and after['state'] != 'accepted':
                raise ValueError('All-source field selection is incomplete')
            if sharded and stage == 'source_adjudication' and not empty_shard and target not in [
                    row['input'].get('batch_id') for row in rows if row['input'].get('stage') == 'source_adjudication']:
                raise ValueError('All-source adjudication shard is incomplete')
            if split and not sharded and phase == 'diligence_source_adjudication' and len(rows) < len(requests) + 1:
                raise ValueError('All-source adjudication is incomplete')
            return status({'state': 'needs_resume', 'reason': 'diligence_field_selection_complete' if phase == 'diligence_field_selection'
                           else 'diligence_source_adjudication_empty' if empty_shard
                           else 'diligence_source_adjudication_complete' if stage == 'source_adjudication'
                           else 'diligence_source_batch_complete', 'next_phase': phases[index + 1]})
        if coverage['state'] != 'accepted':
            raise ValueError('Core/source phases require completed all-source traversal and field selection')
        return status(_advance_checkpointed(root, request, phase, budget, attempts, models))
    except PreparationBudgetExceeded:
        return status({'state': 'blocked', 'reason': 'source_unit_phase_time_limit', 'phase': phase})
    except (ValueError, RuntimeError) as exc:
        return status({'state': 'blocked', 'reason': 'source_unit_phase_failed', 'phase': phase, 'detail': str(exc)[:500]})



def _advance_checkpointed(root,request,phase,budget,attempts,models):
    """Fixed scope checkpoints share the original finite engine attempt arrays."""
    flow = request['flow_contract']
    phases = phases_for(flow)
    actual_index = phases.index(phase)
    index = (actual_index - len(COVERAGE_PHASES_V12 if flow == FLOW_V12 else COVERAGE_PHASES_V10 if flow in {FLOW_V10, FLOW_V11, FLOW_V12} else COVERAGE_PHASES_V7 if flow in {FLOW_V7, FLOW_V8, FLOW_V9} else COVERAGE_PHASES_V6 if flow == FLOW_V6 else COVERAGE_PHASES_V5)
             if flow in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12} else actual_index)
    core_author_end = 10 if flow in {FLOW_V4,FLOW_V5,FLOW_V6,FLOW_V7,FLOW_V8,FLOW_V9,FLOW_V10, FLOW_V11, FLOW_V12} else 6
    core_pin = request.get('core_author_pin',request['author_pin'])
    def saved(key): return lambda: _write(root,files_for(flow)[key],attempts[key])
    def model(key,options): return models.get(key) or LocalModel(request[key]['name'],**options)
    def next_result(reason):
        return {'state':'needs_resume','reason':reason,'next_phase':phases[actual_index+1]}
    coverage_kwargs = {'coverage': _coverage_bundle(request, attempts)} if flow in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12} else {}
    try:
        if index < 2:
            if attempts['memo_section_author_attempts'] or attempts['memo_section_review_attempts']:
                raise ValueError('Checkpointed flow cannot move backwards')
            if index == 0:
                if attempts['source_unit_author_attempts'] or attempts['source_unit_review_attempts']:
                    # Cached exact source stages may replay without inference only.
                    result = evidence.characterize_sources(_selected(request),request['characterizer_pin'],
                        attempts['source_characterization_attempts'],lambda:None,None,EMPTY_BUDGET)
                else:
                    result = evidence.characterize_sources(_selected(request),request['characterizer_pin'],
                        attempts['source_characterization_attempts'],saved('source_characterization_attempts'),
                        model('characterizer_pin',evidence.OPTIONS),budget)
                return next_result('source_characterization_complete') if result['state']=='accepted' else {**result,'next_phase':phase}
        proof = _proof(request,attempts['source_characterization_attempts'])
        authored = author_engine.run_author(request['memo'],request['sources'],proof,request['author_pin'],
            attempts['source_unit_author_attempts'],saved('source_unit_author_attempts') if index==1 else lambda:None,
            model('author_pin',author_engine.OPTIONS_V2) if index==1 and not attempts['source_unit_review_attempts'] else None,
            budget if index==1 and not attempts['source_unit_review_attempts'] else EMPTY_BUDGET,contract=request['author_contract'])
        if authored['state']!='accepted': return {**authored,'next_phase':phase}
        if index==1: return next_result('source_unit_author_complete')
        from agents.research import memo_source_unit_review_v3, memo_section_units, memo_section_review
        # Replaying first discovers the next unreviewed scope; it cannot infer.
        reviewed = review_engine.run_review(request['memo'],request['sources'],proof,authored,
            request['author_pin'],request['reviewer_pin'],attempts['source_unit_review_attempts'],lambda:None,None,EMPTY_BUDGET)
        if index < 5:
            if any(attempts[k] for k in CORE_FILES): raise ValueError('Source review cannot follow core work')
            target = phase.removeprefix('source_unit_review_')
            groups = [g[0] for g in memo_source_unit_review_v3.frozen_requests(request['memo'],request['sources'],proof,authored,request['author_pin'],request['reviewer_pin'])]
            if reviewed['state']=='blocked': return {**reviewed,'next_phase':phase}
            if target in groups:
                current = reviewed.get('batch_id')
                if reviewed['state']=='needs_resume' and current==target:
                    reviewed = review_engine.run_review(request['memo'],request['sources'],proof,authored,
                        request['author_pin'],request['reviewer_pin'],attempts['source_unit_review_attempts'],
                        saved('source_unit_review_attempts'),model('reviewer_pin',memo_source_unit_review_v3.OPTIONS),budget)
                elif reviewed['state']=='needs_resume' and groups.index(current)<groups.index(target):
                    raise ValueError('Review checkpoint skipped an unfinished source group')
                if reviewed['state']=='blocked': return {**reviewed,'next_phase':phase}
                if reviewed['state']=='needs_resume' and reviewed.get('batch_id')==target:
                    return {**reviewed,'next_phase':phase}
            return next_result('source_unit_review_complete')
        gate = _gate(request,proof,authored,reviewed)
        author_phase = index < core_author_end
        if author_phase and attempts['memo_section_review_attempts']: raise ValueError('Core author cannot follow core review')
        core_contract = request.get('section_author_contract','memo-section-units-author-v1')
        core = memo_section_units.run_author(authored['memo'],request['sources'],core_pin,
            attempts['memo_section_author_attempts'],lambda:None,None,EMPTY_BUDGET,contract=core_contract, **coverage_kwargs)
        if author_phase:
            if flow in {FLOW_V4,FLOW_V5,FLOW_V6,FLOW_V7,FLOW_V8,FLOW_V9,FLOW_V10, FLOW_V11, FLOW_V12}:
                target = phase.removeprefix('memo_section_author_')
                if core['state']=='needs_resume' and core['pending_field'] != target and memo_section_units.FIELDS.index(core['pending_field'])<memo_section_units.FIELDS.index(target):
                    raise ValueError('Author checkpoint skipped an unfinished core field')
                should_call = core['state']=='needs_resume' and core['pending_field']==target
            else:
                target = None
                should_call = core['state']=='needs_resume'
            if should_call:
                role_key = 'core_author_pin' if flow in {FLOW_V4,FLOW_V5,FLOW_V6,FLOW_V7,FLOW_V8,FLOW_V9,FLOW_V10, FLOW_V11, FLOW_V12} else 'author_pin'
                core = memo_section_units.run_author(authored['memo'],request['sources'],core_pin,
                    attempts['memo_section_author_attempts'],saved('memo_section_author_attempts'),
                    model(role_key,memo_section_units.options_for(core_contract)),budget,contract=core_contract, **coverage_kwargs)
            if core['state']=='blocked': return {**core,'next_phase':phase}
            if core['state']=='needs_resume' and (flow not in {FLOW_V4,FLOW_V5,FLOW_V6,FLOW_V7,FLOW_V8,FLOW_V9,FLOW_V10, FLOW_V11, FLOW_V12} or core['pending_field']==target):
                return {**core,'next_phase':phase}
            return next_result('memo_section_author_complete')
        if core['state']!='accepted': raise ValueError('Core review requires complete author coverage')
        target = phase.removeprefix('memo_section_review_')
        core_review = memo_section_review.run_review(authored['memo'],request['sources'],core,core_pin,
            request.get('core_reviewer_pin',request['reviewer_pin']),attempts['memo_section_review_attempts'],lambda:None,None,EMPTY_BUDGET,
            **({'contract':request['section_review_contract']} if 'section_review_contract' in request else {}), **coverage_kwargs)
        if core_review['state']=='blocked': return {**core_review,'next_phase':phase}
        if core_review['state']=='needs_resume':
            current = core_review['pending_field']
            if current==target:
                core_review = memo_section_review.run_review(authored['memo'],request['sources'],core,core_pin,
                    request.get('core_reviewer_pin',request['reviewer_pin']),attempts['memo_section_review_attempts'],saved('memo_section_review_attempts'),
                    model('core_reviewer_pin' if 'core_reviewer_pin' in request else 'reviewer_pin',memo_section_review.options_for(request.get('section_author_contract','memo-section-units-author-v1'))),budget,
                    **({'contract':request['section_review_contract']} if 'section_review_contract' in request else {}), **coverage_kwargs)
            elif memo_section_units.FIELDS.index(current)<memo_section_units.FIELDS.index(target):
                raise ValueError('Review checkpoint skipped an unfinished core field')
            if core_review['state']=='blocked': return {**core_review,'next_phase':phase}
            if core_review['state']=='needs_resume' and core_review.get('pending_field')==target:
                return {**core_review,'next_phase':phase}
        if actual_index < len(phases)-1: return next_result('memo_section_review_complete')
        gate = (_flow5_final_gate(request, gate, core, core_review, _coverage_result(request, attempts)) if flow in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12} else
                _full_gate(gate,core,core_review,flow=flow,core_pin=core_pin if flow==FLOW_V4 else None, core_reviewer_pin=request.get('core_reviewer_pin'), section_review_contract=request.get('section_review_contract')))
        return {'state':'accepted','final_memo_digest':gate['final_memo_digest'],'content_review':gate}
    except PreparationBudgetExceeded:
        return {'state':'blocked','reason':'source_unit_phase_time_limit','phase':phase}
    except (ValueError,RuntimeError) as exc:
        return {'state':'blocked','reason':'source_unit_phase_failed','phase':phase,'detail':str(exc)[:500]}

if __name__ == '__main__': main()
