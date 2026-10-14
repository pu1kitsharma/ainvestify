"""Full core review blocks purpose/evidence defects and exact-projection tampering."""
import copy
import json
from types import SimpleNamespace

import pytest

from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_section_review as review
from tests.research.test_memo_section_units import execute, Model as Author, PIN
from tests.research.test_memo_causal_review import sample

REVIEW_PIN = {'name':'local-reviewer','digest':'d'*64}


def fixture():
    memo, sources = sample()
    authored, _ = execute(memo,sources,Author())
    return memo,sources,authored


class Reviewer:
    name = REVIEW_PIN['name']
    thinking = False
    max_tokens = 500
    context_tokens = 8192
    temperature = 0

    def __init__(self, defect=None, malformed=(), timeout=False):
        self.defect,self.malformed,self.timeout = defect,malformed,timeout
        self.calls = 0

    def generate_for_task(self,task,instruction,evidence,schema,*,attempt=0):
        self.calls += 1
        assert task == review.TASK
        payload = json.loads(evidence)
        field = payload['field']
        assert instruction == (review.RETRY if payload.get('correction_number') else review.INSTRUCTION)
        self.last_route = {'model':self.name,**review.OPTIONS}
        self.last_response_text = ''
        if self.timeout: raise TimeoutError('synthetic timeout')
        obj = {'judgments': {sid: {'evidence_id':unit['supporting_evidence_id'],
            'status':unit['status'],'fulfills_field_purpose':True,
            'preserves_source_attribution':True,'preserves_time_scope':True,
            'has_unsupported_premise':False,'has_unsupported_metric':False,
            'has_false_missing_data_claim':False,
            'reason':'The unit preserves source scope and its requested field purpose.'}
            for sid,unit in payload['units'].items()}}
        if self.defect and field=='risks_and_countercase':
            key,value = self.defect
            obj['judgments'][next(iter(obj['judgments']))][key] = value
        if field in self.malformed and not payload.get('correction_number'):
            obj['judgments'] = {}
        self.last_response_text = json.dumps(obj)
        return schema.model_validate(obj)


def run(memo,sources,authored,model,rows=None):
    rows = [] if rows is None else rows
    budget = PreparationBudget(105,max_calls=6,max_requests=6)
    for _ in range(6):
        result = review.run_review(memo,sources,authored,PIN,REVIEW_PIN,rows,lambda:None,model,budget)
        if result['state'] != 'needs_resume': return result,rows
    return result,rows


def test_full_five_field_exact_review_and_replay_with_one_global_shape_correction():
    memo,sources,authored = fixture()
    result,rows = run(memo,sources,authored,Reviewer(malformed=['business_and_market']))
    assert result['state']=='accepted' and len(rows)==6
    assert result['coverage']==list(review.author.FIELDS)
    assert result['memo_digest']==review.digest(authored['memo'])
    assert rows[1]['failure_kind']=='schema_validation'
    assert 'validation_error' in rows[2]['input']
    assert review.run_review(memo,sources,authored,PIN,REVIEW_PIN,rows,lambda:None,None,
        SimpleNamespace(calls=0,max_calls=0))==result
    for change in ('input','raw','schema','id'):
        changed=copy.deepcopy(rows)
        if change=='input': changed[0]['input']['field']='other_field'
        if change=='raw': changed[0]['raw_response']+=' '
        if change=='schema': changed[0]['schema']['title']='Other schema'
        if change=='id': changed[1]['id']=changed[0]['id']
        with pytest.raises(ValueError):
            review.run_review(memo,sources,authored,PIN,REVIEW_PIN,changed,lambda:None,None,
                SimpleNamespace(calls=0,max_calls=0))


@pytest.mark.parametrize('defect',[
    ('fulfills_field_purpose',False),('preserves_source_attribution',False),
    ('preserves_time_scope',False),('has_unsupported_premise',True),
    ('has_unsupported_metric',True),('has_false_missing_data_claim',True),
    ('status','unsupported'),('evidence_id',None)])
def test_wrong_purpose_or_any_semantic_flag_blocks_without_author_retry(defect):
    memo,sources,authored = fixture()
    model=Reviewer(defect=defect)
    result,rows=run(memo,sources,authored,model)
    assert result['state']=='blocked' and result['reason']=='core_section_content_not_supported'
    assert result['findings'] and len(rows)==model.calls==4
    assert all('correction_number' not in row['input'] for row in rows)
    assert result['investment_approval'] is False
    assert review.run_review(memo,sources,authored,PIN,REVIEW_PIN,rows,lambda:None,None,
        SimpleNamespace(calls=0,max_calls=0))==result


def test_author_projection_binding_cannot_review_one_answer_but_release_another_memo():
    memo,sources,authored=fixture()
    variants=[]
    changed=copy.deepcopy(authored); changed['memo']['business_and_market']['analysis']='Unreviewed investor content ' * 10; variants.append(changed)
    changed=copy.deepcopy(authored); changed['field_patches']['business_and_market']['analysis']='Unreviewed investor content ' * 10; variants.append(changed)
    changed=copy.deepcopy(authored); changed['memo']['unknowns'][0]['question']='An altered inquiry unrelated to the recorded author.'; variants.append(changed)
    changed=copy.deepcopy(authored); changed['request_digest']='e'*64; variants.append(changed)
    changed=copy.deepcopy(authored); changed['answer']['risks_and_countercase']['units']['S1']['status']='source_reported'; variants.append(changed)
    changed=copy.deepcopy(authored); changed['answer']['business_and_market']['units']['S1']['supporting_evidence_id']='S2.e001'; variants.append(changed)
    for changed in variants:
        with pytest.raises(ValueError):
            review.frozen_requests(memo,sources,changed,PIN,REVIEW_PIN)


def test_second_shape_failure_is_terminal_and_timeout_is_not_semantic_review():
    memo,sources,authored=fixture()
    model,rows=Reviewer(malformed=['investment_thesis','business_and_market']),[]
    with pytest.raises(ValueError,match='global shape correction exhausted'):
        run(memo,sources,authored,model,rows)
    assert model.calls==len(rows)==3
    model,rows=Reviewer(timeout=True),[]
    with pytest.raises(ValueError,match='inference failed'):
        run(memo,sources,authored,model,rows)
    assert model.calls==len(rows)==1
    with pytest.raises(ValueError,match='inference failed'):
        review.run_review(memo,sources,authored,PIN,REVIEW_PIN,rows,lambda:None,None,
            SimpleNamespace(calls=0,max_calls=0))
