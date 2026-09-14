// Isolated browser regression: all API responses are fixtures; no saved leads
// or real research jobs are changed. Install Playwright or provide its module path.
const playwrightModule = process.env.DISCOVERY_PLAYWRIGHT_MODULE || 'playwright';
const { chromium } = require(playwrightModule);
const { expect } = require(`${playwrightModule}/test`);
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1360, height: 1000 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const profile = (id, name, offering) => ({ id, name, website: `https://${id}.example/`, evidence: [
      { id: `${id}-e`, field: 'offering', value: offering, quote: offering, source_url: `https://${id}.example/`, retrieved_at: new Date().toISOString() },
    ], assessment: null });
    const hotel = { id: 'hotel-lead', company_id: 'hotel', company_name: 'Historic Hotel', status: 'new', discovery_signals: [], company_profile: profile('hotel', 'Historic Hotel', 'Hotel operator') };
    const tech = { id: 'tech-lead', company_id: 'tech', company_name: 'Technology Example', status: 'new', discovery_signals: [], company_profile: profile('tech', 'Technology Example', 'Warehouse automation software') };
    const makeRun = (id, thesis, status, lead_ids) => ({ id, thesis, geography: 'India', status, lead_ids, company_ids: [],
      seed_urls: [], search_queries: [thesis], discovered_urls: [], warnings: [], phase: 'researching_companies',
      started_at: new Date().toISOString(), completed_at: status === 'running' ? null : new Date().toISOString(), error: null,
      source_coverage: [{host:'source.example',name:'Fixture Search',category:'Web search',url:'https://source.example/',status:'Unavailable',discovered_companies:0,supported_companies:0,cited_claims:0,records_read:0,matches:0,issues:1,outcomes:[{url:'https://source.example/',status:'blocked',detail:'Diagnostic detail kept out of the main flow',retrieved_at:new Date().toISOString()}]}],
      sources: [{url:'https://source.example/',status:'blocked',detail:'Diagnostic detail kept out of the main flow'}] });
    const history = makeRun('old', 'hotel operators', 'completed', [hotel.id]);
    const current = makeRun('tech', 'tech startups', 'running', []);
    current.research_plan = {interpretation:'Technology companies in India',status:'model_interpreted',model:'fixture',criteria:[{dimension:'sector',requirement:'Technology offering',evidence_needed:'Cited products'}]};
    current.reasoning_log = [{step:'Screen candidate',company:'Technology Example',decision:'research_candidate',detail:'Warehouse software matches the technology brief'}];
    let runs = [current, history];
    let visible = [];
    let releaseRequest;
    await page.route('http://localhost:5173/api/**', async route => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      let body;
      if (path === '/api/leads/web-runs' && request.method() === 'POST') {
        const submitted = request.postDataJSON();
        assert.equal(submitted.prepare_workflow, false);
        assert.equal(submitted.thesis, 'climate startups');
        await new Promise(resolve => { releaseRequest = resolve; });
        body = makeRun('climate', submitted.thesis, 'partial', []);
        runs = [body, ...runs];
      } else if (path === '/api/leads/web-runs') body = runs;
      else if (path === '/api/leads') body = [hotel, tech];
      else if (path === '/api/operations/datasets') body = {sources:[{id:'register',name:'Example company register',url:'https://register.example/',access:'metadata_only',granularity:'company',license_name:'Requires entitlement',terms_url:'https://register.example/terms',limitation:'Records have not been imported.'}]};
      else if (path === '/api/leads/web-runs/tech/leads') body = visible;
      else if (path === '/api/leads/web-runs/old/leads') body = [hotel];
      else if (path === '/api/leads/web-runs/climate/leads') body = [];
      else if (path === '/api/leads/tech-lead/decision') { tech.status = 'reviewed'; body = tech; }
      else throw new Error(`Unexpected API path: ${path}`);
      await route.fulfill({ json: body });
    });
    await page.goto('http://localhost:5173/leads');
    await expect(page.getByRole('heading', { name: 'tech startups India', exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Historic Hotel', exact: true })).toHaveCount(0);
    await expect(page.getByText('Diagnostic detail kept out of the main flow')).not.toBeVisible();
    await expect(page.getByRole('heading',{name:'AI research brief',exact:true})).toBeVisible();
    await page.getByText('AI decisions and research actions · 1',{exact:true}).click();
    await expect(page.getByText('Warehouse software matches the technology brief',{exact:true})).toBeVisible();
    await expect(page.getByText('Additional signals:', { exact: false })).toHaveCount(0);
    await page.getByText('Search details and source coverage', {exact:true}).click();
    await expect(page.getByRole('heading', {name:'Web search',exact:true})).toBeVisible();
    await page.getByText('Fixture Search', {exact:true}).click();
    await expect(page.getByText('Diagnostic detail kept out of the main flow')).toBeVisible();
    await page.getByText('Dataset access and licensing', {exact:true}).click();
    await expect(page.getByText('Metadata only · records not connected · Company records', {exact:true})).toBeVisible();
    await page.getByText('Search details and source coverage', {exact:true}).click();

    visible = [tech]; current.lead_ids = [tech.id];
    await expect(page.getByRole('heading', { name: tech.company_name, exact: true })).toBeVisible({timeout:10000});
    current.status = 'completed'; current.completed_at = new Date().toISOString();
    await page.getByRole('button', { name: 'Shortlist company', exact: true }).click();
    await page.getByRole('tab', { name: 'Shortlist', exact: true }).click();
    await expect(page.getByRole('heading', { name: tech.company_name, exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: hotel.company_name, exact: true })).toHaveCount(0);
    await page.getByRole('tab', { name: 'Search history', exact: true }).click();
    await page.getByRole('button').filter({hasText:'hotel operators'}).click();
    await expect(page.getByRole('heading', { name: hotel.company_name, exact: true })).toBeVisible();
    await page.getByLabel('What companies are you looking for?').fill('climate startups');
    await expect(page.getByRole('button', {name:'Find companies', exact:true})).toBeEnabled({timeout:10000});
    await page.getByRole('button', {name:'Find companies', exact:true}).click();
    await expect(page.getByRole('heading', {name:hotel.company_name, exact:true})).toHaveCount(0);
    await expect.poll(() => !!releaseRequest).toBe(true);
    releaseRequest();
    await expect(page.getByRole('heading', {name:'climate startups India',exact:true})).toBeVisible();
    await expect(page.getByRole('heading', {name:'No matching companies were established in this search',exact:true})).toBeVisible();
    await page.setViewportSize({width:390,height:844});
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    assert.deepEqual(errors, []);
    console.log('PASS: run isolation, progressive results, shortlist, history, new-search clearing, empty state, mobile width, browser errors');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
