import type { ValidationReport } from "@/types";
export async function exportReport(report: ValidationReport, download = true) {
  const { jsPDF } = await import("jspdf");
  const { default: autoTable } = await import("jspdf-autotable");
  const pdf = new jsPDF({ unit: "pt", format: "a4" });
  pdf.setFontSize(16); pdf.text("TradeGuard AI | Validation Report", 36, 42);
  pdf.setFontSize(10);
  pdf.text([report.reference + " | " + report.status.toUpperCase(), report.shipment.originCountry + " to " + report.shipment.destinationCountry, "Generated: " + new Date(report.generatedAt).toLocaleString(), "Prepared by: " + report.generatedBy, "Pending human reviews: " + report.pendingReviews], 36, 65);
  autoTable(pdf, { startY: 140, head: [["Document", "Type"]], body: report.results.documents.map(doc => [doc.filename, doc.typeLabel ?? doc.type]), styles: { fontSize: 8 }, margin: 36 });
  autoTable(pdf, { head: [["Field", "Status", "Document values / source"]], body: report.results.matrix.map(field => [field.label, field.status.replace(/_/g, " "), field.cells.map(cell => {
    const doc = report.results.documents.find(item => item.id === cell.documentId);
    return (doc?.filename ?? cell.documentId) + ": " + (cell.rawValue ?? "Missing / unavailable") + (cell.source ? " | page " + cell.source.page + " | confidence " + (cell.source.confidence === null ? "unknown" : Math.round(cell.source.confidence * 100) + "%") + " | region " + (cell.source.bbox?.join(", ") ?? "unavailable") + (cell.source.excerpt ? " | " + cell.source.excerpt : "") + (cell.source.sheetName ? " | sheet " + cell.source.sheetName + " " + (cell.source.cellRange ?? "") : "") + (cell.source.modelId ? " | model " + cell.source.modelId + " " + (cell.source.modelVersion ?? "") : "") + (cell.source.extractedAt ? " | extracted " + cell.source.extractedAt : "") : "");
  }).join("\n")]), styles: { fontSize: 7, cellPadding: 4 }, margin: 36 });
  autoTable(pdf, { head: [["Finding", "Explanation / follow-up", "Human decision"]], body: report.results.findings.map(finding => [finding.label + " (" + finding.severity + ")", finding.explanation + "\n" + (finding.suggestion ?? ""), finding.reviewAction ? finding.reviewAction.decision.replace(/_/g, " ") + "\n" + (finding.reviewAction.reason ?? "") + "\n" + finding.reviewAction.reviewerName + "\n" + finding.reviewAction.reviewedAt : "PENDING REVIEW"]), styles: { fontSize: 7 }, margin: 36 });
  autoTable(pdf, { head: [["Coverage", "Fields"]], body: [["Not checked", report.results.coverage.notCheckedFields.join(", ")], ["Cannot verify", report.results.matrix.filter(field => field.status === "cannot_verify").map(field => field.label).join(", ")], ["Review purpose", "Review completion does not resolve confirmed discrepancies or constitute customs clearance. A qualified customs professional remains accountable."]], styles: { fontSize: 8 }, margin: 36 });
  for (let page = 1; page <= pdf.getNumberOfPages(); page++) { pdf.setPage(page); pdf.setFontSize(8); pdf.text("TradeGuard AI | " + report.status + " | Page " + page + " of " + pdf.getNumberOfPages(), 36, 824); }
  if (download) pdf.save("tradeguard-report-" + report.reference.replace(/[^a-zA-Z0-9_-]/g, "_") + ".pdf");
  return pdf.output("blob");
}
