"""Bounded, verbatim research openings with their complete source retained.

Candidates are reading aids, not verified facts. The reviewer must assess their
relevance and meaning against the parent record, including qualifications.
"""
import hashlib
import re
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

CODE_BLOCK=re.compile(r'^(?:\d+\s+)?(?:import\b|const\b|function\b|HTTP\s+\d|[(){}])')

class ResearchExcerpt(BaseModel):
    id: str
    fact_id: str
    quote: str = Field(min_length=30, max_length=750)


def business_excerpts(facts):
    public=[f for f in facts if f.get('context_format')=='whole_html_blocks_v3']
    explicit=[f for f in facts if f.get('category') in {'offering','business_model','product','customers'}
              and not (public and f.get('origin')=='public_page_claim')]
    home=[f for f in public if urlsplit(f.get('source_url','')).path.strip('/')=='']
    # The opening capture precedes testimonials, careers and other footer
    # content. Explicitly supplied product records remain available as well.
    sources=explicit+home[:1]
    if not sources:
        sources=[f for f in facts if f.get('category') not in {'commercial_terms','pricing'}][:1]
    result=[];seen=set()
    for source in sources:
        blocks=source['quote'].split('\n\n')
        for index,block in enumerate(blocks):
            if not 50<=len(block)<=650 or len(re.findall(r'\w+',block))<8:continue
            if block.lstrip().startswith(('"','“')) or CODE_BLOCK.match(block):continue
            start=index;end=index+1
            while start and index-start<2 and len(blocks[start-1])<90 and len('\n\n'.join(blocks[start-1:index]))<140 and not re.search(r'[.!?]$',blocks[start-1]) and not CODE_BLOCK.match(blocks[start-1]):
                start-=1
            # Adjacent explicit qualifications travel with the excerpt. The
            # complete parent is also retained and included in model review.
            while end<len(blocks) and re.match(r'^(?:however|except|only|subject to|excluding|provided that|but |not )',blocks[end],re.I):
                end+=1
            quote='\n\n'.join(blocks[start:end])
            if not 30<=len(quote)<=750 or quote in seen:continue
            seen.add(quote)
            identifier='E'+hashlib.sha256((source['id']+'\0'+quote).encode()).hexdigest()[:12]
            result.append(ResearchExcerpt(id=identifier,fact_id=source['id'],quote=quote))
            if len(result)>=8:return result
    return result


def resolve_excerpt(identifier, facts):
    match=next((e for e in business_excerpts(facts) if e.id==identifier),None)
    if match is None:raise ValueError('business: Select a supplied business excerpt; a pricing footer or arbitrary fragment cannot replace the company description.')
    return match


def validate_settlement_summary(summary, facts, fact_ids):
    """Reject the observed conversion of a supplier-settlement payment to a fee.

    This is a narrow semantic guard, not proof of the full summary. Complete
    commercial sources and the model-written explanation also go to review.
    """
    sources=' '.join(f['quote'] for f in facts if f['id'] in fact_ids)
    settles=re.search(r'\bsettles?\b[^.!?]{0,180}\b(?:supplier|source|carrier|broker|chain)\b',sources,re.I)
    if settles and re.search(r'\b(?:single|consolidated|whole|entire|total|full|all[- ]in)\b(?:\s+\w+){0,3}\s+(?:fee|revenue|income)\b',summary,re.I):
        raise ValueError('economics: The source describes one customer payment that settles suppliers and other parties. Do not call the whole payment a company fee, revenue or income. Describe the payment flow and explicitly leave the company fee or retained share unknown unless separately disclosed.')


