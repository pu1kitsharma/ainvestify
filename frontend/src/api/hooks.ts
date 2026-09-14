import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiClientError } from "./client";
import { api } from "./client";
import type {
  AuditEvent,
  Deal,
  DealSummary,
  DealStatus,
  DocumentType,
  ExtractionResult,
  FieldDecisionResponse,
  InvestorContact,
  MemoVersion,
  PlannerDecision,
  ResearchFinding,
  ReviewPayload,
  RouterDecision,
  SourcedLead,
  SourceDocument,
  LeadStatus,
  WebSourcingRun,
} from "./types";

// --- Dashboard / deals ------------------------------------------------

export function useDeals(status?: DealStatus) {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return useQuery({
    queryKey: ["deals", status ?? "all"],
    queryFn: () => api.get<DealSummary[]>(`/api/deals${qs}`),
  });
}

export function useDeal(dealId: string | undefined) {
  return useQuery({
    queryKey: ["deal", dealId],
    queryFn: () => api.get<Deal>(`/api/deals/${dealId}`),
    enabled: !!dealId,
  });
}

export function useCreateDeal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; stage?: string }) => api.post<Deal>("/api/deals", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["deals"] }),
  });
}

// --- Prompt bar ---------------------------------------------------------

export function useClassifyPrompt() {
  return useMutation({
    mutationFn: (prompt: string) => api.post<RouterDecision>("/api/prompt/classify", { prompt }),
  });
}

// --- Leads ---------------------------------------------------------------

export function useLeads(status?: LeadStatus, webRunOnly?: boolean) {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (webRunOnly) params.set("web_run_only", "true");
  const qs = params.toString();
  return useQuery({
    queryKey: ["leads", status ?? "all", webRunOnly ?? false],
    queryFn: () => api.get<SourcedLead[]>(`/api/leads${qs ? `?${qs}` : ""}`),
  });
}

export function useWebRuns() {
  return useQuery({
    queryKey: ["webRuns"],
    queryFn: () => api.get<WebSourcingRun[]>("/api/leads/web-runs"),
    refetchInterval: (q) => q.state.data?.some((r) => ["running", "cancel_requested"].includes(r.status)) ? 2500 : false,
  });
}

export function useStartWebRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { thesis: string; geography?: string; seed_urls?: string[]; prepare_workflow?: boolean }) =>
      api.post<WebSourcingRun>("/api/leads/web-runs", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["webRuns"] }),
  });
}

export function useCancelWebRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<WebSourcingRun>(`/api/leads/web-runs/${id}/cancel`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["webRuns"] }),
  });
}

export function useSourceLeads() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { sector_keyword: string; location_filter?: string | null }) =>
      api.post<SourcedLead[]>("/api/leads/source", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["leads"] }),
  });
}

export function useSourceIbTargets() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { sector_keyword: string }) => api.post<SourcedLead[]>("/api/leads/source-ib", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["leads"] }),
  });
}

export function useLeadDecision() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ leadId, decision }: { leadId: string; decision: "keep" | "dismiss" }) =>
      api.post<SourcedLead>(`/api/leads/${leadId}/decision`, { decision }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["leads"] }),
  });
}

export function usePromoteLead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ leadId, name }: { leadId: string; name?: string }) =>
      api.post<Deal>(`/api/leads/${leadId}/promote`, { name }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["leads"] });
      qc.invalidateQueries({ queryKey: ["deals"] });
    },
  });
}

// --- Deal lifecycle (sign mandate, ingest, extract) -----------------------

function invalidateDeal(qc: ReturnType<typeof useQueryClient>, dealId: string) {
  qc.invalidateQueries({ queryKey: ["deal", dealId] });
  qc.invalidateQueries({ queryKey: ["deals"] });
  qc.invalidateQueries({ queryKey: ["auditLog", dealId] });
  qc.invalidateQueries({ queryKey: ["sourceDocuments", dealId] });
  qc.invalidateQueries({ queryKey: ["operations"] });
}

export function useSignMandate(dealId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { mandate_type: string; terms_summary: string }) =>
      api.post<Deal>(`/api/deals/${dealId}/mandate`, body),
    onSuccess: () => invalidateDeal(qc, dealId),
  });
}

export function useUploadDocument(dealId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api.postForm<Deal>(`/api/deals/${dealId}/documents`, form);
    },
    onSuccess: () => invalidateDeal(qc, dealId),
  });
}

export function useExtractDeal(dealId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body?: { model?: string; reviewer_feedback?: string | null }) =>
      api.post<ExtractionResult>(`/api/deals/${dealId}/extract`, body ?? {}),
    onSuccess: () => {
      invalidateDeal(qc, dealId);
      qc.invalidateQueries({ queryKey: ["review", dealId] });
    },
  });
}

export function useSourceDocuments(dealId: string | undefined) {
  return useQuery({
    queryKey: ["sourceDocuments", dealId],
    queryFn: () => api.get<SourceDocument[]>(`/api/deals/${dealId}/source-documents`),
    enabled: !!dealId,
  });
}

export function useAuditLog(dealId: string | undefined) {
  return useQuery({
    queryKey: ["auditLog", dealId],
    queryFn: () => api.get<AuditEvent[]>(`/api/deals/${dealId}/audit-log`),
    enabled: !!dealId,
  });
}

// --- Directive bar --------------------------------------------------------

export function useDirectivePreview(dealId: string) {
  return useMutation({
    mutationFn: (directive: string) =>
      api.post<PlannerDecision>(`/api/deals/${dealId}/directive/preview`, { directive }),
  });
}

// --- Review ----------------------------------------------------------------

