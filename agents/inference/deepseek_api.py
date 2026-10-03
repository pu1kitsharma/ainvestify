"""Bounded public-only reasoning; no Claude harness or hosted private fallback."""
import json
import os
from pathlib import Path
import subprocess
import sys

from agents.inference.public_contract import PublicEvidenceModel
from agents.inference.public_cache import PublicResultCache, cache_key
from agents.preparation.preparation_budget import ACTIVE_BUDGET
from agents.inference.spend_guard import reserve_monthly

PREFIX = 'deepseek-api:'


def model_name():
    return PREFIX + 'deepseek-flash'


def run_public(model, task, instruction, evidence, schema):
    """Call only after the caller's public-evidence manifest has been checked."""
    budget = ACTIVE_BUDGET.get()
    if budget is None:
        raise ValueError('Public API inference requires a bounded job budget.')
    settings = {'max_tokens':6000,'thinking':{'type':'enabled'},'reasoning_effort':'high'}
    cache = PublicResultCache()
    if not cache.url:
        raise ValueError('Configure local ELASTICSEARCH_URL before paid reasoning. Uncached paid generation is disabled.')
    key = cache_key(model.name, task, instruction, evidence, schema,
                    {**settings,'provider_contract':'deepseek-flash-2026-09-30-v1'})
    model.last_route = {'provider':'deepseek_api','model':model.name,'invoked':False,
                        'data_scope':'public_website_evidence','cache_key':key}
    hit = cache.get(key, schema)
    if hit:
        budget.cache_hits += 1
        model.last_response_text = hit['raw_response']
        model.last_route.update(cache_hit=True, usage={}, cost_usd=0, original_usage=hit['usage'])
        return schema.model_validate_json(model.last_response_text)
    model.last_route['cache_hit'] = False
    secret = os.environ.get('DEEPSEEK_API_KEY', '')
    if not secret and os.environ.get('DEEPSEEK_API_KEY_FILE'):
        secret = Path(os.environ['DEEPSEEK_API_KEY_FILE']).read_text().strip()
    if not secret:
        raise ValueError('Configure server-side DEEPSEEK_API_KEY or DEEPSEEK_API_KEY_FILE. Private data remains local; no Claude fallback.')
    lease = cache.claim(key)
    # A previous worker may have completed between lookup and lease acquisition.
    hit = cache.get(key, schema)
    if hit:
        budget.cache_hits += 1
        cache.release(key, lease)
        model.last_response_text = hit['raw_response']
        model.last_route.update(cache_hit=True, usage={}, cost_usd=0, original_usage=hit['usage'])
        return schema.model_validate_json(model.last_response_text)
    body = {'model':'deepseek-flash', **settings, 'response_format':{'type':'json_object'},
        'messages':[{'role':'system','content':instruction+'\nReturn only JSON matching this schema: '+json.dumps(schema.model_json_schema())},
                    {'role':'user','content':evidence}]}
    # Conservative byte-based input bound and peak list prices, 30 Sep 2026.
    # Reserve the full bound on errors too; never retry after a lost response.
    bound = (len(json.dumps(body).encode()) * .30 + settings['max_tokens'] * 1.20) / 1_000_000
    budget.reserve_cost(bound)
    budget.start_request()
    model.last_route['spend_reservation'] = reserve_monthly(bound,key)
    env = {k:v for k,v in os.environ.items() if k in {'PATH','LANG','SSL_CERT_FILE','SSL_CERT_DIR'}}
    env['DEEPSEEK_API_KEY'] = secret
    process = subprocess.Popen([sys.executable,'-m','agents.inference.deepseek_http_worker'],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env,
        cwd=str(Path(__file__).resolve().parents[2]))
    model.last_route.update(invoked=True, reserved_cost_usd=bound)
    pending = json.dumps(body)
    try:
        while True:
            if getattr(model,'on_activity',None):model.on_activity('generating',0,task)
            try:
                stdout, _ = process.communicate(input=pending, timeout=min(1,budget.remaining()))
                break
            except subprocess.TimeoutExpired:
                pending = None
    finally:
        if process.poll() is None:
            process.kill();process.communicate()
    try:
        data = json.loads(stdout)
    except ValueError:
        raise ValueError('Public reasoning returned an unreadable response; no automatic retry.') from None
    if process.returncode or data.get('error'):
        raise ValueError('Public reasoning API unavailable (HTTP %s); check credentials and credit. No fallback.' % data.get('status','transport'))
    model.last_response_text = data.get('content') or ''
    model.last_route.update(usage=data.get('usage',{}), response_id=data.get('id'), served_model=data.get('model'))
    if data.get('model') != 'deepseek-flash':
        raise ValueError('Public reasoning returned an unexpected model; original output is retained without publishing.')
    if data.get('finish_reason') != 'stop' or data.get('tool_calls'):
        raise ValueError('Public reasoning response was incomplete or attempted an unapproved tool.')
    result = schema.model_validate_json(model.last_response_text)
    if json.loads(model.last_response_text) != result.model_dump(mode='json'):
        raise ValueError('Public reasoning answer differs from its validated projection.')
    cache.put(key, model.last_response_text, model.name, data.get('usage',{}))
    cache.release(key, lease)
    return result


class DeepSeekPublicModel(PublicEvidenceModel):
    """Public drafting with a provider-neutral boundary and no CLI dependency."""
    name = model_name()

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        self.last_response_text = ''
        self.last_route = {'invoked':False,'provider':'deepseek_api'}
        if task not in {'authored_draft','authored_research','authored_work','authored_founder','authored_review'}:
            raise ValueError('Unsupported public drafting task.')
        self._check_payload(evidence)
        return run_public(self, task, instruction, evidence, schema)
