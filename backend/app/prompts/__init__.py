"""Versioned prompts (AI-SPEC §11.2). The version travels with every extracted field and every
model_invocations row, so a finding can be traced to the exact prompt that produced it.

Change a prompt's wording -> bump its version. A prompt change is a code change, and the
evaluation harness (scripts/evaluate.py) should be re-run before it ships."""

from app.domain.enums import DocType
from app.domain.fields import FIELD_LABELS
from app.schemas import ai

CLASSIFY_VERSION = "classify.v1"
EXPLAIN_VERSION = "explain.v1"
EXTRACT_VERSION = "v1"  # full id is extract.{doc_type}.v1

SYSTEM = (
    "You are a careful trade-document reader working for a licensed customs broker. You read shipping "
    "documents and report exactly what is printed on them. You never guess, infer, complete or correct a "
    "value: if something is not printed, or you cannot read it, you say so. Your output is checked by "
    "deterministic code and then by a human who is legally accountable for the declaration."
)

# ---------------------------------------------------------------- classify

_DOC_TYPE_HINTS = {
    DocType.COMMERCIAL_INVOICE: "seller's bill to the buyer: invoice number, prices, invoice total",
    DocType.PACKING_LIST: "packages, cartons, marks, net and gross weights; usually no prices",
    DocType.BILL_OF_LADING: "ocean transport contract issued by a carrier: B/L number, vessel, voyage, ports, containers",
    DocType.AIR_WAYBILL: "air transport document: AWB number, flight, airports",
    DocType.CERTIFICATE_OF_ORIGIN: "certifies where goods were made, often issued by a chamber of commerce; may support a preference claim",
    DocType.PURCHASE_ORDER: "buyer's order to the seller: PO number, ordered quantities and prices",
    DocType.CUSTOMS_DECLARATION: "declaration to customs (bill of entry, shipping bill, entry summary): HS codes, declared values",
    DocType.INSURANCE_CERTIFICATE: "cargo insurance certificate or policy: insured value, insurer",
    DocType.UNKNOWN: "none of the above, or the page is unreadable",
}


def classify(filename: str, text_excerpt: str | None) -> tuple[str, str]:
    types = "\n".join(f"- {t.value}: {hint}" for t, hint in _DOC_TYPE_HINTS.items())
    text = (
        "Identify the type of this trade document from its first page.\n\n"
        f"Allowed types:\n{types}\n\n"
        "Rules:\n"
        "- Judge from the document's content and title, not from the filename alone.\n"
        "- If the page is blank, unreadable, or not one of the listed types, answer UNKNOWN.\n"
        "- confidence is your probability (0 to 1) that the type is correct.\n"
        "- evidence is the short printed phrase that decided it, or null.\n\n"
        f"Filename (a weak hint only): {filename}\n"
    )
    if text_excerpt:
        text += f"\nEmbedded text of the first page (may be incomplete):\n{text_excerpt}\n"
    return CLASSIFY_VERSION, text


# ---------------------------------------------------------------- extract

FIELD_HINTS: dict[str, str] = {
    "seller_name": "the seller / exporter company name",
    "seller_address": "the seller's postal address",
    "buyer_name": "the buyer / importer company name",
    "buyer_address": "the buyer's postal address",
    "consignee_name": "the consignee (party the goods are delivered to)",
    "consignee_address": "the consignee's postal address",
    "notify_party_name": "the notify party",
    "shipper_name": "the shipper (on transport documents)",
    "incoterm": "the Incoterm with its place if printed together, e.g. 'FOB Shenzhen'",
    "incoterm_place": "the named place of the Incoterm when printed separately",
    "currency": "the currency of the invoice or order values, e.g. 'USD'",
    "invoice_total": "the grand total value of the document, with its currency symbol or code as printed",
    "payment_terms": "payment terms",
    "po_number": "the purchase order number",
    "invoice_number": "the commercial invoice number",
    "invoice_date": "the invoice date exactly as printed (do not reformat)",
    "product_description": "the description of the goods",
    "hs_code": "the HS / tariff code exactly as printed, keeping dots and all digits",
    "country_of_origin": "the country where the goods originate",
    "quantity": "the total quantity of goods with its unit as printed, e.g. '100 PCS'",
    "quantity_uom": "the unit of the total quantity, e.g. PCS, SET, CTN",
    "unit_price": "the unit price with currency as printed",
    "line_total": "the line total value",
    "net_weight": "the total net weight with its unit as printed, e.g. '480 kg'",
    "net_weight_uom": "the unit of the net weight",
    "gross_weight": "the total gross weight with its unit as printed",
    "gross_weight_uom": "the unit of the gross weight",
    "package_count": "the total number of packages",
    "package_type": "the type of package, e.g. cartons, pallets",
    "marks_and_numbers": "the shipping marks and numbers",
    "bl_number": "the bill of lading number",
    "bl_date": "the bill of lading / shipped-on-board date as printed",
    "vessel_name": "the vessel name",
    "voyage_number": "the voyage number",
    "flight_number": "the flight number",
    "port_of_loading": "the port of loading",
    "port_of_discharge": "the port of discharge",
    "place_of_delivery": "the place of delivery",
    "container_numbers": "the container number(s) as printed",
    "seal_numbers": "the seal number(s)",
    "preference_claim": "whether a preferential tariff treatment is claimed: answer 'Yes' or 'No' only if the document states it",
    "origin_criterion": "the origin criterion on a certificate of origin",
    "certificate_number": "the certificate of origin number",
    "exporter_reference": "the exporter's reference number",
}


