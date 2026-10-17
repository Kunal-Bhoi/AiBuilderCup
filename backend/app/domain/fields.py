"""Canonical field catalogue (§4.2) and the applicability matrix (§4.5).

The applicability matrix drives the difference between CANNOT_VERIFY and NOT_APPLICABLE,
and it is what lets the UI honestly state what was not checked (principle 2.4)."""

from dataclasses import dataclass

from app.domain.enums import DocType

FIELD_GROUPS: dict[str, list[tuple[str, str]]] = {
    "Parties": [
        ("seller_name", "Seller name"),
        ("seller_address", "Seller address"),
        ("buyer_name", "Buyer name"),
        ("buyer_address", "Buyer address"),
        ("consignee_name", "Consignee name"),
        ("consignee_address", "Consignee address"),
        ("notify_party_name", "Notify party"),
        ("shipper_name", "Shipper name"),
    ],
    "Commercial terms": [
        ("incoterm", "Incoterm"),
        ("incoterm_place", "Incoterm place"),
        ("currency", "Currency"),
        ("invoice_total", "Invoice total"),
        ("payment_terms", "Payment terms"),
        ("po_number", "PO number"),
        ("invoice_number", "Invoice number"),
        ("invoice_date", "Invoice date"),
    ],
    "Goods": [
        ("product_description", "Product description"),
        ("hs_code", "HS code"),
        ("country_of_origin", "Country of origin"),
        ("quantity", "Quantity"),
        ("quantity_uom", "Quantity unit"),
        ("unit_price", "Unit price"),
        ("line_total", "Line total"),
        ("net_weight", "Net weight"),
        ("net_weight_uom", "Net weight unit"),
        ("gross_weight", "Gross weight"),
        ("gross_weight_uom", "Gross weight unit"),
        ("package_count", "Package count"),
        ("package_type", "Package type"),
        ("marks_and_numbers", "Marks and numbers"),
    ],
    "Transport": [
        ("bl_number", "B/L number"),
        ("bl_date", "B/L date"),
        ("vessel_name", "Vessel name"),
        ("voyage_number", "Voyage number"),
        ("flight_number", "Flight number"),
        ("port_of_loading", "Port of loading"),
        ("port_of_discharge", "Port of discharge"),
        ("place_of_delivery", "Place of delivery"),
        ("container_numbers", "Container numbers"),
        ("seal_numbers", "Seal numbers"),
    ],
    "Regulatory": [
        ("preference_claim", "Preference claim"),
        ("origin_criterion", "Origin criterion"),
        ("certificate_number", "Certificate number"),
        ("exporter_reference", "Exporter reference"),
    ],
}

FIELD_LABELS: dict[str, str] = {k: label for fields in FIELD_GROUPS.values() for k, label in fields}
FIELD_GROUP_OF: dict[str, str] = {k: g for g, fields in FIELD_GROUPS.items() for k, _ in fields}
CANONICAL_FIELDS: list[str] = list(FIELD_LABELS.keys())

