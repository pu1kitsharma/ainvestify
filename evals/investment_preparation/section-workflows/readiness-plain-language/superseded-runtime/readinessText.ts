import type {Section} from './PreparationWorkspace';

export type ReadableCheck={title:string;purpose:string;request:string[];steps:string[];result:string;limit:string;service:string};
const actions:Record<string,{question:string;done:string;records:string;definition:string}>={
 'completed order':{question:'Do new customers complete their first order?',done:'completed an order',records:'Order records with the same customer IDs, dates and completed or cancelled status.',definition:'what counts as a completed order'},
 'completed booking':{question:'Do new customers complete a booking?',done:'completed a booking',records:'Booking records with the same customer IDs, dates and completed or cancelled status.',definition:'what counts as a completed booking'},
 'completed delivery':{question:'Do new customers receive a delivery?',done:'received a completed delivery',records:'Delivery records with the same customer IDs, dates and completed or cancelled status.',definition:'what counts as a completed delivery'},
 'completed installation':{question:'Do new customers get the product installed?',done:'had an installation completed',records:'Installation records with the same customer IDs, dates and completed or cancelled status.',definition:'what counts as a completed installation'},
 'completed service visit':{question:'Do new customers complete a service visit?',done:'completed a service visit',records:'Service-visit records with the same customer IDs, dates and completed or cancelled status.',definition:'what counts as a completed service visit'},
 'recorded product use':{question:'Do new customers start using the product?',done:'used the product',records:'Product-activity records with the same customer IDs, dates and activity types.',definition:'which recorded activity counts as product use'},
 'funding':{question:'Do new customers add money to their account?',done:'added money to their account',records:'Account-funding records with the same customer IDs, dates and completed or reversed status.',definition:'what counts as completed account funding'},
 'enrollment':{question:'Do new customers enroll in the service?',done:'enrolled in the service',records:'Service-enrollment records with the same customer IDs, dates and active or cancelled status.',definition:'how service enrollment differs from initial account sign-up'},
};
function object(value:unknown):Record<string,unknown>|undefined{return value&&typeof value==='object'&&!Array.isArray(value)?value as Record<string,unknown>:undefined;}

// Reading aids for the two registered initial methods. Unknown/custom methods
// retain their original view; do not guess their financial or time semantics.
export function readableCheck(request:Section|undefined,action:Section|undefined,company:string):ReadableCheck|undefined{
 if(request?.status!=='complete'||action?.status!=='complete'||JSON.stringify(request.content?.analysis_plan)!==JSON.stringify(action.content?.analysis_plan))return;
 const plan=object(request.content?.analysis_plan),left=object(plan?.left),right=object(plan?.right);
 if(!plan||!left||!right||typeof left.service!=='string'||left.service!==right.service||left.entity!==right.entity||left.population!==right.population||left.window!=='Latest six completed months'||right.window!==left.window||left.exposure!==right.exposure||plan.missing_inputs!=='request_records_and_defer_decision'||plan.inference_limit!=='descriptive_only_no_causal_claim')return;
 const service=left.service;
 if(plan.kind==='measurement'&&plan.purpose==='contribution'&&plan.operation==='subtract'&&plan.expected_output==='contribution_profit'&&plan.population_relation==='same_population'&&plan.partner_charge_treatment==='already_deducted_from_revenue'&&left.role==='recognized_revenue'&&left.dimension==='money'&&right.dimension==='money'&&JSON.stringify(left.deducted_costs)===JSON.stringify(['partner_charge'])&&JSON.stringify(right.deducted_costs)===JSON.stringify([])&&left.revenue_treatment==='net'&&right.role==='variable_service_cost'&&left.unit===right.unit&&left.time_basis==='flow'&&right.time_basis==='flow'&&left.exposure==='Complete operating month'){
  return {title:`What money does ${company} actually keep?`,purpose:'Check whether the income from this service covers the direct cost of providing it.',service,
   request:['Customer bills, refunds and payment records for the last six completed months, with personal details removed.','Supplier and partner bills, plus staff and support costs for the same work.','Agreements showing which company earns the fees and what must be paid to others.'],
   steps:['Work out the income the company actually earns. Separate money held for customers, taxes passed on, and money owed to partners.','Subtract the direct costs of providing the service. Count each cost once; compare the same service, month and currency.'],
   result:'Make a monthly table of income, direct costs and the amount left. If costs use up the income, investigate pricing and delivery costs before recommending expansion.',
   limit:'Leave missing amounts unanswered. This check excludes fixed head-office costs, so the amount left is not the company’s overall profit.'};
 }
 if(plan.kind==='measurement'&&plan.purpose==='cohort_rate'&&plan.operation==='divide'&&plan.expected_output==='cohort_rate'&&plan.population_relation==='numerator_subset_of_denominator'&&left.unit==='unique customers'&&right.unit==='unique customers'&&left.time_basis==='observation_window'&&right.time_basis==='observation_window'&&left.exposure==='First ninety days after cohort entry; exclude immature accounts'&&left.name==='Customers completing the specified activation event'&&right.name==='Eligible newly registered customers with complete follow-up'){
  const event=Object.keys(actions).find(event=>typeof left.record_needed==='string'&&left.record_needed.includes(`Count each eligible customer once if ${event} occurs after registration within follow-up.`));
  if(!event)return;
  const wording=actions[event];
  return {title:wording.question,purpose:'Find out how often a new sign-up turns into the customer action being checked.',service,
   request:['A customer list for the last six completed months, with sign-up dates and service plans. Use anonymous customer IDs.',wording.records],
   steps:[`Agree which customers belong in the comparison and ${wording.definition}.`,`Use only customers with a full 90 days of records after sign-up. Count each customer once if they ${wording.done} within those 90 days.`,`Divide that count by all qualifying new customers with a full 90 days of records. Show the percentage by sign-up month and service plan.`],
   result:'Use the result to choose where to investigate customers getting stuck. Agree an improvement target with the founders using the actual results.',
   limit:'Missing records mean the answer is unknown. This check does not establish repeat use, customer satisfaction or why customers stopped.'};
 }
}

export function readinessChecklist(company:string,checks:ReadableCheck[]):string{
 return `${company} — records to request and checks to run\n\nThese are proposed checks, not completed findings.\n\n`+checks.map((c,i)=>`${i+1}. ${c.title}\nService: ${c.service}\n${c.purpose}\n\nAsk the founders for\n${c.request.map(s=>'- '+s).join('\n')}\n\nWhat to do with the records\n${c.steps.map((s,j)=>`${j+1}. ${s}`).join('\n')}\n\nWhat this helps decide\n${c.result}\n\n${c.limit}`).join('\n\n');
}
