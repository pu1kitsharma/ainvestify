"""Public directory adapters. Sources are configured; company results are fetched.

YC's public regional cards are one discovery source, not an exhaustive startup
register. Parse visible card text only; no private API keys or embedded state.
"""
from __future__ import annotations

import re
from urllib.parse import quote, urljoin, urlsplit

from bs4 import BeautifulSoup

from schemas import CompanyEvidence, CompanyProfile
from agents.geography import matches_location


def wants_startups(brief: str) -> bool:
    return bool(re.search(r"\b(start[ -]?ups?|early[ -]stage|seed[ -]stage)\b", brief, re.I))


# Supplementary directories that only cover ONE region -- every company they
# list operates there, so querying them for any other region silently injects
# wrong-geography candidates (found live: blume.vc had no gate at all and was
# queried for every search, including a "United States" one, entirely by
# accident of how the old code was written). Declared as an explicit table
# instead of scattered `if region == ...:` branches so adding or auditing a
# region's supplementary sources is a one-line data change, not new
# conditional logic that can accidentally apply somewhere it shouldn't.
REGION_ONLY_DIRECTORIES: dict[str, list[str]] = {
    "india": ["https://blume.vc/startups", "https://villgro.org/companies/"],
}
GLOBAL_DIRECTORIES = [
    "https://www.antler.co/portfolio",
    "https://sosv.com/portfolio/",
    "https://seedcamp.com/our-companies/",
]


def startup_directory_urls(brief: str, geography: str | None) -> list[str]:
    if not wants_startups(brief):
        return []
    region = (geography or "").strip().casefold()
    if not region or region in {"global", "worldwide", "any region", "anywhere"}:
        urls = ["https://www.ycombinator.com/companies"]
    else:
        # The public location route is source configuration, never a company list.
        slug = quote(re.sub(r"\s+", "-", region), safe="-")
        urls = [f"https://www.ycombinator.com/companies/location/{slug}"]
    # Global publishers may contain companies in any requested region. Company
    # geography is checked from each card, never inferred from the publisher.
    return GLOBAL_DIRECTORIES + urls + REGION_ONLY_DIRECTORIES.get(region, [])


def parse_directory_entries(url: str, html: str) -> list[dict[str, str]]:
    host = (urlsplit(url).hostname or "").removeprefix("www.")
    if host in {"antler.co", "sosv.com", "seedcamp.com"}:
        return parse_global_portfolio(url, html, host)
    if host in {"blume.vc", "villgro.org"}:
        return parse_portfolio_entries(url, html, host)
    if urlsplit(url).hostname != "www.ycombinator.com":
        return []
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select("script, style, svg, template, noscript"):
        node.decompose()
    entries, seen = [], set()
    for card in soup.select("li"):
        name = card.select_one("span.text-2xl")
        link = card.select_one('a[href^="/companies/"]')
        description = card.select_one(".line-clamp-3")
        if not name or not link or not description:
            continue
        href = link.get("href", "")
        if not re.fullmatch(r"/companies/[a-z0-9-]+", href) or href in seen:
            continue
        metadata = [el.get_text(" ", strip=True) for el in card.select("span.text-gray-700")]
        # Require the observed layout contract; markup drift cannot shift a
        # headcount into the location or silently mark a public company active.
        if len(metadata) < 3 or metadata[0] not in {"Active", "Public", "Acquired", "Inactive"}:
            continue
        text = " ".join(card.get_text(" ", strip=True).split())
        batch = re.search(r"\b[WSPF]20\d{2}\b", text)
        entries.append({"name": name.get_text(" ", strip=True), "profile_url": urljoin(url, href),
                        "offering": " ".join(description.get_text(" ", strip=True).split())[:1200],
                        "status": metadata[0], "location": metadata[-1],
                        "batch": batch.group() if batch else "",
                        "sector": ", ".join(el.get_text(" ", strip=True) for el in card.select("div.yc-tw-Pill")
                                             if not re.search(r"\b[WSPF]20\d{2}\b", el.get_text())),
                        "quote": text[:4000]})
        seen.add(href)
        if len(entries) >= 60:
            break
    return entries


