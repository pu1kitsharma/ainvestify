from dataclasses import asdict

from agents.discovery.web_sources import parse_page, Page
from agents.preparation.authored_discovery import source_blocks, source_spans
from agents.research.source_cache import PageSnapshot


def test_article_sidebar_roles_preserve_every_raw_block_but_offer_only_primary_context():
    page=parse_page('https://example.org/story','''<title>Primary Company</title>
      <header>Publisher header</header><main><article>
      <p>Primary Company provides invoice processing.</p>
      <aside><p>Other Company raised money and offers unrelated insurance.</p></aside>
      <p>Primary Company is based in India.</p></article></main>
      <footer>Footer company rankings</footer>''')
    assert len(page.content_block_roles)==len(page.content_blocks)
    all_blocks=source_blocks(page,include_ancillary=True)
    primary=source_blocks(page)
    assert any('Other Company' in block for block in all_blocks.values())
    assert not any('Other Company' in block or 'Footer' in block for block in primary.values())
    assert 'Other Company' in page.text
    assert set(primary)<set(all_blocks)
    assert all(page.content_block_roles[int(key[1:])-1] in {'article','main'} for key in primary)


def test_public_snapshot_roundtrip_keeps_scope_metadata():
    page=parse_page('https://example.org/','<main><p>Primary Company provides services.</p></main><aside>Sidebar</aside>')
    restored=Page(**PageSnapshot(**asdict(page)).model_dump())
    assert restored.content_blocks==page.content_blocks
    assert restored.content_block_roles==page.content_block_roles
    assert source_blocks(restored)==source_blocks(page)


def test_complete_units_keep_legal_abbreviations_and_negative_temporal_scope():
    text='Unlike Acme, Beta Ltd. offers invoice financing. Acme no longer offers wallets.'
    spans,groups,coverage=source_spans({'b1':text})
    assert groups['b1']['q1_1']=='Unlike Acme, Beta Ltd. offers invoice financing.'
    assert groups['b1']['q1_2']=='Acme no longer offers wallets.'
    assert not coverage['omitted_units']
    for span in spans.values():
        assert text[span['start']:span['end']]==span['text']


def test_overlong_and_truncated_units_are_unselectable_with_explicit_omissions():
    long='Acme formerly offered wallets until 2015, but no longer does, '+('because conditions changed '*30)+'.'
    block=long+' Acme provides a different service. An archive snippet...'
    spans,groups,coverage=source_spans({'b1':block})
    assert list(groups['b1'].values())==['Acme provides a different service.']
    assert {unit['reason'] for unit in coverage['omitted_units']}=={'overlong_complete_unit','truncated_source_unit'}
    assert all('2015' not in span['text'] for span in spans.values())


def test_publication_is_literal_hashed_conflicts_unknown_and_modified_is_not_publication():
    import hashlib
    from agents.preparation.authored_discovery import publisher_evidence
    html='<title>Indian fintech Primary Company</title><meta property="article:published_time" content="2023-10-05T12:34:56Z"><meta property="article:modified_time" content="2026-10-01T10:00:00Z"><main><p>Primary Company provides payments.</p></main>'
    page=parse_page('https://example.org/story',html)
    evidence,bindings,date=publisher_evidence(page,'Primary Company')
    assert date['value']=='2023-10-05T12:34:56Z' and date['qualification']=='article_vintage_only'
    assert [e.field for e in evidence]==['publisher_title','publisher_publication_date']
    assert all(b['source_sha256']==hashlib.sha256(html.encode()).hexdigest() for b in bindings)
    assert bindings[1]['source_path']=='meta[property="article:published_time"]@content'
    assert not any('modified' in row['source_path'] for row in page.publisher_metadata)
    restored=Page(**PageSnapshot(**asdict(page)).model_dump())
    assert restored.publisher_metadata==page.publisher_metadata
    conflict=parse_page(page.url,html+'<meta property="article:published_time" content="2022-01-01T00:00:00Z">')
    ev,bind,date=publisher_evidence(conflict,'Primary Company')
    assert date['status']=='conflicting_publisher_dates'
    assert not any(e.field=='publisher_publication_date' for e in ev)
    modified=parse_page(page.url,'<title>Primary Company</title><meta property="article:modified_time" content="2026-10-01T10:00:00Z">')
    assert publisher_evidence(modified,'Primary Company')[2]=='not_established'