def validate_billing_summary(summary, facts, fact_ids):
    """Keep an explicitly annual fee/monthly collection distinction visible."""
    for fact in facts:
        if fact['id'] not in fact_ids:continue
        for block in fact['quote'].split('\n\n'):
            if not (re.search(r'\b(?:fees?|percentage|rates?)\b',block,re.I) and
                    re.search(r'\bannual(?:ly)?\b',block,re.I) and
                    re.search(r'\b(?:deduct\w*|collect\w*|bill\w*|installments?|instalments?)\b',block,re.I) and
                    re.search(r'\bmonthly\b',block,re.I)):continue
            if not (re.search(r'\bannual(?:ly)?\b',summary,re.I) and re.search(r'\bmonthly\b|\beach month\b',summary,re.I)):
                raise ValueError('economics: The source distinguishes an annual fee from monthly collection. State both explicitly: the fee is annual and collected/deducted monthly; do not describe an annual deduction. Preserve the other plan and partner qualifications.')
            if re.search(r'\b(?:deduct\w*|collect\w*)\b[^.!?;]{0,70}\bannually\b',summary,re.I):
                raise ValueError('economics: An annual fee collected monthly is not an annual deduction. Correct the collection period while retaining the annual fee basis.')
    sources=' '.join(f['quote'] for f in facts if f['id'] in fact_ids)
    custody_charge=re.compile(r'\bcustod(?:y|ial)\s+(?:fees?|charges?)\b|\b(?:fees?|charges?)\b[^.!?;]{0,60}\bfor custody\b',re.I)
    for sentence in re.split(r'[.!?]\s+',summary):
        if custody_charge.search(sentence) and not re.search(r'\b(?:no|not|unknown|undisclosed)\b',sentence,re.I) and not custody_charge.search(sources):
            raise ValueError('economics: Custody of assets does not establish a custody fee or payment to the custodian. The supplied source does not disclose that charge. Describe only the stated advisory/brokerage terms and licensed partner roles; do not invent a custody settlement.')


def commercial_terms_text(summary):
    """Render charging terms; leave accounting-result assertions out of this field.

    The shared original remains in the attempt/history. Realized income and
    recognition are separate questions requiring company records, not an
    inference from a public fee schedule. Drop whole sentences, never splice a
    qualification off an assertion. Remaining prose still requires validation
    and source review; an empty result cannot pass the summary schema.
    """
    accounting=re.compile(r'\brecogniz\w*\b[^.!?]{0,60}\b(?:revenue|income|profit)\b|\b(?:revenue|income)\s+recognition\b|\bretain\w*\s+the\s+difference\s+as\s+(?:revenue|income)\b',re.I)
    return ' '.join(sentence for sentence in re.split(r'(?<=[.!?])\s+',summary.strip()) if not accounting.search(sentence))


def service_descriptions(service, facts, fact_ids):
    """Bind plan headings to their next complete description, not the page.

    A pricing page can describe several services. Shared trading/navigation
    text must not establish the operating model of every named plan on it.
    """
    label=re.sub(r'\s+(?:plan|tier|package)$','',service.strip(),flags=re.I)
    pattern=re.compile(r'\b'+re.escape(label)+r'\b',re.I)
    descriptions=[]
    for fact in facts:
        if fact['id'] not in fact_ids:continue
        blocks=fact['quote'].split('\n\n')
        for index,block in enumerate(blocks):
            if re.fullmatch(r'\s*'+re.escape(label)+r'(?:\s+(?:plan|tier|package))?\s*',block,re.I) and index+1<len(blocks):
                descriptions.append(blocks[index+1])
            else:
                for match in pattern.finditer(block):
                    clause=re.split(r'[;\n]',block[match.end():],maxsplit=1)[0]
                    if re.match(r'\s+(?:includes?|provides?|offers?|is)\b',clause,re.I):descriptions.append(clause)
    return descriptions


def managed_service(service, facts, fact_ids):
    for description in service_descriptions(service,facts,fact_ids):
        if re.search(r'\b(?:no|without)\s+(?:advisory|managed)',description,re.I):continue
        if re.search(r'\b(?:advisory|managed[- ](?:strategies|portfolios?)|portfolio (?:management|monitoring|rebalancing))\b',description,re.I):return True
    return False
