// Isolated browser regression: all company API calls are fixtures, no user data changed.
const modulePath = process.env.DISCOVERY_PLAYWRIGHT_MODULE || 'playwright';
const { chromium } = require(modulePath);
const { expect } = require(`${modulePath}/test`);
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext({ viewport: {width:1360,height:1000}, permissions:['clipboard-read','clipboard-write'] });
    const page = await context.newPage();
    const errors=[]; page.on('pageerror', e=>errors.push(e.message));
    const fact={id:'claim',field:'offering',value:'Factory robotics',quote:'Example builds factory robotics',source_url:'https://source.example/',retrieved_at:new Date().toISOString()};
    const lead={id:'selected',company_name:'Selected Robotics',status:'reviewed',promoted_deal_id:null,company_profile:{name:'Selected Robotics',website:'https://robotics.example/',evidence:[fact],assessment:null}};
    const historical={...lead,id:'old',company_name:'Historical Hotel',status:'new'};
    let leads=[lead,historical],starts=0;
    const workspace={id:'workspace',lead_id:'selected',basis_hash:'current',company_brief:{},controls:[],events:[],automation:null,model:'Codex editorial review',analysis_review:{note:'Reviewed during a coding session'}};
    await page.route('http://localhost:5173/api/**',async route=>{
      const path=new URL(route.request().url()).pathname;
      let body;
      if(path==='/api/leads')body=leads;
      else if(path==='/api/deals')body=[];
      else if(path==='/api/operations/workspaces')body=[workspace];
      else if(path==='/api/operations/leads/selected/brief-jobs'){
        starts++;workspace.automation={status:'running',phase:'Drafting your founder pitch'};body=workspace;
      }else if(path==='/api/operations/workspaces/workspace/company-brief'){
        await route.fulfill({status:200,contentType:'text/markdown',body:'# Selected Robotics company brief'});return;
      }else throw Error('Unexpected request '+path);
      await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
    });
    await page.goto('http://localhost:5173/operations');
    await expect(page.getByRole('heading',{name:'Move companies toward a fundraise'})).toBeVisible();
    await expect(page.getByText('Historical Hotel')).toHaveCount(0);
    await page.getByRole('link',{name:'Selected Robotics',exact:true}).click();
    await expect(page.getByRole('tab')).toHaveCount(3);
    await expect(page.getByText(/coding session/)).toHaveCount(0);
    await page.getByRole('button',{name:'Prepare company brief',exact:true}).click();
    await expect(page.getByRole('status')).toContainText('Drafting your founder pitch');
    assert.equal(starts,1);
    await page.reload();
    await expect(page.getByRole('status')).toBeVisible();
    workspace.company_brief={version:9,basis_hash:'current',research:{business:'Factory robots automate picking for production teams.',reason_to_meet:'Recurring production bottlenecks create a reason to test paid demand.',main_risk:'Installation and service costs could exceed contract revenue.',first_question:'What does one installation cost to deliver and maintain?',evidence_ids:['claim']}};
    workspace.automation={status:'failed',phase:'Generation needs attention',error:'Fixture failure'};
    await expect(page.getByRole('heading',{name:'What does this company do?'})).toBeVisible({timeout:10000});
    await expect(page.getByRole('alert')).toContainText("needs attention");
    await page.getByRole('button',{name:'Update / finish brief',exact:true}).click();
    workspace.company_brief.pitch={subject:'Testing production automation together',observation:'Your company builds factory robots.',proposed_help:'We could help design a paid pilot and measure installation costs against collected fees.',meeting_ask:'Would you be open to a short conversation?',evidence_ids:['claim']};
    workspace.company_brief.readiness={priorities:[1,2,3].map(i=>({title:`Priority ${i}`,investor_question:'Will customers pay enough to cover service costs?',action:'Run a paid installation pilot and record delivery costs.',output:'Paid pilot scorecard',done_when:'Show payments and fully costed delivery, including unsuccessful pilots.'})),evidence_ids:['claim']};
    workspace.automation={status:'completed',phase:'Saved'};
    await expect(page.getByRole('link',{name:'Download brief ↓'})).toBeVisible({timeout:10000});
    await page.getByRole('tab',{name:'2. Pitch founders',exact:true}).click();
    await expect(page.getByText(workspace.company_brief.pitch.proposed_help)).toBeVisible();
    await page.getByRole('button',{name:'Copy email',exact:true}).click();
    await expect(page.getByRole('button',{name:'Copied',exact:true})).toBeVisible();
    assert((await page.evaluate(()=>navigator.clipboard.readText())).includes('Hi Selected Robotics team,'));
    await page.getByRole('tab',{name:'3. Get investment ready',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Build the investment case'})).toBeVisible();
    await expect(page.getByRole('button',{name:'Prepare investment case',exact:true})).toBeVisible();
    await page.getByRole('tab',{name:'1. Research',exact:true}).click();
    await page.getByText('Sources behind this brief',{exact:true}).click();
    await expect(page.getByText(fact.quote,{exact:true})).toBeVisible();
    await page.setViewportSize({width:390,height:844});
    for(const name of ['1. Research','2. Pitch founders','3. Get investment ready']){
      await page.getByRole('tab',{name,exact:true}).click();
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'Mobile overflow '+name);
    }
    workspace.basis_hash='changed';await page.getByRole('tab',{name:'1. Research',exact:true}).click();await page.reload();
    await expect(page.getByText('Company evidence has changed.',{exact:false})).toBeVisible();
    await expect(page.getByRole('link',{name:'Download brief ↓'})).toHaveCount(0);
    await page.getByRole('tab',{name:'2. Pitch founders',exact:true}).click();
    await expect(page.getByRole('button',{name:'Copy email',exact:true})).toBeDisabled();
    await page.getByRole('link',{name:'Company records & approvals →'}).click();
    await expect(page.getByRole('heading',{name:'Company records & approvals'})).toBeVisible();
    await expect(page.getByText('Reviewed during a coding session',{exact:true})).not.toBeVisible();
    await page.getByRole('link',{name:"← Back to Selected Robotics's brief"}).click();
    await expect(page.getByRole('tab')).toHaveCount(3);
    assert.deepEqual(errors,[]);
    console.log('PASS: shortlist, three-step workspace, background/reload/retry, founder email clipboard, independent investment preparation, citations, mobile layout, stale protection, collapsed technical history');
  }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
