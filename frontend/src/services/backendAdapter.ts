import type { components } from "@/types/backend.generated";
import type { Shipment, ShipmentStatus, ShipmentDocument, MatrixCell, MatrixField, Finding, ReviewAction, ValidationResults, ProcessingStatus, ValidationCoverage } from "@/types";
type Schema = components["schemas"];
export type BackendShipment = Schema["ShipmentDetail"];
export type BackendSummary = Schema["ShipmentSummary"];
export type BackendDocument = Schema["DocumentOut"];
export type BackendMatrix = Schema["MatrixResponse"];
export type BackendFinding = Schema["DiscrepancyOut"];
export type BackendCoverage = Schema["CoverageResponse"];
export type BackendReport = Schema["ReportOut"];
export const DOC_LABELS: Record<Schema["DocType"], string> = { COMMERCIAL_INVOICE: "Commercial Invoice", PACKING_LIST: "Packing List", BILL_OF_LADING: "Bill of Lading", AIR_WAYBILL: "Air Waybill", CERTIFICATE_OF_ORIGIN: "Certificate of Origin", PURCHASE_ORDER: "Purchase Order", CUSTOMS_DECLARATION: "Customs Declaration", INSURANCE_CERTIFICATE: "Insurance Certificate", UNKNOWN: "Unknown" };
const STATUS_MAP: Record<Schema["ShipmentStatus"], ShipmentStatus> = { DRAFT: "draft", UPLOADING: "uploading", QUEUED: "queued", PROCESSING: "processing", AWAITING_REVIEW: "ready_for_review", REVIEWED: "reviewed", REPORT_ISSUED: "finalized", FAILED: "failed", ARCHIVED: "archived" };
export function shipmentStatus(status: Schema["ShipmentStatus"]) { return STATUS_MAP[status]; }
export function documentStatus(status: Schema["DocumentStatus"]): ShipmentDocument["status"] { return status === "EXTRACTED" ? "processed" : status === "FAILED" ? "failed" : status === "SUPERSEDED" ? "superseded" : status === "REGISTERED" ? "uploaded" : "processing"; }
export function adaptDocument(doc: BackendDocument): ShipmentDocument {
  return { id: doc.document_id, filename: doc.filename, type: (doc.doc_type || "UNKNOWN").toLowerCase() as ShipmentDocument["type"], typeLabel: DOC_LABELS[doc.doc_type || "UNKNOWN"], status: documentStatus(doc.status), sizeBytes: doc.size_bytes, uploadedAt: doc.created_at, pageCount: doc.page_count ?? undefined, backendStatus: doc.status, errorCode: doc.error_code ?? undefined, typeConfidence: doc.doc_type_confidence, supersededBy: doc.superseded_by ?? undefined };
}
export function adaptSummary(data: BackendSummary): Shipment {
  return { id: data.shipment_id, reference: data.reference, status: shipmentStatus(data.status), version: data.version, originCountry: "", destinationCountry: "", preferentialDutyClaim: false, documents: [], documentCount: data.document_count, createdAt: data.created_at, updatedAt: data.updated_at, createdBy: "", discrepancyCount: data.open_discrepancy_count };
}
export function adaptShipment(data: BackendShipment): Shipment {
  return { ...adaptSummary({ ...data, document_count: data.documents.length }), documents: data.documents.map(adaptDocument), createdBy: data.created_by, validatedAt: data.current_run?.finished_at ?? undefined, reportId: data.report_id ?? undefined, missingDocuments: data.missing_documents, currentRun: data.current_run ?? undefined };
}
export function xyxyToBbox(box: number[] | null | undefined): [number, number, number, number] | null {
  if (!box || box.length !== 4 || box.some(value => !Number.isFinite(value))) return null;
  const [left, top, right, bottom] = box;
  return left >= 0 && top >= 0 && right <= 1 && bottom <= 1 && right > left && bottom > top ? [left, top, right - left, bottom - top] : null;
}
export function adaptCell(cell: Schema["CellOut"]): MatrixCell {
  return { documentId: cell.document_id, rawValue: cell.raw_value, normalizedValue: cell.normalized_value, normalizedUnit: cell.normalized_unit ?? undefined, cellStatus: cell.cell_status,
    source: cell.provenance ? { page: cell.provenance.page ?? 1, pageKnown: cell.provenance.page !== null, bbox: xyxyToBbox(cell.provenance.bbox), confidence: cell.confidence, excerpt: null, modelId: cell.provenance.model, modelVersion: cell.provenance.model_version, promptVersion: cell.provenance.prompt_version, extractedAt: cell.provenance.extracted_at } : null };
}
export function verdictStatus(verdict: Schema["Verdict"]): MatrixField["status"] {
  if (["AGREE", "AGREE_AT_HS_ROOT", "TOLERANCE_MATCH"].includes(verdict)) return "match";
  if (verdict === "DISAGREE") return "mismatch";
  if (verdict === "NOT_APPLICABLE") return "not_applicable";
  return "cannot_verify";
}
export function adaptDecision(decision: Schema["DecisionOut"]): ReviewAction {
  return { decision: decision.action, reason: decision.reason ?? undefined, reviewerId: decision.actor_user_id, reviewerName: decision.actor_user_id, reviewedAt: decision.decided_at, chosenDocumentId: decision.chosen_document_id ?? undefined, chosenValue: decision.chosen_value ?? undefined };
}
export function adaptFinding(finding: BackendFinding): Finding {
  return { id: finding.discrepancy_id, fieldKey: finding.field_key, label: finding.label, severity: ({ BLOCKING: "high", WARNING: "medium", INFO: "low" } as const)[finding.severity], status: verdictStatus(finding.verdict), explanation: finding.explanation ?? (finding.explanation_state === "PENDING" ? "Explanation is still being prepared." : "No explanation is available. Review the source values."), suggestion: finding.suggested_value !== null ? "Suggested value: " + finding.suggested_value : null, reviewStatus: finding.decided ? "reviewed" : "pending", reviewAction: finding.latest_decision ? adaptDecision(finding.latest_decision) : undefined, affectedDocuments: finding.cells.map(cell => cell.document_id), version: finding.version, suggestedValue: finding.suggested_value, suggestedDocumentId: finding.suggested_document_id, verdict: finding.verdict, verdictReason: finding.verdict_reason, explanationState: finding.explanation_state, cells: finding.cells.map(adaptCell) };
}
export function adaptCoverage(coverage: BackendCoverage): ValidationCoverage {
  return { checkedFields: coverage.checked_fields.map(field => field.field_key), notCheckedFields: coverage.out_of_scope.map(field => field.key), singleSourceFields: coverage.single_source_fields, cannotVerifyFields: coverage.cannot_verify_fields, notApplicableFields: coverage.not_applicable_fields, outOfScope: coverage.out_of_scope, uncheckedDocuments: coverage.unchecked_documents, missingDocuments: coverage.missing_documents };
}
export function adaptResults(matrix: BackendMatrix, findings: BackendFinding[], coverage: BackendCoverage): ValidationResults {
  const fields: MatrixField[] = matrix.field_groups.flatMap(group => group.fields.map(field => ({ fieldKey: field.field_key, label: field.label, group: group.group, status: verdictStatus(field.verdict), verdict: field.verdict, reason: field.verdict_reason, cells: field.cells.map(adaptCell) })));
  // The matrix intentionally omits not-applicable fields; coverage still reports them.
  for (const field of coverage.not_applicable_fields) if (!fields.some(item => item.fieldKey === field.field_key)) fields.push({ fieldKey: field.field_key, label: field.label, group: field.group, status: "not_applicable", verdict: field.verdict, cells: [] });
  for (const field of coverage.out_of_scope) fields.push({ fieldKey: field.key, label: field.label, status: "not_checked", reason: field.reason, cells: [] });
  const count = (status: string) => fields.filter(field => field.status === status).length;
  return { shipmentId: matrix.shipment_id, status: shipmentStatus(matrix.status), documents: matrix.documents.map(doc => ({ id: doc.document_id, filename: doc.filename, type: (doc.doc_type || "UNKNOWN").toLowerCase(), typeLabel: DOC_LABELS[doc.doc_type || "UNKNOWN"], pageCount: doc.page_count, status: doc.status, errorCode: doc.error_code ?? undefined })), summary: { matched: count("match"), mismatched: count("mismatch"), cannotVerify: count("cannot_verify"), notChecked: count("not_checked"), notApplicable: count("not_applicable") }, matrix: fields, findings: findings.map(adaptFinding), coverage: adaptCoverage(coverage), generatedAt: matrix.generated_at ?? "", runId: matrix.run_id ?? undefined };
}
const STAGES = ["INGEST", "CLASSIFY", "EXTRACT", "RECONCILE", "EXPLAIN", "READY"];
const LABELS = ["Read and render documents", "Classify document types", "Extract fields", "Compare document values", "Explain discrepancies", "Prepare human review"];
export function adaptProcessing(data: BackendShipment): ProcessingStatus {
  const run = data.current_run;
  const complete = ["AWAITING_REVIEW", "REVIEWED", "REPORT_ISSUED"].includes(data.status);
  const index = run?.stage ? STAGES.indexOf(run.stage) : -1;
  return { shipmentId: data.shipment_id, shipmentStatus: shipmentStatus(data.status), currentStageIndex: complete ? 5 : index, errorMessage: run?.error_message ?? undefined, stages: STAGES.map((id, i) => ({ id, label: LABELS[i], description: complete ? "Completed by the backend" : i === index ? "Current backend stage" : "Awaiting backend progress", status: complete || (index >= 0 && i < index) ? "done" : i === index && data.status === "FAILED" ? "failed" : i === index && data.status === "PROCESSING" ? "running" : "pending" })), documentStatuses: data.documents.map(doc => ({ documentId: doc.document_id, filename: doc.filename, status: doc.status === "EXTRACTED" ? "done" : doc.status === "FAILED" ? "failed" : doc.status === "REGISTERED" ? "queued" : doc.status === "SUPERSEDED" ? "skipped" : "processing" })) };
}
