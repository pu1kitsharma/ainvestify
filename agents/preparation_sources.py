"""Bounded source records and citation metadata; no generated company prose."""
from schemas import utcnow


def source_record(lead, workspace):
    from agents.analyst_pack import raw_sources, financial_facts
    rows=[];size=0;omitted=0
    at=workspace.analyst_pack.get('record',{}).get('prepared_at') or utcnow()
    # Reserve bounded space for the latest calculations/company records and
    # their complete source qualifications. No partial financial quote enters
    # inference, and no older record silently crowds out the business sources.
    numeric=[]
    for fact in reversed(financial_facts(workspace,at)):
        if size+len(fact['quote'])>4500:
            omitted+=1;continue
        numeric.insert(0,fact);size+=len(fact['quote'])
    categories={e.id:e.field for e in lead.company_profile.evidence}
    for source in raw_sources(lead):
        # Preserve whole records. Never truncate away a closing qualification.
        if size+len(source['quote'])>14000:
            omitted+=1;continue
        size+=len(source['quote'])
        rows.append({**source,'id':'S'+str(len(rows)+1),'source_id':source['id'],
                     'category':categories.get(source['id'],'source_passage'),'subject':'unclear','status':'source_reported',
                     'classification':'complete_supplied_context_not_model_extracted'})
    rows.extend(numeric)
    collection=workspace.research.get('preparation_sources',{})
    incomplete_collection=any(p.get('status')!='ok' for p in collection.get('pages',[]))
    return {'facts':rows,'prepared_at':at,'batches':{},'extraction':'complete_context_no_generation',
            'coverage':'partial' if omitted or incomplete_collection or any(len(e.quote)>4000 for e in lead.company_profile.evidence) else 'selected_sources_processed',
            'unknowns':[],'source_selection':{'scope':'bounded_supplied_records','omitted_for_context':omitted,'max_context_characters':14000}}


def inference_facts(facts):
    # Full quotes reach every task. URLs/timestamps and duplicate IDs remain
    # code-owned citation metadata rather than repeated inference tokens.
    return [{k:f[k] for k in ('id','quote','status','category') if k in f} for f in facts]


