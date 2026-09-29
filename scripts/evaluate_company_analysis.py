"""Bounded fresh analysis evaluation in an isolated, temporary database.

Reuse only a live company's retained public source collection, never its draft,
private workspace records or previous model responses. --fresh-research also
runs public search/fetch. Does not replace the live report. Output retains the
exact prompts, model responses, validation outcome and timing for inspection.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.company_analysis import run_analysis_loop, analysis_view, public_basis
from agents.operating_workflow import reconcile_workspace
from agents.public_research import fresh_collection
from schemas import CompanyProfile, SourcedLead, utcnow
from store import Store
from workflow_schemas import AutomationRun


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lead-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fresh-research', action='store_true')
    args = parser.parse_args()
    with Store() as live:
        original = live.get_lead('default_tenant', args.lead_id)
        if not original:
            raise ValueError('Company not found')
        workspace = live.get_workspace('default_tenant', lead_id=original.id)
        retained = workspace.company_analysis if workspace else {}
        profile = CompanyProfile(tenant_id='evaluation', name=original.company_name,
                                 website=original.company_profile.website)
        sources = retained.get('sources', [])
        collected = retained.get('source_collected_at', retained.get('at'))
        if not args.fresh_research and (not sources or not fresh_collection({'at': collected})
                or retained.get('public_basis') != public_basis(workspace)):
            raise ValueError('No current public collection; use --fresh-research.')
    with tempfile.TemporaryDirectory(prefix='company-analysis-eval-') as directory:
        with Store(Path(directory) / 'evaluation.sqlite3') as store:
            lead = SourcedLead(tenant_id='evaluation', company_id=profile.id,
                              company_name=profile.name, company_profile=profile)
            store.save_company(profile)
            store.save_lead(lead)
            w = reconcile_workspace(store, lead)
            w.automation = AutomationRun(model='evaluation', worker_id='evaluation', status='running')
            if not args.fresh_research:
                w.company_analysis = {'at': utcnow(), 'source_collected_at': collected,
                    'public_basis': public_basis(w), 'sources': sources}
            store.save_workspace(w, expected_revision=w.revision)
            error = None
            try:
                run_analysis_loop(store, lead, w.automation.id)
            except Exception as exc:
                error = str(exc)
            result = store.get_workspace(lead.tenant_id, workspace_id=w.id)
            report = result.company_analysis
            output = {'company': profile.name, 'evaluation': 'fresh_search_and_draft' if args.fresh_research
                      else 'fresh_draft_from_retained_public_sources', 'error': error,
                      'published': bool(analysis_view(result).get('answer')), 'analysis': report}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(output, indent=2))
            print(json.dumps({k: v for k, v in output.items() if k != 'analysis'}))
            print(json.dumps({'budget': report.get('budget'), 'retry_loop':report.get('retry_loop'), 'issues': report.get('issues')}))
            return 0 if output['published'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
