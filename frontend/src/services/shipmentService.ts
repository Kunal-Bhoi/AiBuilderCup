import axios from "axios";
import type { components } from "@/types/backend.generated";
import type { Shipment, CreateShipmentPayload, ReviewFindingPayload, ValidationReport, UploadProgress } from "@/types";
import { mockShipmentService } from "./mockShipmentService";
import { apiClient, ApiError } from "./api";
import { USE_MOCK, MAX_FILE_BYTES, MAX_DOCUMENTS } from "./config";
import { adaptSummary, adaptShipment, adaptDocument, adaptResults, adaptProcessing, adaptFinding } from "./backendAdapter";
import type { BackendShipment, BackendMatrix, BackendFinding, BackendCoverage, BackendReport } from "./backendAdapter";
import { makeReport } from "@/lib/validation";
type Schema = components["schemas"];
export const realService = {
  async listShipments(): Promise<Shipment[]> {
    const shipments: Shipment[] = [];
    let cursor: string | null = null;
    const seen = new Set<string>();
    do {
      const { data }: { data: Schema["ShipmentList"] } = await apiClient.get("/shipments", { params: { limit: 100, ...(cursor ? { cursor } : {}) } });
      shipments.push(...data.items.map(adaptSummary)); cursor = data.next_cursor;
      if (cursor && seen.has(cursor)) throw new Error("The server repeated a shipment page. Reload and try again.");
      if (cursor) seen.add(cursor);
    } while (cursor);
    return shipments;
  },
  async listDocuments() {
    const shipments = await realService.listShipments();
    const all: Shipment[] = [];
    // Limit simultaneous detail requests; summaries intentionally have no document array.
    for (let offset = 0; offset < shipments.length; offset += 4) all.push(...await Promise.all(shipments.slice(offset, offset + 4).filter(shipment => (shipment.documentCount ?? 0) > 0).map(shipment => realService.getShipment(shipment.id))));
    return all.flatMap(shipment => shipment.documents.map(document => ({ ...document, shipment })));
  },
  async getShipment(id: string) { const { data } = await apiClient.get<BackendShipment>(`/shipments/${id}`); return adaptShipment(data); },
  async createShipment(payload: CreateShipmentPayload) { const { data } = await apiClient.post<BackendShipment>("/shipments", { reference: payload.reference.trim() }); return adaptShipment(data); },
  async uploadDocuments(id: string, files: File[], onProgress?: UploadProgress) {
    if (!files.length) return [];
    if (files.some(file => file.size <= 0 || file.size > MAX_FILE_BYTES)) throw new Error("Choose non-empty files up to 50 MB each.");
    const shipment = await realService.getShipment(id);
    if (shipment.documents.length + files.length > MAX_DOCUMENTS) throw new Error("A shipment can contain at most 20 documents.");
    const { data } = await apiClient.post<Schema["UploadUrlsResponse"]>(`/shipments/${id}/upload-urls`, { files: files.map(file => ({ filename: file.name, size_bytes: file.size, content_type: file.type || mimeType(file.name) })) });
    if (data.uploads.length !== files.length) throw new Error("The server did not prepare every upload. Retry the upload.");
    const registered = [];
    // Register each successful upload so a later failure cannot hide completed files.
    for (let index = 0; index < files.length; index++) {
      const file = files[index], upload = data.uploads[index];
      await axios.put(upload.signed_url, file, { headers: upload.headers, timeout: 120000, onUploadProgress: event => onProgress?.(file, event.total ? Math.round(event.loaded / event.total * 100) : 0) });
      const response = await apiClient.post<Schema["RegisterDocumentsResponse"]>(`/shipments/${id}/documents`, { upload_ids: [upload.upload_id] });
      registered.push(...response.data.documents.map(adaptDocument)); onProgress?.(file, 100);
    }
    return registered;
  },
  async removeDocument(id: string, documentId: string) { await apiClient.delete(`/shipments/${id}/documents/${documentId}`); },
  async updateDocumentType(id: string, documentId: string, type: Schema["DocType"]) { const { data } = await apiClient.patch<Schema["DocumentOut"]>(`/shipments/${id}/documents/${documentId}`, { doc_type: type }); return adaptDocument(data); },
  async getDocumentPage(documentId: string, page: number): Promise<Schema["PageImageOut"]> { const { data } = await apiClient.get<Schema["PageImageOut"]>(`/documents/${documentId}/pages/${page}/image`); return data; },
  async getDocumentContent(_documentId: string): Promise<Blob> { throw new Error("Original-file download is not provided by this backend. Use the rendered page preview."); },
  async startValidation(id: string) { await apiClient.post<Schema["AnalyzeResponse"]>(`/shipments/${id}/analyze`); return { message: "Analysis started" }; },
  async getProcessingStatus(id: string) { const { data } = await apiClient.get<BackendShipment>(`/shipments/${id}`); return adaptProcessing(data); },
  async getValidationResults(id: string) {
    const [matrix, findings, coverage] = await Promise.all([
      apiClient.get<BackendMatrix>(`/shipments/${id}/matrix`),
      apiClient.get<Schema["DiscrepancyList"]>(`/shipments/${id}/discrepancies`, { params: { include_decided: true } }),
      apiClient.get<BackendCoverage>(`/shipments/${id}/coverage`),
    ]);
    return adaptResults(matrix.data, findings.data.items, coverage.data);
  },
  async reviewFinding(id: string, findingId: string, payload: ReviewFindingPayload) {
    if (payload.expectedVersion === undefined) throw new Error("Reload the finding before recording a decision.");
    if (["OVERRIDE", "DISMISS_AS_NOT_AN_ISSUE"].includes(payload.decision) && (payload.reason?.trim().length ?? 0) < 10) throw new Error("Provide a reason of at least 10 characters.");
    if (payload.decision === "OVERRIDE" && !payload.chosenDocumentId && !payload.chosenValue?.trim()) throw new Error("Choose a source document or enter a corrected value.");
    const body: Schema["DecisionRequest"] = { action: payload.decision, expected_version: payload.expectedVersion, reason: payload.reason?.trim() || null, chosen_document_id: payload.chosenDocumentId || null, chosen_value: payload.chosenValue?.trim() || null };
    await apiClient.post<Schema["DecisionResponse"]>(`/discrepancies/${findingId}/decision`, body);
    const { data } = await apiClient.get<Schema["DiscrepancyList"]>(`/shipments/${id}/discrepancies`, { params: { include_decided: true } });
    const finding = data.items.find(item => item.discrepancy_id === findingId);
    if (!finding) throw new Error("Decision saved. Reload the shipment to see its current findings.");
    return adaptFinding(finding);
  },
  async finalizeReview(id: string) { await apiClient.post<BackendReport>(`/shipments/${id}/report`); return realService.getShipment(id); },
  async getReport(id: string): Promise<ValidationReport> {
    const [shipment, results] = await Promise.all([realService.getShipment(id), realService.getValidationResults(id)]);
    const report = makeReport(shipment, results);
    report.canFinalize = shipment.status === "reviewed" && report.pendingReviews === 0;
    const history = await apiClient.get<Schema["DecisionList"]>(`/shipments/${id}/decisions`);
    report.reviewerDecisions = history.data.items.map(decision => ({ findingId: decision.discrepancy_id, field: results.matrix.find(field => field.fieldKey === decision.field_key)?.label ?? decision.field_key, decision: decision.action, reason: decision.reason ?? undefined, reviewerName: decision.actor_user_id, reviewedAt: decision.decided_at }));
    if (shipment.reportId || shipment.status === "finalized") {
      const { data } = await apiClient.get<BackendReport>(`/shipments/${id}/report`);
      report.status = "finalized"; report.issuedReport = data; report.generatedAt = data.issued_at; report.generatedBy = data.issued_by; shipment.finalizedAt = data.issued_at;
    }
    return report;
  },
  async downloadReport(id: string): Promise<Blob> {
    const { data } = await apiClient.get<BackendReport>(`/shipments/${id}/report`);
    // Use a separate client: never forward API credentials to a storage URL.
    const response = await axios.get<Blob>(data.download_url, { responseType: "blob", timeout: 60000 });
    const signature = new TextDecoder().decode(await response.data.slice(0, 5).arrayBuffer());
    if (signature !== "%PDF-") throw new Error("The report download did not return a PDF. Retry to refresh its download link.");
    return response.data;
  },
  async getDashboardStats() {
    const shipments = await realService.listShipments();
    return { totalShipments: shipments.length, pendingValidations: shipments.filter(s => ["queued", "processing"].includes(s.status)).length, requiresReview: shipments.filter(s => ["ready_for_review", "reviewed"].includes(s.status)).length, completedValidations: shipments.filter(s => s.status === "finalized").length, totalDiscrepancies: shipments.reduce((sum, s) => sum + s.discrepancyCount, 0) };
  },
  async getEffectiveness() { return (await apiClient.get<Schema["EffectivenessResponse"]>("/org/effectiveness")).data; },
  async verifyAudit() { return (await apiClient.get<Schema["AuditVerifyResponse"]>("/org/audit/verify")).data; },
};
function mimeType(name: string) { const extension = name.split(".").pop()?.toLowerCase(); return ({ pdf: "application/pdf", png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", webp: "image/webp", tif: "image/tiff", tiff: "image/tiff", heic: "image/heic", heif: "image/heif" } as Record<string, string>)[extension || ""] || "application/octet-stream"; }
export const shipmentService = USE_MOCK ? mockShipmentService : realService;
export { USE_MOCK, ApiError };
