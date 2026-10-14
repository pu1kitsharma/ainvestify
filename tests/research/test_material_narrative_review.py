"""Complete narrative units and exact unknown binding; synthetic evidence only."""
import copy
import json
import pytest
from agents.inference.model_authorship import digest
from agents.research import material_narrative_review as engine
from scripts import private_material_review_worker as worker

RISK = 'If the reported pilot does not scale, execution could be delayed. This is an unproved prospective consequence.'
REQUEST = 'Request dated pilot records and customer evidence. These records would inform commercial diligence.'
QUESTION = 'What audited financial records are available?'
NEEDED = 'Request audited statements and dated receivables records.'
PIN = {'name':'qwen3:14b','digest':'a'*64,'options':engine.BATCH_OPTIONS}


def request():
    assertions = [dict(text=RISK,source_id='S1',source_quote='The company reports one pilot.',memo_field='risks_and_countercase',field_function='conditional_hypothesis'),
                  dict(text=REQUEST,source_id='S1',source_quote='The company reports one pilot.',memo_field='diligence_plan',field_function='verification_request')]
    financial = 'Financial evidence status: unverified.\nOpen diligence question: '+QUESTION+'\nEvidence requested: '+NEEDED
    body = {'review_contract':engine.CONTRACT,'review_model':PIN,
            'memo_sections':[['Pilot evidence', '[S1] The company reports one pilot.', '[S1] Company'],
                             [QUESTION, 'The financial position is unresolved.\n\n'+NEEDED, ''],
                             ['Sources and retained versions', '[S1] https://example.invalid | version 1', '']],
            'memo_assertion_candidates':{'funding_required':False,'slots':{'risk':[assertions[0]],'diligence':[assertions[1]]}},
            'financial_unknown_candidates':{'unknowns':[{'id':'u1','question':QUESTION,'evidence_needed':NEEDED}],'claims':[]},
            'decks':{'intro_deck':[['Prospective execution risk',RISK.rstrip('.')+' [S1].','[S1]','evidence']],
                     'pitch_deck':[['Diligence records',REQUEST.rstrip('.')+' [S1].','[S1]','evidence'],
                                   ['Financial diligence',financial,'','evidence']]}}
    risk_slide=body['decks']['intro_deck'][0]
    request_slide=body['decks']['pitch_deck'][0]
    financial_slide=body['decks']['pitch_deck'][1]
    body['decks']['intro_deck']=[request_slide,request_slide,risk_slide,financial_slide]
    body['decks']['pitch_deck']=[risk_slide,request_slide,request_slide,request_slide,risk_slide,financial_slide]
    return {**body,'digest':digest(body)}

class Reviewer:
    name='qwen3:14b'
    def __init__(self, bad_heading=False, bad_product_purpose=False):
        self.calls=0;self.bad_heading=bad_heading;self.bad_product_purpose=bad_product_purpose;self.last_response_text='';self.last_route={}
    def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
        assert task==engine.TASK
        self.calls+=1
        payload=json.loads(evidence)
        answer={row['row_id']:{'relation':engine.SUPPORTED,'narrative_function':row['declared_narrative_function'],
            'matches_declared_function':True,'heading_body_relevant':not self.bad_heading,'slide_purpose_relevant':not (self.bad_product_purpose and row['required_slide_purpose']=='product'),
            'preserves_source_and_conditional_scope':True,'faithful_to_bound_provenance':True,
            'challenged_clause':None,'reason':'This whole unit preserves its exact cited or reviewed unknown provenance.'}
            for row in payload['rows']}
        self.last_response_text=json.dumps(answer);self.last_route={'model':self.name,**engine.BATCH_OPTIONS}
        return schema.model_validate(answer)


def setup(tmp_path):
    body=request()
    (tmp_path/'material_review_request.json').write_text(json.dumps(body))
    (tmp_path/'material_review_budget.json').write_text(json.dumps({'seconds':105}))
    return body


