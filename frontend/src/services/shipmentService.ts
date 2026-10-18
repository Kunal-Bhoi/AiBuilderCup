/**
 * Shipment Service — switches between mock and real HTTP depending on env.
 * Set VITE_USE_MOCK=false to use real backend.
 */

import { mockShipmentService } from "./mockShipmentService";
import { apiClient } from "./api";
import { makeReport, summarizeResults } from "@/lib/validation";
import type {
  Shipment,
  ShipmentDocument,
  ValidationResults,
  ProcessingStatus,
  ValidationReport,
  CreateShipmentPayload,
  ReviewFindingPayload,
  Finding,
  DashboardStats,
} from "@/types";

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== "false";

export const realService = {
  async listShipments(): Promise<Shipment[]> {
    const { data } = await apiClient.get<Shipment[]>("/shipments");
    return data;
  },
  async getShipment(id: string): Promise<Shipment> {
    const { data } = await apiClient.get<Shipment>(`/shipments/${id}`);
    return data;
  },
  async createShipment(payload: CreateShipmentPayload): Promise<Shipment> {
    const { data } = await apiClient.post<Shipment>("/shipments", payload);
    return data;
  },
  async uploadDocuments(
    shipmentId: string,
    files: File[]
  ): Promise<ShipmentDocument[]> {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    const { data } = await apiClient.post<ShipmentDocument[]>(
      `/shipments/${shipmentId}/documents`,
      form,
      { headers: { "Content-Type": "multipart/form-data" } }
    );
    return data;
  },
  async removeDocument(
    shipmentId: string,
    documentId: string
  ): Promise<void> {
    await apiClient.delete(
      `/shipments/${shipmentId}/documents/${documentId}`
    );
  },
  async getDocumentContent(documentId: string): Promise<Blob> {
    const { data } = await apiClient.get<Blob>(`/documents/${documentId}/content`, { responseType: "blob" });
    return data;
  },
  async startValidation(shipmentId: string): Promise<{ message: string }> {
    const { data } = await apiClient.post<{ message: string }>(
      `/shipments/${shipmentId}/validate`
    );
    return data;
  },
  async getProcessingStatus(shipmentId: string): Promise<ProcessingStatus> {
    const { data } = await apiClient.get<Shipment & { processing?: ProcessingStatus }>(`/shipments/${shipmentId}`);
    if (data.processing) return data.processing;
    const complete = ["ready_for_review", "finalized"].includes(data.status);
    const labels = ["Document classification", "Field extraction", "Data normalisation", "Cross-document reconciliation", "Discrepancy explanation", "Evidence recording"];
    return { shipmentId, shipmentStatus: data.status, currentStageIndex: complete ? 5 : -1,
      stages: labels.map((label, index) => ({ id: String(index), label, description: complete ? "Validation completed" : "Waiting for stage details from the backend", status: complete ? "done" : "pending" })),
      documentStatuses: data.documents.map(document => ({ documentId: document.id, filename: document.filename, status: document.status === "processed" ? "done" : document.status === "failed" ? "failed" : document.status === "processing" ? "processing" : "queued" })) };
  },
  async getValidationResults(shipmentId: string): Promise<ValidationResults> {
    const { data } = await apiClient.get<ValidationResults>(
      `/shipments/${shipmentId}/results`
    );
    const labels: Record<string, string> = { commercial_invoice: "Commercial Invoice", packing_list: "Packing List", bill_of_lading: "Bill of Lading", air_waybill: "Air Waybill", certificate_of_origin: "Certificate of Origin", purchase_order: "Purchase Order", customs_declaration: "Customs Declaration" };
    return summarizeResults({ ...data,
      generatedAt: data.generatedAt ?? new Date().toISOString(),
      documents: data.documents.map(doc => ({ ...doc, typeLabel: doc.typeLabel ?? labels[doc.type] ?? "Unclassified document" })),
      findings: data.findings.map(finding => ({ ...finding, label: finding.label ?? data.matrix.find(field => field.fieldKey === finding.fieldKey)?.label ?? finding.fieldKey, affectedDocuments: finding.affectedDocuments ?? data.documents.map(doc => doc.id) })),
    });
  },
  async reviewFinding(
    shipmentId: string,
    findingId: string,
    payload: ReviewFindingPayload
  ): Promise<Finding> {
    const { data } = await apiClient.post<Finding>(
      `/shipments/${shipmentId}/findings/${findingId}/review`,
      payload
    );
    return data;
  },
  async finalizeReview(shipmentId: string): Promise<Shipment> {
    const { data } = await apiClient.post<Shipment>(
      `/shipments/${shipmentId}/finalize`
    );
    return data;
  },
  async getReport(shipmentId: string): Promise<ValidationReport> {
    const [shipment, results] = await Promise.all([realService.getShipment(shipmentId), realService.getValidationResults(shipmentId)]);
    return makeReport(shipment, results);
  },
  async downloadReport(shipmentId: string): Promise<Blob> {
    const { data } = await apiClient.get<Blob>(`/shipments/${shipmentId}/report`, { responseType: "blob" });
    return data;
  },
  async getDashboardStats(): Promise<DashboardStats> {
    const shipments = await realService.listShipments();
    return { totalShipments: shipments.length, pendingValidations: shipments.filter(s => ["queued", "processing"].includes(s.status)).length, requiresReview: shipments.filter(s => s.status === "ready_for_review").length, completedValidations: shipments.filter(s => s.status === "finalized").length, totalDiscrepancies: shipments.reduce((total, s) => total + s.discrepancyCount, 0) };
  },
};

export const shipmentService = USE_MOCK ? mockShipmentService : realService;
export { USE_MOCK };
