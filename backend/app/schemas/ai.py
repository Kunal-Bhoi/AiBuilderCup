"""Backend <-> ai-service payloads (§6).

/ai/v1/extract is pinned by the spec. classify, reconcile and explain are DRAFT shapes the
backend proposes; they are mirrored in contracts/fixtures/ai/ and must be confirmed with the
AI developer. Models are permissive on input (extra="ignore") so additive changes on the AI
side do not break the worker."""

from pydantic import BaseModel, ConfigDict, Field


class _M(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Usage(_M):
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = "unknown"
    model_version: str = "unknown"
    prompt_version: str = "unknown"
    latency_ms: int = 0


class PageRef(_M):
    page: int
    image_url: str
    width_px: int
    height_px: int


# ---- classify (DRAFT) ----
class ClassifyDocumentIn(_M):
    document_id: str
    filename: str
    page_count: int
    pages: list[PageRef]
    text_layer_excerpt: str | None = None


class ClassifyRequest(_M):
    request_id: str
    documents: list[ClassifyDocumentIn]


class PageRange(_M):
    doc_type: str
    start_page: int
    end_page: int


class ClassifiedDocument(_M):
    document_id: str
    doc_type: str
    confidence: float
    page_ranges: list[PageRange] | None = None


class DuplicateGroup(_M):
    doc_type: str
    document_ids: list[str]
    primary_document_id: str | None = None


class MissingDocument(_M):
    doc_type: str
    severity: str = "WARNING"
    reason: str


class ClassifyResponse(_M):
    request_id: str
    documents: list[ClassifiedDocument]
    duplicates: list[DuplicateGroup] = []
    missing_documents: list[MissingDocument] = []
    usage: Usage | None = None


# ---- extract (frozen, §6) ----
class ExtractOptions(_M):
    confidence_floor: float = 0.55
    max_pages: int = 15
    redact: bool = True


class ExtractRequest(_M):
    request_id: str
    document_id: str
    doc_type: str
    pages: list[PageRef]
    text_layer: str | None = None
    options: ExtractOptions = Field(default_factory=ExtractOptions)


class Provenance(_M):
    page: int | None = None
    bbox: list[float] | None = None


class ExtractedFieldOut(_M):
    field_key: str
    raw_value: str | None = None
    normalized_value: str | None = None
    normalized_unit: str | None = None
    confidence: float = 0.0
    provenance: Provenance = Field(default_factory=Provenance)


class UnreadableField(_M):
    field_key: str
    reason: str = "REGION_ILLEGIBLE"


class ExtractResponse(_M):
    request_id: str
    document_id: str
    fields: list[ExtractedFieldOut] = []
    unreadable_fields: list[UnreadableField] = []
    usage: Usage = Field(default_factory=Usage)
    warnings: list[str] = []


# ---- reconcile (DRAFT) ----
class ReconcileDocumentIn(_M):
    document_id: str
    doc_type: str


class ReconcileFieldIn(_M):
    document_id: str
    field_key: str
    raw_value: str | None
    normalized_value: str | None
    normalized_unit: str | None
    confidence: float
    cell_status: str


class ReconcileOptions(_M):
    confidence_floor: float = 0.55


class ReconcileRequest(_M):
    request_id: str
    shipment_id: str
    documents: list[ReconcileDocumentIn]
    fields: list[ReconcileFieldIn]
    options: ReconcileOptions = Field(default_factory=ReconcileOptions)


class ValueGroup(_M):
    normalized_value: str | None
    document_ids: list[str]


class FieldVerdictOut(_M):
    field_key: str
    verdict: str
    verdict_reason: str | None = None
    value_groups: list[ValueGroup] = []


class ReconcileResponse(_M):
    request_id: str
    verdicts: list[FieldVerdictOut]
    missing_documents: list[MissingDocument] = []
    usage: Usage | None = None


# ---- explain (DRAFT) ----
class ExplainValueIn(_M):
    document_id: str
    doc_type: str
    raw_value: str | None
    normalized_value: str | None
    confidence: float


class RelatedField(_M):
    field_key: str
    value: str | None


class ExplainRequest(_M):
    request_id: str
    shipment_id: str
    field_key: str
    verdict: str
    values: list[ExplainValueIn]
    related_fields: list[RelatedField] = []


class ExplainResponse(_M):
    request_id: str
    explanation: str | None = None
    likely_incorrect_document_id: str | None = None
    suggested_value: str | None = None
    assessment_confidence: str | None = None  # HIGH | MODERATE | LOW
    usage: Usage | None = None