def test_complete_condition_request_and_unknown_provenance_replay(tmp_path):
    body=setup(tmp_path);calls=engine.batch_calls(body)
    assert any(row['sentence'].startswith('If ') and 'unproved prospective consequence' in row['sentence'] for call in calls for row in call[2])
    assert len(engine.deck_rows(body,'intro_deck'))==6
    assert len(engine.deck_rows(body,'pitch_deck'))==8
    assert all('full_slide_body' in row for call in calls for row in call[3]['rows'])
    assert not any('example.invalid' in json.dumps(call[3]) for call in calls)
    model=Reviewer()
    for _ in calls: result=worker.review_materials(tmp_path,model)
    assert result['state']=='accepted' and model.calls==len(calls)
    assert len(calls)<=12 and all(len(call[2])<=3 for call in calls)
    rows=json.loads((tmp_path/'material_review_attempts.json').read_text())
    assert engine.evaluate_attempts(body,rows)[0]==result
    changed=copy.deepcopy(rows);changed[0]['response_hash']='b'*64
    with pytest.raises(ValueError,match='raw response changed'):engine.evaluate_attempts(body,changed)


@pytest.mark.parametrize('bad', ['unbound','detached','wrong_unknown','missing_request'])
def test_unbound_uncited_or_detached_units_block_before_inference(bad):
    body=request()
    if bad=='unbound':body['decks']['intro_deck'][0][1]='The company has verified profitable growth.'
    elif bad=='detached':body['decks']['intro_deck'][0][1]='This is an unproved prospective consequence [S1].'
    elif bad=='wrong_unknown':body['memo_sections'][1][1]='Different records are requested.'
    else:body['decks']['pitch_deck'][-1][1]='Financial evidence status: unverified.\nOpen diligence question: '+QUESTION
    with pytest.raises(ValueError):engine.batch_calls(body)


def test_heading_semantic_rejection_blocks_even_when_relation_supported(tmp_path):
    setup(tmp_path)
    result=worker.review_materials(tmp_path,Reviewer(bad_heading=True))
    assert result['state']=='blocked'
    assert result['review']['findings'][0]['heading_body_relevant'] is False


def test_financial_only_source_retains_complete_multiline_quote_and_typed_role():
    body=request()
    financial_claim={'id':'f1','source_id':'S2','assertion':'The company describes a future revenue target.',
                     'source_quote':'The company describes a future revenue target.\nUnits are illustrative; this is a future target, not actual revenue.',
                     'memo_field':'business_and_market','field_function':'source_report'}
    body['financial_unknown_candidates']['claims']=[financial_claim]
    body['decks']['pitch_deck'][-1][1]='The company describes a future revenue target [S2].\n'+body['decks']['pitch_deck'][-1][1]
    body['memo_sections'].append(['Financial report','[S2] '+financial_claim['assertion']+'\n[S2] '+financial_claim['source_quote'],'[S2] Company'])
    calls=engine.batch_calls(body)
    sources=[item for call in calls for item in call[3]['provenance'].values() if item.get('source_id')=='[S2]']
    assert any(item.get('exact_source_quote')==financial_claim['source_quote'] for item in sources)
    assert any(row['declared_narrative_function']=='source_report' for call in calls for row in call[3]['rows'] if '[S2]' in row['sentence'])
    assert all('example.invalid' not in json.dumps(call[3]) for call in calls)


def test_mandatory_semantic_flags_require_actual_booleans():
    schema=engine.batch_calls(request())[0][4]
    item={'relation':engine.SUPPORTED,'narrative_function':'conditional_hypothesis','matches_declared_function':1,
          'heading_body_relevant':True,'slide_purpose_relevant':True,'preserves_source_and_conditional_scope':True,'faithful_to_bound_provenance':True,
          'challenged_clause':None,'reason':'This complete assertion preserves its unproved prospective scope.'}
    with pytest.raises(ValueError):schema.model_validate({'r01':item})


def test_source_bound_body_in_wrong_product_slot_blocks_independently(tmp_path):
    body=setup(tmp_path)
    rows=engine.deck_rows(body,'intro_deck')
    assert rows[1]['required_slide_purpose']=='product'
    assert rows[1]['full_slide_body']==body['decks']['intro_deck'][1][1]
    result=worker.review_materials(tmp_path,Reviewer(bad_product_purpose=True))
    assert result['state']=='blocked'
    finding=result['review']['findings'][0]
    assert finding['relation']==engine.SUPPORTED and finding['heading_body_relevant'] is True
    assert finding['slide_purpose_relevant'] is False


