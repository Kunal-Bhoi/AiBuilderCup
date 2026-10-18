import { afterEach, describe, expect, it, vi } from "vitest";
import { realService } from "./shipmentService";
import { apiClient } from "./api";
import { MOCK_SHIPMENTS, MOCK_VALIDATION_RESULTS } from "@/mocks/fixtures";
afterEach(() => vi.restoreAllMocks());
describe("HTTP adapter", () => {
  it("polls the documented shipment endpoint without inventing stage progress", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: structuredClone(MOCK_SHIPMENTS[2]) });
    const status = await realService.getProcessingStatus("shp-003");
    expect(get).toHaveBeenCalledWith("/shipments/shp-003");
    expect(status.shipmentStatus).toBe("processing");
    expect(status.currentStageIndex).toBe(-1);
    expect(status.stages.every(stage => stage.status === "pending")).toBe(true);
  });
  it("supports the original minimal results contract", async () => {
    const data = structuredClone(MOCK_VALIDATION_RESULTS);
    const payload = {
      shipmentId: data.shipmentId, status: data.status,
      documents: data.documents.map(({ id, filename, type }) => ({ id, filename, type })),
      matrix: data.matrix, summary: { matched: 7, mismatched: 3, cannotVerify: 1, notChecked: 1 },
      findings: data.findings.map(({ id, fieldKey, severity, status, explanation, suggestion, reviewStatus }) => ({ id, fieldKey, severity, status, explanation, suggestion, reviewStatus })),
      coverage: data.coverage,
    };
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: payload });
    const results = await realService.getValidationResults("shp-001");
    expect(results.documents[0].typeLabel).toBe("Commercial Invoice");
    expect(results.findings[0].label).toBe("Total Quantity");
    expect(results.findings[0].affectedDocuments).toHaveLength(3);
    expect(Object.values(results.summary).reduce((sum, value) => sum + value, 0)).toBe(results.matrix.length);
  });
  it("uploads original files using multipart form data", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: [] });
    const file = new File(["source"], "invoice.pdf");
    await realService.uploadDocuments("shp-test", [file]);
    const form = post.mock.calls[0][1] as FormData;
    expect(post.mock.calls[0][0]).toBe("/shipments/shp-test/documents");
    expect((form.getAll("files")[0] as File).name).toBe("invoice.pdf");
  });
  it("downloads documents and reports as files", async () => {
    const blob = new Blob(["%PDF-test"], { type: "application/pdf" });
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: blob });
    expect(await realService.getDocumentContent("doc-a")).toBe(blob);
    expect(get).toHaveBeenCalledWith("/documents/doc-a/content", { responseType: "blob" });
    expect(await realService.downloadReport("shp-a")).toBe(blob);
    expect(get).toHaveBeenCalledWith("/shipments/shp-a/report", { responseType: "blob" });
  });
});
