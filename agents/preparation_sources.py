"""Bounded source records and citation metadata; no generated company prose."""
from schemas import utcnow


def is_public_source(source):
    from ipaddress import ip_address
    from urllib.parse import urlsplit
    from agents.web_sources import normalize_url, SourceError
    if source.get('origin') not in {'public_page_claim', 'preparation_public_page'}:
        return False
    try:
        host = urlsplit(normalize_url(source.get('source_url', ''))).hostname
        if not host or '.' not in host or host.endswith(('.local', '.localhost', '.internal', '.test', '.invalid')):
            return False
        try:
            return ip_address(host).is_global
        except ValueError:
            return True
    except SourceError:
        return False


def source_record(lead, workspace, *, public_only=False):
    from agents.analyst_pack import raw_sources, financial_facts
    rows=[];size=0;omitted=0
    at=workspace.analyst_pack.get('record',{}).get('prepared_at') or utcnow()
    # Reserve bounded space for the latest calculations/company records and
    # their complete source qualifications. No partial financial quote enters
    # inference, and no older record silently crowds out the business sources.
    numeric=[]
    for fact in reversed([] if public_only else financial_facts(workspace,at)):
        if size+len(fact['quote'])>4500:
            omitted+=1;continue
        numeric.insert(0,fact);size+=len(fact['quote'])
    categories={e.id:e.field for e in lead.company_profile.evidence}
    selected_claims={e.id:e.value for e in lead.company_profile.evidence
                     if e.origin == 'public_page_claim' and e.value and e.value in e.quote}
    sources = raw_sources(lead)
    current_urls = {p['url'] for p in workspace.research.get('preparation_sources', {}).get('pages', []) if p.get('blocks_collected')}
    # Interleave complete passages across fresh pages so a long homepage cannot
    # crowd out ownership/news/customer sources. Historical evidence comes last.
    by_url = {}
    for source in sources:
        by_url.setdefault(source['source_url'], []).append(source)
    ordered_urls = sorted(by_url, key=lambda url: url not in current_urls)
    sources = [by_url[url][i] for i in range(max((len(v) for v in by_url.values()), default=0))
               for url in ordered_urls if i < len(by_url[url])]
    for source in sources:
        if public_only and not is_public_source(source):
            omitted += 1
            continue
        # Preserve whole records. Never truncate away a closing qualification.
        if size+len(source['quote'])>24000:
            omitted+=1;continue
        size+=len(source['quote'])
        rows.append({**source,'id':'S'+str(len(rows)+1),'source_id':source['id'],
                     'category':categories.get(source['id'],'source_passage'),'subject':'unclear','status':'source_reported',
                     'classification':'complete_supplied_context_not_model_extracted'})
        if source['id'] in selected_claims:
            rows[-1]['selected_claim'] = selected_claims[source['id']]
    rows.extend(numeric)
    collection=workspace.research.get('preparation_sources',{})
    incomplete_collection=any(p.get('status')!='ok' for p in collection.get('pages',[]))
    return {'facts':rows,'prepared_at':at,'batches':{},'extraction':'complete_context_no_generation',
            'coverage':'partial' if omitted or incomplete_collection or any(len(e.quote)>4000 for e in lead.company_profile.evidence) else 'selected_sources_processed',
            'unknowns':[],'source_selection':{'scope':'bounded_supplied_records','omitted_for_context':omitted,'max_context_characters':24000}}


def compact_repeated_blocks(text):
    """Remove only exactly repeated adjacent paragraph sequences for inference.

    Retained source records stay unchanged. Different prices or qualifications
    prevent a sequence from matching; standalone headings are not globally
    deduplicated across unrelated sections.
    """
    paragraphs = text.split('\n\n')
    output = []
    index = 0
    while index < len(paragraphs):
        repeated = 0
        for size in range(min(100, (len(paragraphs) - index) // 2), 0, -1):
            if paragraphs[index:index+size] == paragraphs[index+size:index+2*size]:
                repeated = size
                break
        if repeated:
            block = paragraphs[index:index+repeated]
            output.extend(block)
            index += repeated
            while paragraphs[index:index+repeated] == block:
                index += repeated
        else:
            output.append(paragraphs[index])
            index += 1
    return '\n\n'.join(output)


def inference_facts(facts):
    # Whole source passages reach every task, with exact adjacent repetitions
    # compacted. URLs/timestamps and duplicate IDs remain citation metadata.
    return [{**{k:f[k] for k in ('id','status','category','selected_claim','source_url','retrieved_at','observed_at') if k in f},
             'quote':compact_repeated_blocks(f['quote'])} for f in facts]