def temporal_request():
    body=request();body['review_contract']='semantic_v15'
    body['memo_assertion_candidates']['as_of_date']='2026-10-09'
    quote='The company reports a revenue target. Mar23 FY23Exit was the target period.'
    excerpt='Mar23 FY23Exit';start=quote.index(excerpt)
    claim={'id':'f1','source_id':'S2','assertion':'The company describes a future revenue target.',
           'source_quote':quote,'memo_field':'business_and_market','field_function':'source_report',
           'temporal_evidence':[{'id':'t1','source_id':'S2','start':start,'end':start+len(excerpt),'exact_text':excerpt}]}
    body['financial_unknown_candidates']['claims']=[claim]
    for deck in body['decks'].values():
        for slide in deck:
            slide[1]=slide[1].replace('Financial evidence status:', 'Requested financial evidence status:')
    first='The company describes a future revenue target [S2]. The source reported a historical target [S2]. Exact period excerpt: Mar23 FY23Exit [S2].'
    body['decks']['pitch_deck'][-1][1]=first+'\n'+body['decks']['pitch_deck'][-1][1]
    body.pop('digest', None)
    return {**body,'digest':digest(body)}

class TemporalReviewer(Reviewer):
    def __init__(self, temporal=True):super().__init__();self.temporal=temporal
    def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
        assert task in {'material_narrative_review_v15','material_narrative_review_v16','material_narrative_review_v17'} and 'historical company target' in instruction
        self.calls+=1;payload=json.loads(evidence)
        assert payload['as_of_date']=='2026-10-09'
        answer={row['row_id']:{'relation':engine.SUPPORTED,'narrative_function':row['declared_narrative_function'],
            'matches_declared_function':True,'heading_body_relevant':True,'slide_purpose_relevant':True,
            'preserves_source_and_conditional_scope':True,'faithful_to_bound_provenance':True,
            'temporal_scope_preserved':self.temporal,'challenged_clause':None,
            'reason':'The complete unit preserves its explicit historical period and requested-record scope.'} for row in payload['rows']}
        self.last_response_text=json.dumps(answer);self.last_route={'model':self.name,**engine.BATCH_OPTIONS}
        return schema.model_validate(answer)


def test_temporal15_binds_exact_inline_period_and_open_record_state(tmp_path):
    body=temporal_request();calls=engine.batch_calls(body)
    financial=[row for call in calls for row in call[2] if 'Exact period excerpt:' in row['sentence']]
    assert len(financial)==2 and 'Mar23 FY23Exit' in financial[0]['sentence']
    unknowns=[row for call in calls for row in call[2] if row['declared_narrative_function']=='open_diligence_status']
    assert unknowns and all(span['knowledge_state']=='unresolved' for row in unknowns for span in row['provenance'])
    assert any(row['declared_narrative_function']=='verification_request' for call in calls for row in call[2])
    assert len(engine.deck_rows(body,'pitch_deck'))<=16 and len(calls)<=12
    (tmp_path/'material_review_request.json').write_text(json.dumps(body))
    (tmp_path/'material_review_budget.json').write_text(json.dumps({'seconds':105}))
    model=TemporalReviewer()
    for _ in calls:result=worker.review_materials(tmp_path,model)
    assert result['state']=='accepted' and result['review']['review_contract']=='semantic_v15'
    assert engine.evaluate_attempts(body,json.loads((tmp_path/'material_review_attempts.json').read_text()))[0]==result
    old=engine.batch_calls(request())[0][4].model_json_schema()
    assert 'temporal_scope_preserved' not in json.dumps(old)


def test_temporal15_false_scope_blocks_even_with_supported_source_relation(tmp_path):
    body=temporal_request()
    (tmp_path/'material_review_request.json').write_text(json.dumps(body))
    (tmp_path/'material_review_budget.json').write_text(json.dumps({'seconds':105}))
    result=worker.review_materials(tmp_path,TemporalReviewer(temporal=False))
    assert result['state']=='blocked' and result['review']['findings'][0]['temporal_scope_preserved'] is False


def test_temporal15_rejects_unbound_or_detached_period():
    body=temporal_request();body['decks']['pitch_deck'][-1][1]=body['decks']['pitch_deck'][-1][1].replace('Mar23 FY23Exit','Current year')
    with pytest.raises(ValueError,match='complete frozen'):engine.batch_calls(body)