# §4.5. Columns: INVOICE, PACKING, BL/AWB, COO, PO, DECL. "" = not applicable.
_COLS = [
    DocType.COMMERCIAL_INVOICE,
    DocType.PACKING_LIST,
    DocType.BILL_OF_LADING,
    DocType.CERTIFICATE_OF_ORIGIN,
    DocType.PURCHASE_ORDER,
    DocType.CUSTOMS_DECLARATION,
]
_MATRIX: dict[str, tuple[str, str, str, str, str, str]] = {
    "invoice_number": ("R", "O", "", "O", "", "R"),
    "invoice_date": ("R", "O", "", "", "", "R"),
    "seller_name": ("R", "O", "", "R", "R", "R"),
    "buyer_name": ("R", "O", "", "R", "R", "R"),
    "consignee_name": ("O", "O", "R", "O", "", "R"),
    "notify_party_name": ("", "", "O", "", "", ""),
    "incoterm": ("R", "", "O", "", "O", "R"),
    "currency": ("R", "", "", "", "O", "R"),
    "invoice_total": ("R", "", "", "", "O", "R"),
    "product_description": ("R", "R", "R", "R", "R", "R"),
    "hs_code": ("O", "O", "", "R", "O", "R"),
    "country_of_origin": ("O", "O", "", "R", "", "R"),
    "quantity": ("R", "R", "O", "O", "R", "R"),
    "quantity_uom": ("R", "R", "O", "O", "R", "R"),
    "unit_price": ("R", "", "", "", "R", "O"),
    "net_weight": ("O", "R", "O", "", "", "R"),
    "gross_weight": ("O", "R", "R", "", "", "R"),
    "package_count": ("O", "R", "R", "O", "", "R"),
    "package_type": ("", "R", "R", "", "", "O"),
    "marks_and_numbers": ("", "R", "R", "", "", "O"),
    "bl_number": ("", "", "R", "", "", "R"),
    "bl_date": ("", "", "R", "", "", "O"),
    "vessel_name": ("", "", "O", "", "", "O"),
    "port_of_loading": ("O", "", "R", "", "", "R"),
    "port_of_discharge": ("O", "", "R", "", "", "R"),
    "container_numbers": ("", "O", "R", "", "", "O"),
    "po_number": ("O", "O", "", "", "R", ""),
    "preference_claim": ("", "", "", "R", "", "O"),
    "certificate_number": ("", "", "", "R", "", "O"),
}

APPLICABILITY: dict[str, dict[str, str]] = {}
for _field, _row in _MATRIX.items():
    _entry = {col.value: v for col, v in zip(_COLS, _row) if v}
    # The B/L column covers both bills of lading and air waybills.
    if DocType.BILL_OF_LADING.value in _entry:
        _entry[DocType.AIR_WAYBILL.value] = _entry[DocType.BILL_OF_LADING.value]
    APPLICABILITY[_field] = _entry

# Canonical fields with no row in §4.5 are not expected in any document type in v1.
for _field in CANONICAL_FIELDS:
    APPLICABILITY.setdefault(_field, {})


def applicability(field_key: str, doc_type: str | None) -> str | None:
    """'R', 'O', or None when the field is not expected in that document type."""
    if not doc_type:
        return None
    return APPLICABILITY.get(field_key, {}).get(doc_type)


def applicable_fields(doc_type: str | None) -> list[str]:
    return [f for f in CANONICAL_FIELDS if applicability(f, doc_type)]


@dataclass(frozen=True)
class OutOfScope:
    key: str
    label: str
    reason: str


# Principle 2.4: what we deliberately do NOT check, displayed as prominently as what we do.
OUT_OF_SCOPE: list[OutOfScope] = [
    OutOfScope("insurance_value", "Insurance value", "Insurance certificates are classified but their values are not cross-checked in v1."),
    OutOfScope("freight_charges", "Freight charges", "Freight and ancillary charges are not extracted."),
    OutOfScope("hs_tariff_validity", "HS code validity against tariff", "HS codes are compared across documents, not validated against a national tariff schedule."),
    OutOfScope("duty_and_tax", "Duty and tax computation", "No duty, tax or valuation computation is performed."),
    OutOfScope("currency_conversion", "Currency conversion", "Different currencies are reported as a disagreement, never converted."),
    OutOfScope("sanctions_screening", "Sanctions and denied-party screening", "Parties are not screened against any list."),
    OutOfScope("line_item_reconciliation", "Line-item level reconciliation", "Goods are compared at shipment level, not per line item."),
    OutOfScope("signatures_and_stamps", "Signatures and stamps", "Presence or authenticity of signatures and stamps is not checked."),
]
OUT_OF_SCOPE_KEYS = [o.key for o in OUT_OF_SCOPE]

# Required document types given what is present (used when the AI service does not report them).
REQUIRED_DOC_TYPES = [DocType.COMMERCIAL_INVOICE, DocType.PACKING_LIST]