export function useReview(dealId: string | undefined) {
  return useQuery({
    queryKey: ["review", dealId],
    queryFn: () => api.get<ReviewPayload>(`/api/deals/${dealId}/review`),
    enabled: !!dealId,
  });
}

/** True on a 409 -- the compare-and-swap conflict api/routers/review.py's
 * _persist_and_respond raises when another decision landed on this deal's
 * extraction result in between this client's read and write. Distinct from
 * every other error: the fix is "refresh and retry the same click," not
 * "something is broken." */
export function isReviewConflict(error: unknown): boolean {
  return error instanceof ApiClientError && error.status === 409;
}

export function useFieldDecision(dealId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      field,
      decision,
      newValue,
      note,
    }: {
      field: string;
      decision: "approve" | "edit" | "reject" | "acknowledge";
      newValue?: string;
      note?: string;
    }) =>
      api.post<FieldDecisionResponse>(`/api/deals/${dealId}/review/fields/${field}`, {
        decision,
        new_value: newValue,
        note,
      }),
    onSuccess: (data) => {
      qc.setQueryData<ReviewPayload>(["review", dealId], (prev) =>
        prev ? { ...prev, extraction_result: data.extraction_result } : prev,
      );
      invalidateDeal(qc, dealId);
      qc.invalidateQueries({ queryKey: ["review", dealId] });
    },
  });
}

export function useCapTableDecision(dealId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ decision, note }: { decision: "approve" | "reject"; note?: string }) =>
      api.post<FieldDecisionResponse>(`/api/deals/${dealId}/review/cap-table`, { decision, note }),
    onSuccess: () => {
      invalidateDeal(qc, dealId);
      qc.invalidateQueries({ queryKey: ["review", dealId] });
    },
  });
}

export function useFundingHistoryDecision(dealId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ decision, note }: { decision: "approve" | "reject"; note?: string }) =>
      api.post<FieldDecisionResponse>(`/api/deals/${dealId}/review/funding-history`, { decision, note }),
    onSuccess: () => {
      invalidateDeal(qc, dealId);
      qc.invalidateQueries({ queryKey: ["review", dealId] });
    },
  });
}

// --- Research (used by the directive bar's research/rerun_research + the
// /research tab in the next checkpoint) -----------------------------------

export function useRunResearch(dealId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { company_name: string; sector_query?: string }) =>
      api.post<ResearchFinding[]>(`/api/deals/${dealId}/research/run`, body),
    onSuccess: () => invalidateDeal(qc, dealId),
  });
}

export function useResearchFindings(dealId: string | undefined) {
  return useQuery({
    queryKey: ["research", dealId],
    queryFn: () => api.get<ResearchFinding[]>(`/api/deals/${dealId}/research`),
    enabled: !!dealId,
  });
}

export function useFindingDecision(dealId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ findingId, decision }: { findingId: string; decision: "approve" | "reject" }) =>
      api.post<ResearchFinding>(`/api/deals/${dealId}/research/${findingId}/decision`, { decision }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["research", dealId] }),
  });
}

export function useMarkResearchReviewed(dealId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<Deal>(`/api/deals/${dealId}/research/mark-reviewed`),
    onSuccess: () => invalidateDeal(qc, dealId),
  });
}

// --- Documents (compiled memo suite) ---------------------------------------

export function useDocuments(dealId: string | undefined, documentType?: DocumentType) {
  const qs = documentType ? `?document_type=${documentType}` : "";
  return useQuery({
    queryKey: ["documents", dealId, documentType ?? "all"],
    queryFn: () => api.get<MemoVersion[]>(`/api/deals/${dealId}/documents${qs}`),
    enabled: !!dealId,
  });
}

function invalidateDocuments(qc: ReturnType<typeof useQueryClient>, dealId: string) {
  qc.invalidateQueries({ queryKey: ["documents", dealId] });
  invalidateDeal(qc, dealId);
}

export function useCompileCim(dealId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<MemoVersion>(`/api/deals/${dealId}/compile/cim`),
    onSuccess: () => invalidateDocuments(qc, dealId),
  });
}

export function useTeaserDraft(dealId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (business_description: string) =>
      api.post<MemoVersion>(`/api/deals/${dealId}/compile/teaser/draft`, { business_description }),
    onSuccess: () => invalidateDocuments(qc, dealId),
  });
}

export function useConfirmTeaser(dealId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ memoId, confirmed }: { memoId: string; confirmed: boolean }) =>
      api.post<MemoVersion>(`/api/deals/${dealId}/compile/teaser/${memoId}/confirm`, { confirmed }),
    onSuccess: () => invalidateDocuments(qc, dealId),
  });
}

export function useCompileProforma(dealId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (growth_rate_override?: number) =>
      api.post<MemoVersion>(`/api/deals/${dealId}/compile/proforma`, { growth_rate_override }),
    onSuccess: () => invalidateDocuments(qc, dealId),
  });
}

export function useRerunAnalytics(dealId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post(`/api/deals/${dealId}/analytics/rerun`),
    onSuccess: () => invalidateDeal(qc, dealId),
  });
}

// --- Investors (demand book) ------------------------------------------------

export function useInvestors(dealId: string | undefined) {
  return useQuery({
    queryKey: ["investors", dealId],
    queryFn: () => api.get<InvestorContact[]>(`/api/deals/${dealId}/investors`),
    enabled: !!dealId,
  });
}

export function useAddInvestor(dealId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      investor_name: string;
      firm?: string;
      nda_status?: string;
      interest_level?: string;
      notes?: string;
    }) => api.post<InvestorContact>(`/api/deals/${dealId}/investors`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["investors", dealId] });
      invalidateDeal(qc, dealId);
    },
  });
}
