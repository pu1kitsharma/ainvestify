"""Phase separation, complete role-aware review and exact private replay."""
import copy
import json
import pytest
from agents.inference.model_authorship import digest
from agents.preparation.preparation_budget import PreparationBudget, preparation_budget
from agents.research import memo_source_unit_review as review
from scripts import private_source_unit_worker as worker
from tests.research.test_memo_causal_review import sample
from tests.research.test_rationale_evidence import Model as Characterizer
from tests.research.test_memo_source_unit_author import Model as Author

PIN={'name':'qwen3.5:9b','digest':'a'*64}

class Reviewer:
    name=PIN['name']
    def __init__(self,fail=False):
        self.__dict__.update(review.OPTIONS);self.calls=0;self.fail=fail
    def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
        self.calls+=1;self.last_route={'model':self.name,**review.OPTIONS}
        if self.fail:raise RuntimeError('Synthetic local transport failure')
        p=json.loads(evidence)
        rows={}
        for key,unit in p['units'].items():
            factual=unit['required_function']=='investment_rationale'
            eid=unit['eligible_evidence_ids'][0] if factual else None
            sid=p['evidence_spans'][eid]['source_id'] if eid else None
            rows[key]={'function':unit['required_function'],'evidence_id':eid,
                'source_time_basis':p['source_cards'][sid]['reporting_basis'] if sid else 'not_applicable',
                'asserted_time_basis':'mixed' if factual else 'not_applicable',
                'quantification_scope':'source_stated' if factual else 'not_applicable',
                'requires_explicit_quantification_claim':False,'has_unsupported_premise':False,'preserves_time_scope':True,
                'reason':'The wording retains source timing and its required purpose.',
                'relation':'supported_fact' if factual else 'conditional_question'}
        answer={'judgments':rows};self.last_response_text=json.dumps(answer)
        return schema.model_validate(answer)

def setup(root,fail=False):
    memo,sources=sample()
    body={'flow_contract':worker.FLOW,'memo':memo,'sources':sources,
          'characterizer_pin':PIN,'author_pin':PIN,'reviewer_pin':PIN}
    worker._write(root,'content_request.json',{**body,'digest':digest(body)})
    char=Characterizer();char.name=PIN['name']
    author=Author();author.name=PIN['name']
    reviewer=Reviewer(fail)
    return body,{'characterizer_pin':char,'author_pin':author,'reviewer_pin':reviewer}

def invoke(root,phase,models):
    b=PreparationBudget(100,max_calls=6,max_requests=6)
    with preparation_budget(b): return worker.advance(root,phase,b,models=models)

def test_three_separate_passes_cover_unknown_premises_and_exact_replay(tmp_path):
    body,models=setup(tmp_path)
    first=invoke(tmp_path,worker.PHASES[0],models)
    assert first['next_phase']==worker.PHASES[1]
    assert models['author_pin'].calls==models['reviewer_pin'].calls==0
    second=invoke(tmp_path,worker.PHASES[1],models)
    assert second['next_phase']==worker.PHASES[2]
    assert models['reviewer_pin'].calls==0
    final=invoke(tmp_path,worker.PHASES[2],models)
    assert final['state']=='accepted'
    record=worker.load_source_unit_revision(tmp_path)
    memo,gate=worker.replay_source_unit_revision(body['memo'],body['sources'],record)
    assert gate==final['content_review']
    assert gate['final_memo_digest']==digest(memo)
    assert gate['investment_approval'] is False
    assert len(gate['review']['unknown_status'])==3*len(body['memo']['unknowns'])
    assert set(gate['review']['unknown_status'].values())=={'unresolved'}
    changed=copy.deepcopy(record);changed['author_pin']['digest']='b'*64
    with pytest.raises(ValueError,match='original inputs'):
        worker.replay_source_unit_revision(body['memo'],body['sources'],changed)
    changed=copy.deepcopy(record);changed['source_unit_review_attempts'][0]['answer']['judgments'].clear()
    with pytest.raises(ValueError):
        worker.replay_source_unit_revision(body['memo'],body['sources'],changed)

def test_review_transport_failure_never_rewrites_company_text(tmp_path):
    _,models=setup(tmp_path,fail=True)
    invoke(tmp_path,worker.PHASES[0],models);invoke(tmp_path,worker.PHASES[1],models)
    authored_calls=models['author_pin'].calls
    result=invoke(tmp_path,worker.PHASES[2],models)
    assert result['state']=='blocked'
    assert result['reason']=='source_unit_review_inference_failed'
    assert models['author_pin'].calls==authored_calls


def test_worker_uses_all_bounded_calls_inside_one_author_phase(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'content_budget.json').write_text(json.dumps({'seconds': 105, 'max_calls': 6}))
    (tmp_path / 'content_result.json').write_text(json.dumps({'state': 'needs_resume', 'next_phase': 'source_unit_author'}))
    phases = []
    def advance(root, phase, budget):
        phases.append(phase)
        budget.calls += 1
        return {'state': 'needs_resume', 'next_phase': 'source_unit_review' if len(phases) == 4 else phase}
    monkeypatch.setattr(worker, 'advance', advance)
    worker.main()
    assert phases == ['source_unit_author'] * 4
    assert json.loads((tmp_path / 'content_result.json').read_text())['next_phase'] == 'source_unit_review'


def test_worker_stops_at_six_calls_without_crossing_phase(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'content_budget.json').write_text(json.dumps({'seconds': 105, 'max_calls': 6}))
    (tmp_path / 'content_result.json').write_text(json.dumps({'state': 'needs_resume', 'next_phase': 'source_unit_author'}))
    phases = []
    def advance(root, phase, budget):
        phases.append(phase)
        budget.calls += 1
        return {'state': 'needs_resume', 'next_phase': phase}
    monkeypatch.setattr(worker, 'advance', advance)
    worker.main()
    assert phases == ['source_unit_author'] * 6
