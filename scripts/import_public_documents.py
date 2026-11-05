"""Collect public PDF/workbook evidence and import it into an internal room."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery.deal_documents.public_sources import Policy, adopt_room, collect, import_documents, research_room


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--company', required=True)
    parser.add_argument('--website', required=True, help='Official website; operator verifies company identity')
    parser.add_argument('--document-url', action='append', default=[], help='Repeat for each PDF/.xlsx/.xlsm URL; inspect homepage links only when no URLs or local files are given')
    parser.add_argument('--local-file', type=Path, action='append', default=[],
                        help='Human-downloaded PDF/.xlsx/.xlsm; repeat with --source-url. File modification time records download time')
    parser.add_argument('--source-url', action='append', default=[],
                        help='Public URL for the corresponding --local-file; publisher comes from --company or configured publishers. No automated request or terms attestation')
    parser.add_argument('--out', type=Path, required=True, help='New archive folder; originals and manifest survive parser failures')
    parser.add_argument('--config', type=Path, help='JSON: publishers (exact regulator/exchange hosts to names), terms_reviewed_hosts')
    parser.add_argument('--terms-reviewed-host', action='append', default=[],
                        help='Exact host reviewed for public access and terms allowing automated collection; repeat for every host')
    parser.add_argument('--max-documents', type=int, default=10)
    parser.add_argument('--max-mib', type=int, default=32)
    parser.add_argument('--max-total-mib', type=int, default=100)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--tenant', required=True)
    parser.add_argument('--room', help='Existing room; otherwise create an internal public research room without asserting a mandate')
    args = parser.parse_args()
    if len(args.local_file) != len(args.source_url):
        parser.error('Pair each --local-file with one --source-url')
    config = json.loads(args.config.read_text(encoding='utf-8')) if args.config else {}
    policy = Policy(args.company, args.website, publishers=config.get('publishers', {}),
        terms_reviewed_hosts=tuple(config.get('terms_reviewed_hosts', []) + args.terms_reviewed_host),
        max_documents=args.max_documents, max_bytes=args.max_mib * 1024**2,
        max_total_bytes=args.max_total_mib * 1024**2)
    from store import Store
    with Store(args.db) as store:
        room = store.get_workspace(args.tenant, workspace_id=args.room) if args.room else None
        if args.room:
            lead = store.get_lead(args.tenant, room.lead_id) if room else None
            if not lead or lead.company_name != policy.company:
                parser.error('Choose a room for this exact company')
        manifest = collect(policy, args.out, args.document_url,
                           local_files=list(zip(args.local_file, args.source_url)))
        if not manifest['documents']:
            print(json.dumps({'manifest': str(args.out / 'manifest.json'), 'errors': manifest['errors']}))
            return 1
        room = adopt_room(store, args.tenant, room, policy.website) if room else research_room(store, args.tenant, policy.company, policy.website)
        result = {'room': room.id, 'deal': room.deal_id, 'manifest': str(args.out / 'manifest.json')}
        try:
            result['document_ids'] = import_documents(store, args.tenant, room.id, args.out)
        except Exception:
            print(json.dumps(result), file=sys.stderr)
            raise
        result['errors'] = manifest['errors']
        print(json.dumps(result))
        return 1 if manifest['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