def test_semantic16_long_attributed_period_caption_is_versioned(tmp_path):
    body=temporal_request()
    short='The source reported a historical target'
    long='The dated company source reported the historical target period as Mar23 FY23Exit, without demonstrating achieved results.'
    assert 100<len(long)<180
    for deck in body['decks'].values():
        for slide in deck:slide[1]=slide[1].replace(short,long.rstrip('.'))
    with pytest.raises(ValueError,match='complete frozen'):engine.batch_calls(body)
    body['review_contract']='semantic_v16';body.pop('digest');body['digest']=digest(body)
    calls=engine.batch_calls(body)
    (tmp_path/'material_review_request.json').write_text(json.dumps(body))
    (tmp_path/'material_review_budget.json').write_text(json.dumps({'seconds':105}))
    model=TemporalReviewer()
    for _ in calls:result=worker.review_materials(tmp_path,model)
    assert result['state']=='accepted' and result['review']['review_contract']=='semantic_v16'
    attempts=json.loads((tmp_path/'material_review_attempts.json').read_text())
    assert all(row['task']=='material_narrative_review_v16' for row in attempts)
    assert engine.evaluate_attempts(body,attempts)[0]==result


def typed_temporal_request():
    body=temporal_request();body['review_contract']='semantic_v17'
    claim=body['financial_unknown_candidates']['claims'][0]
    quote='The company reports a revenue target. Mar 23 FY23 Exit was the target period.'
    excerpt='Mar 23 FY23 Exit';start=quote.index(excerpt)
    claim['source_quote']=quote
    claim['temporal_evidence']=[{'id':'t1','source_id':'S2','start':start,'end':start+len(excerpt),'exact_text':excerpt,'period_tokens':['Mar 23','FY23']}]
    text='The company describes a future revenue target [S2]. Temporal classification: Historical source-reported target [S2]. Selected period: Mar 23 [S2]. Exact period excerpt: Mar 23 FY23 Exit [S2].'
    for deck in body['decks'].values():
        for slide in deck:
            if 'Exact period excerpt:' in slide[1]:slide[1]=text+'\n'+slide[1].split('\n',1)[1]
    body.pop('digest');body['digest']=digest(body)
    return body


def test_semantic17_exact_typed_temporal_projection_and_independent_gate(tmp_path):
    body=typed_temporal_request();calls=engine.batch_calls(body)
    assert all(len(call[2])<=3 for call in calls) and len(calls)<=12
    (tmp_path/'material_review_request.json').write_text(json.dumps(body))
    (tmp_path/'material_review_budget.json').write_text(json.dumps({'seconds':105}))
    for _ in calls:result=worker.review_materials(tmp_path,TemporalReviewer())
    assert result['state']=='accepted' and result['review']['review_contract']=='semantic_v17'
    changed=typed_temporal_request()
    changed['decks']['pitch_deck'][-1][1]=changed['decks']['pitch_deck'][-1][1].replace('Selected period: Mar 23','Selected period: Mar 24')
    with pytest.raises(ValueError,match='complete frozen'):engine.batch_calls(changed)


class CompactReviewer(Reviewer):
    def __init__(self, false_flag=None):super().__init__();self.false_flag=false_flag
    def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
        assert task=='material_narrative_review_v18' and 'm=matches_declared_function' in instruction
        self.calls+=1;payload=json.loads(evidence)
        reverse={value:key for key,value in engine.FUNCTIONS.items()}
        answer={row['row_id']:{'r':'supported','f':reverse[row['declared_narrative_function']],
            'm':True,'h':True,'p':True,'s':True,'e':True,'t':True,'c':None,
            'why':'This exact unit preserves its declared scope and source evidence.'} for row in payload['rows']}
        if self.false_flag:next(iter(answer.values()))[self.false_flag]=False
        self.last_response_text=json.dumps(answer)
        # LocalModel omits bound_strings telemetry when false, while the
        # immutable request explicitly pins false. This must replay exactly.
        self.last_route={'model':self.name,**{key:value for key,value in engine.COMPACT_OPTIONS.items() if key!='bound_strings'}}
        return schema.model_validate(answer)


def compact_request():
    body=typed_temporal_request();body['review_contract']='semantic_v18'
    body['review_model']={**PIN,'options':engine.COMPACT_OPTIONS};body.pop('digest');body['digest']=digest(body)
    return body


