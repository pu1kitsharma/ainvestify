"""Reject unsupported numeric assertions before any model critique can approve them.

This checks citation coverage and literal support, not semantic truth, audit
status, unit conversion, or whether a quoted marketing claim is accurate.
"""
import re
from pydantic import BaseModel, Field

NUMBERS = re.compile(r'(?<![\w])\d+(?:[.,]\d+)*(?:\s*%|\+|x)?', re.I)
CITATIONS = re.compile(r'\b(?:E|M|C|F|D)\d+\b')

def validate_outcome_claims(product, payload):
    """Require attribution/conditional framing for claimed benefits.

    A conservative language guard for observed failure classes, not a universal
    entailment checker. Source presence and reviewer approval do not prove impact.
    """
    fields={f'sections.{i}.content':section.content for i,section in enumerate(product.sections)}
    fields.update(purpose=product.purpose, decision_question=product.decision_question)
    errors=[]
    for field,text in fields.items():
        for sentence in re.split(r'(?<=[.!?])\s+',text):
            benefit=re.search(r'\b(ensures?|guarantees?|eliminates?|reduces?|improves?|accelerates?|boosts?|increases?|saves?)\b',sentence,re.I)
            qualified=re.search(r'\b(claims?|reports?|reported|says?|describes?|aims?|could|may|might|would|hypothes[ie]s|propos\w*|test\w*|whether|unverified|not verified|not established)\b',sentence,re.I)
            if benefit and not qualified:
                errors.append(f'{field}: Attribute the claimed benefit or state it as a hypothesis; this is not an observed result: {sentence[:250]}')
            no_revenue=re.search(r'\b(no revenue|zero revenue|pre.revenue)\b(?!\s+(?:data|information|metrics|evidence|figures|records))',sentence,re.I)
            if no_revenue and not any(no_revenue.group().casefold() in s.get('quote','').casefold() for s in payload.get('sources',[])):
                errors.append(f'{field}: Missing revenue records mean revenue is unknown, not zero or pre-revenue.')
    if errors:
        raise ValueError(' '.join(errors))

class NumericClaim(BaseModel):
    statement: str = Field(min_length=5,max_length=500,description='Copy the complete numeric assertion exactly as it appears in the document. Attribute source claims; never promote them to verified results.')
    source_id: str = Field(min_length=1,max_length=100)
    quote: str = Field(min_length=5,max_length=1100,description='Exact supporting excerpt from the supplied source, not a paraphrase or a new claim.')


def numbers(text):
    return {m.group().replace(' ','').replace(',','').casefold() for m in NUMBERS.finditer(CITATIONS.sub('',text))}


def validate_numeric_claims(product, payload):
    sources={e['id']:e for e in payload.get('sources',[])}
    fields={key:getattr(product,key) for key in ('title','purpose','decision_question','next_action','completion_test')}
    fields.update({f'sections.{i}.content':s.content for i,s in enumerate(product.sections)})
    text='\n'.join(fields.values())
    # Unused annotations are not document assertions. Discard them rather than
    # retrying an otherwise valid document for dead metadata. Every number that
    # actually appears in the prose still requires exact supporting coverage.
    product.numeric_claims=[claim for claim in product.numeric_claims if claim.statement in text]
    # Bind explicitly cited sentences in code. Requiring a second verbatim copy
    # of the same sentence from the model caused avoidable annotation failures.
    # No citation is inferred: the sentence must name a real supplied source,
    # and that exact source passage must contain every asserted number.
    for value in fields.values():
        for sentence in re.split(r'(?<=[.!?])\s+', value):
            if not numbers(sentence) or any(c.statement == sentence for c in product.numeric_claims):
                continue
            for source_id in CITATIONS.findall(sentence):
                source=sources.get(source_id,{})
                quote=source.get('quote','')
                if quote and len(quote)<=1100 and numbers(sentence)<=numbers(quote) and len(sentence)<=500:
                    product.numeric_claims.append(NumericClaim(statement=sentence,source_id=source_id,quote=quote))
                    break
    uncovered=dict(fields)
    errors=[]
    references=text+'\n'+'\n'.join(r.record+' '+r.why for r in product.missing_inputs)
    if set(CITATIONS.findall(references))-set(sources):
        errors.append('Document refers to source IDs absent from the input; name actual requested records, not invented E-numbers.')
    for claim in product.numeric_claims:
        source=sources.get(claim.source_id)
        if not source or claim.quote not in source.get('quote',''):
            errors.append(f'An exact quote from {claim.source_id} is required for {claim.statement[:60]!r}.')
            continue
        if not numbers(claim.statement)<=numbers(claim.quote):
            errors.append(f'Numbers in {claim.statement[:60]!r} are not present in its cited quote.')
            continue
        if source.get('field')=='team' and not re.search(r'founder|previous|prior|former|career',claim.statement,re.I):
            errors.append('Founder-history figures cannot become target-company performance; attribute the previous role.')
            continue
        required_terms={'team_size':r'team|employee|staff|headcount', 'founded':r'found|establish|incorporat|launch'}
        if source.get('field') in required_terms and not re.search(required_terms[source['field']],claim.statement,re.I):
            errors.append(f'{source["field"]} evidence cannot support a different business measure in {claim.statement[:50]!r}.')
            continue
        uncovered={key:value.replace(claim.statement,'') for key,value in uncovered.items()}
    for key,value in uncovered.items():
        if numbers(value):
            errors.append(f'Unattributed numeric assertions in {key}: {", ".join(sorted(numbers(value)))}. Remove unsupported figures or bind actual facts to quotes; proposed test parameters belong in measurements.')
    if errors:
        raise ValueError(' '.join(errors))
