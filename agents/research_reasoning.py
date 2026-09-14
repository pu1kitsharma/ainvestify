"""LLM interpretation and evidence-bound candidate screening, before selection."""
from agents.local_models import generate_task
import json
import re
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, create_model
from schemas import utcnow
from agents.investment_practice import practice_instruction, practice_manifest
from agents.geography import matches_location


class Criterion(BaseModel):
    dimension: Literal['sector', 'geography', 'growth', 'stage', 'other']
    requirement: str
    evidence_needed: str


class ResearchPlan(BaseModel):
    interpretation: str
    sector_terms: list[str] = Field(min_length=1, max_length=8)
    criteria: list[Criterion] = Field(min_length=1, max_length=6)
    queries: list[str] = Field(min_length=1, max_length=3)
    follow_up_terms: list[str] = Field(min_length=1, max_length=5)


def wants_growth(brief):
    return bool(re.search(r'\b(growing|growth|scaling|expanding)\b', brief, re.I))


def interpret_brief(run, model):
    try:
        plan = generate_task(model, 'sourcing_plan', practice_instruction('sourcing_plan', 'Interpret this company sourcing request. Extract the actual sector and its business synonyms, '
            'all selection criteria, the evidence needed to evaluate each, 3 short discovery queries of 5-9 words (not questions) and research follow-up terms. '
            'Services we provide (incubation/fundraising) are not company sectors. Rapid growth needs dated comparable business metrics; '
            'portfolio membership, funding alone and promotional adjectives do not prove growth. Never add years, stages or requirements '
            'the user did not request. Geography parameter controls geographic scope. Do not invent company names or results.'),
            json.dumps({'request':run.thesis, 'geography':run.geography, 'today':utcnow()[:10]}), ResearchPlan)
        data = ResearchPlan.model_validate(plan.model_dump()).model_dump()
        data['status'] = 'model_interpreted'
        data['routing'] = dict(model.last_route) if isinstance(getattr(model, 'last_route', None), dict) else {}
    except Exception:
        from agents.public_directories import industry_terms
        data = dict(interpretation=run.thesis, sector_terms=industry_terms(run.thesis), criteria=[dict(dimension='sector', requirement=run.thesis, evidence_needed='Company offering relevant to the request')],
            queries=[f'{run.thesis} {run.geography or ""} companies'], follow_up_terms=['products', 'customers'], status='fallback')
    if run.geography and not any(c['dimension']=='geography' for c in data['criteria']):
        data['criteria'].append(dict(dimension='geography', requirement=f'Operating in {run.geography}', evidence_needed='Company-specific location or operating-market evidence'))
    if data['sector_terms'] and not any(c['dimension']=='sector' for c in data['criteria']):
        data['criteria'].insert(0, dict(dimension='sector', requirement=data['sector_terms'][0], evidence_needed='Cited offering, sector or business model relevant to the request'))
    if wants_growth(run.thesis) and not any(c['dimension']=='growth' for c in data['criteria']):
        data['criteria'].append(dict(dimension='growth', requirement='Rapid business growth', evidence_needed='Dated comparable revenue, customer or transaction metrics; baseline and period'))
    if wants_growth(run.thesis):
        for criterion in data['criteria']:
            if criterion['dimension']=='growth':
                criterion['evidence_needed'] = 'Dated comparable revenue, customer or transaction metrics with a baseline and period; funding alone does not establish growth'
        data['follow_up_terms'] = list(dict.fromkeys(['revenue growth', 'customer growth'] + data['follow_up_terms']))[:5]
    from agents.web_discovery import discovery_queries
    data['queries'] = discovery_queries(run.thesis, run.geography, data['queries'])[:3]
    data['model'] = model.name
    data['practice'] = practice_manifest('sourcing_plan')
    run.research_plan = data
    run.reasoning_log.append(dict(at=utcnow(), step='Interpret request', detail=data['interpretation'], model=model.name, status=data['status']))
    return data


def geography_conflict(profile, geography):
    if not geography or geography.casefold() in {'global','worldwide','anywhere','any region'}:
        return False
    locations = ' '.join(e.value for e in profile.evidence if e.field=='location').casefold()
    if not locations or matches_location(geography, locations):
        return False
    # Reject explicit foreign-country evidence, while retaining unknown city
    # mappings for model review. This never manufactures a matching location.
    countries = ['india','usa','united states','united kingdom','england','uk','canada','singapore','australia','germany','france','portugal']
    return any(re.search(r'\b'+re.escape(c)+r'\b',locations) for c in countries if c!=geography.casefold())


class CriterionVerdict(BaseModel):
    dimension: Literal['sector','geography','growth','stage','other']
    status: Literal['supported','unknown','mismatch']
    reason: str = Field(max_length=400)
    evidence_ids: list[str] = Field(default_factory=list, max_length=5)


class CandidateVerdict(BaseModel):
    candidate_id: str
    priority: int = Field(ge=1, le=3)
    reason: str = Field(max_length=400)
    criteria: list[CriterionVerdict] = Field(min_length=1, max_length=6)


