"""Load a company's own documents into a new room and queue its fact base, from the operator's machine.

PowerPoint files are converted to PDF first, because the ingestion parser reads PDF and workbooks.
The documents stay private: they are copied into the run folder and the database, nothing else.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--company', required=True)
    parser.add_argument('--website', default='', help='Official website, when known')
    parser.add_argument('--file', action='append', required=True, type=Path, help='Repeat for each PDF, PowerPoint or workbook')
    parser.add_argument('--db', required=True)
    parser.add_argument('--tenant', required=True)
    parser.add_argument('--root', required=True, type=Path, help='Folder that holds every room\'s run folder')
    parser.add_argument('--model', default='qwen3.8:latest')
    args = parser.parse_args()

    from agents.analysis.operating_workflow import reconcile_workspace
    from agents.core.planner_agent import promote_lead_to_deal
    from delivery.deal_documents import deck_render, runs
    from delivery.ingestion import ingest_upload
    from schemas import CompanyEvidence, CompanyProfile, DealStatus, SourcedLead
    from store import Store

    with Store(args.db) as store:
        seen = CompanyEvidence(field='name', value=args.company, quote=args.company, source_url=f'operator-upload:{args.company}', origin='operator_upload')
        profile = CompanyProfile(tenant_id=args.tenant, name=args.company, website=args.website, evidence=[seen])
        store.save_company(profile)
        lead = SourcedLead(tenant_id=args.tenant, company_name=args.company, company_id=profile.id, company_profile=profile)
        store.save_lead(lead)
        deal = promote_lead_to_deal(store, lead)
        room = reconcile_workspace(store, lead)
        room.deal_id = deal.id
        store.save_workspace(room, expected_revision=room.revision)
        run_dir = args.root / args.tenant / room.id
        sources = run_dir / 'sources'
        sources.mkdir(parents=True, exist_ok=True, mode=0o700)
        imported = []
        for path in args.file:
            target = sources / path.name
            if path.suffix.lower() in ('.pptx', '.ppt'):
                target = target.with_suffix('.pdf')
                target.write_bytes(deck_render.to_pdf(path.read_bytes(), path.suffix.lower().lstrip('.')))
            else:
                target.write_bytes(path.read_bytes())
            target.chmod(0o600)
            document = ingest_upload(target, args.tenant, deal.id)
            store.save_document(document)

            def append(current, document=document):
                current.document_ids.append(document.id)
                current.status = DealStatus.INGESTED
            store.update_deal(args.tenant, deal.id, append)
            imported.append(document.id)
        run = runs.create(store.conn, args.tenant, room.id, deal.id, args.company, run_dir, args.model)
        runs.queue(store.conn, run, 'facts', 'operator')
        print(json.dumps({'room': room.id, 'deal': deal.id, 'run': run['id'], 'documents': imported}))


if __name__ == '__main__':
    main()