def test_semantic18_compact_wire_projects_all_canonical_flags_and_exact_replay(tmp_path):
    body=compact_request();calls=engine.batch_calls(body)
    assert all(call[3]['batch_size']==2 and len(call[2])<=2 for call in calls) and len(calls)<=12
    (tmp_path/'material_review_request.json').write_text(json.dumps(body))
    (tmp_path/'material_review_budget.json').write_text(json.dumps({'seconds':105}))
    model=CompactReviewer()
    for _ in calls:result=worker.review_materials(tmp_path,model)
    assert result['state']=='accepted' and result['review']['review_contract']=='semantic_v18'
    rows=[row for deck in result['review']['decks'].values() for row in deck['rows']]
    assert all(row['relation']==engine.SUPPORTED and all(row[flag] is True for flag in engine._flags(body)) for row in rows)
    assert all('why' not in row and 20<=len(row['reason'])<=120 for row in rows)
    attempts=json.loads((tmp_path/'material_review_attempts.json').read_text())
    assert all('error' not in row and row['answer']==json.loads(row['raw_response']) for row in attempts)
    from agents.inference.model_authorship import response_answer
    assert all(response_answer(attempts,row['id'])==row['answer'] for row in attempts)
    assert engine.evaluate_attempts(body,attempts)[0]==result
    changed=copy.deepcopy(attempts);changed[0]['routing']['bound_strings']=True
    with pytest.raises(ValueError,match='frozen route'):engine.evaluate_attempts(body,changed)
    old=engine.batch_calls(typed_temporal_request())[0][4].model_json_schema()
    assert 'CompactJudgment' not in old['$defs']


@pytest.mark.parametrize('flag',['m','h','p','s','e','t'])
def test_semantic18_every_compact_semantic_flag_can_independently_block(tmp_path,flag):
    body=compact_request()
    (tmp_path/'material_review_request.json').write_text(json.dumps(body))
    (tmp_path/'material_review_budget.json').write_text(json.dumps({'seconds':105}))
    result=worker.review_materials(tmp_path,CompactReviewer(false_flag=flag))
    assert result['state']=='blocked' and result['review']['findings']


def test_semantic18_missing_flags_full_enum_and_strict_booleans():
    body=compact_request();schema=engine.batch_calls(body)[0][4]
    wire=schema.model_json_schema()['$defs']['CompactJudgment']
    assert set(wire['required'])=={'r','f','m','h','p','s','e','t','c','why'}
    assert set(wire['properties']['f']['enum'])==set(engine.FUNCTIONS)
    value={'r':'supported','f':'request','m':True,'h':True,'p':True,'s':True,'e':True,'t':True,'c':None,'why':'This preserves the exact requested-record scope.'}
    for invalid in ({key:item for key,item in value.items() if key!='t'}, {**value,'t':1}):
        with pytest.raises(ValueError):engine.CompactJudgment.model_validate(invalid)


def test_semantic18_adaptive_plan_retains_all_32_units_in_12_batches(monkeypatch):
    body=compact_request();template=engine.deck_rows(body,'pitch_deck')[0]
    monkeypatch.setattr(engine,'deck_rows',lambda request,deck:[{**template,'deck':deck,'row_id':f'r{index:02d}'} for index in range(1,17)])
    calls=engine.batch_calls(body)
    assert len(calls)==12 and all(call[3]['batch_size']==3 for call in calls)
    assert sum(len(call[2]) for call in calls)==32
    for deck in engine.DECKS:
        assert [row['row_id'] for call in calls if call[1]==deck for row in call[2]]==[f'r{index:02d}' for index in range(1,17)]


class InlineReviewer(CompactReviewer):
    def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
        assert task=='material_narrative_review_v19' and 'm means ONLY' in instruction
        self.calls+=1;payload=json.loads(evidence)
        assert 'provenance' not in payload and 'full_slide_provenance' in payload
        reverse={value:key for key,value in engine.FUNCTIONS_V19.items()}
        answer={}
        for row in payload['rows']:
            assert 'own_provenance' in row and 'provenance_ids' not in row
            assert str(row['slide_index']) in payload['full_slide_provenance']
            answer[row['row_id']]={'r':'supported','f':reverse[row['declared_narrative_function']],
                'm':True,'h':True,'p':True,'s':True,'e':True,'t':True,'c':None,
                'why':'This exact record preserves its declared purpose and evidence.'}
        if self.false_flag:next(iter(answer.values()))[self.false_flag]=False
        self.last_response_text=json.dumps(answer);self.last_route={'model':self.name,**engine.CONTEXT_COMPACT_OPTIONS}
        return schema.model_validate(answer)