class Screening(BaseModel):
    candidates: list[CandidateVerdict] = Field(max_length=24)


def screening_schema(candidate_ids, evidence_ids, dimensions):
    criterion = create_model('CitedCriterion', __base__=CriterionVerdict,
        dimension=(Literal[tuple(dimensions)], ...),
        evidence_ids=(list[Literal[tuple(sorted(evidence_ids))]], Field(min_length=1,max_length=3)))
    candidate = create_model('CitedCandidate', __base__=CandidateVerdict,
        candidate_id=(Literal[tuple(candidate_ids)], ...),
        criteria=(list[criterion], Field(min_length=len(dimensions),max_length=len(dimensions))))
    return create_model('CitedScreening', __base__=Screening,
        candidates=(list[candidate], Field(min_length=len(candidate_ids),max_length=len(candidate_ids))))


def dated_growth_evidence(evidence):
    text = evidence.value + ' ' + evidence.quote
    years = [int(y) for y in re.findall(r'\b(20\d{2})\b', evidence.value or evidence.quote)]
    year = datetime.now(timezone.utc).year
    recent = bool(years and year-2 <= max(years) <= year)
    comparison = re.search(r'(grew|growth|increas|year.over.year|yoy|from\b.+\bto\b)',text,re.I)
    metric = re.search(r'\b(revenue|sales|customer|user|transaction|volume|arr|mrr)',text,re.I)
    measured = re.search(r'\d+(?:\.\d+)?\s*(?:%|percent|fold|x\b)|from\s+\D{0,12}\d.+\bto\s+\D{0,12}\d',text,re.I)
    forecast = re.search(r'\b(expect|forecast|project|target|aim|anticipat)\w*\b',text,re.I)
    return evidence.field in {'traction','revenue','customers','growth'} and recent and bool(metric and measured and comparison) and not forecast


