import type { ShipmentStatus, MatrixCell, ValidationStatus } from "@/types";
export const canEditDocuments = (status: ShipmentStatus) => ["draft", "uploading", "failed", "ready_for_review", "reviewed"].includes(status);
export const hasResults = (status: ShipmentStatus) => ["ready_for_review", "reviewed", "finalized"].includes(status);
export function cellValidationStatus(cell: MatrixCell, fieldStatus: ValidationStatus): ValidationStatus {
  if (fieldStatus === "not_checked") return "not_checked";
  if (cell.cellStatus === "NOT_APPLICABLE" || fieldStatus === "not_applicable") return "not_applicable";
  if (cell.cellStatus && cell.cellStatus !== "PRESENT") return "cannot_verify";
  if (!cell.rawValue?.trim()) return "cannot_verify";
  return fieldStatus;
}
