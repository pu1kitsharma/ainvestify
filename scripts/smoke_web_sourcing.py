"""Explicit live smoke check; uses public pages, local Ollama and a temporary DB.

python3 scripts/smoke_web_sourcing.py https://company.example/ --fetch-only
python3 scripts/smoke_web_sourcing.py https://company.example/
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.company_sourcing import source_companies
from agents.local_models import LocalModel
from agents.web_discovery import discover_pages
from agents.web_sources import PublicWebFetcher, SourceError
from schemas import WebSourcingRun
from store import Store

parser = argparse.ArgumentParser()
parser.add_argument("url", nargs="?")
parser.add_argument("--brief", default="Identify operating companies across sectors worth incubation support; establish demand and missing evidence.")
parser.add_argument("--geography", default="India")
parser.add_argument("--discover-only", action="store_true")
parser.add_argument("--fetch-only", action="store_true")
parser.add_argument("--max-pages", type=int, default=1)
parser.add_argument("--diagnose", action="store_true", help="Print public-page extraction output for debugging")
args = parser.parse_args()


class DiagnosticModel(LocalModel):
    def generate(self, instruction, evidence, schema):
        if args.diagnose:
            payload = json.loads(evidence)
            if "PAGE_BLOCKS" in payload:
                print(json.dumps({"page_blocks": payload["PAGE_BLOCKS"],
                                  "links": payload["PAGE_LINKS"][:10]}, indent=2), flush=True)
        result = super().generate(instruction, evidence, schema)
        if args.diagnose:
            print(result.model_dump_json(indent=2), flush=True)
        return result

if args.discover_only:
    run = WebSourcingRun(tenant_id="smoke", thesis=args.brief, geography=args.geography or None, model="local")
    urls = discover_pages(run, DiagnosticModel(), None, lambda: True)
    print(run.model_dump_json(indent=2))
    sys.exit(0 if urls else 1)
elif args.fetch_only:
    if not args.url:
        parser.error("--fetch-only needs a URL")
    try:
        page = PublicWebFetcher().fetch(args.url)
        print(json.dumps({"url": page.url, "title": page.title, "text_characters": len(page.text),
                          "links": len(page.links), "truncated": page.truncated}, indent=2))
    except SourceError as exc:
        print(json.dumps({"status": exc.status, "detail": str(exc)}))
        sys.exit(1)
else:
    with tempfile.TemporaryDirectory(prefix="ainvestify-smoke-") as folder:
        with Store(Path(folder) / "smoke.db") as store:
            run = WebSourcingRun(tenant_id="smoke", thesis=args.brief,
                                geography=args.geography or None, seed_urls=[args.url] if args.url else [], model="local")
            result = source_companies(store, run, max_pages=args.max_pages, max_companies=2, model=DiagnosticModel())
            print(result.model_dump_json(indent=2))
            for lead in store.list_leads("smoke"):
                profile = lead.company_profile
                print(json.dumps({"company": profile.name, "website": profile.website,
                                  "evidence_fields": [e.field for e in profile.evidence],
                                  "assessment_status": profile.assessment.status,
                                  "recommendation": profile.assessment.recommendation}, indent=2))
            sys.exit(0 if result.company_ids else 1)
