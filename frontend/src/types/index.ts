// ─── Core Type Definitions ───────────────────────────────────────────────────

export type ValidationStatus =
  | "match"
  | "mismatch"
  | "cannot_verify"
  | "not_applicable"
  | "not_checked";

export type ShipmentStatus =
  | "draft"
  | "queued"
  | "processing"
  | "ready_for_review"
  | "finalized"
  | "failed";

export type ReviewDecision =
  | "confirm_issue"
  | "override_finding"
  | "request_correction";

export type DocumentType =
  | "commercial_invoice"
  | "packing_list"
  | "bill_of_lading"
  | "air_waybill"
  | "certificate_of_origin"
  | "purchase_order"
  | "customs_declaration"
  | "unknown";

export type FindingSeverity = "low" | "medium" | "high";
export type ReviewStatus = "pending" | "reviewed";

// ─── Evidence & Extraction ───────────────────────────────────────────────────

export interface SourceEvidence {
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
  documentId: string;
  rawValue: string | null;
  normalizedValue: string | number | null;
  source: SourceEvidence | null;
}

export interface MatrixField {
  fieldKey: string;
  label: string;
  status: ValidationStatus;
  cells: MatrixCell[];
}

// ─── Findings ─────────────────────────────────────────────────────────────────

export interface ReviewAction {
  decision: ReviewDecision;
  reason?: string;
  reviewerId: string;
  reviewerName: string;
  reviewedAt: string;
}

export interface Finding {
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
  id: string;
  filename: string;
  type: DocumentType;
  typeLabel: string;
  sizeBytes: number;
  uploadedAt: string;
  status: "uploaded" | "queued" | "processing" | "processed" | "failed";
  pageCount?: number;
  contentUrl?: string;
}

// ─── Shipment ─────────────────────────────────────────────────────────────────

export interface Shipment {
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
  checkedFields: string[];
  notCheckedFields: string[];
}

export interface ValidationResults {
  shipmentId: string;
  status: ShipmentStatus;
  documents: {
    id: string;
    filename: string;
    type: string;
    typeLabel: string;
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
  shipmentId: string;
  shipmentStatus: ShipmentStatus;
  stages: ProcessingStage[];
  currentStageIndex: number;
  documentStatuses: {
    documentId: string;
    filename: string;
    status: "queued" | "processing" | "done" | "failed";
  }[];
}

// ─── Report ───────────────────────────────────────────────────────────────────

export interface ReportSection {
  title: string;
  content: string;
}

export interface ValidationReport {
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

export interface CreateShipmentPayload {
  reference: string;
  originCountry: string;
  destinationCountry: string;
  preferentialDutyClaim: boolean;
}

export interface ReviewFindingPayload {
  decision: ReviewDecision;
  reason?: string;
}

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