def inline_request():
    body=compact_request();body['review_contract']='semantic_v19'
    body['review_model']={**PIN,'options':engine.CONTEXT_COMPACT_OPTIONS};body.pop('digest');body['digest']=digest(body)
    return body


def test_semantic19_exact_inline_own_record_and_separate_full_slide_proof(tmp_path):
    body=inline_request();calls=engine.batch_calls(body)
    questions=[(call,row) for call in calls for row in call[3]['rows'] if row['sentence']=='Open diligence question: '+QUESTION]
    assert questions
    for call,row in questions:
        own=row['own_provenance']
        assert all(span['kind']=='reviewed_unknown' and span['source_verification_status']=='accepted_question_record' and span['knowledge_state']=='unresolved' for span in own)
        assert own[0]['question']==QUESTION and own[0]['evidence_needed']==NEEDED
        full=call[3]['full_slide_provenance'][str(row['slide_index'])]
        assert any(span.get('source_id')=='[S2]' and 'Mar 23 FY23 Exit' in span['exact_source_quote'] for span in full)
        assert not any(span.get('source_id')=='[S2]' for span in own)
    schema=calls[0][4].model_json_schema()['$defs']['ContextCompactJudgment']
    assert set(schema['properties']['f']['enum']) == set(engine.FUNCTIONS_V19)
    assert any(row['declared_narrative_function']=='requested_record_list' for call in calls for row in call[3]['rows'])
    assert schema['properties']['why']['maxLength']==80 and schema['properties']['c']['anyOf'][0]['maxLength']==120
    (tmp_path/'material_review_request.json').write_text(json.dumps(body));(tmp_path/'material_review_budget.json').write_text(json.dumps({'seconds':105}))
    for _ in calls:result=worker.review_materials(tmp_path,InlineReviewer())
    assert result['state']=='accepted'
    attempts=json.loads((tmp_path/'material_review_attempts.json').read_text())
    assert all('error' not in row and row['answer']==json.loads(row['raw_response']) and row['routing']['bound_strings'] is True for row in attempts)
    assert engine.evaluate_attempts(body,attempts)[0]==result
    changed=copy.deepcopy(attempts);changed[0]['input']['rows'][0]['own_provenance']=[]
    with pytest.raises(ValueError,match='frozen route'):engine.evaluate_attempts(body,changed)
    old=engine.batch_calls(compact_request())
    assert all('provenance' in call[3] and 'full_slide_provenance' not in call[3] for call in old)
    assert old[0][4].model_json_schema()['$defs']['CompactJudgment']['properties']['why']['maxLength']==120


@pytest.mark.parametrize('flag',['m','h','p','s','e','t'])
def test_semantic19_scope_proof_separation_does_not_waive_any_flag(tmp_path,flag):
    body=inline_request();(tmp_path/'material_review_request.json').write_text(json.dumps(body));(tmp_path/'material_review_budget.json').write_text(json.dumps({'seconds':105}))
    result=worker.review_materials(tmp_path,InlineReviewer(false_flag=flag))
    assert result['state']=='blocked' and result['review']['findings']


def test_semantic19_worker_uses_bound_true_and_preserves_grammar_limits(tmp_path,monkeypatch):
    from agents.inference.local_models import generation_schema
    body=inline_request();calls=engine.batch_calls(body)
    grammar=generation_schema(calls[0][4],bound_strings=True)
    assert grammar['$defs']['ContextCompactJudgment']['properties']['why']['maxLength']==80
    (tmp_path/'material_review_request.json').write_text(json.dumps(body));(tmp_path/'material_review_budget.json').write_text(json.dumps({'seconds':105}))
    constructed=[]
    def model(name,**options):
        constructed.append((name,options));return InlineReviewer()
    monkeypatch.setattr(worker,'LocalModel',model)
    result=worker.review_materials(tmp_path)
    assert result['state']=='needs_resume' and constructed==[('qwen3:14b',engine.CONTEXT_COMPACT_OPTIONS)]


