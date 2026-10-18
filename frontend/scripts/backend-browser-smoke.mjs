import { mkdir, readFile, writeFile } from "node:fs/promises";
import assert from "node:assert/strict";
import { chromium } from "playwright";
import { jsPDF } from "jspdf";
const fixtures = JSON.parse(await readFile("src/mocks/backend-contract.json", "utf8"));
const browser = await chromium.launch({ channel: process.env.TRADEGUARD_BROWSER || "msedge", headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true, reducedMotion: "reduce" });
const page = await context.newPage(), errors = [], requests = [], issued = [];
page.on("pageerror", error => errors.push(error.message));
const base = process.env.TRADEGUARD_URL || "http://127.0.0.1:5175";
await mkdir("artifacts", { recursive: true });
const state = { created: false, analysed: false, stage: 0, conflict: true, status: "DRAFT", documents: [], finding: structuredClone(fixtures.findings.items[0]), decisions: [] };
const pdf = new jsPDF(); pdf.text("Contract browser report fixture", 15, 20);
const pdfBytes = Buffer.from(pdf.output("arraybuffer"));
const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=", "base64");
const now = () => new Date().toISOString();
const detail = () => ({ ...structuredClone(fixtures.shipment), status: state.status, documents: state.documents, open_discrepancy_count: state.finding.decided ? 0 : 1, decided_discrepancy_count: state.finding.decided ? 1 : 0, report_id: state.status === "REPORT_ISSUED" ? fixtures.report.report_id : null, current_run: state.analysed ? { ...fixtures.shipment.current_run, state: ["AWAITING_REVIEW", "REVIEWED", "REPORT_ISSUED"].includes(state.status) ? "SUCCEEDED" : "RUNNING", stage: ["INGEST", "CLASSIFY", "EXTRACT", "RECONCILE", "EXPLAIN", "READY"][Math.min(5, state.stage)] } : null });
await context.route("http://storage.test/**", async route => {
  const request = route.request();
  assert.equal(request.headers()["authorization"], undefined, "Storage must not receive bearer tokens");
  assert.equal(request.headers()["x-dev-user"], undefined, "Storage must not receive development identity");
  if (request.method() === "PUT") return route.fulfill({ status: 200, body: "" });
  return route.fulfill({ status: 200, contentType: request.url().endsWith(".pdf") ? "application/pdf" : "image/png", body: request.url().endsWith(".pdf") ? pdfBytes : png });
});
await context.route("**/api/v1/**", async route => {
  const request = route.request(), url = new URL(request.url()), path = url.pathname.replace("/api/v1", ""), method = request.method();
  const body = request.postData() ? JSON.parse(request.postData()) : undefined;
  if (method !== "GET") requests.push({ method, path, body });
  const ok = (data, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
  const fail = (message, status = 400, code = "VALIDATION_FAILED") => ok({ error: { code, message, retryable: false, field: null, request_id: "req_browser", details: {} } }, status);
  if (path === "/health") return ok({ status: "ok", service_role: "all", version: "test" });
  if (path === "/shipments" && method === "GET") return ok({ items: state.created ? [{ ...fixtures.summary, status: state.status, document_count: state.documents.length, open_discrepancy_count: state.analysed && !state.finding.decided ? 1 : 0 }] : [], next_cursor: null });
  if (path === "/shipments" && method === "POST") { assert.deepEqual(Object.keys(body), ["reference"]); state.created = true; return ok(detail(), 201); }
  if (path === "/shipments/shp_contract" && method === "GET") {
    if (state.status === "PROCESSING" && ++state.stage >= 6) state.status = "AWAITING_REVIEW";
    return ok(detail());
  }
  if (path.endsWith("/upload-urls")) {
    return ok({ uploads: body.files.map((file, index) => { const id = "up_" + (state.documents.length + index); return { upload_id: id, filename: file.filename, signed_url: "http://storage.test/" + id, method: "PUT", headers: { "Content-Type": file.content_type }, expires_at: new Date(Date.now() + 900000).toISOString() }; }) });
  }
  if (path.endsWith("/documents") && method === "POST") {
    const docs = body.upload_ids.map(id => { const index = Number(id.split("_")[1]); const doc = { ...fixtures.shipment.documents[index], status: "REGISTERED", page_count: null }; state.documents.push(doc); return doc; });
    state.status = "UPLOADING"; return ok({ documents: docs }, 201);
  }
  if (/\/documents\/doc_/.test(path) && method === "PATCH") {
    const doc = state.documents.find(doc => path.endsWith(doc.document_id)); doc.doc_type = body.doc_type; doc.doc_type_source = "USER"; return ok(doc);
  }
  if (path.endsWith("/analyze") && method === "POST") {
    state.analysed = true; state.status = "PROCESSING"; state.stage = 0;
    state.documents = state.documents.map(doc => ({ ...doc, status: "EXTRACTED", page_count: 2 }));
    return ok({ shipment_id: "shp_contract", run_id: "run_contract", status: state.status }, 202);
  }
  if (path.endsWith("/matrix")) return ok({ ...fixtures.matrix, status: state.status });
  if (path.endsWith("/discrepancies")) { assert.equal(url.searchParams.get("include_decided"), "true"); return ok({ ...fixtures.findings, items: [state.finding] }); }
  if (path.endsWith("/coverage")) return ok(fixtures.coverage);
  if (path.endsWith("/decisions")) return ok({ shipment_id: "shp_contract", items: state.decisions });
  if (/\/documents\/[^/]+\/pages\/\d+\/image/.test(path)) return ok({ document_id: path.split("/")[2], page: Number(path.split("/")[4]), width_px: 800, height_px: 1100, url: "http://storage.test/" + path.split("/")[2] + "-page.png", expires_at: new Date(Date.now() + 300000).toISOString() });
  if (path === "/discrepancies/dsc_quantity/decision" && method === "POST") {
    assert.ok(["ACCEPT_SUGGESTION", "OVERRIDE", "FLAG_FOR_FOLLOW_UP", "DISMISS_AS_NOT_AN_ISSUE"].includes(body.action));
    assert.equal(typeof body.expected_version, "number");
    if (state.conflict) {
      state.conflict = false; state.finding.version = 2;
      return fail("Someone else reviewed this finding first. Review the refreshed values.", 409, "CONFLICT_STALE_VERSION");
    }
    assert.equal(body.expected_version, 2, "Must use refreshed version");
    assert.equal(body.action, "OVERRIDE"); assert.equal(body.chosen_value, "100"); assert.ok(body.reason.length >= 10);
    const decision = { decision_id: "dec_contract", discrepancy_id: "dsc_quantity", shipment_id: "shp_contract", field_key: "quantity", action: body.action, chosen_document_id: body.chosen_document_id, chosen_value: body.chosen_value, reason: body.reason, actor_user_id: request.headers()["x-dev-user"] || "user_dev", decided_at: now() };
    state.finding = { ...state.finding, version: 3, decided: true, latest_decision: decision }; state.decisions.push(decision); state.status = "REVIEWED";
    return ok({ decision, discrepancy_version: 3, shipment_status: state.status, remaining_undecided: 0 }, 201);
  }
  if (path.endsWith("/report") && method === "POST") { assert.equal(state.status, "REVIEWED"); state.status = "REPORT_ISSUED"; issued.push(true); return ok(fixtures.report, 201); }
  if (path.endsWith("/report") && method === "GET") return state.status === "REPORT_ISSUED" ? ok(fixtures.report) : fail("Report not issued", 404);
  if (path === "/org/effectiveness") return ok({ org_id: "org_dev", shipments_analyzed: 1, discrepancies_total: 1, decisions_total: state.decisions.length, by_action: {}, by_severity: {}, by_field: [], suggestion_acceptance_rate: null, override_rate: null, override_against_assessment_rate: null, median_seconds_to_decision: null, undecided_discrepancies: state.finding.decided ? 0 : 1, cost: { total_usd: .012 } });
  if (path === "/org/audit/verify") return ok({ org_id: "org_dev", valid: true, events_checked: 10, first_break: null });
  throw new Error("Unexpected backend request: " + method + " " + path);
});
const visible = locator => locator.waitFor({ state: "visible", timeout: 20000 });
const pass = text => console.log("PASS " + text);
async function submitOverride(reason) {
  await page.getByRole("button", { name: /^(Review Finding|Re-review)$/ }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Override value", exact: false }).click();
  assert.equal(await dialog.getByRole("button", { name: "Submit Review", exact: true }).isDisabled(), true);
  await dialog.getByLabel("Corrected value").fill("100");
  await dialog.getByLabel("Reason (at least 10 characters)").fill(reason);
  await dialog.getByRole("button", { name: "Submit Review", exact: true }).click();
}
try {
  await page.goto(base + "/shipments/new");
  await page.getByLabel("Shipment reference").fill("CONTRACT-001");
  assert.equal(await page.getByLabel("Origin country").count(), 0);
  await page.getByRole("button", { name: "Continue to documents" }).click(); await page.waitForURL("**/edit");
  pass("creation sends only backend-supported fields");
  await page.locator("input[type=file]").setInputFiles([{ name: "invoice.pdf", mimeType: "application/pdf", buffer: pdfBytes }, { name: "packing.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.from("contract workbook fixture") }]);
  await page.getByRole("button", { name: "Save documents", exact: true }).click();
  await visible(page.getByLabel("Document type for invoice.pdf")); await page.getByLabel("Document type for invoice.pdf").selectOption("COMMERCIAL_INVOICE");
  await page.getByRole("button", { name: "Start Validation", exact: true }).click();
  await page.waitForURL("**/results", { timeout: 25000 }); await visible(page.getByRole("table", { name: "Document validation matrix" }));
  pass("signed uploads, registration, type correction, and processing reach results");
  await visible(page.getByText("Missing supporting documents", { exact: true }));
  await visible(page.getByText("Only one supporting source", { exact: true }));
  await visible(page.getByText("HS root agreement only", { exact: true }));
  await page.screenshot({ path: "artifacts/backend-results.png", fullPage: true });
  await page.getByRole("button", { name: /^100\b/ }).first().click(); await page.getByRole("button", { name: "Review Finding", exact: true }).click();
  await page.waitForURL("**/review?finding=dsc_quantity");
  await visible(page.getByAltText("invoice.pdf page 2"));
  await visible(page.getByAltText("packing.xlsx page 2"));
  assert.equal(await page.getByLabel("Source evidence region").count(), 2);
  const box = page.getByLabel("Source evidence region").first(); assert.ok((await box.getAttribute("style")).includes("width: 30"));
  await page.screenshot({ path: "artifacts/backend-review.png", fullPage: true });
  pass("server page previews and converted highlights render for PDF and XLSX");
  await submitOverride("Checked the source against the warehouse count.");
  await visible(page.getByText(/Someone else reviewed this finding first/).first());
  await page.getByRole("dialog").getByRole("button", { name: "Cancel", exact: true }).click();
  await submitOverride("Reviewed the latest source values and confirmed 100 units.");
  await page.getByRole("dialog").waitFor({ state: "hidden" });
  pass("stale-version error is shown and retry uses refreshed version");
  await page.getByRole("button", { name: "View Report" }).click(); await visible(page.getByRole("button", { name: "Issue Report", exact: true }));
  assert.equal(await page.getByRole("button", { name: "Export PDF", exact: true }).isDisabled(), true);
  await page.getByRole("button", { name: "Issue Report", exact: true }).click(); await page.getByRole("button", { name: "Confirm issue" }).click();
  await visible(page.getByText("Report Issued", { exact: true }));
  const download = page.waitForEvent("download"); await page.getByRole("button", { name: "Export PDF", exact: true }).click(); await (await download).saveAs("artifacts/backend-issued-report.pdf");
  assert.equal(issued.length, 1); pass("report is issued once and PDF downloads through the returned storage link");
  await page.goto(base + "/settings"); await page.getByLabel("Development role").selectOption("VIEWER"); await page.getByRole("button", { name: "Save session" }).click(); await page.waitForURL("**/dashboard");
  await page.goto(base + "/shipments/shp_contract/review"); await visible(page.getByRole("button", { name: "Re-review", exact: true })); assert.equal(await page.getByRole("button", { name: "Re-review", exact: true }).isDisabled(), true); pass("viewer controls cannot record review decisions");
  await page.goto(base + "/analytics"); await page.getByRole("button", { name: "Verify audit history" }).click(); await visible(page.getByText(/History verified/)); pass("backend review analytics and audit verification work");
  await page.goto(base + "/documents"); await visible(page.getByText("invoice.pdf", { exact: true }));
  assert.equal(errors.length, 0, errors.join("; ")); pass("document library works without browser errors");
  await writeFile("artifacts/backend-browser-requests.json", JSON.stringify(requests, null, 2));
} finally { await browser.close(); }
