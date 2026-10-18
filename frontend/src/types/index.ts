import type { components } from "./backend.generated";
// ─── Core Type Definitions ───────────────────────────────────────────────────

export type ValidationStatus =
  | "match"
  | "mismatch"
  | "cannot_verify"
  | "not_applicable"
  | "not_checked";

export type ShipmentStatus =
  | "uploading"
  | "reviewed"
  | "archived"
  | "draft"
  | "queued"
  | "processing"
  | "ready_for_review"
  | "finalized"
  | "failed";

export type ReviewDecision = components["schemas"]["DecisionAction"];

export type DocumentType =
  | "commercial_invoice"
  | "packing_list"
  | "bill_of_lading"
  | "air_waybill"
  | "certificate_of_origin"
  | "purchase_order"
  | "customs_declaration"
  | "insurance_certificate"
  | "unknown";

export type FindingSeverity = "low" | "medium" | "high";
export type ReviewStatus = "pending" | "reviewed";

// ─── Evidence & Extraction ───────────────────────────────────────────────────

export interface SourceEvidence {
  pageKnown?: boolean;
  promptVersion?: string;
  page: number;
  bbox: [number, number, number, number] | null;
  confidence: number | null;
  excerpt: string | null;
  sheetName?: string;
  cellRange?: string;
  modelId?: string;
  modelVersion?: string;
  extractedAt?: string;
}

// ─── Matrix Types ─────────────────────────────────────────────────────────────

export interface MatrixCell {
  cellStatus?: components["schemas"]["CellStatus"];
  normalizedUnit?: string;
  documentId: string;
  rawValue: string | null;
  normalizedValue: string | number | null;
  source: SourceEvidence | null;
}

export interface MatrixField {
  group?: string;
  verdict?: components["schemas"]["Verdict"];
  reason?: string | null;
  fieldKey: string;
  label: string;
  status: ValidationStatus;
  cells: MatrixCell[];
}

// ─── Findings ─────────────────────────────────────────────────────────────────

export interface ReviewAction {
  chosenDocumentId?: string;
  chosenValue?: string;
  decision: ReviewDecision;
  reason?: string;
  reviewerId: string;
  reviewerName: string;
  reviewedAt: string;
}

export interface Finding {
  version?: number;
  suggestedValue?: string | null;
  suggestedDocumentId?: string | null;
  verdict?: components["schemas"]["Verdict"];
  verdictReason?: string | null;
  explanationState?: components["schemas"]["ExplanationState"];
  cells?: MatrixCell[];
  id: string;
  fieldKey: string;
  label: string;
  severity: FindingSeverity;
  status: ValidationStatus;
  explanation: string;
  suggestion: string | null;
  reviewStatus: ReviewStatus;
  reviewAction?: ReviewAction;
  affectedDocuments: string[];
}

// ─── Documents ────────────────────────────────────────────────────────────────

export interface ShipmentDocument {
  backendStatus?: components["schemas"]["DocumentStatus"];
  typeConfidence?: number | null;
  errorCode?: string;
  supersededBy?: string;
  id: string;
  filename: string;
  type: DocumentType;
  typeLabel: string;
  sizeBytes: number;
  uploadedAt: string;
  status: "uploaded" | "queued" | "processing" | "processed" | "superseded" | "failed";
  pageCount?: number;
  contentUrl?: string;
}

// ─── Shipment ─────────────────────────────────────────────────────────────────

export interface Shipment {
  version?: number;
  documentCount?: number;
  reportId?: string;
  currentRun?: components["schemas"]["RunOut"];
  missingDocuments?: components["schemas"]["MissingDocumentOut"][];
  id: string;
  reference: string;
  originCountry: string;
  destinationCountry: string;
  preferentialDutyClaim: boolean;
  status: ShipmentStatus;
  documents: ShipmentDocument[];
  createdAt: string;
  updatedAt: string;
  createdBy: string;
  discrepancyCount: number;
  validatedAt?: string;
  finalizedAt?: string;
}

// ─── Validation Results ───────────────────────────────────────────────────────

export interface ValidationSummary {
  matched: number;
  mismatched: number;
  cannotVerify: number;
  notChecked: number;
  notApplicable: number;
}

export interface ValidationCoverage {
  singleSourceFields?: components["schemas"]["CoverageField"][];
  cannotVerifyFields?: components["schemas"]["CoverageField"][];
  notApplicableFields?: components["schemas"]["CoverageField"][];
  outOfScope?: components["schemas"]["OutOfScopeOut"][];
  uncheckedDocuments?: components["schemas"]["UncheckedDocument"][];
  missingDocuments?: components["schemas"]["MissingDocumentOut"][];
  checkedFields: string[];
  notCheckedFields: string[];
}

export interface ValidationResults {
  runId?: string;
  shipmentId: string;
  status: ShipmentStatus;
  documents: {
    id: string;
    filename: string;
    type: string;
    typeLabel: string;
    pageCount?: number | null;
    status?: string;
    errorCode?: string;
  }[];
  summary: ValidationSummary;
  matrix: MatrixField[];
  findings: Finding[];
  coverage: ValidationCoverage;
  generatedAt: string;
}

// ─── Processing Stages ────────────────────────────────────────────────────────

export type ProcessingStageStatus = "pending" | "running" | "done" | "failed";

export interface ProcessingStage {
  id: string;
  label: string;
  description: string;
  status: ProcessingStageStatus;
  startedAt?: string;
  completedAt?: string;
}

export interface ProcessingStatus {
  errorMessage?: string;
  shipmentId: string;
  shipmentStatus: ShipmentStatus;
  stages: ProcessingStage[];
  currentStageIndex: number;
  documentStatuses: {
    documentId: string;
    filename: string;
    status: "queued" | "processing" | "done" | "skipped" | "failed";
  }[];
}

// ─── Report ───────────────────────────────────────────────────────────────────

export interface ReportSection {
  title: string;
  content: string;
}

export interface ValidationReport {
  issuedReport?: components["schemas"]["ReportOut"];
  shipmentId: string;
  reference: string;
  generatedAt: string;
  generatedBy: string;
  status: "draft" | "finalized";
  shipment: Shipment;
  results: ValidationResults;
  reviewerDecisions: {
    findingId: string;
    field: string;
    decision: ReviewDecision;
    reason?: string;
    reviewerName: string;
    reviewedAt: string;
  }[];
  pendingReviews: number;
  canFinalize: boolean;
}

// ─── API Payloads ─────────────────────────────────────────────────────────────

export interface CreateShipmentPayload { reference: string; }
export interface ReviewFindingPayload {
  decision: ReviewDecision;
  reason?: string;
  expectedVersion?: number;
  chosenDocumentId?: string;
  chosenValue?: string;
}
export type UploadProgress = (file: File, percent: number) => void;

// ─── UI State ─────────────────────────────────────────────────────────────────

export interface ToastMessage {
  id: string;
  title: string;
  description?: string;
  variant: "default" | "destructive" | "success";
}

export interface DashboardStats {
  totalShipments: number;
  pendingValidations: number;
  requiresReview: number;
  completedValidations: number;
  totalDiscrepancies: number;
}