class FullInlineReviewer(InlineReviewer):
    def __init__(self,false_flag=None,malformed_hypothesis=False):super().__init__(false_flag);self.malformed_hypothesis=malformed_hypothesis
    def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
        assert task=='material_narrative_review_v20' and 'prospective effect does not require' in instruction
        self.calls+=1;payload=json.loads(evidence);answer={}
        for row in payload['rows']:
            value={'r':engine.SUPPORTED,'f':row['declared_narrative_function'],
                   'm':True,'h':True,'p':True,'s':True,'e':True,'t':True,'c':None,
                   'why':'This exact unit preserves its declared function and source scope.'}
            if self.false_flag:value[self.false_flag]=False
            if self.malformed_hypothesis and row['declared_narrative_function']=='conditional_hypothesis':value['r']='unsupported_assertion'
            answer[row['row_id']]=value
        self.last_response_text=json.dumps(answer);self.last_route={'model':self.name,**engine.CONTEXT_COMPACT_OPTIONS}
        return schema.model_validate(answer)


def full_inline_request():
    body=inline_request();body['review_contract']='semantic_v20';body.pop('digest');body['digest']=digest(body);return body


def test_semantic20_full_value_wire_keeps_raw_identity_and_no_relation_override(tmp_path):
    body=full_inline_request();calls=engine.batch_calls(body)
    (tmp_path/'material_review_request.json').write_text(json.dumps(body));(tmp_path/'material_review_budget.json').write_text(json.dumps({'seconds':105}))
    for _ in calls:result=worker.review_materials(tmp_path,FullInlineReviewer())
    assert result['state']=='accepted'
    attempts=json.loads((tmp_path/'material_review_attempts.json').read_text())
    assert all(row['answer']==json.loads(row['raw_response']) and 'error' not in row for row in attempts)
    assert all(value['r']==engine.SUPPORTED and value['f'] in engine.FUNCTIONS_V19.values() for row in attempts for value in row['answer'].values())
    assert engine.evaluate_attempts(body,attempts)[0]==result
    wire=calls[0][4].model_json_schema()['$defs']['FullContextCompactJudgment']
    assert set(wire['properties']['f']['enum'])==set(engine.FUNCTIONS_V19.values())
    assert set(wire['properties']['r']['enum'])==set(engine.RELATIONS.values())
    old=engine.batch_calls(inline_request())[0][4].model_json_schema()['$defs']['ContextCompactJudgment']
    assert set(old['properties']['r']['enum'])==set(engine.RELATIONS)


def test_semantic20_unsupported_null_clause_still_blocks_hypothesis(tmp_path):
    body=full_inline_request();calls=engine.batch_calls(body)
    (tmp_path/'material_review_request.json').write_text(json.dumps(body));(tmp_path/'material_review_budget.json').write_text(json.dumps({'seconds':105}))
    model=FullInlineReviewer(malformed_hypothesis=True)
    for _ in calls:
        result=worker.review_materials(tmp_path,model)
        if result['state']=='blocked':break
    assert result['state']=='blocked' and result['reason']=='narrative_review_malformed'
    attempts=json.loads((tmp_path/'material_review_attempts.json').read_text())
    assert any(value['r']=='unsupported_assertion' and value['c'] is None for row in attempts for value in row['answer'].values())


def test_semantic20_deduplicates_only_identical_proof_preserving_distinct_sets():
    body=full_inline_request();packet=body['memo_assertion_candidates'];risk=packet['slots']['risk'][0]
    packet['slots']['risk'] += [copy.deepcopy(risk),copy.deepcopy(risk)]
    older={**body,'review_contract':'semantic_v19'}
    old=engine.deck_rows(older,'intro_deck');new=engine.deck_rows(body,'intro_deck')
    assert len(old)==len(new)
    for before,after in zip(old,new):
        assert {digest(span) for span in before['provenance']} == {digest(span) for span in after['provenance']}
        assert len(after['provenance'])==len({digest(span) for span in before['provenance']})
    assert any(len(before['provenance'])>len(after['provenance']) for before,after in zip(old,new))


@pytest.mark.parametrize('flag',['m','h','p','s','e','t'])
def test_semantic20_full_relations_do_not_waive_independent_flags(tmp_path,flag):
    body=full_inline_request();(tmp_path/'material_review_request.json').write_text(json.dumps(body));(tmp_path/'material_review_budget.json').write_text(json.dumps({'seconds':105}))
    result=worker.review_materials(tmp_path,FullInlineReviewer(false_flag=flag))
    assert result['state']=='blocked' and result['review']['findings']
