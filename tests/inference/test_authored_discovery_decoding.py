"""Discovery opts into existing decoder/context gates; unrelated tasks do not."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

from agents.inference.local_models import generate_authored_task
from agents.preparation.authored_discovery import Plan


def transport(monkeypatch):
    answer = {'interpretation':'Find preliminary fintech company research candidates in India.',
              'criteria':[], 'coverage_aim':'Include varied financial technology products.',
              'queries':['fintech','Indian fintech']}
    raw = json.dumps(answer)
    client = Mock()
    client.chat.return_value = {'model':'qwen3.5:9b','message':{'content':raw},
                               'prompt_eval_count':100,'eval_count':50,'done_reason':'stop'}
    monkeypatch.setattr('agents.inference.local_models.ollama.Client',lambda **kwargs:client)
    return client, raw


def test_discovery_bounds_reach_actual_wire_and_preserve_limits_and_raw_body(monkeypatch):
    client,raw = transport(monkeypatch)
    model = SimpleNamespace(name='qwen3.5:9b')
    payload = {'request':'fintrch','geography':'india'}
    result = generate_authored_task(model,'authored_discovery_plan','Plan',json.dumps(payload),Plan)
    assert result.queries == ['fintech','Indian fintech']
    sent = client.chat.call_args.kwargs
    assert sent['format']['$defs']['Criterion']['properties']['evidence_needed']['maxLength']==180
    assert sent['options']['num_ctx']==8192 and sent['options']['num_predict']==550
    assert sent['think'] is False
    assert sent['options']['presence_penalty']==0 and sent['options']['repeat_penalty']==1
    assert json.loads(sent['messages'][1]['content'])==payload
    assert all(model.last_route[key] is True for key in ('bound_strings','compact_prompt','require_full_context','factual_sampling'))
    assert model.last_response_text==raw


def test_other_authored_tasks_keep_their_existing_decoder_policy(monkeypatch):
    client,raw = transport(monkeypatch)
    model = SimpleNamespace(name='qwen3.5:9b')
    generate_authored_task(model,'authored_work','Plan','{}',Plan)
    sent = client.chat.call_args.kwargs
    assert 'maxLength' not in sent['format']['$defs']['Criterion']['properties']['evidence_needed']
    assert sent['options']['num_ctx']==8192 and sent['options']['num_predict']==1400
    assert all(key not in model.last_route for key in ('bound_strings','compact_prompt','require_full_context'))
    assert model.last_response_text==raw


def test_match_only_wire_has_no_financial_prose_and_keeps_discovery_limits(monkeypatch):
    from agents.preparation.authored_discovery import extraction_schema
    schema=extraction_schema({'b1':'Synthetic Service offers payments.'},spans={'q1_1':{'block_id':'b1','text':'Synthetic Service offers payments.'}},
        websites=(),match_criteria=[],primary_only=True)
    answer={'companies':[{'name':'Synthetic Service','name_block_id':'b1','entity_type':'company','website':None,
        'facts':[{'field':'offering','source_span_id':'q1_1'}],
        'proof_contract':'selected_fact_roles_v3','decision':'match','topic_fit':'supported','topic_evidence_ids':['OFFERING'],
        'product_support':'direct_service_evidence','product_attribution':'same_company','product_evidence_ids':['OFFERING'],
        'geography_support':'unrestricted','geography_evidence_ids':[],'explicit_requirements':'supported','criteria_checks':[],
        'known_closed_or_discontinued':False,'current_verification_required':False,'current_operating_status':'not_verified',
        'financial_assessment':'not_performed','scope':'preliminary_research_only'}],'follow_links':[]}
    raw=json.dumps(answer)
    client=Mock();client.chat.return_value={'model':'qwen3.5:9b','message':{'content':raw},'prompt_eval_count':100,'eval_count':50,'done_reason':'stop'}
    monkeypatch.setattr('agents.inference.local_models.ollama.Client',lambda **kwargs:client)
    model=SimpleNamespace(name='qwen3.5:9b')
    result=generate_authored_task(model,'authored_discovery_match','Match','{}',schema)
    sent=client.chat.call_args.kwargs
    properties=sent['format']['$defs']['ObservedDiscoveryCompany']['properties']
    assert 'rationale' not in properties and 'strengths' not in properties and 'concerns' not in properties
    assert properties['financial_assessment']['const']=='not_performed'
    assert sent['options']['num_ctx']==8192 and sent['options']['num_predict']==650
    assert all(model.last_route[key] is True for key in ('bound_strings','compact_prompt','require_full_context','factual_sampling'))
    assert model.last_response_text==raw and result.companies[0].decision=='match'
    assert sent['format']['$defs']['ObservedDiscoveryCompany']['properties']['proof_contract']['const']=='selected_fact_roles_v3'
    assert sent['think'] is False
    directory=extraction_schema({'b1':'Synthetic Service offers payments.'},spans={'q1_1':{'block_id':'b1','text':'Synthetic Service offers payments.'}},websites=(),match_criteria=[])
    model.thinking=True  # This source-only role has a fixed nonthinking policy.
    generate_authored_task(model,'authored_discovery_match','Match','{}',directory)
    assert client.chat.call_args.kwargs['options']['num_predict']==1100
    assert client.chat.call_args.kwargs['think'] is False

