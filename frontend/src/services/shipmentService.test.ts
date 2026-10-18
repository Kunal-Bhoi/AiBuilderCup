import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import axios, { AxiosHeaders, type InternalAxiosRequestConfig } from "axios";
import { realService } from "./shipmentService";
import { apiClient, ApiError } from "./api";
import { adaptResults, adaptProcessing, xyxyToBbox, adaptShipment, adaptSummary, type BackendShipment, type BackendMatrix, type BackendFinding, type BackendCoverage, type BackendReport } from "./backendAdapter";
import { cellValidationStatus } from "@/lib/workflow";
import fixtures from "@/mocks/backend-contract.json";
import type { components } from "@/types/backend.generated";
type Schema = components["schemas"];
const fixture = fixtures as unknown as { shipment: BackendShipment; matrix: BackendMatrix; findings: Schema["DiscrepancyList"]; coverage: BackendCoverage; summary: Schema["ShipmentSummary"]; report: BackendReport; decisions: Schema["DecisionList"] };
beforeEach(() => {
  for (const name of ["localStorage", "sessionStorage"]) { const data = new Map<string, string>(); vi.stubGlobal(name, { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => data.set(key, value), removeItem: (key: string) => data.delete(key) }); }
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
describe("backend response mapping", () => {
  it("maps all nine server shipment states without dropping reviewed or archived shipments", () => {
    const cases = { DRAFT: "draft", UPLOADING: "uploading", QUEUED: "queued", PROCESSING: "processing", AWAITING_REVIEW: "ready_for_review", REVIEWED: "reviewed", REPORT_ISSUED: "finalized", FAILED: "failed", ARCHIVED: "archived" } as const;
    for (const [server, expected] of Object.entries(cases)) expect(adaptShipment({ ...fixture.shipment, status: server as Schema["ShipmentStatus"] }).status).toBe(expected);
  });
  it("keeps list document counts without inventing documents or route metadata", () => {
    const shipment = adaptSummary(fixture.summary);
    expect(shipment.id).toBe("shp_contract"); expect(shipment.documentCount).toBe(2); expect(shipment.documents).toEqual([]); expect(shipment.originCountry).toBe("");
  });
  it("converts highlight coordinates from corners to width and height", () => {
    expect(xyxyToBbox([.1, .2, .4, .25])).toEqual([.1, .2, .4 - .1, .25 - .2]);
    expect(xyxyToBbox([.4, .2, .1, .25])).toBeNull(); expect(xyxyToBbox([0, 0, 2, 2])).toBeNull(); expect(xyxyToBbox(null)).toBeNull();
  });
  it("combines matrix, decided findings, missing documents, and coverage without losing uncertainty", () => {
    const results = adaptResults(fixture.matrix, fixture.findings.items, fixture.coverage);
    expect(results.findings[0].version).toBe(1);
    expect(results.matrix.find(field => field.fieldKey === "hs_code")?.verdict).toBe("AGREE_AT_HS_ROOT");
    expect(results.matrix.find(field => field.fieldKey === "net_weight")?.status).toBe("cannot_verify");
    expect(results.matrix.find(field => field.fieldKey === "vessel_name")?.status).toBe("not_applicable");
    expect(results.coverage.uncheckedDocuments?.[0].error_code).toBe("DOCUMENT_CORRUPT");
    expect(results.coverage.missingDocuments).toHaveLength(1);
    expect(Object.values(results.summary).reduce((sum, n) => sum + n, 0)).toBe(results.matrix.length);
  });
  it("never displays low-confidence, absent, or unreadable cells as matches", () => {
    const results = adaptResults(fixture.matrix, fixture.findings.items, fixture.coverage);
    const cell = results.matrix[0].cells[0];
    for (const cellStatus of ["LOW_CONFIDENCE", "ABSENT", "UNREADABLE"] as const) expect(cellValidationStatus({ ...cell, cellStatus }, "match")).toBe("cannot_verify");
    expect(cellValidationStatus({ ...cell, cellStatus: "NOT_APPLICABLE" }, "match")).toBe("not_applicable");
  });
  it("maps every run stage and completes zero-finding REVIEWED runs", () => {
    for (const [index, stage] of ["INGEST", "CLASSIFY", "EXTRACT", "RECONCILE", "EXPLAIN", "READY"].entries()) {
      const status = adaptProcessing({ ...fixture.shipment, status: "PROCESSING", current_run: { ...fixture.shipment.current_run!, state: "RUNNING", stage } });
      expect(status.currentStageIndex).toBe(index); expect(status.stages[index].status).toBe("running");
    }
    expect(adaptProcessing({ ...fixture.shipment, status: "REVIEWED" }).stages.every(stage => stage.status === "done")).toBe(true);
  });
});
describe("real HTTP contract", () => {
  it("fetches every shipment cursor page", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValueOnce({ data: { items: [fixture.summary], next_cursor: "second-page" } }).mockResolvedValueOnce({ data: { items: [], next_cursor: null } });
    expect(await realService.listShipments()).toHaveLength(1);
    expect(get).toHaveBeenNthCalledWith(2, "/shipments", { params: { limit: 100, cursor: "second-page" } });
  });
  it("rejects repeated cursors rather than looping forever", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: { items: [], next_cursor: "repeat" } });
    await expect(realService.listShipments()).rejects.toThrow("repeated");
  });
  it("posts only reference when creating a shipment", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: fixture.shipment });
    await realService.createShipment({ reference: "  NEW-001  " });
    expect(post).toHaveBeenCalledWith("/shipments", { reference: "NEW-001" });
  });
  it("uploads through signed PUT and registration without leaking API credentials", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: { ...fixture.shipment, documents: [] } });
    const post = vi.spyOn(apiClient, "post").mockResolvedValueOnce({ data: { uploads: [{ upload_id: "up_1", filename: "invoice.pdf", signed_url: "http://storage.test/upload", headers: { "Content-Type": "application/pdf" } }] } }).mockResolvedValueOnce({ data: { documents: [fixture.shipment.documents[0]] } });
    const put = vi.spyOn(axios, "put").mockResolvedValue({ data: "" });
    const file = new File(["source bytes"], "invoice.pdf", { type: "application/pdf" }); const progress = vi.fn();
    expect((await realService.uploadDocuments("shp_contract", [file], progress))[0].id).toBe("doc_invoice");
    expect(post.mock.calls[0][0]).toBe("/shipments/shp_contract/upload-urls");
    expect(post.mock.calls[0][1]).toEqual({ files: [{ filename: "invoice.pdf", size_bytes: file.size, content_type: "application/pdf" }] });
    expect(put.mock.calls[0][2]?.headers).toEqual({ "Content-Type": "application/pdf" });
    expect(post.mock.calls[1][1]).toEqual({ upload_ids: ["up_1"] }); expect(progress).toHaveBeenCalledWith(file, 100);
  });
  it("rejects files above the backend limit before requesting upload addresses", async () => {
    const post = vi.spyOn(apiClient, "post");
    await expect(realService.uploadDocuments("shp_contract", [new File([new Uint8Array(50 * 1024 * 1024 + 1)], "large.pdf")])).rejects.toThrow("50 MB"); expect(post).not.toHaveBeenCalled();
  });
  it("uses analyze, matrix, discrepancies including decided, and coverage endpoints", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: {} });
    await realService.startValidation("shp_contract"); expect(post).toHaveBeenCalledWith("/shipments/shp_contract/analyze");
    const get = vi.spyOn(apiClient, "get").mockImplementation(async path => ({ data: path.endsWith("/matrix") ? fixture.matrix : path.endsWith("/discrepancies") ? fixture.findings : fixture.coverage }));
    const result = await realService.getValidationResults("shp_contract");
    expect(get).toHaveBeenCalledWith("/shipments/shp_contract/discrepancies", { params: { include_decided: true } }); expect(result.findings).toHaveLength(1);
  });
  it("sends chosen source, reason, and expected version for a review", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: {} });
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: fixture.findings });
    await realService.reviewFinding("shp_contract", "dsc_quantity", { decision: "OVERRIDE", expectedVersion: 1, chosenDocumentId: "doc_invoice", chosenValue: "100", reason: "Verified against the warehouse count." });
    expect(post).toHaveBeenCalledWith("/discrepancies/dsc_quantity/decision", { action: "OVERRIDE", expected_version: 1, chosen_document_id: "doc_invoice", chosen_value: "100", reason: "Verified against the warehouse count." });
  });
  it("rejects missing versions and invalid overrides before a write", async () => {
    const post = vi.spyOn(apiClient, "post");
    await expect(realService.reviewFinding("s", "d", { decision: "FLAG_FOR_FOLLOW_UP" })).rejects.toThrow("Reload");
    await expect(realService.reviewFinding("s", "d", { decision: "OVERRIDE", expectedVersion: 1, reason: "A sufficiently long reason" })).rejects.toThrow("Choose");
    await expect(realService.reviewFinding("s", "d", { decision: "DISMISS_AS_NOT_AN_ISSUE", expectedVersion: 1, reason: "ok" })).rejects.toThrow("10 characters"); expect(post).not.toHaveBeenCalled();
  });
  it("uses report issue rather than a nonexistent finalize route", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: fixture.report });
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: { ...fixture.shipment, status: "REPORT_ISSUED", report_id: "rpt_contract" } });
    expect((await realService.finalizeReview("shp_contract")).status).toBe("finalized");
    expect(post).toHaveBeenCalledWith("/shipments/shp_contract/report");
  });
  it("downloads the signed PDF URL using a separate client and checks the PDF header", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: fixture.report });
    const get = vi.spyOn(axios, "get").mockResolvedValue({ data: new Blob(["%PDF-contract"]) });
    expect(await (await realService.downloadReport("shp_contract")).text()).toBe("%PDF-contract");
    expect(get).toHaveBeenCalledWith("http://storage.test/report.pdf", { responseType: "blob", timeout: 60000 });
    get.mockResolvedValueOnce({ data: new Blob(['{"error":"expired"}']) });
    await expect(realService.downloadReport("shp_contract")).rejects.toThrow("did not return a PDF");
  });
  it("uses page-image metadata and supports document-type corrections", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: { url: "http://storage.test/page.png" } });
    await realService.getDocumentPage("doc_invoice", 2); expect(get).toHaveBeenCalledWith("/documents/doc_invoice/pages/2/image");
    const patch = vi.spyOn(apiClient, "patch").mockResolvedValue({ data: fixture.shipment.documents[0] });
    await realService.updateDocumentType("shp_contract", "doc_invoice", "COMMERCIAL_INVOICE");
    expect(patch).toHaveBeenCalledWith("/shipments/shp_contract/documents/doc_invoice", { doc_type: "COMMERCIAL_INVOICE" });
  });
  it("preserves stale-review details from the server error envelope", async () => {
    const original = apiClient.defaults.adapter;
    apiClient.defaults.adapter = async config => { const error = Object.assign(new Error("Conflict"), { response: { status: 409, data: { error: { code: "CONFLICT_STALE_VERSION", message: "Someone else reviewed this finding.", retryable: false, details: { current_version: 2 }, request_id: "req_conflict" } } } }); throw error; };
    try { await expect(apiClient.get("/test")).rejects.toMatchObject({ name: "ApiError", status: 409, code: "CONFLICT_STALE_VERSION", details: { current_version: 2 }, requestId: "req_conflict" }); } finally { apiClient.defaults.adapter = original; }
  });
});