def extract(doc_type: str, field_keys: list[str], page_numbers: list[int]) -> tuple[str, str]:
    version = f"extract.{doc_type.lower()}.{EXTRACT_VERSION}"
    label = doc_type.replace("_", " ").lower()
    fields = "\n".join(f"- {k}: {FIELD_LABELS.get(k, k)}. {FIELD_HINTS.get(k, '')}" for k in field_keys)
    pages = ", ".join(str(n) for n in page_numbers)
    text = (
        f"This document is a {label}. Its pages are attached as images, each preceded by a 'Page N' label "
        f"(pages {pages}). Extract the fields below.\n\n"
        f"Fields (return exactly one row for every one of them, in this order):\n{fields}\n\n"
        "For each row:\n"
        "- value: the text exactly as printed, including units and currency symbols. Do not convert, translate, "
        "reformat dates, or fix typos. If the field is not printed or you cannot read it, value is null.\n"
        "- null_reason: null when value is present; otherwise 'field_absent' (not printed on this document), "
        "'region_illegible' (printed but unreadable: blurred, stamped over, cut off) or 'ambiguous' "
        "(several conflicting candidates and you cannot tell which applies).\n"
        "- page: the 'Page N' number of the image where you read the value, or null when value is null.\n"
        "- box_2d: the bounding box of the value on that page as [ymin, xmin, ymax, xmax], integers normalised "
        "to 0-1000 with the origin at the top-left. Box the value itself, not its label. null when value is null.\n"
        "- raw_text: the full printed line the value came from (label and value), or null.\n"
        "- confidence: your probability from 0 to 1 that value is exactly what is printed. Use low values for "
        "handwriting, stamps, glare, skew or small print.\n\n"
        "If a value appears in several places, use the document-level total or the most prominent printed one. "
        "A handwritten correction over a printed value: report the handwritten value, lower the confidence and "
        "mention both in raw_text."
    )
    return version, text


# ---------------------------------------------------------------- explain

def explain(req: ai.ExplainRequest) -> tuple[str, str]:
    label = FIELD_LABELS.get(req.field_key, req.field_key)
    values = "\n".join(
        f"- document_id={v.document_id} ({v.doc_type.replace('_', ' ').lower()}): printed \"{v.raw_value}\""
        f" normalised \"{v.normalized_value}\" (extraction confidence {v.confidence:.2f})" for v in req.values)
    related = "\n".join(f"- {FIELD_LABELS.get(r.field_key, r.field_key)}: {r.value}" for r in req.related_fields) or "- none"
    text = (
        f"The documents of one shipment disagree on the field \"{label}\".\n\n"
        f"Conflicting values:\n{values}\n\n"
        f"Related fields on which all documents agree:\n{related}\n\n"
        "Assess which document is most likely wrong and why, for a customs broker who will decide.\n"
        "Rules:\n"
        "- Use only the information above. Do not assume facts about the shipment that are not given.\n"
        "- likely_incorrect_document_id must be one of the document_ids above, or null if there is no sound "
        "basis to single one out. Do not pick one just to give an answer.\n"
        "- suggested_value is the printed value you believe is correct, copied exactly from one of the "
        "conflicting values, or null.\n"
        "- assessment_confidence is HIGH, MODERATE or LOW. A majority of documents alone is at most MODERATE.\n"
        "- explanation: at most three sentences in plain English, naming the documents by type. State that the "
        "broker should confirm with the shipper when the evidence is weak."
    )
    return EXPLAIN_VERSION, text
