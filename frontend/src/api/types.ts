// Mirrors schemas.py and api/models.py. Kept as plain interfaces (no
// runtime validation library) since the backend is the single source of
// truth for these shapes -- this file exists so the frontend gets
// autocomplete/type-checking, not as an independent schema to keep in sync
// by hand copy-pasting field-by-field logic.

export type FieldStatus = "proposed" | "approved" | "edited" | "rejected" | "not_found";

export type DealStatus =
  | "new"
  | "mandate_signed"
  | "ingested"
  | "extracted"
  | "reviewed"
  | "needs_manual_input"
  | "researched"
  | "research_reviewed"
  | "compiled";

export type LeadStatus = "new" | "reviewed" | "promoted_to_deal" | "dismissed";

export interface ExtractedValue {
  value: number | null;
  unit: string | null;
  source_block_id: string | null;
  source_page: number | null;
  confidence: number | null;
  extraction_method: string | null;
  reason: string | null;
  status: FieldStatus;
  reviewer: string | null;
  reviewed_at: string | null;
  edit_note: string | null;
  retry_count: number;
}

export interface CapTableRow {
  holder: string | null;
  pct: number | null;
  share_class: string | null;
}

export interface FundingRound {
  round_name: string | null;
  amount: number | null;
  date: string | null;
  lead_investor: string | null;
  source_block_id: string | null;
  source_page: number | null;
}

export const SCALAR_FIELDS = [
  "arr",
  "arr_prior_year",
  "mrr",
  "growth_rate_yoy",
  "burn_monthly",
  "cash_on_hand",
  "runway_months",
  "headcount",
] as const;
export type ScalarField = (typeof SCALAR_FIELDS)[number];

export const SCALAR_FIELD_LABELS: Record<ScalarField, string> = {
  arr: "ARR",
  arr_prior_year: "ARR (Prior Year)",
  mrr: "MRR",
  growth_rate_yoy: "YoY Growth Rate",
  burn_monthly: "Monthly Burn",
  cash_on_hand: "Cash on Hand",
  runway_months: "Runway (months)",
  headcount: "Headcount",
};

export type ExtractionResult = {
  tenant_id: string;
  deal_id: string;
  document_id: string;
  cap_table: CapTableRow[];
  cap_table_source_block_id: string | null;
  cap_table_status: FieldStatus;
  cap_table_reviewer: string | null;
  cap_table_reviewed_at: string | null;
  cap_table_retry_count: number;
  funding_history: FundingRound[];
  funding_history_status: FieldStatus;
  funding_history_reviewer: string | null;
  funding_history_reviewed_at: string | null;
  funding_history_retry_count: number;
  extracted_at: string;
  cross_check_flags: string[];
} & Record<ScalarField, ExtractedValue>;

export interface Deal {
  id: string;
  tenant_id: string;
  name: string;
  stage: string | null;
  status: DealStatus;
  created_at: string;
  document_ids: string[];
  mandate_type: string | null;
  mandate_terms_summary: string | null;
  mandate_signed_at: string | null;
}

export interface DealSummary {
  deal: Deal;
  document_count: number;
  research_finding_count: number;
  memo_version_count: number;
  investor_count: number;
}

export interface DiscoverySignal {
  content: string;
  source_url: string | null;
  source_type: string;
  discovered_at: string;
}

export interface SourcedLead {
  id: string;
  tenant_id: string;
  company_name: string;
  sector_tag: string | null;
  discovery_signals: DiscoverySignal[];
  status: LeadStatus;
  promoted_deal_id: string | null;
}

export interface ResearchFinding {
  id: string;
  tenant_id: string;
  deal_id: string;
  topic: string;
  content: string;
  source_url: string | null;
  source_type: string;
  retrieved_at: string;
  status: FieldStatus;
}

export interface InvestorContact {
  id: string;
  tenant_id: string;
  deal_id: string;
  investor_name: string;
  firm: string | null;
  teaser_sent_at: string | null;
  nda_status: "not_sent" | "sent" | "signed";
  cim_shared_at: string | null;
  interest_level: "new" | "cold" | "warm" | "hot" | "passed" | "committed";
  notes: string | null;
  updated_at: string;
}

export interface DocBlock {
  id: string;
  document_id: string;
  page: number;
  block_type: "text" | "table";
  coordinates: Record<string, unknown>;
  content: string | string[][];
}

export interface SourceDocument {
  id: string;
  tenant_id: string;
  deal_id: string;
  filename: string;
  type: string;
  storage_uri: string;
  blocks: DocBlock[];
}

export interface AuditEvent {
  id: string;
  tenant_id: string;
  deal_id: string;
  actor: string;
  action: string;
  target_id: string;
  timestamp: string;
  before: unknown;
  after: unknown;
}

export type DocumentType = "cim" | "teaser" | "proforma";

// Mirrors agents/compilation_agent.py's build_cim_data / build_teaser_data /
// generate_proforma_projection return shapes -- MemoVersion.structured_data
// is exactly one of these three depending on document_type.

export interface StructuredFinancialField {
  label: string;
  value: number | null;
  unit: string | null;
  status: FieldStatus;
  edited: boolean;
  show_source: boolean;
  source_block_id: string | null;
  source_page: number | null;
}

export interface CimStructuredData {
  deal_id: string;
  generated_at: string;
  version_number: number;
  narrative: string | null;
  financials: Record<ScalarField, StructuredFinancialField>;
  cross_check_flags: string[];
  cap_table: {
    available: boolean;
    rows: CapTableRow[];
    source_block_id: string | null;
  };
  funding_history: {
    available: boolean;
    rounds: FundingRound[];
  };
  external_signals: { topic: string; content: string; source: string }[];
  charts: { chart_type: string; storage_uri: string }[];
}

export interface TeaserStructuredData {
  generated_at: string;
  version_number: number;
  business_description: string;
  financials: Record<"arr" | "growth_rate_yoy" | "burn_monthly" | "runway_months" | "headcount", StructuredFinancialField>;
  charts: { chart_type: string; storage_uri: string }[];
}

export interface ProformaStructuredData {
  assumptions: string[];
  rows: { year: number; arr: number; cash_on_hand: number | null }[];
  growth_rate_pct: number;
  is_projected: true;
  deal_id: string;
  generated_at: string;
  version_number: number;
}

export interface MemoVersion {
  id: string;
  tenant_id: string;
  deal_id: string;
  version_number: number;
  generated_at: string;
  approved_by: string | null;
  content_uri: string;
  document_type: DocumentType;
  structured_data: Record<string, unknown> | null;
}

export interface ReviewPayload {
  extraction_result: ExtractionResult | null;
  ready_for_compilation: boolean;
  cross_check_flags: string[];
}

export interface ReviewDecisionOutcome {
  resolved: boolean;
  retries_used: number;
  audit_events: AuditEvent[];
  message: string | null;
}

export interface FieldDecisionResponse {
  outcome: ReviewDecisionOutcome;
  extraction_result: ExtractionResult;
  deal: Deal;
}

export interface RouterDecision {
  action: "source_leads" | "screen_deal" | "unknown";
  sector_keyword: string | null;
  location_filter: string | null;
  reasoning: string;
}

export interface PlannerDecision {
  action: string;
  reasoning: string;
  target_field: string | null;
}

export interface ApiError {
  detail: string;
}
