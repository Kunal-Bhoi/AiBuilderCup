import type { Shipment, ShipmentDocument, ValidationResults, ProcessingStatus, CreateShipmentPayload, ReviewFindingPayload } from "@/types";
import { MOCK_SHIPMENTS, MOCK_PROCESSING_STATUS } from "@/mocks/fixtures";
import { buildFixtureResults } from "@/mocks/buildResults";
import { makeReport } from "@/lib/validation";
import { fileOperation } from "./fileStore";
import { generateSampleDocument } from "./sampleDocuments";
import { exportReport } from "@/lib/exportReport";
import { sleep } from "@/lib/utils";

const KEY = "tradeguard-demo-v3";
interface Store { shipments: Shipment[]; results: Record<string, ValidationResults>; jobs: Record<string, number> }
function read(): Store {
  const stored = localStorage.getItem(KEY);
  let store: Store;
  if (stored) store = JSON.parse(stored) as Store;
  else {
    store = { shipments: structuredClone(MOCK_SHIPMENTS), results: {}, jobs: {} };
    store.shipments.forEach(shipment => {
      if (["ready_for_review", "finalized"].includes(shipment.status)) {
        store.results[shipment.id] = buildFixtureResults(shipment);
        shipment.discrepancyCount = store.results[shipment.id].summary.mismatched;
      }
      if (["queued", "processing"].includes(shipment.status)) store.jobs[shipment.id] = Date.now();
    });
  }
  store.shipments.forEach(shipment => {
    const start = store.jobs[shipment.id];
    if (start === undefined || !["queued", "processing"].includes(shipment.status)) return;
    const elapsed = Date.now() - start;
    shipment.status = elapsed < 700 ? "queued" : elapsed < 10000 ? "processing" : "ready_for_review";
    if (shipment.status === "ready_for_review") {
      shipment.validatedAt = new Date(start + 10000).toISOString();
      shipment.updatedAt = shipment.validatedAt;
      shipment.documents.forEach(document => { document.status = "processed"; });
      store.results[shipment.id] = buildFixtureResults(shipment);
      shipment.discrepancyCount = store.results[shipment.id].summary.mismatched;
    }
  });
  save(store); return store;
}
function save(store: Store) { localStorage.setItem(KEY, JSON.stringify(store)); }
function get(store: Store, id: string) {
  const shipment = store.shipments.find(item => item.id === id);
  if (!shipment) throw new Error("Shipment not found. Select a shipment from the dashboard.");
  return shipment;
}
function editable(shipment: Shipment) {
  if (!["draft", "uploading", "ready_for_review", "reviewed", "failed"].includes(shipment.status)) throw new Error("Documents can only be changed in draft or failed shipments.");
}
export const mockShipmentService = {
  async listShipments() { await sleep(150); return read().shipments; },
  async getShipment(id: string) { await sleep(100); return get(read(), id); },
  async createShipment(payload: CreateShipmentPayload): Promise<Shipment> {
    await sleep(150);
    const store = read();
    if (!payload.reference.trim()) throw new Error("Enter a shipment reference.");
    if (store.shipments.some(shipment => shipment.reference.toLowerCase() === payload.reference.trim().toLowerCase())) throw new Error("This shipment reference already exists.");
    const shipment: Shipment = { ...payload, originCountry: "", destinationCountry: "", preferentialDutyClaim: false, reference: payload.reference.trim(), id: "shp-" + crypto.randomUUID(), status: "draft", documents: [], discrepancyCount: 0, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), createdBy: "sarah.chen@acmefreight.com" };
    store.shipments.unshift(shipment); save(store); return shipment;
  },
  async uploadDocuments(id: string, files: File[], onProgress?: import("@/types").UploadProgress): Promise<ShipmentDocument[]> {
    editable(get(read(), id));
    if (get(read(), id).documents.length + files.length > 20) throw new Error("A shipment can contain at most 20 documents.");
    const documents: ShipmentDocument[] = [];
    for (const file of files) {
      if (!/\.(pdf|png|jpe?g|xlsx|webp|tiff?|hei[cf])$/i.test(file.name) || file.size === 0 || file.size > 50 * 1024 * 1024) throw new Error("Use a non-empty PDF, PNG, JPG, or XLSX file up to 50 MB.");
      const document: ShipmentDocument = { id: "doc-" + crypto.randomUUID(), filename: file.name, type: "unknown", typeLabel: "Unclassified document", sizeBytes: file.size, uploadedAt: new Date().toISOString(), status: "uploaded" };
      await fileOperation("put", document.id, file); documents.push(document); onProgress?.(file, 100);
    }
    const store = read(); const shipment = get(store, id); editable(shipment);
    shipment.documents.push(...documents); shipment.updatedAt = new Date().toISOString(); save(store); return documents;
  },
  async listDocuments() { return read().shipments.flatMap(shipment => shipment.documents.map(document => ({ ...document, shipment }))); },
  async updateDocumentType(id: string, documentId: string, type: string) { const store = read(); const shipment = get(store, id); editable(shipment); const doc = shipment.documents.find(item => item.id === documentId); if (!doc) throw new Error("Document not found"); doc.type = type.toLowerCase() as ShipmentDocument["type"]; doc.typeLabel = type.toLowerCase().replace(/_/g, " "); save(store); return doc; },
  async getDocumentPage(_id: string, _page: number): Promise<{ url: string }> { throw new Error("Use the demo PDF preview."); },
  async removeDocument(id: string, documentId: string) {
    const store = read(); const shipment = get(store, id); editable(shipment);
    await fileOperation("delete", documentId);
    shipment.documents = shipment.documents.filter(document => document.id !== documentId); save(store);
  },
  async getDocumentContent(documentId: string): Promise<Blob> {
    const store = read();
    const shipment = store.shipments.find(item => item.documents.some(document => document.id === documentId));
    if (!shipment) throw new Error("Document not found.");
    const file = await fileOperation("get", documentId);
    if (file) return file;
    if (MOCK_SHIPMENTS.some(item => item.documents.some(document => document.id === documentId))) return generateSampleDocument(shipment.documents.find(document => document.id === documentId)!, store.results[shipment.id] ?? buildFixtureResults(shipment));
    throw new Error("The original file is no longer stored in this browser. Re-add it to a draft shipment.");
  },
  async startValidation(id: string) {
    const store = read(); const shipment = get(store, id); editable(shipment);
    if (shipment.documents.length === 0) throw new Error("Add at least one document before starting validation.");
    shipment.status = "queued"; shipment.updatedAt = new Date().toISOString();
    shipment.documents.forEach(document => { document.status = "queued"; });
    store.jobs[id] = Date.now(); save(store); return { message: "Demo validation started" };
  },
  async getProcessingStatus(id: string): Promise<ProcessingStatus> {
    const store = read(); const shipment = get(store, id);
    const complete = ["ready_for_review", "finalized"].includes(shipment.status);
    const currentStageIndex = complete ? 5 : shipment.status === "failed" ? 1 : shipment.status === "processing" ? Math.min(5, Math.floor((Date.now() - store.jobs[id] - 700) / 1550)) : -1;
    return { shipmentId: id, shipmentStatus: shipment.status, currentStageIndex,
      stages: MOCK_PROCESSING_STATUS.stages.map((stage, index) => ({ id: stage.id, label: stage.label, description: stage.description, status: complete || index < currentStageIndex ? "done" : index === currentStageIndex ? shipment.status === "failed" ? "failed" : "running" : "pending" })),
      documentStatuses: shipment.documents.map(document => ({ documentId: document.id, filename: document.filename, status: complete ? "done" : shipment.status === "failed" ? "failed" : shipment.status === "processing" ? "processing" : "queued" })),
    };
  },
  async getValidationResults(id: string) { const store = read(); get(store, id); if (!store.results[id]) throw new Error("Results are available after validation completes."); return store.results[id]; },
  async reviewFinding(id: string, findingId: string, payload: ReviewFindingPayload) {
    const store = read(); const shipment = get(store, id);
    if (!["ready_for_review", "reviewed"].includes(shipment.status)) throw new Error("Only shipments awaiting review can be changed. Finalized reports are locked.");
    if (!["ACCEPT_SUGGESTION", "OVERRIDE", "FLAG_FOR_FOLLOW_UP", "DISMISS_AS_NOT_AN_ISSUE"].includes(payload.decision)) throw new Error("Select a valid review decision.");
    if (["OVERRIDE", "DISMISS_AS_NOT_AN_ISSUE"].includes(payload.decision) && (payload.reason?.trim().length ?? 0) < 10) throw new Error("Explain the override using at least 10 characters.");
    const finding = store.results[id]?.findings.find(item => item.id === findingId);
    if (!finding) throw new Error("Finding not found.");
    if (payload.expectedVersion !== undefined && payload.expectedVersion !== (finding.version ?? 1)) throw new Error("This finding has changed. Reload before reviewing it.");
    if (payload.decision === "OVERRIDE" && !payload.chosenDocumentId && !payload.chosenValue?.trim()) throw new Error("Choose a document or value.");
    finding.version = (finding.version ?? 1) + 1;
    finding.reviewStatus = "reviewed";
    finding.reviewAction = { decision: payload.decision, chosenDocumentId: payload.chosenDocumentId, chosenValue: payload.chosenValue, reason: payload.reason?.trim(), reviewerId: "usr-current", reviewerName: "Sarah Chen", reviewedAt: new Date().toISOString() };
    shipment.updatedAt = new Date().toISOString(); save(store); return finding;
  },
  async finalizeReview(id: string) {
    const store = read(); const shipment = get(store, id); const results = store.results[id];
    if (shipment.status !== "ready_for_review" || !results) throw new Error("Complete validation before finalizing the review.");
    if (results.findings.some(finding => finding.reviewStatus === "pending")) throw new Error("Review every finding before finalizing.");
    shipment.status = "finalized"; shipment.finalizedAt = new Date().toISOString(); shipment.updatedAt = shipment.finalizedAt;
    results.status = "finalized"; save(store); return shipment;
  },
  async getReport(id: string) { const store = read(); const shipment = get(store, id); if (!store.results[id]) throw new Error("Complete validation before generating a report."); return makeReport(shipment, store.results[id]); },
  async downloadReport(id: string) { return exportReport(await mockShipmentService.getReport(id), false); },
  async getDashboardStats() {
    const shipments = read().shipments;
    return { totalShipments: shipments.length, pendingValidations: shipments.filter(s => ["queued", "processing"].includes(s.status)).length, requiresReview: shipments.filter(s => s.status === "ready_for_review").length, completedValidations: shipments.filter(s => s.status === "finalized").length, totalDiscrepancies: shipments.reduce((sum, s) => sum + s.discrepancyCount, 0) };
  },
  resetStore() { localStorage.removeItem(KEY); window.location.reload(); },
};
