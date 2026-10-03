"""Evidence-bound admission for the current India pre-seed/seed mandate.

No company-name lists: the model classifies supplied public evidence and code
checks the classification, source binding and freshness before publishing.
"""
from datetime import date, datetime
import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


POLICY = 'india_preseed_seed_v1'
GLOBAL_POLICY = 'global_research_v1'
GLOBAL_SCOPE = '''Research operating companies worldwide unless the user's brief specifies a geography, sector or stage.
Apply only restrictions actually present in that brief. Keep unknown location, stage, operating status and current funding as unknown; do not infer them from old directory labels.
This discovery output is a preliminary research candidate, not an investment recommendation. Investment suggestions require a later company due-diligence review of identity, dated funding/status history, product, market, team, financial evidence, risks, contradictory sources and material unknowns.'''
SCOPE = '''Mandatory discovery mandate: Indian operating startups at PRE-SEED or SEED only.
Exclude Series A or later, listed businesses, unicorns, mature incumbents and acquired subsidiaries.
India means the company's operating base is in India, not merely that it sells to India.
Seek recent seed/pre-seed announcements and early-stage accelerator portfolios in the requested sector.
For each candidate provide eligibility with exact quoted location and stage evidence from supplied blocks.
Use the latest evidenced funding stage, not a historical seed round for a now-mature company.
Unknown stage, location, maturity or undated stage evidence is unresolved, not eligible.
Do not use absence of later funding as proof of current stage. No fabricated dates or companies.
Stage evidence older than 548 days needs fresh confirmation. Eligibility is a screening assessment,
not a claim that the company is fundraising or suitable for investment.'''


class EligibilityQuote(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_block_id: str
    quote: str = Field(min_length=3, max_length=500)


class Eligibility(BaseModel):
    model_config = ConfigDict(extra='forbid')
    country: Literal['India', 'other', 'unknown']
    stage: Literal['pre_seed', 'seed', 'later', 'unknown']
    maturity: Literal['emerging', 'established', 'listed', 'unicorn', 'acquired', 'unknown']
    stage_as_of: Optional[date] = Field(description='Exact full date supported by date_evidence; null if unavailable. Never use retrieval date as funding date.')
    location_evidence: EligibilityQuote
    stage_evidence: EligibilityQuote
    date_evidence: EligibilityQuote
    rationale: str = Field(min_length=10, max_length=400)


def scoped_request(request, policy):
    if policy == POLICY:
        return request + '\n\n' + SCOPE
    if policy == GLOBAL_POLICY:
        return request + '\n\n' + GLOBAL_SCOPE
    return request


def eligibility_issue(candidate, blocks, *, today=None):
    evidence = getattr(candidate, 'eligibility', None)
    if evidence is None:
        return 'Stage and India eligibility were not established.'
    if evidence.country != 'India' or evidence.stage not in {'pre_seed', 'seed'} or evidence.maturity != 'emerging':
        return 'Outside the India pre-seed/seed mandate, or eligibility remains unknown.'
    for item in (evidence.location_evidence, evidence.stage_evidence, evidence.date_evidence):
        if item.quote not in blocks.get(item.source_block_id, ''):
            return 'Eligibility references unsupported source text.'
    # A city name by itself can be ambiguous and does not establish the
    # company's operating country. Require the country in the cited span.
    if not re.search(r'\bIndia\b', evidence.location_evidence.quote, re.I):
        return 'The cited location does not explicitly establish an Indian operating base.'
    stage_text = evidence.stage_evidence.quote
    if (not re.search(r'\bseed\b', stage_text, re.I)
            or re.search(r'\bseries\s+[a-z]\b|\bunicorn\b|\bpre[ -]ipo\b', stage_text, re.I)):
        return 'The cited stage passage does not establish a seed/pre-seed stage without later-stage conflict.'
    if evidence.stage_as_of not in observed_dates(evidence.date_evidence.quote):
        return 'The stage date is not supported by its quoted source date.'
    today = today or date.today()
    if evidence.stage_as_of is None or not 0 <= (today - evidence.stage_as_of).days <= 548:
        return 'A dated, recent stage confirmation is needed.'
    return None


def observed_dates(text):
    """Bind common full dates without guessing missing months/days."""
    dates = set()
    patterns = [(r'\b\d{4}-\d{2}-\d{2}\b', ('%Y-%m-%d',)),
                (r'\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b', ('%d %B %Y','%d %b %Y')),
                (r'\b[A-Za-z]+\s+\d{1,2},?\s+\d{4}\b', ('%B %d %Y','%b %d %Y'))]
    for pattern, formats in patterns:
        for value in re.findall(pattern,text):
            for format in formats:
                try:
                    dates.add(datetime.strptime(value.replace(',',''),format).date())
                except ValueError:
                    pass
    return dates
