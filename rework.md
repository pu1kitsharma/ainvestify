 # Investment Banking & Venture Capital Workspace

> **2026-09-13 priority update:** This document is retained as broader strategy/history. The current, narrower user-directed lifecycle and build order are in [deal_automation_architecture.md §16](deal_automation_architecture.md#16-llm-driven-company-selection-incubation-and-vc-fundraising-plan). Start with evidence-backed company selection, then incubation/readiness, materials, and VC fundraising through closing. Existing feature-status inventories below are historical and must be checked against code.

 ## End-to-End Product Strategy, Workflow, Architecture, and Product Roadmap

 **Status:** Product strategy / architecture analysis\
 **Market:** Indian startup ecosystem, investment banking, venture capital, private equity, growth advisory\
 **Core thesis:** Build an AI-native workspace that takes a company from first discovery through mandate, diligence, financing, growth support, and ultimately exit.

---

 # 1\. Executive Summary

 The product being built is significantly larger than an AI document-processing or investment-banking automation tool.

 The underlying opportunity is to build an **AI-native operating system for deal origination, diligence, capital raising, transaction execution, and company growth**.

 The current system already contains a strong foundation:

```
Sourcing
    ↓
Human promotion
    ↓
Deal creation
    ↓
Document ingestion
    ↓
Financial extraction
    ↓
Human review
    ↓
External research
    ↓
Analytics
    ↓
Teaser / CIM / Pro-forma
```

 This represents the **transaction intelligence core**.

 However, a complete investment banking / VC / growth platform needs to surround this core with several additional workflows:

```
Relationship / CRM
        ↓
Origination
        ↓
Qualification
        ↓
Pitch
        ↓
Mandate
        ↓
Diligence
        ↓
Underwriting
        ↓
Valuation / Modeling
        ↓
Transaction Structure
        ↓
Marketing / Fundraising
        ↓
Execution
        ↓
Closing
        ↓
Portfolio / Company Support
        ↓
Follow-on / Exit
```

 The key insight is that these are not necessarily one business model.

 There are three closely related but distinct workflows:

 1. **Investment banking / advisory** — represent the company.
2. **VC / PE investing** — represent the capital provider.
3. **Growth / venture advisory / accelerator** — actively help the company become financeable, grow, and raise capital.

 The proposed platform can support all three, provided they are represented as different workflows rather than being forced into one pipeline.

---

 # 2\. What the Product Really Is

 A better description than "AI investment banking software" is:

 > **An AI-native workspace for deal origination, diligence, capital raising, transaction execution, and company growth.**

 An even more ambitious formulation is:

 > **The workspace where a financial institution takes a company from first signal → mandate → diligence → financing → growth → exit.**

 The product sits between:

 - CRM
- investment banking deal management
- VC/PE deal sourcing
- financial analysis
- data-room management
- diligence
- research
- financial modeling
- valuation
- investor targeting
- fundraising execution
- document generation
- portfolio/company operations

 The important distinction is that the platform should not merely **generate documents**.

 It should understand the **state of the deal**.

---

 # 3\. The Real-World Lifecycle

 A complete company/deal lifecycle can be represented as:

```
DISCOVER
   ↓
QUALIFY
   ↓
ENGAGE
   ↓
PITCH
   ↓
MANDATE
   ↓
DILIGENCE
   ↓
UNDERWRITE
   ↓
STRUCTURE
   ↓
PREPARE
   ↓
MARKET
   ↓
EXECUTE
   ↓
CLOSE
   ↓
SUPPORT
   ↓
FOLLOW-ON
   ↓
EXIT
```

 Each stage represents a different business activity.

---

 # 4\. Stage 1 — Discovery / Origination

 This is where the relationship begins.

 The platform identifies potential companies from:

 - public databases
- startup ecosystems
- GitHub
- Hacker News
- SEC / EDGAR
- Indian corporate sources
- company websites
- funding announcements
- founder networks
- referrals
- existing relationships
- inbound applications
- events
- research
- sector-specific databases

 The current `sourcing_agent.py` already handles an important part of this.

 Its job should remain narrow:

```
External signals
      ↓
Candidate company
      ↓
SourcedLead
```

 It should not try to perform financial underwriting.

---

 # 5\. Stage 2 — Qualification

 A sourced company is not automatically a deal.

 The platform should score whether it is worth pursuing.

 Potential dimensions:

```
Sector fit
Stage fit
Geographic fit
Revenue / traction
Growth
Funding requirement
Founder quality
Market attractiveness
Competitive position
Existing relationship
Potential transaction
Potential fee
Probability of winning mandate
Strategic relevance
```

 The output becomes something like:

```
Lead Score: 87 / 100

Transaction:
Series C fundraising

Estimated transaction:
$50–75M

Fit:
High

Relationship:
Medium

Timing:
Likely within 3 months

Recommendation:
Pursue
```

 This is the beginning of a real **origination pipeline**.

---

 # 6\. Stage 3 — Relationship / CRM

 This is one of the largest missing pieces.

 A real banking workflow does not jump directly from:

```
Lead → Deal
```

 It usually looks more like:

```
Lead
 ↓
Qualified lead
 ↓
Relationship established
 ↓
Introduction
 ↓
Meeting
 ↓
Opportunity
 ↓
Pitch
 ↓
Proposal
 ↓
Mandate
 ↓
Deal
```

 The platform therefore needs a relationship layer.

 A company should have:

```
Company
 ├── Founders
 ├── Executives
 ├── Investors
 ├── Board
 ├── Contacts
 ├── Relationship owner
 ├── Introducer
 ├── Meetings
 ├── Emails
 ├── Notes
 ├── Opportunities
 └── Historical transactions
```

 The system should eventually answer:

 > Who at our firm knows this founder?

 > Who introduced this company?

 > When did we last speak with management?

 > Which partner has relationships with potential investors?

 > Which companies are we currently trying to win?

 This is a major part of the value of an institutional system.

---

 # 7\. Stage 4 — Pitch / Beauty Contest

 This is a major missing product layer.

 Before receiving a mandate, an investment bank may need to pitch against other advisors.

 For example:

```
Indian SaaS company
        ↓
Needs $75M Series C
        ↓
Several banks/advisors compete
        ↓
Pitch
        ↓
Company chooses advisor
```

 The platform should therefore support a **Pitch Opportunity**.

 A pitch can contain:

```
Company overview
Investment thesis
Market analysis
Growth story
Competitive positioning
Comparable companies
Precedent transactions
Valuation framing
Potential investors
Transaction strategy
Proposed process
Bank credentials
Relevant precedent deals
Team
Timeline
Fees
Next steps
```

 The output could be:

 - pitch deck
- pitch memo
- management briefing
- valuation overview
- investor universe
- proposed transaction strategy

 This is different from a CIM.

 ### Pitch

 Designed to **win the mandate**.

 ### CIM

 Designed to **market the company after receiving the mandate**.

 ### Teaser

 Designed to **generate initial investor interest**.

 ### IC Memo

 Designed to **make an investment decision**.

 Those should remain distinct document types.

---

 # 8\. Stage 5 — Mandate / Engagement

 Once the company selects the advisor:

```
Pitch
  ↓
Commercial discussion
  ↓
Engagement letter
  ↓
Mandate
  ↓
Deal
```

 The system should create a formal `Mandate`.

 Potential fields:

```
Mandate
 ├── Client
 ├── Advisor
 ├── Transaction type
 ├── Target raise / transaction size
 ├── Geography
 ├── Sector
 ├── Fee structure
 ├── Retainer
 ├── Success fee
 ├── Exclusivity
 ├── Start date
 ├── Expected close
 ├── Team
 └── Status
```

 This is where your current:

```
new → mandate_signed
```

 state becomes particularly important.

---

 # 9\. Stage 6 — Data Room / Document Ingestion

 Your current ingestion architecture is strong.

 The data room should eventually become a first-class object.

```
Deal
 └── Data Room
      ├── Corporate
      ├── Financial
      ├── Tax
      ├── Legal
      ├── Commercial
      ├── HR
      ├── Technology
      └── Other
```

 Documents should be:

```
Uploaded
   ↓
Classified
   ↓
Parsed
   ↓
Chunked / blocked
   ↓
Cited
   ↓
Extracted
   ↓
Reviewed
```

 Your `DocBlock` concept is particularly useful here.

 The critical principle should remain:

 > **Every material extracted fact must retain provenance.**

---

 # 10\. Stage 7 — Financial Extraction

 The current `extraction_agent.py` is the beginning of the financial intelligence engine.

 Potential extracted fields include:

 ### Revenue

 - Revenue
- ARR
- MRR
- Growth
- Revenue mix
- Geography
- Customer concentration

 ### Profitability

 - Gross margin
- EBITDA
- EBIT
- Net income
- Contribution margin

 ### Cash

 - Cash
- Burn
- Runway
- Operating cash flow
- Capex

 ### Capital structure

 - Debt
- Equity
- Preferred shares
- Convertible instruments
- ESOP
- Warrants

 ### Cap table

 - Founders
- Employees
- Investors
- Ownership
- Fully diluted ownership

 ### Operating metrics

 - Customers
- Churn
- NRR
- CAC
- LTV
- Sales efficiency
- Headcount

---

 # 11\. The Evidence / Citation Principle

 This is arguably one of the strongest architectural decisions in the existing system.

 The rule:

 > **Every number traces to a citation or stays null.**

 should become a platform-wide invariant.

 Not only numbers.

 Eventually every material claim should look like:

```
Claim
 ├── value
 ├── source
 ├── source type
 ├── document
 ├── page
 ├── block ID
 ├── extraction timestamp
 ├── confidence
 ├── reviewer
 └── review status
```

 For example:

```
ARR
₹84.2 Cr

Source:
FY25 Financial Statements

Page:
47

Block:
DOC-0231

Status:
Human approved
```

 Clicking the citation should resolve directly to the underlying evidence.

 This transforms the platform from an AI summarizer into an **auditable financial intelligence system**.

---

 # 12\. Stage 8 — Human Review

 AI should not be the final authority.

 The current review checkpoint is therefore conceptually important.

 The rule should be:

```
AI proposes
   ↓
Human reviews
   ↓
Approve / Edit / Reject / Acknowledge
   ↓
Approved fact
```

 The system should maintain a distinction between:

```
Machine extracted
Human approved
Human edited
Human rejected
Unresolved
```

 This distinction should remain visible throughout the deal.

---

 # 13\. Stage 9 — Commercial / Market Diligence

 Financial extraction is only one component of diligence.

 A complete diligence framework should include:

 ## Financial diligence

 - Revenue
- ARR
- Burn
- Cash
- Debt
- Margins
- Working capital
- Cap table
- Dilution
- Revenue concentration
- Unit economics

 ## Commercial diligence

 - TAM
- SAM
- SOM
- Market growth
- Competitors
- Pricing
- Customer concentration
- Retention
- Churn
- Sales pipeline
- Sales efficiency

 ## Product / technology diligence

 - Product architecture
- Technical debt
- IP
- Security
- AI dependencies
- Open-source exposure
- Engineering organization
- Product roadmap

 ## Legal diligence

 - Incorporation
- Subsidiaries
- Shareholder agreements
- IP ownership
- Litigation
- Material contracts
- Regulatory exposure
- Employment matters

 ## Tax / regulatory diligence

 For India, this can become particularly important:

 - GST
- Income tax
- FEMA
- Transfer pricing
- ESOP taxation
- Cross-border structures
- RBI considerations
- Sector-specific regulation
- SEBI considerations

 ## People diligence

 - Founders
- Key employees
- Compensation
- ESOP pool
- Retention
- Founder dependency
- Succession
- Hiring needs

---

 # 14\. Stage 10 — Diligence Completeness

 The platform should know not only what it knows, but what it does not know.

 For example:

```
Diligence completeness: 82%

Financial       █████████░ 90%
Commercial      ████████░░ 80%
Legal           ██████░░░░ 60%
Technology      ███████░░░ 70%
Tax             █████░░░░░ 50%
People          ████████░░ 80%
```

 This produces a useful concept:

 > **Diligence readiness**

 rather than simply "documents uploaded."

---

 # 15\. Stage 11 — Risk Register

 Every deal should have a structured risk register.

 Example:

 | Risk | Severity | Evidence | Mitigation | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| Customer concentration | High | Financials p.42 | Diversification | CFO | Open |
| Founder dependency | Medium | Management interview | Hiring | CEO | Open |
| Regulatory exposure | High | Legal memo | Counsel review | Legal | Open |
| Runway | Medium | Cash forecast | Fundraise | CFO | Open |

 This should feed directly into:

 - IC memo
- CIM
- investment recommendation
- management Q&A
- transaction checklist

---

 # 16\. Stage 12 — Underwriting

 This is where the platform moves from:

 > "What does the company look like?"

 to:

 > "Should we transact with this company?"

 Underwriting combines:

```
Financials
+
Market
+
Management
+
Competition
+
Transaction structure
+
Valuation
+
Risks
+
Returns
```

 The output becomes:

```
Investment / transaction thesis
        ↓
Expected outcome
        ↓
Risk / reward
        ↓
Recommendation
```

---

 # 17\. Stage 13 — Financial Modeling

 The current `analytics_agent.py` can eventually evolve into a deterministic financial engine.

 For startups:

```
Revenue
ARR
Growth
Gross margin
Burn
Cash
NRR
CAC
LTV
Headcount
```

 feeds:

```
Operating model
      ↓
Forecast
      ↓
Cash requirements
      ↓
Valuation
      ↓
Dilution
      ↓
Fundraise structure
```

 For M&A:

```
DCF
Trading comps
Transaction comps
Precedent transactions
Synergies
Purchase price
Consideration mix
Accretion / dilution
```

 For VC:

```
Entry valuation
Ownership
Future dilution
Exit valuation
Exit ownership
MOIC
IRR
```

 The modeling engine should be deterministic wherever possible.

 AI can explain, populate, and assist.

 It should not silently invent financial calculations.

---

 # 18\. Stage 14 — Valuation

 The system should eventually support multiple valuation methods.

 ### Venture

 - Revenue multiple
- ARR multiple
- Comparable startups
- Growth-adjusted multiples
- Scenario valuation

 ### Public-market comparable

 - EV / Revenue
- EV / EBITDA
- P / E
- Growth-adjusted metrics

 ### Transaction comps

 - Acquisition multiples
- Sector-specific transaction metrics

 ### DCF

 - Revenue forecast
- Margin forecast
- FCF
- Discount rate
- Terminal value

 The platform should show the methodology rather than outputting one mysterious "AI valuation."

---

 # 19\. Stage 15 — Cap Table / Dilution Engine

 For fundraising, this becomes essential.

 Example:

```
Pre-money valuation
₹500 Cr

New investment
₹100 Cr

Post-money valuation
₹600 Cr

New investor ownership
16.67%
```

 Then simulate:

```
Existing founders
Existing investors
Employee pool
New investor
Future round
```

 The platform should allow scenarios:

```
                 Base    Downside    Upside

Raise             100       75         125
Pre-money         500      400         700
Post-money        600      475         825
Dilution         16.7%    15.8%       15.2%
```

 This becomes an actual transaction-planning engine.

---

 # 20\. Stage 16 — Investment Committee / IC Memo

 For VC / PE workflows, this is essential.

 After diligence:

```
Diligence
   ↓
Model
   ↓
Valuation
   ↓
Investment thesis
   ↓
IC memo
   ↓
Investment Committee
   ↓
Pass / More diligence / Invest
```

 The IC memo could contain:

```
Executive summary
Investment thesis
Market
Product
Traction
Financials
Unit economics
Competition
Team
Valuation
Deal structure
Risks
Mitigants
Exit scenarios
Return scenarios
Recommendation
```

 Again, material assertions should trace back to evidence.

---

 # 21\. Stage 17 — Investor / Buyer Universe

 The current `investors` route should eventually become a major system.

 Given:

 > Indian B2B SaaS company raising $40M Series C

 the system should produce:

```
Potential investors

Tier 1
 ├── Investor A
 ├── Investor B
 └── Investor C

Tier 2
 ├── Investor D
 ├── Investor E
 └── Investor F
```

 Each investor can have:

```
Stage
Geography
Sector
Typical check
Previous investments
Partner
Portfolio overlap
Investment thesis
Recent activity
Relationship strength
Likelihood of fit
```

 The system should be able to answer:

 > Build the first 30-investor target list.

---

 # 22\. Stage 18 — Fundraising Process

 After investor selection:

```
Investor universe
       ↓
Target list
       ↓
Outreach
       ↓
NDA
       ↓
Data room
       ↓
Management presentation
       ↓
Q&A
       ↓
Indications of interest
       ↓
Term sheets
       ↓
Negotiation
       ↓
Final investor
       ↓
Documentation
       ↓
Closing
```

 Each investor should have an execution state.

 Example:

```
Investor A
Status: Management meeting
Interest: High
Questions: 4
Last contact: 3 days ago

Investor B
Status: NDA
Interest: Medium

Investor C
Status: Passed
Reason: Valuation
```

 This turns the platform into a fundraising execution CRM.

---

 # 23\. Stage 19 — Teaser / CIM / Transaction Documents

 The existing compilation architecture is already moving in the right direction.

 The important distinction is:

```
build_*_data()
        ↓
plain structured data
        ↓
render_*_markdown()
```

 This is excellent because the same structured representation can drive:

 - Markdown
- frontend UI
- PDF
- presentation
- audit trail
- API responses

 The three documents should have distinct purposes.

 ## Teaser

 Anonymous / minimally identifying.

 Purpose:

 > Generate initial investor interest.

 ## CIM

 Detailed transaction marketing document.

 Purpose:

 > Enable investors to understand the opportunity.

 ## Pro-forma / model

 Purpose:

 > Explain financial performance and future economics.

 The teaser allowlist should remain structurally enforced.

---

 # 24\. Stage 20 — Data Room + Q&A

 Eventually the system should support investor questions.

```
Investor question
       ↓
Search evidence
       ↓
Retrieve relevant documents
       ↓
Draft answer
       ↓
Cite evidence
       ↓
Human approve
       ↓
Send answer
```

 For example:

 > Why did gross margin decline in FY25?

 The system should find:

```
FY25 financial statement
Management commentary
Relevant contract
Previous year comparison
```

 Then produce a cited draft.

 This is an extremely natural extension of the existing evidence architecture.

---

 # 25\. Stage 21 — Execution / Closing

 After the commercial process:

```
Term sheet
    ↓
Legal diligence
    ↓
Definitive documents
    ↓
Conditions precedent
    ↓
Approvals
    ↓
Signing
    ↓
Closing
```

 The platform should eventually contain a transaction checklist.

 Example:

```
Closing readiness: 87%

✓ Term sheet
✓ Board approval
✓ Investor diligence
✓ Financial diligence
△ Legal opinion
△ Definitive agreement
✓ Cap table
✓ Funds flow
```

---

 # 26\. Stage 22 — Post-Transaction Company / Portfolio Workspace

 This is where the platform can become much larger than investment banking software.

 After the transaction closes:

```
Company
   ↓
Portfolio / client workspace
```

 It can track:

 ### Financial

 - Revenue
- ARR
- Burn
- Cash
- Runway
- Gross margin

 ### GTM

 - Pipeline
- Conversion
- CAC
- Sales efficiency
- Expansion

 ### People

 - Headcount
- Hiring
- Retention
- Key positions

 ### Strategy

 - Initiatives
- Market expansion
- Product launches
- Partnerships

 ### Capital

 - Current investors
- Future fundraising
- Debt
- ESOP

 ### Board

 - Board meetings
- Board packs
- KPIs
- Decisions

---

 # 27\. "Incubation" Should Be a Separate Layer

 One correction to the original concept is important:

 Traditional investment banks generally should not be conceptualized as startup incubators.

 VC funds, accelerators, venture studios, and some financial institutions can play that role.

 However, the combination is real.

 Morgan Stanley is a useful example because its current Inclusive & Sustainable Ventures program provides early-stage startups with capital, mentorship, networking, business-growth resources and access to Morgan Stanley experts. Its current program describes a five-month accelerator and an equity investment for participating startups.  Morgan Stanley+2

 Morgan Stanley also explicitly describes its founder offering as spanning early-stage companies and providing capital-raising and strategic-advisory capabilities including IPOs, debt/equity raises and M&A.  Morgan Stanley+1

 So the platform should treat:

```
Investment Banking
VC / PE
Accelerator / Venture Studio
Growth Advisory
```

 as related but distinct operating modes.

---

 # 28\. Three Core Modes

 ## Mode A — Investment Banking / Advisory

 The firm represents the company.

```
Company
   ↓
Banker
   ↓
Investors / Buyers / Lenders
```

 Typical transactions:

  - Equity fundraising
- Debt financing
- M&A
- IPO
- Private placement
- Strategic transactions
- Restructuring
- Recapitalization

 Morgan Stanley's investment banking business publicly describes M&A and global capital-markets services including equity, debt and leveraged transactions.  Morgan Stanley

---

 # 29\. Mode B — VC / PE

 The firm represents capital.

```
Fund
 ↓
Source companies
 ↓
Evaluate
 ↓
Diligence
 ↓
Investment Committee
 ↓
Term sheet
 ↓
Invest
 ↓
Portfolio
 ↓
Exit
```

 This requires:

 - investment thesis
- fund mandate
- portfolio construction
- IC
- ownership
- dilution
- returns
- follow-on decisions
- exits

---

 # 30\. Mode C — Growth / Venture Platform

 This is the hybrid.

```
Company
 ↓
Evaluate
 ↓
Help improve
 ↓
GTM
 ↓
Finance
 ↓
Fundraising readiness
 ↓
Investor introductions
 ↓
Follow-on
 ↓
Exit
```

 This is the most natural place for:

 - incubators
- accelerators
- venture studios
- founder platforms
- growth advisory firms

---

 # 31\. The Product Should Support All Three

 Rather than forcing everything into one state machine, the platform should eventually model:

```
Organization
    │
    ├── Advisory engagements
    │
    ├── Investment opportunities
    │
    ├── Portfolio companies
    │
    ├── Fundraising processes
    │
    ├── M&A processes
    │
    └── Growth programs
```

 This is a much more powerful domain model.

---

 # 32\. The Evidence Graph

 The strongest architectural primitive should eventually become an **Evidence Graph**.

 Conceptually:

```
                    COMPANY
                       │
          ┌────────────┼────────────┐
          ↓            ↓            ↓
      Documents      People       Events
          │            │            │
          ↓            ↓            ↓
      Extracted      Meetings     Funding
       Facts
          │
          ↓
       Claims
          │
          ↓
      Research
          │
          ↓
       Analysis
          │
          ↓
      Decision
```

 Every claim can answer:

```
Where did this come from?
Who reviewed it?
When was it extracted?
Was it edited?
What other sources corroborate it?
```

 This should be the backbone of the platform.

---

 # 33\. Why This Is Better Than "AI Agents Everywhere"

 The temptation would be to create:

```
Sourcing Agent
Pitch Agent
Diligence Agent
Valuation Agent
Research Agent
CIM Agent
Investor Agent
Email Agent
```

 But the stronger architecture is:

```
Deterministic domain logic
          +
Evidence layer
          +
Human checkpoints
          +
Specialized AI assistance
```

 AI should operate **inside controlled workflows**.

 It should not own the financial truth.

 This preserves the principle already established in the current architecture:

 > Business rules live in pure functions, not inside the UI.

---

 # 34\. The Correct AI / Human Boundary

 A useful rule is:

```
AI:
Discover
Extract
Classify
Summarize
Compare
Draft
Recommend
Route

Human:
Approve
Reject
Edit
Commit
Negotiate
Sign
Invest
```

 This creates an institutional-grade workflow.

---

 # 35\. Existing Architecture → Future Architecture

 The current system:

```
agents/
store.py
api/
frontend/
```

 can evolve into:

```
domain/
    companies/
    people/
    mandates/
    deals/
    funds/
    portfolios/
    transactions/

evidence/
    documents/
    citations/
    claims/
    provenance/

agents/
    sourcing/
    extraction/
    research/
    diligence/
    valuation/
    pitch/
    compilation/

workflows/
    origination/
    mandate/
    fundraising/
    ma/
    investment/
    portfolio/

analytics/
    financial_model/
    valuation/
    cap_table/
    returns/

execution/
    investors/
    outreach/
    qna/
    closing/

api/

frontend/
```

 The exact directory structure can differ, but the conceptual separation is important.

---

 # 36\. Deal State Machine

 The existing:

```
new
→ mandate_signed
→ ingested
→ extracted
→ reviewed
→ researched
→ research_reviewed
→ compiled
```

 is a good beginning.

 Eventually, it may become:

```
LEAD
 ↓
QUALIFIED
 ↓
ENGAGED
 ↓
PITCHING
 ↓
MANDATE_SIGNED
 ↓
DATA_ROOM_OPEN
 ↓
DILIGENCE
 ↓
UNDERWRITING
 ↓
STRUCTURING
 ↓
MARKETING
 ↓
OUTREACH
 ↓
NEGOTIATION
 ↓
DOCUMENTATION
 ↓
CLOSED
 ↓
PORTFOLIO / CLIENT
 ↓
EXIT
```

 Not every transaction needs every state.

 The transaction type should determine the applicable workflow.

---

 # 37\. Transaction Types

 The system should eventually recognize different transaction types.

```
Equity Fundraise
Debt Raise
M&A Sell-side
M&A Buy-side
IPO
Private Placement
Secondary
Recapitalization
Strategic Partnership
Venture Investment
PE Investment
Growth Investment
```

 Each should have a different checklist.

 For example:

```
Equity fundraise
    → investor universe
    → teaser
    → CIM
    → management meetings
    → term sheets
```

 versus:

```
Sell-side M&A
    → buyer universe
    → teaser
    → CIM
    → IOIs
    → LOIs
    → management meetings
    → final bids
    → definitive agreement
```

---

 # 38\. Indian Market Specialization

 The Indian startup ecosystem should not merely be a geographic label.

 The product can become genuinely India-native.

 Potential areas include:

 - Indian corporate structures
- Pvt Ltd / LLP structures
- MCA data
- GST
- FEMA
- RBI
- SEBI
- ESOP structures
- Indian tax
- cross-border holding structures
- Singapore / Delaware holding companies
- INR / USD modeling
- Indian public comps
- Indian startup funding history
- Indian investor ecosystem
- domestic vs offshore capital
- sector-specific Indian regulations

 This could become a major differentiation from generic global deal software.

---

 # 39\. India-Native Investor Intelligence

 The investor graph should eventually understand:

```
Indian VC
Global VC
Growth fund
Family office
PE
Strategic investor
Sovereign fund
Debt provider
Private credit
Corporate venture
```

 And classify:

```
Stage
Sector
Ticket
Geography
Ownership preference
Lead / follow
Board participation
Typical valuation
Portfolio conflicts
Recent activity
```

 The platform can then recommend investors rather than merely list them.

---

 # 40\. Relationship Intelligence

 Over time the system should understand:

```
Founder A
    │
    ├── knows Partner X
    ├── previously raised from Fund Y
    ├── introduced by Banker Z
    └── met Investor Q
```

 And:

```
Investor Q
    │
    ├── invested in Company A
    ├── knows Founder B
    ├── Partner C covers SaaS
    └── recently raised Fund D
```

 This creates a graph that can answer:

 > Who is the warmest path to this investor?

 That is potentially more valuable than generic AI research.

---

 # 41\. The Audit Log Is Not Optional

 The current placeholder `Audit-log` should become a core feature.

 Every consequential action should be logged:

```
2026-09-13 14:02
Analyst approved ARR
Source: DOC-0231

2026-09-13 14:08
Analyst edited burn
Old: ₹4.2 Cr
New: ₹3.8 Cr
Reason: management clarification

2026-09-13 14:15
Research claim acknowledged

2026-09-13 14:23
CIM generated
```

 This is especially important if the system is eventually used by regulated financial institutions.

---

 # 42\. What Is Already Real

 Based on the current implementation:

 ## Real

 - Sourcing against live external APIs
- Lead management
- Deal promotion
- PDF / Excel ingestion
- Cited DocBlocks
- LLM financial extraction
- Citation-required extraction
- Human review checkpoint
- External research
- Deterministic analytics
- Teaser / CIM / Pro-forma generation
- Structured data builders
- FastAPI backend
- React frontend
- SQLite persistence
- Tenant scoping
- Concurrency protections
- Dashboard
- Leads workflow
- Deal workspace
- Review workflow
- Citation drawer
- Directive preview / confirmation
- 93 backend tests
- Browser-level frontend verification

 ## Not yet production-real

 - Extraction against real company data
- Full diligence
- Research UI
- Document management UI
- Investor workflow
- Audit-log UI
- Formal frontend test suite
- Real authentication
- Production authorization model
- Full financial modeling
- Valuation engine
- Cap-table engine
- Investor outreach
- Term-sheet workflow
- Closing workflow
- Portfolio management
- Company operating layer

 That distinction should remain explicit.

---

 # 43\. The Most Important Product Principle

 The product should never optimize for:

 > "How much work can the AI do without a human?"

 Instead optimize for:

 > **"How much high-quality deal work can one professional supervise?"**

 That is a much better metric.

 For example:

```
Traditional analyst

100 documents
        ↓
Manual reading
        ↓
Spreadsheet
        ↓
Research
        ↓
Draft
        ↓
Review
```

 versus:

```
AI-native analyst

100 documents
        ↓
Automated ingestion
        ↓
Evidence extraction
        ↓
Structured model
        ↓
Research
        ↓
Exceptions
        ↓
Human review
        ↓
Final transaction materials
```

 The goal isn't to eliminate the analyst.

 The goal is to make the analyst dramatically more capable.

---

 # 44\. Recommended Product Roadmap

 ## Phase 1 — Finish the Deal Workspace

 Priority:

 1. Research tab
2. Documents tab
3. Investors tab
4. Audit log
5. Evidence viewer
6. Data-room structure
7. Diligence checklist

 This turns the current prototype into a coherent transaction workspace.

---

 ## Phase 2 — Origination

 Build:

```
CRM
Leads
Relationships
Meetings
Opportunities
Pitch
Mandates
```

 This moves the system upstream.

---

 ## Phase 3 — Underwriting

 Build:

```
Financial model
Valuation
Cap table
Dilution
Scenarios
Risk register
IC memo
```

 This moves the system from document processing to financial decision support.

---

 ## Phase 4 — Transaction Execution

 Build:

```
Investor universe
Outreach
NDA
Data room
Q&A
Management meetings
IOIs
LOIs
Term sheets
Closing
```

 This creates an actual transaction operating system.

---

 ## Phase 5 — Company / Portfolio

 Build:

```
Portfolio dashboard
KPIs
GTM
Fundraising readiness
Board reporting
Strategic initiatives
Follow-on financing
Exit planning
```

 This creates the company-building layer.

---

 # 45\. The Long-Term Product Architecture

 The end-state can be visualized as six major planes:

```
┌─────────────────────────────────────────────────────────────┐
│                  RELATIONSHIP / CRM                         │
│ Founders • Investors • Bankers • Meetings • Emails • Tasks │
├─────────────────────────────────────────────────────────────┤
│                     ORIGINATION                             │
│ Sourcing • Screening • Leads • Pitch • Mandate              │
├─────────────────────────────────────────────────────────────┤
│                   DEAL INTELLIGENCE                          │
│ Data Room • Extraction • Research • Diligence • Evidence    │
├─────────────────────────────────────────────────────────────┤
│                    FINANCIAL ENGINE                          │
│ Models • Valuation • Cap Table • Scenarios • Returns        │
├─────────────────────────────────────────────────────────────┤
│                  TRANSACTION ENGINE                          │
│ CIM • Teaser • IC Memo • Investor List • Q&A • Term Sheet   │
├─────────────────────────────────────────────────────────────┤
│                  COMPANY / PORTFOLIO                          │
│ GTM • KPIs • Fundraising • Board • Strategy • Exit          │
└─────────────────────────────────────────────────────────────┘

                        ↓↓↓

                  EVIDENCE GRAPH

 Documents ──┐
             ├── Claims ── Analysis ── Decisions
 Research ───┤
             │
 Human review┘
```

---

 # 46\. The Strategic Moat

 The moat should not be:

 > "We have an LLM."

 It should be:

 ### 1\. Structured financial data

 The platform understands the company financially.

 ### 2\. Evidence graph

 Every important assertion has provenance.

 ### 3\. Human decision history

 The platform learns what analysts approved, changed, rejected and why.

 ### 4\. Transaction history

 The system accumulates knowledge about:

 - deals
- investors
- valuations
- outcomes
- processes
- sector patterns

 ### 5\. Relationship graph

 It knows:

 - founders
- investors
- bankers
- partners
- introductions
- prior transactions

 ### 6\. Workflow intelligence

 It understands what stage a deal is actually in.

 ### 7\. India-specific knowledge

 It understands the structures, regulations, investors and conventions of the Indian market.

 Together, these are much harder to replicate than a document chatbot.

---

 # 47\. The Ultimate Vision

 The end state could look like this:

```
                    COMPANY SIGNAL
                         │
                         ▼
                  AI ORIGINATION
                         │
                         ▼
                    QUALIFICATION
                         │
                         ▼
                    RELATIONSHIP
                         │
                         ▼
                       PITCH
                         │
                         ▼
                      MANDATE
                         │
                         ▼
                  ┌──────────────┐
                  │ DEAL ROOM    │
                  └──────┬───────┘
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
          FINANCIAL   COMMERCIAL   LEGAL
          DILIGENCE   DILIGENCE    DILIGENCE
              │          │          │
              └──────────┼──────────┘
                         ▼
                     UNDERWRITE
                         │
                         ▼
                    VALUATION
                         │
                         ▼
                     STRUCTURE
                         │
                         ▼
                ┌─────────────────┐
                │ TRANSACTION DOCS│
                │ Teaser / CIM / IC│
                └────────┬────────┘
                         │
                         ▼
                   INVESTOR / BUYER
                       OUTREACH
                         │
                         ▼
                    NEGOTIATION
                         │
                         ▼
                       CLOSE
                         │
                         ▼
                COMPANY / PORTFOLIO
                       WORKSPACE
                         │
                         ▼
                    FOLLOW-ON
                         │
                         ▼
                       EXIT
```

---

 # 48\. Final Product Definition

 The strongest definition of the product is therefore:

 > **An AI-native operating system for investment banking, venture capital, private equity and growth advisory that manages the complete lifecycle of a company — from sourcing and relationship development through mandate, diligence, underwriting, valuation, capital raising, transaction execution, and post-deal growth.**

 The first version does **not** need to implement everything.

 The current system has already established the most important foundation:

```
Source
  ↓
Evidence
  ↓
Extract
  ↓
Human review
  ↓
Research
  ↓
Analyze
  ↓
Compile
```

 The next step is to surround that core with:

```
CRM
+
Pitch
+
Mandate
+
Diligence
+
Modeling
+
Valuation
+
Investor execution
+
Closing
+
Portfolio support
```

 The resulting product is not merely a better CIM generator.

 It becomes a **deal operating system**.

 And the eventual ambition can go one step further:

 > **A financial institution's operating system for discovering companies, deciding which ones matter, helping them become financeable, raising capital for them, executing transactions, and continuing to support them after the transaction.**

 That is the broader product thesis worth designing the architecture around.\
 :::
