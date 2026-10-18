import type { Shipment, ValidationResults, ValidationReport } from "@/types";
export function summarizeResults(results: ValidationResults): ValidationResults {
  results.matrix.forEach(field => {
    if (field.status === "match" && field.cells.filter(cell => !!cell.rawValue?.trim() && cell.source !== null && (!cell.cellStatus || cell.cellStatus === "PRESENT")).length < 2) field.status = "cannot_verify";
  });
  const count = (status: string) => results.matrix.filter(field => field.status === status).length;
  results.summary = { matched: count("match"), mismatched: count("mismatch"), cannotVerify: count("cannot_verify"), notChecked: count("not_checked"), notApplicable: count("not_applicable") };
  results.coverage = {
    checkedFields: results.matrix.filter(field => !["not_checked", "not_applicable"].includes(field.status)).map(field => field.fieldKey),
    notCheckedFields: results.matrix.filter(field => field.status === "not_checked").map(field => field.fieldKey),
  };
  return results;
}
export function makeReport(shipment: Shipment, results: ValidationResults): ValidationReport {
  const pendingReviews = results.findings.filter(finding => finding.reviewStatus === "pending").length;
  return {
    shipmentId: shipment.id, reference: shipment.reference, generatedAt: shipment.finalizedAt ?? shipment.validatedAt ?? results.generatedAt,
    generatedBy: shipment.createdBy, status: shipment.status === "finalized" ? "finalized" : "draft", shipment, results, pendingReviews,
    canFinalize: ["ready_for_review", "reviewed"].includes(shipment.status) && pendingReviews === 0,
    reviewerDecisions: results.findings.flatMap(finding => finding.reviewAction ? [{ findingId: finding.id, field: finding.label, ...finding.reviewAction }] : []),
  };
}
