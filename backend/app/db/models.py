"""SQLAlchemy models for the §10 schema.

Additions beyond §10, all internal (none appear on the wire as new contract):
  uploads           pending signed-URL uploads before registration
  analysis_runs     one row per pipeline run: stage, missing documents, verdict counts
  pipeline_events   SSE event log, replayed on reconnect (replaces Redis, see README)
  shipments.current_run_id, documents.text_layer,
  discrepancies.verdict / verdict_reason / likely_incorrect_document_id / assessment_confidence
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _now() -> Any:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Organisation(Base):
    __tablename__ = "organisations"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("365"))
    created_at: Mapped[datetime] = _now()


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(Text, primary_key=True)  # Firebase UID
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)  # stored lower-cased
    display_name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


class Membership(Base):
    __tablename__ = "memberships"
    org_id: Mapped[str] = mapped_column(Text, ForeignKey("organisations.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (CheckConstraint("role IN ('OWNER','APPROVER','VIEWER')"),)


class Shipment(Base):
    __tablename__ = "shipments"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    org_id: Mapped[str] = mapped_column(Text, ForeignKey("organisations.id"), nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    current_run_id: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("org_id", "reference"),
        Index(
            "ix_shipments_org_created",
            "org_id",
            text("created_at DESC"),
            text("id DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class Upload(Base):
    __tablename__ = "uploads"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    shipment_id: Mapped[str] = mapped_column(Text, ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False)
    org_id: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    object_name: Mapped[str] = mapped_column(Text, nullable=False)
    document_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    shipment_id: Mapped[str] = mapped_column(Text, ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False)
    org_id: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    gcs_uri: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    doc_type: Mapped[str | None] = mapped_column(Text)
    doc_type_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    doc_type_source: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str | None] = mapped_column(Text)
    superseded_by: Mapped[str | None] = mapped_column(Text, ForeignKey("documents.id"))
    text_layer: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    __table_args__ = (
        CheckConstraint("doc_type_source IN ('MODEL','USER')"),
        Index("ix_documents_shipment", "shipment_id"),
        Index("ix_documents_org_sha", "org_id", "sha256"),
    )


class DocumentPage(Base):
    __tablename__ = "document_pages"
    document_id: Mapped[str] = mapped_column(Text, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    page: Mapped[int] = mapped_column(Integer, primary_key=True)
    gcs_uri: Mapped[str] = mapped_column(Text, nullable=False)
    width_px: Mapped[int] = mapped_column(Integer, nullable=False)
    height_px: Mapped[int] = mapped_column(Integer, nullable=False)


class ExtractedField(Base):
    __tablename__ = "extracted_fields"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_id: Mapped[str] = mapped_column(Text, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    shipment_id: Mapped[str] = mapped_column(Text, nullable=False)
    org_id: Mapped[str] = mapped_column(Text, nullable=False)
    field_key: Mapped[str] = mapped_column(Text, nullable=False)
    raw_value: Mapped[str | None] = mapped_column(Text)
    normalized_value: Mapped[str | None] = mapped_column(Text)
    normalized_unit: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    cell_status: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[list[Decimal] | None] = mapped_column(ARRAY(Numeric(6, 5)))
    model: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (
        Index("ix_extracted_fields_shipment_field", "shipment_id", "field_key"),
        Index("ix_extracted_fields_document", "document_id"),
    )


class FieldVerdict(Base):
    __tablename__ = "field_verdicts"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    shipment_id: Mapped[str] = mapped_column(Text, ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False)
    org_id: Mapped[str] = mapped_column(Text, nullable=False)
    field_key: Mapped[str] = mapped_column(Text, nullable=False)
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    verdict_reason: Mapped[str | None] = mapped_column(Text)
    value_groups: Mapped[Any] = mapped_column(JSONB, nullable=False)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _now()
    __table_args__ = (UniqueConstraint("shipment_id", "field_key", "run_id"),)


class Discrepancy(Base):
    __tablename__ = "discrepancies"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    shipment_id: Mapped[str] = mapped_column(Text, ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False)
    org_id: Mapped[str] = mapped_column(Text, nullable=False)
    field_key: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    verdict_reason: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text)
    explanation_state: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'PENDING'"))
    assessment_confidence: Mapped[str | None] = mapped_column(Text)
    likely_incorrect_document_id: Mapped[str | None] = mapped_column(Text, ForeignKey("documents.id"))
    suggested_document_id: Mapped[str | None] = mapped_column(Text, ForeignKey("documents.id"))
    suggested_value: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _now()
    __table_args__ = (
        CheckConstraint("severity IN ('BLOCKING','WARNING','INFO')"),
        Index(
            "ix_discrepancies_open",
            "shipment_id",
            postgresql_where=text("explanation_state <> 'RESOLVED'"),
        ),
    )


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    discrepancy_id: Mapped[str] = mapped_column(Text, ForeignKey("discrepancies.id", ondelete="CASCADE"), nullable=False)
    shipment_id: Mapped[str] = mapped_column(Text, nullable=False)
    org_id: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[str] = mapped_column(Text, ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    chosen_document_id: Mapped[str | None] = mapped_column(Text, ForeignKey("documents.id"))
    chosen_value: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = _now()
    __table_args__ = (Index("ix_decisions_shipment", "shipment_id", "decided_at"),)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    org_id: Mapped[str] = mapped_column(Text, nullable=False)
    shipment_id: Mapped[str | None] = mapped_column(Text)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[Any] = mapped_column(JSONB, nullable=False)
    request_id: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(Text)
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    # Set by the BEFORE INSERT trigger; the server default only satisfies NOT NULL until then.
    hash: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("''"))
    occurred_at: Mapped[datetime] = _now()
    __table_args__ = (
        CheckConstraint("actor_type IN ('USER','SYSTEM','AI')"),
        Index("ix_audit_org_shipment", "org_id", "shipment_id", "occurred_at"),
    )


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    shipment_id: Mapped[str] = mapped_column(Text, ForeignKey("shipments.id"), nullable=False)
    org_id: Mapped[str] = mapped_column(Text, nullable=False)
    gcs_uri: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    kms_key_version: Mapped[str] = mapped_column(Text, nullable=False)
    signature: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    issued_by: Mapped[str] = mapped_column(Text, ForeignKey("users.id"), nullable=False)
    issued_at: Mapped[datetime] = _now()


class JobRun(Base):
    __tablename__ = "job_runs"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    shipment_id: Mapped[str] = mapped_column(Text, ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False)
    org_id: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    error_code: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModelInvocation(Base):
    __tablename__ = "model_invocations"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    org_id: Mapped[str] = mapped_column(Text, nullable=False)
    shipment_id: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[str | None] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = _now()
    __table_args__ = (Index("ix_model_invocations_org", "org_id", "occurred_at"),)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    shipment_id: Mapped[str] = mapped_column(Text, ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False)
    org_id: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)  # QUEUED | RUNNING | SUCCEEDED | FAILED
    current_stage: Mapped[str | None] = mapped_column(Text)
    missing_documents: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    verdict_counts: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_analysis_runs_shipment", "shipment_id", "created_at"),)


class PipelineEvent(Base):
    __tablename__ = "pipeline_events"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    shipment_id: Mapped[str] = mapped_column(Text, nullable=False)
    org_id: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[Any] = mapped_column(JSONB, nullable=False)
    at: Mapped[datetime] = _now()
    __table_args__ = (Index("ix_pipeline_events_shipment", "shipment_id", "id"),)
