"""Opt-in, isolated first-pass diagnostic. Never used by the application API.

Accepts a reviewed public-evidence snapshot. Pro uses the official CLI login,
with tools/customizations disabled. Repairs require --allow-repairs and share
the same time/call ceiling. No API key or cloud fallback.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agents.analyst_pack import prepare_analyst_pack, export_pack
from agents.authored_preparation import validate_authored_pack
from agents.local_models import AnalystModel
from agents.model_authorship import digest
from agents.preparation_budget import PreparationBudget, PreparationBudgetExceeded
from schemas import CompanyEvidence, CompanyProfile, SourcedLead
from store import Store


class FirstPassModel:
    def __init__(self, provider, directory, *, combined_draft=False, reasoned_review=False,
                 model_name='qwen3.5:9b', thinking=False, natural_reasoning=False, allow_repairs=False):
        self.provider = provider
        self.allow_repairs = allow_repairs
        self.directory = directory
        self.name = 'claude-pro-sonnet' if provider == 'pro' else model_name
        self.thinking = thinking
        self.authored_natural_reasoning = natural_reasoning
        self.combined_draft = combined_draft
        self.shared_review_thinking = reasoned_review
        self.local = AnalystModel(self.name, thinking=thinking, review_thinking=reasoned_review) if provider == 'local' else None
        if self.local:
            self.local.authored_natural_reasoning = natural_reasoning
        self.calls = 0
        self.last_route = {}
        self.last_response_text = ''
        self.public_only = provider == 'pro'
        from agents.subscription_model import ClaudeProModel
        self.pro = ClaudeProModel(capture=lambda raw: (self.directory / ('call-' + str(self.calls) + '.json')).write_text(raw)) if self.public_only else None

    def check_subscription(self):
        if self.pro:
            self.pro.check_subscription()

    def set_public_context(self, company, facts):
        self.pro.set_public_context(company, facts)

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        self.last_response_text = ''
        self.last_route = {'invoked': False, 'provider': self.provider}
        if (attempt and not self.allow_repairs) or self.calls >= (6 if self.allow_repairs else 4):
            raise PreparationBudgetExceeded('Diagnostic call limit reached; first-pass mode does not allow corrections.')
        self.calls += 1
        if self.local:
            try:
                return self.local.generate_for_task(task, instruction, evidence, schema, attempt=attempt)
            finally:
                self.last_response_text = self.local.last_response_text
                self.last_route = {'invoked': True, **self.local.last_route}

        try:
            return self.pro.generate_for_task(task, instruction, evidence, schema, attempt=attempt)
        finally:
            self.last_response_text = self.pro.last_response_text
            self.last_route = dict(self.pro.last_route)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', required=True, choices=['pro', 'local'])
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--combined-draft', action='store_true')
    parser.add_argument('--reasoned-review', action='store_true')
    parser.add_argument('--model', default='qwen3.5:9b')
    parser.add_argument('--thinking', action='store_true')
    parser.add_argument('--natural-reasoning', action='store_true')
    parser.add_argument('--allow-repairs', action='store_true', help='Exercise the normal six-call workflow, still bounded to 120 seconds.')
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text())
    if snapshot.get('scope') != 'reviewed_public_evidence_only':
        parser.error('Use an explicitly reviewed public-only snapshot.')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    model = FirstPassModel(args.provider, out, combined_draft=args.combined_draft, reasoned_review=args.reasoned_review,
                           model_name=args.model, thinking=args.thinking, natural_reasoning=args.natural_reasoning, allow_repairs=args.allow_repairs)
    model.check_subscription()
    report = {'provider': args.provider, 'snapshot_hash': digest(snapshot), 'live_data_updated': False,
              'scope': 'bounded_complete_workflow' if args.allow_repairs else 'first_pass_no_repairs', 'independent_quality_audit': None,
              'transport_difference': 'Pro prompt-only JSON; local Ollama constrained JSON. Same application task/schema/evidence.'}
    with tempfile.TemporaryDirectory() as temporary, Store(Path(temporary) / 'isolated.db') as store:
        profile = CompanyProfile(tenant_id='evaluation', name=snapshot['company'], website=snapshot['website'],
                                 evidence=[CompanyEvidence(**e) for e in snapshot['evidence']])
        lead = SourcedLead(tenant_id='evaluation', company_id=profile.id, company_name=profile.name, company_profile=profile)
        store.save_company(profile)
        store.save_lead(lead)
        budget = PreparationBudget(max_seconds=120, max_calls=6 if args.allow_repairs else 4, max_requests=6 if args.allow_repairs else 4)
        def progress(pack):
            report.update(pack=pack, actual_calls=model.calls, budget=budget.snapshot())
            (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        try:
            workspace = prepare_analyst_pack(store, lead, model, progress, budget=budget)
        except Exception as exc:
            report['harness_error'] = type(exc).__name__ + ': ' + str(exc)
            workspace = store.get_workspace(lead.tenant_id, lead_id=lead.id)
            if workspace is None:
                (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
                raise
        validate_authored_pack(workspace.analyst_pack)
        progress(workspace.analyst_pack)
        (out / 'draft.md').write_text(export_pack(workspace.analyst_pack))
        print(json.dumps({'provider': args.provider, 'status': workspace.analyst_pack['status'],
                          'actual_calls': model.calls, 'elapsed_seconds': budget.snapshot()['elapsed_seconds'],
                          'stop_reason': workspace.analyst_pack.get('stop_reason'),
                          'metrics': workspace.analyst_pack.get('generation_metrics')}), flush=True)


if __name__ == '__main__':
    main()
