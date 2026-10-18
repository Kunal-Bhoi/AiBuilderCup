import { MOCK_VALIDATION_RESULTS } from "./fixtures";
import { summarizeResults } from "@/lib/validation";
import type { Shipment, ValidationResults } from "@/types";
// Simulated values always come from the predefined steel-pipes example.
export function buildFixtureResults(shipment: Shipment): ValidationResults {
  const result = structuredClone(MOCK_VALIDATION_RESULTS);
  result.shipmentId = shipment.id; result.status = shipment.status;
  result.generatedAt = shipment.validatedAt ?? new Date().toISOString();
  const originals = result.documents;
  result.documents = shipment.documents.map(document => ({ ...document }));
  result.matrix.forEach(field => {
    const fixtureCells = field.cells;
    field.cells = shipment.documents.map((document, index) => {
      const fixtureIndex = document.type === "unknown" ? index % originals.length : originals.findIndex(original => original.type === document.type);
      const fixture = fixtureCells.find(cell => cell.documentId === originals[fixtureIndex]?.id);
      return fixture ? { ...structuredClone(fixture), documentId: document.id } : { documentId: document.id, rawValue: null, normalizedValue: null, source: null };
    });
    if (field.status === "mismatch" && field.cells.filter(cell => cell.rawValue !== null).length < 2) field.status = "cannot_verify";
  });
  summarizeResults(result);
  result.findings = result.findings.filter(finding => result.matrix.find(field => field.fieldKey === finding.fieldKey)?.status === "mismatch");
  result.matrix.filter(field => field.status === "cannot_verify").forEach(field => {
    result.findings.push({ id: `unverified-${field.fieldKey}`, fieldKey: field.fieldKey, label: field.label, severity: "medium", status: "cannot_verify", explanation: `${field.label} cannot be compared reliably: source values are missing or have insufficient evidence.`, suggestion: "Obtain a readable supporting document and verify this field with the shipper.", reviewStatus: "pending", affectedDocuments: [] });
  });
  result.findings.forEach(finding => {
    finding.affectedDocuments = shipment.documents.map(document => document.id);
    if (shipment.status === "finalized") {
      finding.reviewStatus = "reviewed";
      finding.reviewAction = { decision: "override_finding", reason: "Demo record: supporting evidence checked by the sample reviewer.", reviewerId: "usr-demo", reviewerName: "Marcus Weber", reviewedAt: shipment.finalizedAt! };
    }
  });
  return result;
}
