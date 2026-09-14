"""Company-specific research after broad discovery, using the same evidence checks."""
from agents.local_models import generate_task
import json
import math
import re
from urllib.parse import urlsplit

from agents.web_sources import SourceError, normalize_url
from schemas import WebSourceOutcome


def company_search_hits(hits, profile):
    """A named query may return generic hits; do not spend model budget on them."""
    name = re.sub(r'\W', '', profile.name.casefold())
    host = urlsplit(profile.website).hostname if profile.website else None
    return [h for h in hits if (host and urlsplit(h.url).hostname == host)
            or name in re.sub(r'\W', '', (h.title + ' ' + h.url).casefold())]


def enrich_profiles(profiles, run, model, fetcher, search, checkpoint, page_budget, company_links=None, on_update=None):
    # Import at execution time to keep extraction validation in one place.
    from agents.company_sourcing import (DISCOVERY_INSTRUCTION, PageCandidates, accepted_candidate,
                                        page_blocks, same_name, useful_follow_links)
    from agents.research_reasoning import wants_growth
    run.phase = "enriching_companies"
    used = 0
    fetched = set()
    for profile_index, profile in enumerate(profiles.values()):
        if used >= page_budget or not checkpoint():
            break
        fields = {e.field for e in profile.evidence}
        # Fully populated dossiers still need external corroboration in a later pass.
        growth_needed = wants_growth(run.thesis) and not any(c.get('dimension') == 'growth' and c.get('status') == 'supported' for c in profile.criteria_review)
        if profile.website and {"offering", "location", "team", "traction"}.issubset(fields) and not growth_needed:
            continue
        topics = ' '.join(run.research_plan.get('follow_up_terms', ['official company products customers']))
        query = f'"{profile.name}" revenue customer growth' if growth_needed else f'"{profile.name}" {run.geography or ""} {topics}'.strip()
        observed_links = (company_links or {}).get(profile.id, set())
        # Read an observed company/profile destination before spending time on
        # another broad provider search. Share the budget across candidates.
        hits = search.search_queries([query], run, checkpoint) if growth_needed or not (profile.website or observed_links) else []
        hits = company_search_hits(hits, profile)
        known = ([profile.website] if profile.website else []) + sorted(observed_links)
        # A growth brief must actually search for operating metrics; a queue
        # of generic home/about links must not consume the whole allowance.
        destinations = [h.url for h in hits] + known if growth_needed else known + [h.url for h in hits]
        if growth_needed:
            run.reasoning_log.append(dict(step='Research evidence gap',company=profile.name,model=model.name,
                detail='Searching for dated operating growth evidence required by the research plan.',query=query))
        queue = list(dict.fromkeys(destinations))[:6]
        per_company = 0
        allowance = max(1, math.ceil((page_budget-used) / max(1, len(profiles)-profile_index)))
        while queue and used < page_budget and per_company < allowance and checkpoint():
            url = normalize_url(queue.pop(0))
            if url in fetched:
                continue
            fetched.add(url)
            used += 1
            per_company += 1
            if url not in run.discovered_urls:
                run.discovered_urls.append(url)
            try:
                page = fetcher.fetch(url)
                # On the observed official site, select source passages directly.
                # Generic company extraction used to retain only the name while
                # discarding the product/pricing evidence needed for analysis.
                if profile.website and urlsplit(page.url).hostname == urlsplit(profile.website).hostname:
                    from agents.operating_research import extract_business_evidence
                    facts = extract_business_evidence(profile, page, model)
                    signatures = {(e.field, e.value, e.source_url) for e in profile.evidence}
                    new = [e for e in facts if (e.field,e.value,e.source_url) not in signatures]
                    profile.evidence.extend(new)
                    if on_update: on_update(profile)
                    run.sources.append(WebSourceOutcome(url=page.url, status='partial' if page.truncated else 'ok' if facts else 'no_results',
                        detail=f'{profile.name}: {len(new)} additional exact-passage business facts from the observed company site.'))
                    commercial_links = [l['url'] for l in page.links if re.search(r'customer|case.study|pricing|results|news|annual|press',l['url']+' '+l.get('label',''),re.I)
                                        and urlsplit(l['url']).hostname == urlsplit(page.url).hostname]
                    queue = list(dict.fromkeys(commercial_links + useful_follow_links(page) + queue))
                    continue
                output = generate_task(model, 'extract_evidence', DISCOVERY_INSTRUCTION +
                    "\nResearch only TARGET_COMPANY. Do not substitute a similarly named company. "
                    "Prioritize the requested CRITERIA and missing offering, location, team, customers and business-model evidence. "
                    "For growth seek dated revenue/customer/transaction comparisons, copy complete metric statements with their dates, "
                    "and use traction fields. Do not infer growth from funding or marketing. Choose observed follow_links most likely to answer the missing criteria.",
                    json.dumps({"TARGET_COMPANY": profile.name, "THESIS": run.thesis,
                                "CRITERIA": run.research_plan.get('criteria', []),
                                "KNOWN_EVIDENCE": [e.model_dump() for e in profile.evidence],
                                "PAGE_URL": page.url, "PAGE_TITLE": page.title,
                                "PAGE_BLOCKS": page_blocks(page), "PAGE_LINKS": page.links}), PageCandidates)
                added = 0
                for candidate in output.companies:
                    if not same_name(candidate.name, profile.name):
                        continue
                    supported = accepted_candidate(candidate, page)
                    if supported is None:
                        continue
                    # Exact names alone cannot resolve cross-domain identities.
                    known_urls = {e.source_url for e in profile.evidence}
                    backlink = any(link["url"] in known_urls for link in page.links)
                    business_overlap = any(e.field == old.field and e.value.casefold() == old.value.casefold()
                                           for e in supported.evidence for old in profile.evidence
                                           if e.field in {"offering", "team"})
                    same_site = bool(profile.website and urlsplit(page.url).hostname == urlsplit(profile.website).hostname)
                    linked_site = url in observed_links or any(e.source_url == url for e in profile.evidence)
                    if not (same_site or backlink or business_overlap or linked_site):
                        run.sources.append(WebSourceOutcome(url=url, status="partial",
                            detail=f"Name match for {profile.name}; identity linkage is insufficient. Evidence not merged."))
                        continue
                    if profile.website and supported.website and profile.website != supported.website:
                        run.sources.append(WebSourceOutcome(url=url, status="partial",
                            detail="Conflicting company website; evidence not merged automatically."))
                        continue
                    if not profile.website and supported.website:
                        profile.website = supported.website
                        profile.identity_status = "source_supported_unverified"
                    signatures = {(e.field, e.value, e.source_url) for e in profile.evidence}
                    new = [e for e in supported.evidence if (e.field, e.value, e.source_url) not in signatures]
                    profile.evidence.extend(new)
                    added += len(new)
                observed = {l['url'] for l in page.links}
                directed = [u for u in output.follow_links if u in observed]
                if directed:
                    run.reasoning_log.append(dict(step='Choose research pages', company=profile.name, model=model.name,
                        detail='The model selected observed links to investigate the requested evidence.', urls=directed))
                queue = list(dict.fromkeys(directed + useful_follow_links(page) + queue))
                if added:
                    if on_update:
                        on_update(profile)
                run.sources.append(WebSourceOutcome(url=page.url, status="partial" if page.truncated else "ok" if added else "no_results",
                    detail=f"{profile.name}: {added} additional cited facts; identity and conflicting evidence checks applied."))
            except SourceError as exc:
                run.sources.append(WebSourceOutcome(url=url, status=exc.status, detail=str(exc)))
            except Exception as exc:
                run.sources.append(WebSourceOutcome(url=url, status="partial",
                    detail=f"Company enrichment unavailable ({type(exc).__name__}); prior evidence retained."))
            if not queue and per_company < allowance and used < page_budget and run.research_plan:
                additional = company_search_hits(search.search_queries([query], run, checkpoint), profile)
                queue.extend(h.url for h in additional if h.url not in fetched)
    if used >= page_budget and page_budget:
        run.warnings.append("Company enrichment reached its page budget; unresolved gaps remain explicit.")
    if wants_growth(run.thesis):
        from agents.growth_analysis import analyze_growth
        for profile in profiles.values():
            if not checkpoint(): break
            profile.growth_analysis = analyze_growth(profile, model)
            profile.growth_analysis['research_queries'] = [q for q in run.search_queries if profile.name.casefold() in q.casefold()]
            if on_update: on_update(profile)
    checkpoint()
