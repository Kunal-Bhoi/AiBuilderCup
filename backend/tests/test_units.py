"""Pure-function tests: status machine, applicability, sniffing, stub normalisation and reconciliation."""

import pytest

from app.domain.enums import ShipmentStatus as S
from app.domain.fields import APPLICABILITY, CANONICAL_FIELDS, applicability
from app.domain.status import assert_transition, can_transition
from app.errors import ERROR_TABLE, AppError, ErrorCode
from app.schemas import ai
from app.services import ai_stub
from app.services.documents_io import Kind, sniff


def test_every_error_code_has_status_and_retryability():
    assert set(ERROR_TABLE) == set(ErrorCode)


def test_report_only_from_reviewed():
    assert can_transition(S.REVIEWED, S.REPORT_ISSUED)
    for s in S:
        if s != S.REVIEWED:
            assert not can_transition(s, S.REPORT_ISSUED)
    with pytest.raises(AppError):
        assert_transition(S.DRAFT, S.REPORT_ISSUED)


def test_applicability_matches_spec_samples():
    assert applicability("hs_code", "CERTIFICATE_OF_ORIGIN") == "R"
    assert applicability("hs_code", "BILL_OF_LADING") is None
    assert applicability("gross_weight", "AIR_WAYBILL") == "R"  # B/L column covers AWB
    assert set(APPLICABILITY) == set(CANONICAL_FIELDS)


def test_sniff_ignores_declared_type():
    assert sniff(b"%PDF-1.7 ...") == Kind.PDF
    assert sniff(b"\x89PNG\r\n\x1a\n....") == Kind.PNG
    assert sniff(b"\xff\xd8\xff\xe0") == Kind.JPEG
    assert sniff(b"MZ\x90\x00 not a document") == Kind.UNKNOWN


@pytest.mark.parametrize("raw,expected", [
    ("2026-10-02", "2026-10-02"),
    ("2 Oct 2026", "2026-10-02"),
    ("25/12/2026", "2026-12-25"),
    ("03/04/2026", "AMBIGUOUS:2026-04-03|2026-03-04"),
])
def test_date_ambiguity_is_never_guessed(raw, expected):
    assert ai_stub.normalise("invoice_date", raw)[0] == expected


def _req(values: dict[str, tuple[str, str]], field: str):
    """values: document_id -> (doc_type, normalized value)"""
    return ai.ReconcileRequest(
        request_id="r", shipment_id="s",
        documents=[ai.ReconcileDocumentIn(document_id=d, doc_type=t) for d, (t, _) in values.items()],
        fields=[ai.ReconcileFieldIn(document_id=d, field_key=field, raw_value=v, normalized_value=v,
                                    normalized_unit=None, confidence=0.9, cell_status="PRESENT")
                for d, (_, v) in values.items()])


def _verdict(resp, field):
    return next(v for v in resp.verdicts if v.field_key == field)


def test_reconcile_hs_root_and_disagreement():
    same_root = _req({"a": ("COMMERCIAL_INVOICE", "8471300100"), "b": ("CUSTOMS_DECLARATION", "847130010000")}, "hs_code")
    assert _verdict(ai_stub.reconcile(same_root), "hs_code").verdict == "AGREE_AT_HS_ROOT"
    diff = _req({"a": ("COMMERCIAL_INVOICE", "8471300100"), "b": ("CUSTOMS_DECLARATION", "8473309100")}, "hs_code")
    assert _verdict(ai_stub.reconcile(diff), "hs_code").verdict == "DISAGREE"


def test_reconcile_tolerance_and_exact_quantity():
    tol = _req({"a": ("COMMERCIAL_INVOICE", "48250.00"), "b": ("CUSTOMS_DECLARATION", "48250.40")}, "invoice_total")
    assert _verdict(ai_stub.reconcile(tol), "invoice_total").verdict == "TOLERANCE_MATCH"
    qty = _req({"a": ("COMMERCIAL_INVOICE", "100"), "b": ("PACKING_LIST", "95")}, "quantity")
    assert _verdict(ai_stub.reconcile(qty), "quantity").verdict == "DISAGREE"


def test_reconcile_single_source_is_never_agree():
    one = _req({"a": ("COMMERCIAL_INVOICE", "USD")}, "currency")
    assert _verdict(ai_stub.reconcile(one), "currency").verdict == "SINGLE_SOURCE"
