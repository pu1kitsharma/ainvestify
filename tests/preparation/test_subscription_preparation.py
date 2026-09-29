import json
from unittest.mock import Mock

import pytest
from pydantic import BaseModel

from agents.preparation.preparation_budget import PreparationBudget, preparation_budget
from agents.preparation.preparation_sources import inference_facts, is_public_source
from agents.inference.subscription_model import ClaudeProModel, PRO_MODEL, make_preparation_model


PUBLIC = {'id': 'S1', 'quote': 'The public website describes hotel operations.',
          'source_url': 'https://example.com/', 'origin': 'public_page_claim', 'status': 'source_reported'}


class Result(BaseModel):
    text: str


def payload():
    return json.dumps({'company': 'Example', 'request': {}, 'facts': inference_facts([PUBLIC])})


def test_subscription_payload_rejects_private_context_before_starting_cli(monkeypatch):
    start = Mock(); monkeypatch.setattr('agents.inference.subscription_model.subprocess.Popen', start)
    model = ClaudeProModel(); model.set_public_context('Example', [PUBLIC])
    for key, value in [('request', 'PRIVATE NOTE'), ('uploads', ['PRIVATE RECORD']), ('facts', [{'quote': 'PRIVATE FIGURES'}])]:
        data = json.loads(payload()); data[key] = value
        with preparation_budget(PreparationBudget(1)):
            with pytest.raises(ValueError, match='approved public evidence'):
                model.generate_for_task('authored_draft', 'Write', json.dumps(data), Result)
    start.assert_not_called()


def test_subscription_limit_keeps_reset_time_and_is_not_a_formatting_retry(monkeypatch):
    from agents.inference.subscription_model import SubscriptionLimitError
    model=ClaudeProModel();model.set_public_context('Example',[PUBLIC]);model._authenticated=True
    process=Mock();process.returncode=1;process.poll.return_value=1
    raw="You've hit your session limit · resets 6:20pm (Asia/Calcutta)"
    process.communicate.return_value=(json.dumps([{'type':'result','is_error':True,'result':raw}]),'')
    start=Mock(return_value=process);monkeypatch.setattr('agents.inference.subscription_model.subprocess.Popen',start)
    with preparation_budget(PreparationBudget(10)):
        with pytest.raises(SubscriptionLimitError,match='6:20pm'):
            model.generate_for_task('authored_draft','Write',payload(),Result)
    assert start.call_count==1
    assert model.last_response_text==raw


def test_unexpected_provider_model_is_rejected_without_fallback(monkeypatch):
    from agents.inference.subscription_model import SubscriptionModelError
    model=ClaudeProModel();model.set_public_context('Example',[PUBLIC]);model._authenticated=True
    raw=json.dumps({'text':'Unexpected model output'})
    process=Mock();process.returncode=0;process.poll.return_value=0
    process.communicate.return_value=(json.dumps([
        {'type':'assistant','message':{'id':'one','model':'unexpected-model','content':[{'type':'text','text':raw}]}},
        {'type':'result','num_turns':1,'result':raw}]),'')
    start=Mock(return_value=process);monkeypatch.setattr('agents.inference.subscription_model.subprocess.Popen',start)
    with preparation_budget(PreparationBudget(10)):
        with pytest.raises(SubscriptionModelError):model.generate_for_task('authored_draft','Write',payload(),Result)
    assert start.call_count==1 and model.last_route['response_models']==['unexpected-model']


def test_official_cli_has_no_api_overrides_tools_or_project_context(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'SECRET_NOT_TO_SEND')
    monkeypatch.setenv('CLAUDE_CODE_OAUTH_TOKEN', 'SECRET_NOT_TO_SEND')
    model = ClaudeProModel(); model.set_public_context('Example', [PUBLIC]); model._authenticated = True
    process = Mock(); process.returncode = 0; process.poll.return_value = 0
    output={'text':'Model authored response'}
    process.communicate.return_value = (json.dumps([
        {'type':'assistant','message':{'id':'message1','content':[{'type':'text','text':json.dumps(output)}]}},
        {'type':'result','num_turns':1,'result':json.dumps(output),'modelUsage':{}}
    ]), '')
    start = Mock(return_value=process); monkeypatch.setattr('agents.inference.subscription_model.subprocess.Popen', start)
    with preparation_budget(PreparationBudget(1)) as budget:
        assert model.generate_for_task('authored_draft', 'Write', payload(), Result).text == 'Model authored response'
    args, kwargs = start.call_args
    assert args[0][args[0].index('--model')+1]=='claude-sonnet-5'
    assert args[0][args[0].index('--tools')+1] == ''
    assert '--json-schema' not in args[0] and args[0][args[0].index('--max-turns')+1]=='1'
    assert '--safe-mode' in args[0] and '--no-session-persistence' in args[0]
    assert not any(k.startswith(('ANTHROPIC_', 'CLAUDE_')) for k in kwargs['env'])
    assert kwargs['start_new_session'] is True
    assert 'deal_document' not in kwargs['cwd']
    assert budget.requests == 1