def screen_candidates(profiles, run, model, checkpoint=None, on_batch=None):
    """Rank candidates using their facts, and retain unknowns as unknowns."""
    run.phase = 'screening_candidates'
    if len(profiles) > 1:
        retained = []
        for offset in range(0, len(profiles)):
            if checkpoint and not checkpoint():
                break
            batch = screen_candidates(profiles[offset:offset+1], run, model, checkpoint)
            retained.extend(batch)
            if on_batch:
                on_batch(batch)
        return retained
    aliases, candidates = {}, {}
    for i,p in enumerate(profiles):
        key = f'P{i+1}'
        candidates[key] = p
        aliases[key] = {f'E{j+1}': e for j,e in enumerate(p.evidence)}
    payload = {'request':run.thesis, 'plan':{'interpretation':run.research_plan.get('interpretation',run.thesis), 'criteria':run.research_plan.get('criteria',[]), 'sector_terms':run.research_plan.get('sector_terms',[])}, 'candidates':[
        {'candidate_id':key, 'name':p.name, 'evidence':[{'id':alias,'field':e.field,'value':e.value[:750]} for alias,e in aliases[key].items() if e.field not in {'directory_profile','portfolio_status'}]}
        for key,p in candidates.items()]}
    returned = {}
    for offset in range(0,len(payload['candidates']),6):
        if checkpoint and not checkpoint():
            break
        try:
            batch = {**payload,'candidates':payload['candidates'][offset:offset+6]}
            schema = screening_schema([p['candidate_id'] for p in batch['candidates']],
                {e['id'] for p in batch['candidates'] for e in p['evidence']},
                list(dict.fromkeys(c['dimension'] for c in run.research_plan.get('criteria', []))))
            result = generate_task(model, 'sourcing_screen', practice_instruction('sourcing_screen', 'Screen EVERY supplied candidate against EVERY criterion in the plan. Use only supplied evidence. '
            'Use the exact candidate_id and evidence IDs. Rank research priority 1 highest to 3 lowest based on evidence relevant to the request. '
            'Match business activity semantically to the sector and its synonyms, not exact tags. Companies may belong to multiple industries. An offering in a different sector is mismatch, not unknown. Missing evidence is unknown, never supported. '
            'Growth requires dated comparable operating metrics; funding/accelerator membership does not prove growth. '
            'Keep every reason below 12 words. Cite the evidence you examined even for unknown criteria; the citation does not establish support. '
            'For geographic support cite the location field. For sector support cite offering or sector. No investment advice or fabricated facts.'),
                json.dumps(batch), schema)
            returned.update({v.candidate_id:v for v in result.candidates if v.candidate_id in {p['candidate_id'] for p in batch['candidates']}})
        except Exception as exc:
            run.reasoning_log.append(dict(at=utcnow(), step='Screen candidate batch', status='unavailable',
                detail=f'Model screening unavailable ({type(exc).__name__}); this batch remains unverified.', error_details=str(exc)[:1200], model=model.name))
    ranked = []
    for key,p in candidates.items():
        verdict = returned.get(key)
        reviews = []
        for criterion in run.research_plan.get('criteria', []):
            found = next((v for v in verdict.criteria if v.dimension==criterion['dimension']), None) if verdict else None
            status, reason, ids = 'unknown', 'No validated assessment for this criterion yet.', []
            if found and set(found.evidence_ids).issubset(aliases[key]):
                status, reason = found.status, found.reason
                ids = [aliases[key][id].id for id in found.evidence_ids]
                if status != 'unknown' and not ids:
                    status, reason = 'unknown', 'The proposed verdict lacked supporting citations.'
                if criterion['dimension']=='sector' and status=='supported' and not any(aliases[key][id].field in {'offering','sector','business_model'} for id in found.evidence_ids):
                    status, reason = 'unknown', 'Sector fit requires a cited offering, sector or business model.'
                if criterion['dimension']=='growth' and status=='supported' and not any(dated_growth_evidence(aliases[key][id]) for id in found.evidence_ids):
                    status, reason = 'unknown', 'Rapid growth is unverified: dated comparable operating metrics were not found.'
            method = 'model_assessment'
            if criterion['dimension']=='growth' and p.growth_analysis:
                comparisons = p.growth_analysis.get('comparisons', [])
                status = 'unknown'
                method = 'operating_metric_check'
                ids = [c['evidence_id'] for c in comparisons]
                reason = p.growth_analysis.get('explanation', 'Comparable operating data is missing.')
                if comparisons:
                    reason = '; '.join(f"{c['metric']}: {c['change_pct']:+g}% ({c['period_before']} to {c['period_after']})" for c in comparisons) + '. Reported figures; rapid-growth threshold and corroboration still need assessment.'
            if criterion['dimension']=='geography' and run.geography:
                locations = [e for e in p.evidence if e.field=='location' and matches_location(run.geography, e.value)]
                if locations:
                    status, reason, ids = 'supported', f'Source explicitly reports location in {run.geography}.', [e.id for e in locations]
                    method = 'source_field_check'
                elif status=='supported':
                    status, reason = 'unknown', 'The cited facts do not establish the requested operating geography.'
            if criterion['dimension']=='sector':
                primary = (run.research_plan.get('sector_terms') or [''])[0].casefold().strip()
                tags = [e for e in p.evidence if e.field=='sector' and primary and re.search(r'\b'+re.escape(primary)+r'\b',e.value,re.I)]
                if tags and status=='unknown':
                    status, reason, ids = 'supported', 'The source explicitly labels the company in the requested sector.', [e.id for e in tags]
                    method = 'source_field_check'
                elif status=='unknown' and found:
                    # Found live on a real "robotics in India" search: the
                    # model reliably writes an accurate sector judgment in
                    # `reason` ("AlgoTest is in fintech, not robotics") but
                    # doesn't reliably choose the matching `mismatch` status
                    # literal, and often cites the wrong evidence_id for it
                    # (e.g. the trivial `name` field) even when its reason
                    # shows it read the real offering -- so this checks the
                    # candidate's own offering/sector/business_model evidence
                    # directly rather than trusting what the model cited.
                    # Only fires when that evidence actually exists -- a
                    # genuinely evidence-free candidate stays `unknown`, per
                    # this function's own "retain unknowns as unknowns"
                    # contract.
                    sector_terms_cf = [t.casefold() for t in (run.research_plan.get('sector_terms') or []) if t]
                    offering_evidence = [e for e in p.evidence if e.field in {'offering','sector','business_model'} and e.value.strip()]
                    offering_text = ' '.join(e.value for e in offering_evidence)
                    if offering_text and sector_terms_cf and not any(re.search(r'\b'+re.escape(t)+r'\b', offering_text, re.I) for t in sector_terms_cf):
                        status, reason, ids = 'mismatch', f'Cited offering evidence does not mention {primary or "the requested sector"} or its synonyms.', [e.id for e in offering_evidence]
                        method = 'source_field_check'
            if criterion['dimension']=='geography' and geography_conflict(p,run.geography):
                status, reason = 'mismatch', 'Source-reported operating geography conflicts with the requested geography.'
                ids = [e.id for e in p.evidence if e.field=='location']
            reviews.append(dict(**criterion,status=status,reason=reason,evidence_ids=ids,model=model.name,method=method))
        p.criteria_review = reviews
        excluded = any(r['status']=='mismatch' for r in reviews)
        run.reasoning_log.append(dict(at=utcnow(), step='Screen candidate', company=p.name, company_id=p.id,
            decision='excluded' if excluded else 'research_candidate', detail=verdict.reason if verdict else 'Model screening unavailable; criteria remain unverified.', model=model.name))
        if not excluded:
            ranked.append((verdict.priority if verdict else 3,p))
    ranked.sort(key=lambda item:item[0])
    retained = [p for _,p in ranked]
    if on_batch:
        on_batch(retained)
    return retained
