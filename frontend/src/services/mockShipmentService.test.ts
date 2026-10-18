import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockShipmentService as service } from "./mockShipmentService";
import { MOCK_SHIPMENTS } from "@/mocks/fixtures";
vi.mock("@/lib/utils", () => ({ sleep: async () => {} }));
vi.mock("./fileStore", () => {
  const files = new Map<string, File>();
  return { fileOperation: async (action: string, id: string, file?: File) => { if (action === "put") files.set(id, file!); if (action === "delete") files.delete(id); return files.get(id); } };
});
beforeEach(() => {
  const data = new Map<string, string>();
  vi.stubGlobal("localStorage", { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => data.set(key, value), removeItem: (key: string) => data.delete(key) });
  vi.restoreAllMocks();
});
const payload = { reference: "TEST-001" };
const completeProcessing = async (id: string) => {
  const now = Date.now();
  const clock = vi.spyOn(Date, "now").mockReturnValue(now + 11000);
  const result = await service.getProcessingStatus(id);
  clock.mockRestore();
  return result;
};
describe("demo workflow and review safeguards", () => {
  it("provides five shipments and readable results for both reviewed fixtures", async () => {
    expect(await service.listShipments()).toHaveLength(5);
    const results = await service.getValidationResults("shp-001");
    expect(results.matrix.find(field => field.fieldKey === "quantity")?.cells.map(cell => cell.normalizedValue)).toEqual([100, 95, 100]);
    expect((await service.getReport("shp-002")).status).toBe("finalized");
  });
  it("keeps coverage and summary counts consistent", async () => {
    const results = await service.getValidationResults("shp-001");
    expect(Object.values(results.summary).reduce((sum, count) => sum + count, 0)).toBe(results.matrix.length);
    expect(results.coverage.notCheckedFields).toEqual(["insurance_value"]);
    expect(results.matrix.find(field => field.fieldKey === "total_value")?.status).toBe("cannot_verify");
    expect(results.matrix.find(field => field.fieldKey === "hs_code")?.status).toBe("match");
  });
  it("never changes the source fixture", async () => {
    await service.getReport("shp-002");
    expect(MOCK_SHIPMENTS[0].documents[0].id).toBe("doc-001a");
    expect(MOCK_SHIPMENTS[0].status).toBe("ready_for_review");
  });
  it("rejects duplicate references and invalid routing", async () => {
    await service.createShipment(payload);
    await expect(service.createShipment(payload)).rejects.toThrow("already exists");
    await expect(service.createShipment({ reference: " " })).rejects.toThrow("reference");
  });
  it("cannot start an empty shipment or finalize a draft", async () => {
    const shipment = await service.createShipment(payload);
    await expect(service.startValidation(shipment.id)).rejects.toThrow("at least one");
    await expect(service.finalizeReview(shipment.id)).rejects.toThrow("Complete validation");
  });
  it("saves original files without guessing type from filename", async () => {
    const shipment = await service.createShipment(payload);
    const file = new File(["original bytes"], "commercial_invoice.pdf", { type: "application/pdf" });
    const docs = await service.uploadDocuments(shipment.id, [file]);
    expect(docs[0].type).toBe("unknown");
    expect(await (await service.getDocumentContent(docs[0].id)).text()).toBe("original bytes");
  });
  it("rejects unsupported, empty, and oversized files", async () => {
    const shipment = await service.createShipment(payload);
    await expect(service.uploadDocuments(shipment.id, [new File(["x"], "test.exe")])).rejects.toThrow("non-empty");
    await expect(service.uploadDocuments(shipment.id, [new File([], "empty.pdf")])).rejects.toThrow("non-empty");
    await expect(service.uploadDocuments(shipment.id, [new File([new Uint8Array(50 * 1024 * 1024 + 1)], "large.pdf")])).rejects.toThrow("50 MB");
  });
  it("completes processing with uploaded document IDs and consistent report data", async () => {
    const shipment = await service.createShipment(payload);
    const docs = await service.uploadDocuments(shipment.id, [new File(["a"], "a.pdf"), new File(["b"], "b.pdf"), new File(["c"], "c.pdf")]);
    await service.startValidation(shipment.id);
    expect((await completeProcessing(shipment.id)).shipmentStatus).toBe("ready_for_review");
    const results = await service.getValidationResults(shipment.id);
    expect(results.documents.map(doc => doc.id)).toEqual(docs.map(doc => doc.id));
    expect(results.matrix.every(field => field.cells.every(cell => docs.some(doc => doc.id === cell.documentId)))).toBe(true);
    expect(results.findings.every(finding => finding.affectedDocuments.every(id => docs.some(doc => doc.id === id)))).toBe(true);
    expect((await service.getReport(shipment.id)).reference).toBe(payload.reference);
  });
  it("retries a failed fixture and reaches results", async () => {
    await service.startValidation("shp-004");
    expect((await completeProcessing("shp-004")).shipmentStatus).toBe("ready_for_review");
    expect((await service.getValidationResults("shp-004")).summary.matched).toBe(0);
  });
  it("requires an override explanation and blocks pending finalization", async () => {
    await expect(service.reviewFinding("shp-001", "find-001", { decision: "DISMISS_AS_NOT_AN_ISSUE", reason: "ok" })).rejects.toThrow("10 characters");
    await expect(service.finalizeReview("shp-001")).rejects.toThrow("every finding");
  });
  it("records decisions without erasing discrepancies and locks finalized reviews", async () => {
    const results = await service.getValidationResults("shp-001");
    const before = (await service.getShipment("shp-001")).discrepancyCount;
    for (const finding of results.findings) await service.reviewFinding("shp-001", finding.id, { decision: "FLAG_FOR_FOLLOW_UP" });
    expect((await service.getReport("shp-001")).canFinalize).toBe(true);
    expect((await service.getShipment("shp-001")).discrepancyCount).toBe(before);
    await service.finalizeReview("shp-001");
    const report = await service.getReport("shp-001");
    expect(report.pendingReviews).toBe(0);
    expect(report.results.status).toBe("finalized");
    expect(report.reviewerDecisions).toHaveLength(results.findings.length);
    await expect(service.reviewFinding("shp-001", "find-001", { decision: "FLAG_FOR_FOLLOW_UP" })).rejects.toThrow("locked");
  });
});