def parse_global_portfolio(url, html, host):
    """Parse observed public cards, retaining absent location/status as unknown."""
    soup = BeautifulSoup(html, 'html.parser')
    for node in soup.select('script, style, template, noscript'):
        node.decompose()
    selectors = {
        'antler.co': ('.portco_card', '[fs-cmsfilter-field="name"]', '[fs-cmsfilter-field="description"]', 'a[href]', '.portco_card_tags > div:not([fs-cmsfilter-field="sector"]):not([fs-cmsfilter-field="year"])', '[fs-cmsfilter-field="sector"]'),
        'sosv.com': ('.filtered-listing__item-details', 'h3 a', '.filtered-listing__item-content', 'h3 a[href]', '[data-taxonomy="tx_location"]', '[data-taxonomy="tx_category"]'),
        'seedcamp.com': ('.company__item', '.company__item__name', '.company__item__description__content', 'a.company__item__link[href]', None, None),
    }
    cards, name_sel, description_sel, link_sel, location_sel, sector_sel = selectors[host]
    entries, seen = [], set()
    for card in soup.select(cards):
        name, description, link = card.select_one(name_sel), card.select_one(description_sel), card.select_one(link_sel)
        if not name or not description or not link:
            continue
        href = urljoin(url, link['href'])
        if urlsplit(href).scheme not in {'http', 'https'} or href in seen:
            continue
        seen.add(href)
        entry = dict(name=name.get_text(' ', strip=True), offering=description.get_text(' ', strip=True),
                     profile_url=href, location=' '.join(n.get_text(' ', strip=True) for n in card.select(location_sel)) if location_sel else '',
                     sector=' '.join(n.get_text(' ', strip=True) for n in card.select(sector_sel)) if sector_sel else '',
                     status='', batch='', quote=' '.join(card.get_text(' ', strip=True).split()))
        if entry['name'] and entry['offering']:
            entries.append(entry)
    return entries


def parse_portfolio_entries(url, html, host):
    """Read observed, visible card layouts; missing metadata stays unknown.

    Portfolio membership does not prove a company's current funding stage or
    legal status. No embedded application state or private endpoints are used.
    """
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select("script, style, svg, template, noscript"):
        node.decompose()
    entries = []
    if host == "blume.vc":
        for card in soup.select("div[id]"):
            description = card.select_one("[data-highlight-term] .richtext")
            link = card.select_one("a[href]")
            status = card.select_one('[title="Investment Status"]')
            location = card.select_one('[title="Locations"]')
            if not description or not link or not status or not location:
                continue
            # The card's source-supplied display name is used for highlighting
            # the visible description. Require that name in the actual text.
            name = description.parent.get("data-highlight-term", "")
            text = " ".join(card.get_text(" ", strip=True).split())
            if not name or name.casefold() not in text.casefold():
                continue
            name_start = text.casefold().index(name.casefold())
            name = text[name_start:name_start + len(name)]
            entries.append(dict(name=name, profile_url=urljoin(url, link["href"]),
                offering=description.get_text(" ", strip=True)[:1200], status=status.get_text(" ", strip=True),
                location=location.get_text(" ", strip=True), batch="", sector="", quote=text[:4000],
                status_field="portfolio_status"))
    elif host == "villgro.org":
        for link in soup.select("h3 a[href]"):
            card = link.find_parent(class_="e-parent")
            description = card.select_one(".elementor-widget-text-editor") if card else None
            if not card or not description or len(card.select("h3 a[href]")) != 1:
                continue
            name = link.get_text(" ", strip=True)
            text = " ".join(card.get_text(" ", strip=True).split())
            if not name or name not in text:
                continue
            entries.append(dict(name=name, profile_url=urljoin(url, link["href"]),
                offering=description.get_text(" ", strip=True)[:1200], status="", location="", batch="",
                sector="", quote=text[:4000]))
    return entries[:250]