def test_native_schema_rejects_unrecorded_result_or_hidden_repair_turn(monkeypatch):
    model=ClaudeProModel();model.set_public_context('Example',[PUBLIC]);model._authenticated=True
    model.native_structured_output = True
    output={'text':'Original model answer'}
    message={'type':'assistant','message':{'id':'one','content':[{'type':'tool_use','name':'StructuredOutput','input':output}]}}
    result={'type':'result','num_turns':2,'result':json.dumps(output),'structured_output':output}
    for transcript in ([message,{**result,'structured_output':{'text':'Changed answer'}}],
                       [message,{'type':'assistant','message':{'id':'two','content':[]}},result]):
        process=Mock();process.returncode=0;process.poll.return_value=0
        process.communicate.return_value=(json.dumps(transcript),'')
        monkeypatch.setattr('agents.inference.subscription_model.subprocess.Popen',Mock(return_value=process))
        with preparation_budget(PreparationBudget(10)):
            with pytest.raises(ValueError,match='bounded model response'):
                model.generate_for_task('authored_draft','Write',payload(),Result)


def test_plain_json_rejects_changed_results_and_unrecorded_extra_turns(monkeypatch):
    model = ClaudeProModel(); model.set_public_context('Example', [PUBLIC]); model._authenticated = True
    original = json.dumps({'text': 'Original answer'})
    message = {'type': 'assistant', 'message': {'id': 'one', 'content': [{'type': 'text', 'text': original}]}}
    for result in [
        {'type': 'result', 'num_turns': 1, 'result': json.dumps({'text': 'Changed answer'})},
        {'type': 'result', 'num_turns': 2, 'result': original},
    ]:
        process = Mock(); process.returncode = 0; process.poll.return_value = 0
        process.communicate.return_value = (json.dumps([message, result]), '')
        monkeypatch.setattr('agents.inference.subscription_model.subprocess.Popen', Mock(return_value=process))
        with preparation_budget(PreparationBudget(10)):
            with pytest.raises(ValueError, match='one recorded tool-free'):
                model.generate_for_task('authored_draft', 'Write', payload(), Result)


def test_invalid_native_tool_object_is_retained_as_schema_error(monkeypatch):
    from pydantic import ValidationError
    model=ClaudeProModel();model.set_public_context('Example',[PUBLIC]);model._authenticated=True
    model.native_structured_output = True
    invalid={'wrong_key':'Actual model text'}
    transcript=[{'type':'assistant','message':{'id':'one','content':[{'type':'tool_use','name':'StructuredOutput','input':invalid}]}},
                {'type':'result','num_turns':2,'is_error':True,'subtype':'error_max_turns'}]
    process=Mock();process.returncode=1;process.poll.return_value=1
    process.communicate.return_value=(json.dumps(transcript),'')
    monkeypatch.setattr('agents.inference.subscription_model.subprocess.Popen',Mock(return_value=process))
    with preparation_budget(PreparationBudget(10)):
        with pytest.raises(ValidationError):model.generate_for_task('authored_draft','Write',payload(),Result)
    assert json.loads(model.last_response_text)==invalid


def test_private_sources_and_private_hosts_are_excluded():
    assert is_public_source(PUBLIC)
    for patch in ({'origin': 'company_reported'}, {'origin': 'manual'}, {'source_url': 'file:///private/report'},
                  {'source_url': 'http://127.0.0.1/report'}, {'source_url': 'http://company.internal/report'},
                  {'source_url': 'https://user:password@example.com/report'}):
        assert not is_public_source({**PUBLIC, **patch})


def test_public_context_keeps_model_selected_claim_and_full_directory_context(tmp_path):
    from tests.analysis.test_operating_workflow import company
    from agents.analysis.operating_workflow import reconcile_workspace
    from agents.preparation.preparation_sources import source_record
    from store import Store
    with Store(tmp_path/'test.db') as store:
        lead = company(store)
        e = lead.company_profile.evidence[0]
        e.field = 'offering'; e.value = 'operates hotels'
        e.quote = 'Previous Company makes booking software. Hotel Example operates hotels with independent property contracts.'
        e.source_url = 'https://example.com/directory'; e.origin = 'public_page_claim'
        store.save_company(lead.company_profile); store.save_lead(lead)
        w = reconcile_workspace(store, lead)
        records = source_record(lead, w, public_only=True)['facts']
        selected = next(f for f in records if f['source_id'] == e.id)
        assert selected['quote'] == e.quote
        assert selected['selected_claim'] == e.value
        assert inference_facts([selected])[0]['selected_claim'] == e.value


