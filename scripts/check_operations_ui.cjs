// One isolated browser check for the MVP company journey; never calls a model.
const mod=process.env.DISCOVERY_PLAYWRIGHT_MODULE||'playwright';
const {chromium}=require(mod);
const {expect}=require(mod+'/test');
const assert=require('node:assert/strict');

(async()=>{
 const browser=await chromium.launch();
 try {
  const page=await browser.newPage({viewport:{width:1360,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));let queued=0;
  const lead={id:'lead',company_name:'Fixture Company',status:'reviewed',company_profile:{website:'https://example.test',evidence:[{id:'e',field:'offering',value:'Company description',quote:'Company description from the source',source_url:'https://example.test'}]}};
  const workspace={id:'workspace',lead_id:'lead',basis_hash:'basis',revision:1,controls:[],events:[]};
  await page.route('http://localhost:5173/api/**',async route=>{
   const path=new URL(route.request().url()).pathname;let data;
   if(path==='/api/leads')data=[lead];
   else if(path==='/api/deals')data=[];
   else if(path==='/api/operations/workspaces')data=[workspace];
   else if(path.endsWith('/preparation-jobs')){queued++;workspace.automation={id:'job',status:'running',phase:'Reading company evidence'};data=workspace;}
   else if(path.endsWith('/job/stop')){workspace.automation={id:'job',status:'cancelled',phase:'Preparation stopped'};data=workspace;}
   else throw Error(`Unexpected request: ${path}`);
   await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.goto('http://localhost:5173/');
  await page.getByRole('link',{name:'Prepare company work →'}).click();
  const journey=page.getByRole('navigation',{name:'Company preparation'});
  await expect(journey.getByRole('button')).toHaveCount(3);
  await page.getByRole('button',{name:'Prepare company work',exact:true}).click();assert.equal(queued,1);
  await expect(page.getByRole('status')).toContainText('Reading company evidence');
  await page.getByRole('button',{name:'Stop preparation',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('Preparation stopped');

  workspace.analyst_pack={version:10,basis_hash:'basis',status:'partial',record:{facts:[{id:'f',category:'offering',quote:'A cited company offering',source_url:'https://example.test',retrieved_at:'2026-09-14',status:'source_reported'}]},sections:{
   'research.business':{document:'research',title:'Business and customer',status:'complete',content:{text:'Source-based business interpretation.',fact_ids:['f']}},
   'research.economics':{document:'research',title:'Revenue mechanism',status:'review_failed',candidate:{text:'REJECTED PRIVATE CANDIDATE'},error:'The reviewer quoted an absent passage.'},
   'diligence.request_a':{document:'diligence',status:'complete',content:{question:'Which collected fees remain after refunds and partner settlements?',records_to_request:'Billing ledger and partner settlement statements for the latest completed quarter.',decision:'Establish retained fee revenue.',fact_ids:['f']}},
   'readiness.action_a':{document:'readiness',status:'complete',dependency:'diligence.request_a',content:{required_input:'Requested billing ledger and partner settlements.',action:'Reconcile billed fees with collections, refunds and settlements.',output:'Fee reconciliation with unexplained differences.',decision:'Determine whether retained fee income supports further diligence.',fact_ids:['f']}}
  }};
  workspace.automation={status:'failed',error:'Local generation failed (AttributeError). Saved evidence is retained; retry generation.'};
  await page.reload();
  const failure=page.getByText('Preparation is incomplete. Resume to correct unfinished work; saved drafts are retained.',{exact:true});
  await expect(failure).toBeVisible();
  await expect(page.getByText('Source-based business interpretation.',{exact:true})).toBeVisible();
  await expect(page.getByText('REJECTED PRIVATE CANDIDATE')).toHaveCount(0);
  await page.getByText('Source passages and reported figures',{exact:true}).click();
  await expect(page.getByText('A cited company offering',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Resume preparation',exact:true})).toBeEnabled();
  await expect(journey.getByRole('button',{name:/Research/})).toContainText('Needs attention');
  await journey.getByRole('button',{name:/Pitch founders/}).click();
  await expect(page.getByText('Draft approach to the founders. No message has been sent.')).toBeVisible();
  await journey.getByRole('button',{name:/Investment readiness/}).click();
  await expect(page.getByRole('heading',{name:'What should we check before investor conversations?'})).toBeVisible();
  await expect(page.getByText('Which collected fees remain after refunds and partner settlements?',{exact:true})).toBeVisible();
  await expect(page.getByText('Fee reconciliation with unexplained differences.',{exact:true})).toBeVisible();
  await expect(journey.getByRole('button',{name:/Investment readiness/})).toContainText('Partial draft');
  await expect(page.getByRole('link',{name:'Records request ↓'})).toHaveAttribute('href',/document=diligence/);
  await expect(page.getByRole('link',{name:'Proposed analysis ↓'})).toHaveAttribute('href',/document=readiness/);
  if(process.env.UI_SCREENSHOT_PATH)await page.screenshot({path:process.env.UI_SCREENSHOT_PATH,fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.goto('http://localhost:5173/operations?lead=lead&tab=diligence');
  await expect(page.getByRole('heading',{name:'What should we check before investor conversations?'})).toBeVisible();

  // A completed retry from another tab/worker must replace a stale failure
  // without reloading this page or submitting another generation request.
  const partialPack=structuredClone(workspace.analyst_pack);
  workspace.analyst_pack.status='complete';
  for(const key of ['research.business','research.economics','research.decision','founder.observation','founder.proposal','diligence.request_a','readiness.action_a','diligence.request_b','readiness.action_b']){
   workspace.analyst_pack.sections[key]={document:key.split('.')[0],title:key,status:'complete',content:{text:`Saved completed ${key}`,fact_ids:['f']}};
  }
  workspace.analyst_pack.record.facts[0].quote='A concise supported description. Full qualification and context retained in the parent source.';
  workspace.analyst_pack.sections['research.business'].content={text:'The supplied sources state: “A concise supported description.”',fact_ids:['f'],source_quotes:true,source_excerpt:{id:'excerpt',fact_id:'f',quote:'A concise supported description.'}};
  const pricing='Annual advisory fee billed monthly. Brokerage is charged separately by the partner.';
  const economics='Published terms describe an advisory service paid for by customers, with separate partner brokerage charges.';
  workspace.analyst_pack.record.facts.push({id:'pricing',category:'pricing',quote:pricing,source_url:'https://example.test/pricing',status:'source_reported'});
  workspace.analyst_pack.sections['research.economics'].content={revenue_mechanism:economics,unknown_economics:'Realized revenue and service costs are not established.',fact_ids:['pricing'],source_quotes:false};
  workspace.automation={id:'completed-elsewhere',status:'completed',phase:'Saved'};
  await expect(page.getByRole('button',{name:'Drafts prepared',exact:true})).toBeDisabled({timeout:8000});
  await expect(failure).toHaveCount(0);
  await expect(page.getByText('Saved completed diligence.request_a',{exact:true})).toBeVisible();
  assert.equal(queued,1,'Read-only refresh must not invoke generation');
  await journey.getByRole('button',{name:/Research/}).click();
  await expect(page.getByText('A concise supported description.',{exact:true})).toBeVisible();
  const context=page.getByText(workspace.analyst_pack.record.facts[0].quote,{exact:true}).first();
  await expect(context).not.toBeVisible();
  await page.getByText('Source passages and reported figures',{exact:true}).first().click();
  await expect(context).toBeVisible();
  await expect(page.getByText(economics,{exact:true})).toBeVisible();
  await expect(page.getByText(pricing,{exact:true})).not.toBeVisible();
  await page.getByText('Source passages and reported figures',{exact:true}).nth(1).click();
  await expect(page.getByText(pricing,{exact:true})).toBeVisible();
  // Legacy quoted economics must also avoid reproducing the full price page in the card.
  workspace.analyst_pack.sections['research.economics'].content={revenue_mechanism:pricing,unknown_economics:'Realized revenue is not established.',fact_ids:['pricing'],source_quotes:true};
  await page.reload();
  await expect(page.getByText('Published pricing and terms are in the source details below.',{exact:true})).toBeVisible();
  await expect(page.getByText(pricing,{exact:true})).not.toBeVisible();

  // No company-specific reading guide may replace model-authored fields.
  await page.goto('http://localhost:5173/operations?lead=lead&tab=readiness');
  await expect(page.getByText('Saved completed readiness.action_a',{exact:true})).toBeVisible();
  await expect(page.getByText('What money does Fixture Company actually keep?',{exact:true})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Download simple checklist',exact:true})).toHaveCount(0);

  workspace.analyst_pack=partialPack;
  workspace.automation={status:'failed',error:'Partial preparation'};
  workspace.analyst_pack.sections['research.business'].status='needs_revision';
  await page.goto('http://localhost:5173/');
  await expect(page.getByText('Source-based business interpretation.',{exact:true})).toHaveCount(0);
  await expect(page.getByText('Company description',{exact:true})).toBeVisible();
  workspace.analyst_pack.sections['research.business'].status='complete';
  workspace.analyst_pack.sections['research.business'].content.text='Research saved by another worker.';
  workspace.automation={status:'completed',phase:'Saved'};
  await expect(page.getByText('Research saved by another worker.',{exact:true})).toBeVisible({timeout:8000});
  assert.equal(queued,1);
  workspace.basis_hash='changed';
  await page.goto('http://localhost:5173/operations?lead=lead');
  await expect(page.getByText('Company inputs changed,',{exact:false})).toBeVisible();
  assert.deepEqual(errors,[]);
  console.log('PASS three-step journey, stop/resume, failure recovery without reload or inference, dashboard synchronization, partial and stale work, source links, linked diligence/actions, exports and mobile layout');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
