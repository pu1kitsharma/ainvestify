"""Evidence-based preparation workpaper, separate from generated business prose.

Reference process: Morgan Stanley, The Anatomy of a Deal (2025); YC, A Guide
 to Seed Fundraising. These are operational references, not jurisdictional law.
"""
from decimal import Decimal, InvalidOperation
from schemas import FieldStatus

METRICS = {
    'arr': 'Current ARR', 'arr_prior_year': 'Prior-year ARR',
    'cash_on_hand': 'Cash on hand', 'burn_monthly': 'Monthly net burn',
}


def preparation_workpaper(lead, documents, extraction, controls):
    documents = [d for d in documents if d.tenant_id == lead.tenant_id and d.deal_id == lead.promoted_deal_id]
    doc = next((d for d in documents if extraction and d.id == extraction.document_id), None)
    if extraction and (extraction.tenant_id != lead.tenant_id or extraction.deal_id != lead.promoted_deal_id):
        doc = None
    blocks = {b.id:b for b in doc.blocks if b.document_id == doc.id} if doc else {}
    financials = []
    for name, title in METRICS.items():
        item = getattr(extraction, name, None) if doc else None
        block = blocks.get(item.source_block_id) if item else None
        valid = bool(item and item.status in {FieldStatus.APPROVED, FieldStatus.EDITED} and item.value is not None
                     and block and item.source_page == block.page)
        value = None
        if valid:
            try:
                value = Decimal(str(item.value))
                valid = value.is_finite() and not isinstance(item.value,bool)
            except InvalidOperation:
                valid = False
        financials.append(dict(key=name, title=title, status='reviewed' if valid else 'needs_review' if item and item.value is not None else 'missing',
            value=str(value) if valid else None, unit=item.unit if valid else None,
            document_id=doc.id if valid else None, source_block_id=block.id if valid else None,
            source_page=block.page if valid else None))
    metrics = {m['key']:m for m in financials if m['status']=='reviewed'}
    calculations = []
    def pair(a,b):
        x,y=metrics.get(a),metrics.get(b)
        if not x or not y or not x['unit'] or x['unit'].strip().casefold()!=str(y['unit']).strip().casefold():
            return None
        return Decimal(x['value']),Decimal(y['value'])
    cash_burn=pair('cash_on_hand','burn_monthly')
    if cash_burn and cash_burn[0]>=0 and cash_burn[1]>0:
        calculations.append(dict(name='Cash coverage at supplied burn', value=str(round(cash_burn[0]/cash_burn[1],2)), unit='months',
            formula='cash_on_hand / burn_monthly', inputs=['cash_on_hand','burn_monthly'],
            limitation='A constant-burn calculation, not a cash forecast. Reconcile dates, restricted cash, working capital and future spending before setting raise timing.'))
    arr_pair=pair('arr','arr_prior_year')
    if arr_pair and arr_pair[0]>=0 and arr_pair[1]>0:
        calculations.append(dict(name='ARR change against supplied prior year',value=str(round((arr_pair[0]/arr_pair[1]-1)*100,2)),unit='%',
            formula='(arr / arr_prior_year - 1) * 100',inputs=['arr','arr_prior_year'],
            limitation='Confirm comparable period ends and ARR definition. This is not total revenue growth and must not be used for a non-recurring business.'))
    reviewed = {c.id for c in controls if c.status=='satisfied'}
    requests = [
        dict(id='mandate',workstream='Engagement',owner='Founder / transaction lead',
             deliverable='Transaction objectives and engagement scope',
             request='Confirm primary capital versus founder liquidity, proposed financing route, timing, issuer jurisdiction, advisor role and authority to act.',
             acceptance='An agreed objective and engagement record; a company website is insufficient.',
             status='reviewed' if 'engagement_authority' in reviewed else 'missing'),
        dict(id='financials',workstream='Financial diligence',owner='Finance',
             deliverable='Financial baseline and cash forecast',
             request='Provide period-labelled P&L, balance sheet, cash-flow records and current cash/burn. Include reconciliations and gross/net revenue treatment; ARR applies only to recurring revenue.',
             acceptance='Reconcile source accounts to management metrics, identify adjustments, and distinguish historical figures from assumptions.',
             status='reviewed' if 'financial_review' in reviewed else 'partial' if metrics else 'needs_review' if documents else 'missing'),
        dict(id='commercial',workstream='Commercial diligence / incubation',owner='Founder / commercial lead',
             deliverable='Customer cohort and unit-economics workpaper',
             request='Provide dated customer/order cohorts, invoices, cancellations, repeat purchases, acquisition spend and direct delivery costs. A product demo or website testimonial cannot replace operating records.',
             acceptance='A reproducible cohort definition, retention/repeat-demand calculation and contribution bridge; identify concentration and adverse evidence.',
             status='reviewed' if 'commercial_validation' in reviewed else 'missing'),
        dict(id='capitalization',workstream='Capital structure',owner='Founder / finance / counsel',
             deliverable='Ownership and financing instruments schedule',
             request='Provide the current fully diluted cap table, options, outstanding convertibles, debt, security interests and material investor rights.',
             acceptance='Reconcile ownership and instruments to executed records before modeling dilution or negotiating a financing.',
             status='needs_review' if doc and extraction.cap_table else 'missing'),
        dict(id='materials',workstream='Materials and positioning',owner='Transaction lead',
             deliverable='Investor deck, financial model and indexed data room',
             request='Tie product/customer narrative and market positioning to evidence; build a milestone-based use of funds and downside cash scenario. Flag valuation assumptions and unsupported claims.',
             acceptance='Consistent figures across documents, source links, explicit assumptions and current release approval.',
             status='reviewed' if 'release_approval' in reviewed else 'missing'),
        dict(id='process',workstream='Fundraising execution',owner='Transaction lead',
             deliverable='Qualified investor pipeline and diligence tracker',
             request='Establish investor mandate, geography, stage, check size and conflicts; track authorized contact, NDA, meeting, questions, indications and terms with dated evidence.',
             acceptance='Named mandate evidence and actual process events. A generated investor-type paragraph is not an investor match or commitment.',
             status='reviewed' if 'investor_qualification' in reviewed else 'missing'),
        dict(id='closing',workstream='Closing',owner='Transaction lead / counsel / finance',
             deliverable='Closing conditions and funds reconciliation',
             request='Track negotiated terms, approvals, definitive documents, conditions, signatures, settlement and post-close obligations.',
             acceptance='Executed records and reconciled funds receipt; generated documents never establish a close.',
             status='reviewed' if {'signed_documents','funds_received'}.issubset(reviewed) else 'missing'),
    ]
    return dict(financials=financials,calculations=calculations,requests=requests,
        next_deliverable=next((r['deliverable'] for r in requests if r['status']!='reviewed'),'Review post-close obligations'),
        source_document_count=len(documents),
        references=[{'title':'Morgan Stanley: The Anatomy of a Deal','url':'https://advisor.morganstanley.com/the-archer-lang-group/documents/field/a/ar/archer-lang-group/The_Anatomy_of_a_Deal.pdf'},
                    {'title':'YC: A Guide to Seed Fundraising','url':'https://www.ycombinator.com/library/4A-a-guide-to-seed-fundraising'}])