def test_title_geography_never_transfers_to_another_company_and_is_not_product_evidence():
    from agents.preparation.authored_discovery import publisher_evidence
    page=parse_page('https://example.org/story','<title>Indian fintech Primary Company</title><main><p>Other Company provides insurance software.</p></main>')
    primary,_,_=publisher_evidence(page,'Primary Company')
    other,_,_=publisher_evidence(page,'Other Company')
    assert any(e.field=='publisher_title' for e in primary)
    assert not other
    assert all(e.field!='offering' for e in primary)


def test_publication_date_does_not_become_company_financial_year_or_asof_fact():
    from types import SimpleNamespace
    from schemas import CompanyEvidence
    from agents.preparation.authored_discovery import numeric_assessment_supported
    aliases={
        'E1':CompanyEvidence(field='offering',value='Primary Company offers payments.',quote='Primary Company offers payments.',source_url='https://example.org/'),
        'E2':CompanyEvidence(field='publisher_publication_date',value='2023-10-05T12:34:56Z',quote='2023-10-05T12:34:56Z',source_url='https://example.org/',origin='publisher_metadata')}
    def assessment(text):return SimpleNamespace(rationale=text,strengths=[],concerns=[],missing_information=[],incubation_actions=[],evidence_ids=['E1','E2'])
    assert numeric_assessment_supported(assessment('The source article was published in 2023.'),aliases)
    assert not numeric_assessment_supported(assessment('The company reported revenue during 2023.'),aliases)
    assert not numeric_assessment_supported(assessment('The source article establishes financial performance during 2023.'),aliases)
    assert not numeric_assessment_supported(assessment('The article published in 2023 establishes 2023 revenue growth.'),aliases)
    assert not numeric_assessment_supported(assessment('Current company revenue in 2026 is 999 million.'),aliases)


def test_publisher_homepage_is_not_a_company_website_and_unbound_ads_are_rejected():
    import pytest
    from types import SimpleNamespace
    from agents.preparation.authored_discovery import observed_website_choices,website_company_bound,extraction_schema
    page=parse_page('https://publisher.example/report','<title>Primary Company</title><meta property="article:published_time" content="2023-10-05T00:00:00Z"><article><p>Primary Company offers payments.</p><a href="/tag/primary">Primary Company</a><a href="https://primarycompany.example/">Primary Company</a><a href="https://ad.example/">Advertisement</a></article>')
    choices=observed_website_choices(page,page.links)
    assert not any('publisher.example' in url for url in choices)
    assert website_company_bound(page,SimpleNamespace(name='Primary Company',website='https://primarycompany.example/'),page.links)
    assert not website_company_bound(page,SimpleNamespace(name='Primary Company',website='https://ad.example/'),page.links)
    schema=extraction_schema({'b1':'Primary Company offers payments.'},websites=choices)
    company={'name':'Primary Company','name_block_id':'b1','entity_type':'company','website':page.url,
        'facts':[{'field':'offering','value':'offers payments','source_block_id':'b1'}]}
    with pytest.raises(ValueError):schema.model_validate({'companies':[company],'follow_links':[]})
    company['website']=None
    assert schema.model_validate({'companies':[company],'follow_links':[]}).companies[0].website is None


def test_two_unresolved_companies_on_one_publisher_never_become_publisher_apex_identity():
    from agents.discovery.company_sourcing import accepted_candidate,Candidate,QuotedFact
    page=parse_page('https://publisher.example/report','<title>Company news</title><article><p>Alpha Company offers payments. Beta Company offers lending.</p></article>')
    profiles=[]
    for name,value in [('Alpha Company','offers payments'),('Beta Company','offers lending')]:
        profiles.append(accepted_candidate(Candidate(name=name,name_block_id='b1',website=None,
            facts=[QuotedFact(field='offering',value=value,source_block_id='b1')]),page))
    assert all(profile.website=='' for profile in profiles)
    assert profiles[0].identity_key!=profiles[1].identity_key
    assert all(profile.identity_key.startswith('unresolved:https://publisher.example/report#') for profile in profiles)