TECH_TERMS = ("tech", "software", "saas", "artificial intelligence", " ai ", "robot", "hardware",
              "semiconductor", "developer", "digital", "machine learning", "api", "automation", "automate")
STOP_WORDS = set("find discover identify companies company startup startups businesses business operating worth incubating incubation investment investing invest effort putting in the a an and or for of with that are is from to any all space region early stage seed based promising high potential growth growing rapidly which space help looking me please market ready customer demand risks support assess hands on how could difference india global worldwide".split())


def industry_terms(brief: str) -> list[str]:
    terms = [t for t in re.findall(r"[a-z][a-z-]+", brief.casefold()) if t not in STOP_WORDS]
    return list(dict.fromkeys(terms))


def matches_business(brief: str, text: str) -> bool:
    terms = industry_terms(brief)
    if not terms:
        return True
    text = " " + text.casefold() + " "
    # A robotics mandate cannot expand to every software automation product.
    # Require a physical-robotics indication when robotics is the primary term;
    # broad technology/AI briefs retain their broader scope.
    if terms[0] in {'robotics','robotic','robots','robot'} and not re.search(r'robotic process automation|\brpa\b',brief,re.I):
        physical = re.search(r'\b(robot(?:s|ic|ics)?|humanoid\w*|mechatronic\w*|drone\w*|autonomous (?:vehicle|mobile|machine)\w*|manipulator\w*)\b',text)
        process_only = re.search(r'robotic process automation|\brpa\b',text)
        return bool(physical) and not bool(process_only and not re.search(r'hardware|physical|humanoid|drone|manufactur',text))
    # "Financial technology" must not broaden fintech to every technology firm.
    if 'fintech' in terms:
        return any(t in text for t in ('fintech', 'financial', 'payment', 'lending', 'banking', 'insurance', 'credit', 'wealth management'))
    if set(terms).intersection({"tech", "technology", "technological"}):
        if any(t in text for t in TECH_TERMS):
            return True
    if any(t.startswith(("agri", "farm")) for t in terms):
        if any(t in text for t in ("agri", "farm", "crop", "irrigat", "solar dryer")):
            return True
    # Stem only common plurals; this is a coarse retrieval check, not an
    # investment-fit decision. Detailed constraints remain evidence gaps.
    return any(re.search(r"\b" + re.escape(t.removesuffix("s")), text) for t in terms)


def directory_profiles(page, tenant_id: str, brief: str, geography: str | None = None) -> list[CompanyProfile]:
    entries = list(page.directory_entries)
    if wants_startups(brief):
        entries = [e for e in entries if e.get("status", "") in {"Active", ""}]
        entries.sort(key=lambda e: int(e["batch"][1:]) if e["batch"] else 0, reverse=True)
    profiles = []
    for entry in entries:
        region = (geography or "").strip().casefold()
        if entry["location"] and not matches_location(region, entry["location"]):
            continue
        if not matches_business(brief, entry["offering"] + " " + entry["sector"]):
            continue
        evidence = []
        for column, field in [("name", "name"), ("offering", "offering"), ("location", "location"),
                              ("status", "reported_status"), ("batch", "accelerator_batch"), ("sector", "sector")]:
            value = entry[column]
            # Sector tags are joined from separately visible labels.
            if value and (column == "sector" or value in entry["quote"]):
                start = entry["quote"].find(value)
                passage = entry["quote"][max(0, start - 60):start + len(value) + 80] if start >= 0 else entry["quote"][-800:]
                evidence.append(CompanyEvidence(field=entry.get("status_field", field) if column == "status" else field,
                    value=value, quote=passage, source_url=page.url))
        # Use the company's own public profile to disambiguate unresolved
        # websites. It is a source URL, never mislabeled as the official site.
        evidence.append(CompanyEvidence(field="directory_profile", value=entry["profile_url"],
            quote=f"{entry['name']} links to {entry['profile_url']}", source_url=page.url))
        profiles.append(CompanyProfile(tenant_id=tenant_id, name=entry["name"], website="", evidence=evidence,
                                       identity_status="website_unresolved"))
    return profiles