def test_public_workflow_omits_private_evidence_and_workspace_notes(tmp_path):
    from tests.preparation.test_authored_preparation import CombinedModel
    from tests.analysis.test_operating_workflow import company
    from agents.analysis.analyst_pack import prepare_analyst_pack
    from agents.analysis.operating_workflow import reconcile_workspace
    from schemas import CompanyEvidence
    from store import Store
    class PublicModel(CombinedModel):
        public_only = True
        def set_public_context(self, name, facts):
            assert all(is_public_source(fact) for fact in facts)
        def generate_for_task(self, task, instruction, evidence, schema, **kwargs):
            assert 'PRIVATE_SENTINEL' not in evidence
            assert json.loads(evidence)['request'] == {}
            return super().generate_for_task(task, instruction, evidence, schema, **kwargs)
    with Store(tmp_path/'test.db') as store:
        lead = company(store)
        for evidence in lead.company_profile.evidence:
            evidence.source_url = 'https://example.com/'
        lead.company_profile.evidence.append(CompanyEvidence(field='business_model', value='PRIVATE_SENTINEL',
            quote='PRIVATE_SENTINEL internal financial plan and reported profitability.', origin='company_reported', source_url='https://example.com/private'))
        store.save_company(lead.company_profile); store.save_lead(lead)
        w = reconcile_workspace(store, lead, thesis='PRIVATE_SENTINEL thesis and preferences')
        w.events.append({'detail': 'PRIVATE_SENTINEL history'}); store.save_workspace(w, expected_revision=w.revision)
        pack = prepare_analyst_pack(store, lead, PublicModel()).analyst_pack
        assert pack['status'] == 'complete', pack.get('stop_reason')
        assert 'PRIVATE_SENTINEL' not in json.dumps(pack['attempts'])
        assert pack['generation_config']['public_only'] is True


def test_approved_default_uses_pro_but_explicit_local_selection_stays_local(monkeypatch):
    monkeypatch.delenv('PREPARATION_PROVIDER', raising=False)
    assert make_preparation_model().name == PRO_MODEL
    assert make_preparation_model('qwen3.5:9b').name == 'qwen3.5:9b'
    monkeypatch.setenv('PREPARATION_PROVIDER', 'local')
    assert make_preparation_model().name != PRO_MODEL


def test_deadline_terminates_the_cli_process_instead_of_leaving_it_running(monkeypatch):
    import subprocess
    import sys
    import time
    from agents.preparation.preparation_budget import PreparationBudgetExceeded
    original = subprocess.Popen
    children = []
    def start(command, **kwargs):
        child = original([sys.executable, '-c', 'import time; time.sleep(10)'], **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr('agents.inference.subscription_model.subprocess.Popen', start)
    model = ClaudeProModel(); model._authenticated = True; model.set_public_context('Example', [PUBLIC])
    started = time.monotonic()
    with preparation_budget(PreparationBudget(.05)):
        with pytest.raises(PreparationBudgetExceeded):
            model.generate_for_task('authored_draft', 'Write', payload(), Result)
    assert time.monotonic() - started < 1.5
    assert children and children[0].poll() is not None
    assert model.last_response_text == ''


def test_subscription_auth_failure_never_falls_back_to_an_api_key(monkeypatch):
    monkeypatch.setattr('agents.inference.subscription_model.subprocess.run', Mock(return_value=Mock(returncode=0, stdout='{"loggedIn":false}')))
    start = Mock(); monkeypatch.setattr('agents.inference.subscription_model.subprocess.Popen', start)
    model = ClaudeProModel(); model.set_public_context('Example', [PUBLIC])
    with preparation_budget(PreparationBudget(1)) as budget:
        with pytest.raises(RuntimeError, match='not signed in'):
            model.generate_for_task('authored_draft', 'Write', payload(), Result)
    assert budget.requests == 0
    start.assert_not_called()


@pytest.mark.parametrize('always_fails', [False, True])
def test_interrupted_connection_gets_only_one_recorded_budgeted_retry(monkeypatch, always_fails):
    from agents.inference.model_authorship import recorded_call
    from agents.inference.subscription_model import TransientSubscriptionError
    model = ClaudeProModel(); model.set_public_context('Example', [PUBLIC]); model._authenticated = True
    error = [{'type': 'result', 'is_error': True, 'num_turns': 1,
              'result': 'API Error: Connection closed mid-response. The response above may be incomplete.'}]
    answer = {'text': 'Recorded model answer'}
    success = [{'type': 'assistant', 'message': {'id': 'one', 'content': [
        {'type': 'text', 'text': json.dumps(answer)}]}},
        {'type': 'result', 'num_turns': 1, 'result': json.dumps(answer)}]
    processes = []
    for transcript in [error, error if always_fails else success]:
        process = Mock(); process.returncode = 0; process.poll.return_value = 0
        process.communicate.return_value = (json.dumps(transcript), '')
        processes.append(process)
    start = Mock(side_effect=processes)
    monkeypatch.setattr('agents.inference.subscription_model.subprocess.Popen', start)
    attempts = []
    with preparation_budget(PreparationBudget(10)) as budget:
        if always_fails:
            with pytest.raises(TransientSubscriptionError):
                recorded_call(model, 'authored_draft', 'Write', json.loads(payload()), Result, attempts, lambda: None)
        else:
            result, reference = recorded_call(model, 'authored_draft', 'Write', json.loads(payload()), Result, attempts, lambda: None)
            assert result.text == answer['text'] and reference == attempts[1]['id']
    assert start.call_count == 2 and budget.calls == budget.requests == 2
    assert len(attempts) == 2 and 'interrupted' in attempts[0]['error']
    assert attempts[0]['input'] == attempts[1]['input']
