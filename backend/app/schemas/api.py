"""Frontend <-> backend payloads (§5). The generated contracts/openapi.yaml comes from these,
so the contract cannot drift from the code."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    CellStatus,
    DecisionAction,
    DocType,
    DocTypeSource,
    DocumentStatus,
    ExplanationState,
    Severity,
    ShipmentStatus,
    Verdict,
)


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- shipments
class ShipmentCreate(_M):
    reference: str = Field(min_length=1, max_length=120)


class DocumentOut(_M):
    document_id: str
    filename: str
    doc_type: DocType | None
    doc_type_confidence: float | None
    doc_type_source: DocTypeSource | None
    page_count: int | None
    status: DocumentStatus
    error_code: str | None = None
    superseded_by: str | None = None
    size_bytes: int
    content_type: str
    sha256: str
    created_at: datetime


class RunOut(_M):
    run_id: str
    state: str
    stage: str | None
    error_code: str | None
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None
    verdict_counts: dict[str, int]
    cost_usd: float
    input_tokens: int
    output_tokens: int


class MissingDocumentOut(_M):
    doc_type: str
    severity: Severity
    reason: str


class ShipmentSummary(_M):
    shipment_id: str
    reference: str
    status: ShipmentStatus
    version: int
    document_count: int
    open_discrepancy_count: int
    created_at: datetime
    updated_at: datetime


class ShipmentDetail(_M):
    shipment_id: str
    reference: str
    status: ShipmentStatus
    version: int
    created_by: str
    created_at: datetime
    updated_at: datetime
    documents: list[DocumentOut]
    current_run: RunOut | None
    missing_documents: list[MissingDocumentOut]
    open_discrepancy_count: int
    decided_discrepancy_count: int
    report_id: str | None


class ShipmentList(_M):
    items: list[ShipmentSummary]
    next_cursor: str | None


# ---------------------------------------------------------------- uploads
class UploadFileIn(_M):
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    content_type: str


class UploadUrlsRequest(_M):
    files: list[UploadFileIn] = Field(min_length=1)


class UploadUrlOut(_M):
    upload_id: str
    filename: str
    signed_url: str
    method: Literal["PUT"] = "PUT"
    headers: dict[str, str]
    expires_at: datetime


class UploadUrlsResponse(_M):
    uploads: list[UploadUrlOut]


class RegisterDocumentsRequest(_M):
    upload_ids: list[str] = Field(min_length=1)


class RegisterDocumentsResponse(_M):
    documents: list[DocumentOut]


class DocumentPatch(_M):
    doc_type: DocType


class AnalyzeResponse(_M):
    shipment_id: str
    run_id: str
    status: ShipmentStatus


# ---------------------------------------------------------------- matrix
class ProvenanceOut(_M):
    page: int | None
    bbox: list[float] | None
    model: str
    model_version: str
    prompt_version: str
    extracted_at: datetime


class CellOut(_M):
    document_id: str
    cell_status: CellStatus
    raw_value: str | None
    normalized_value: str | None
    normalized_unit: str | None = None
    confidence: float
    provenance: ProvenanceOut | None


class FieldRowOut(_M):
    field_key: str
    label: str
    verdict: Verdict
    verdict_reason: str | None
    discrepancy_id: str | None
    value_groups: list[dict[str, Any]] = []
    cells: list[CellOut]


class FieldGroupOut(_M):
    group: str
    fields: list[FieldRowOut]


class MatrixDocumentOut(_M):
    document_id: str
    filename: str
    doc_type: DocType | None
    doc_type_confidence: float | None
    doc_type_source: DocTypeSource | None
    page_count: int | None
    status: DocumentStatus
    error_code: str | None = None
    superseded_by: str | None = None


class MatrixResponse(_M):
    shipment_id: str
    status: ShipmentStatus
    run_id: str | None
    generated_at: datetime | None
    documents: list[MatrixDocumentOut]
    field_groups: list[FieldGroupOut]
    missing_documents: list[MissingDocumentOut]
    out_of_scope_fields: list[str]
    verdict_counts: dict[str, int]


# ---------------------------------------------------------------- discrepancies and decisions
class DecisionOut(_M):
    decision_id: str
    discrepancy_id: str
    shipment_id: str
    field_key: str
    action: DecisionAction
    chosen_document_id: str | None
    chosen_value: str | None
    reason: str | None
    actor_user_id: str
    decided_at: datetime


class DiscrepancyOut(_M):
    discrepancy_id: str
    shipment_id: str
    field_key: str
    label: str
    verdict: Verdict
    verdict_reason: str | None
    severity: Severity
    explanation: str | None
    explanation_state: ExplanationState
    assessment_confidence: Literal["HIGH", "MODERATE", "LOW"] | None
    likely_incorrect_document_id: str | None
    suggested_document_id: str | None
    suggested_value: str | None
    version: int
    decided: bool
    latest_decision: DecisionOut | None
    cells: list[CellOut]
    created_at: datetime


class DiscrepancyList(_M):
    shipment_id: str
    run_id: str | None
    items: list[DiscrepancyOut]


class DecisionRequest(_M):
    action: DecisionAction
    chosen_document_id: str | None = None
    chosen_value: str | None = None
    reason: str | None = None
    expected_version: int


class DecisionResponse(_M):
    decision: DecisionOut
    discrepancy_version: int
    shipment_status: ShipmentStatus
    remaining_undecided: int


class DecisionList(_M):
    shipment_id: str
    items: list[DecisionOut]


# ---------------------------------------------------------------- coverage
class CoverageField(_M):
    field_key: str
    label: str
    group: str
    verdict: Verdict


class OutOfScopeOut(_M):
    key: str
    label: str
    reason: str


class UncheckedDocument(_M):
    document_id: str
    filename: str
    doc_type: DocType | None
    status: DocumentStatus
    error_code: str | None
    reason: str


class CoverageResponse(_M):
    shipment_id: str
    run_id: str | None
    checked_fields: list[CoverageField]
    single_source_fields: list[CoverageField]
    cannot_verify_fields: list[CoverageField]
    not_applicable_fields: list[CoverageField]
    out_of_scope: list[OutOfScopeOut]
    unchecked_documents: list[UncheckedDocument]
    missing_documents: list[MissingDocumentOut]


# ---------------------------------------------------------------- reports, pages, org
class ReportOut(_M):
    report_id: str
    shipment_id: str
    issued_by: str
    issued_at: datetime
    content_sha256: str
    signature_algorithm: str
    signature_b64: str
    kms_key_version: str
    download_url: str
    expires_at: datetime


class PageImageOut(_M):
    document_id: str
    page: int
    url: str
    expires_at: datetime
    width_px: int
    height_px: int


class EffectivenessByField(_M):
    field_key: str
    total: int
    by_action: dict[str, int]


class EffectivenessResponse(_M):
    org_id: str
    shipments_analyzed: int
    discrepancies_total: int
    decisions_total: int
    by_action: dict[str, int]
    by_severity: dict[str, int]
    by_field: list[EffectivenessByField]
    suggestion_acceptance_rate: float | None
    override_rate: float | None
    override_against_assessment_rate: float | None
    median_seconds_to_decision: float | None
    undecided_discrepancies: int
    cost: dict[str, float]


class AuditVerifyResponse(_M):
    org_id: str
    valid: bool
    events_checked: int
    first_break: dict[str, Any] | None


class Health(_M):
    status: str
    service_role: str
    version: str
