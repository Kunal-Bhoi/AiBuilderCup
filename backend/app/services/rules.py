"""Deterministic normalisation and reconciliation (principle 2.6).

The comparison is code, not a model: whether two HS codes share a heading is a fact about the
Harmonised System, and whether 48250.00 equals 48,250.00 is arithmetic. Both AI modes use this
module. In stub mode it backs the stand-in AI service; in vertex mode Gemini reads the documents
and explains findings, but every verdict still comes from here.

  normalise(field_key, raw)  -> (normalized_value, normalized_unit), pure
  reconcile(request)         -> one verdict per canonical field, pure
"""

import re
import unicodedata
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

from app.domain.enums import CellStatus, DocType, Verdict
from app.domain.fields import APPLICABILITY, CANONICAL_FIELDS, FIELD_LABELS
from app.schemas import ai

# ---------------------------------------------------------------- normalise

LABEL_TO_FIELD: dict[str, str] = {}
for _k, _label in FIELD_LABELS.items():
    LABEL_TO_FIELD[_label.casefold()] = _k
    LABEL_TO_FIELD[_k.replace("_", " ")] = _k
LABEL_TO_FIELD.update(
    {
        "seller": "seller_name", "exporter": "seller_name", "buyer": "buyer_name", "importer": "buyer_name",
        "consignee": "consignee_name", "shipper": "shipper_name", "notify party": "notify_party_name",
        "description of goods": "product_description", "description": "product_description", "goods": "product_description",
        "hs": "hs_code", "hs code": "hs_code", "tariff code": "hs_code", "origin": "country_of_origin",
        "qty": "quantity", "unit": "quantity_uom", "uom": "quantity_uom", "total": "invoice_total",
        "total value": "invoice_total", "invoice value": "invoice_total", "packages": "package_count",
        "no. of packages": "package_count", "marks": "marks_and_numbers", "b/l no": "bl_number",
        "b/l number": "bl_number", "bl number": "bl_number", "vessel": "vessel_name", "voyage": "voyage_number",
        "port of loading": "port_of_loading", "port of discharge": "port_of_discharge", "container no": "container_numbers",
        "container": "container_numbers", "containers": "container_numbers", "seal": "seal_numbers",
        "certificate no": "certificate_number", "po no": "po_number", "purchase order number": "po_number",
        "invoice no": "invoice_number", "terms": "incoterm", "incoterms": "incoterm",
    }
)

NUMERIC = {"invoice_total", "unit_price", "line_total", "net_weight", "gross_weight"}
INTEGER = {"quantity", "package_count"}
ENUM = {"incoterm", "currency", "quantity_uom", "country_of_origin", "net_weight_uom", "gross_weight_uom", "package_type"}
DATES = {"invoice_date", "bl_date"}
EXACT = {"invoice_number", "bl_number", "po_number", "container_numbers", "seal_numbers", "certificate_number",
         "voyage_number", "flight_number", "exporter_reference"}

_CURRENCY = {"$": "USD", "us$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR", "euro": "EUR", "£": "GBP", "gbp": "GBP",
             "₹": "INR", "inr": "INR", "rs": "INR", "sgd": "SGD", "s$": "SGD", "jpy": "JPY", "¥": "JPY", "cny": "CNY",
             "rmb": "CNY", "aed": "AED", "kwd": "KWD"}
_WEIGHT = {"kg": Decimal(1), "kgs": Decimal(1), "kilograms": Decimal(1), "kilogram": Decimal(1), "lb": Decimal("0.45359237"),
           "lbs": Decimal("0.45359237"), "mt": Decimal(1000), "t": Decimal(1000), "tonnes": Decimal(1000), "g": Decimal("0.001")}
_UOM = {"pcs": "PCS", "pc": "PCS", "pieces": "PCS", "piece": "PCS", "units": "PCS", "unit": "PCS", "nos": "PCS",
        "ea": "PCS", "each": "PCS", "sets": "SET", "set": "SET", "cartons": "CTN", "ctns": "CTN", "carton": "CTN",
        "kg": "KG", "kgs": "KG", "mt": "MT", "pallets": "PLT", "pallet": "PLT"}
_COUNTRY = {"india": "IN", "china": "CN", "people's republic of china": "CN", "singapore": "SG", "japan": "JP",
            "united states": "US", "usa": "US", "germany": "DE", "kuwait": "KW", "united arab emirates": "AE", "uae": "AE",
            "vietnam": "VN", "viet nam": "VN", "korea": "KR", "south korea": "KR", "malaysia": "MY", "australia": "AU"}
_INCOTERMS = {"EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"}


def _decimal(text: str) -> Decimal | None:
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", text.replace(" ", ""))
    if not m:
        return None
    try:
        return Decimal(m.group(0).replace(",", ""))
    except InvalidOperation:
        return None


def _plain(n: Decimal) -> str:
    """Decimal without exponent or trailing zeros: 480.000 -> '480', 47.50 -> '47.5'."""
    return format(n.normalize(), "f")


def normalise(field_key: str, raw: str) -> tuple[str | None, str | None]:
    """Returns (normalized_value, normalized_unit). None value means it could not be normalised.

    Never raises. Model-read text can be anything: an impossible date such as 31/02/2025 or a
    number beyond Decimal precision is "could not normalise" (the raw value is kept and the cell
    drops to CANNOT_VERIFY downstream), never a crash that would lose every document's extraction."""
    try:
        return _normalise(field_key, raw)
    except (ValueError, ArithmeticError):  # date() out of range; decimal.InvalidOperation is an ArithmeticError
        return None, None


def _normalise(field_key: str, raw: str) -> tuple[str | None, str | None]:
    t = unicodedata.normalize("NFKC", raw).strip()
    low = t.casefold()
    if field_key in NUMERIC:
        n = _decimal(t)
        if n is None:
            return None, None
        unit = None
        if field_key in {"net_weight", "gross_weight"}:
            m = re.search(r"(kgs?|kilograms?|lbs?|mt|tonnes|\bt\b|\bg\b)", low)
            factor = _WEIGHT.get(m.group(1), Decimal(1)) if m else Decimal(1)
            return _plain((n * factor).quantize(Decimal("0.001"))), "KG"
        for sym, code in _CURRENCY.items():
            if sym in low:
                unit = code
                break
        return str(n.quantize(Decimal("0.01"))), unit
    if field_key in INTEGER:
        n = _decimal(t)
        if n is None:
            return None, None
        m = re.search(r"[a-z]+", low)
        return _plain(n), (_UOM.get(m.group(0)) if m else None)
    if field_key == "hs_code":
        digits = re.sub(r"[^0-9]", "", t)
        return (digits or None), None
    if field_key == "currency":
        return _CURRENCY.get(low, t.upper()), None
    if field_key == "incoterm":
        m = re.search(r"\b([A-Z]{3})\b", t.upper())
        return (m.group(1) if m and m.group(1) in _INCOTERMS else t.upper()), None
    if field_key == "country_of_origin":
        return _COUNTRY.get(low, t.upper() if len(t) == 2 else t.title()), None
    if field_key in {"quantity_uom", "net_weight_uom", "gross_weight_uom", "package_type"}:
        return _UOM.get(low, t.upper()), None
    if field_key in DATES:
        return _norm_date(t), None
    if field_key in EXACT:
        return re.sub(r"[\s\-_/.]", "", t).upper(), None
    return re.sub(r"\s+", " ", t), None


_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _norm_date(t: str) -> str | None:
    """ISO date, or 'AMBIGUOUS:<a>|<b>' when DD/MM vs MM/DD cannot be settled."""
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", t)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
    m = re.match(r"^(\d{1,2})[\s\-]([A-Za-z]{3})[A-Za-z]*[\s\-,]+(\d{4})$", t)
    if m and m[2].casefold()[:3] in _MONTHS:
        return date(int(m[3]), _MONTHS[m[2].casefold()[:3]], int(m[1])).isoformat()
    m = re.match(r"^(\d{1,2})[/.](\d{1,2})[/.](\d{4})$", t)
    if m:
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        if a > 12:
            return date(y, b, a).isoformat()
        if b > 12:
            return date(y, a, b).isoformat()
        if a == b:
            return date(y, a, b).isoformat()
        return f"AMBIGUOUS:{date(y, b, a).isoformat()}|{date(y, a, b).isoformat()}"
    return None


# ---------------------------------------------------------------- reconcile

TOLERANCE = {
    "invoice_total": (Decimal("0.005"), Decimal("1.00")),
    "unit_price": (Decimal("0.005"), Decimal("0.01")),
    "line_total": (Decimal("0.005"), Decimal("1.00")),
    "net_weight": (Decimal("0.01"), Decimal("0.5")),
    "gross_weight": (Decimal("0.01"), Decimal("0.5")),
}
FUZZY = {"product_description", "seller_name", "buyer_name", "consignee_name", "shipper_name", "notify_party_name",
         "seller_address", "buyer_address", "consignee_address", "port_of_loading", "port_of_discharge",
         "place_of_delivery", "vessel_name", "incoterm_place", "payment_terms", "marks_and_numbers", "origin_criterion"}
_ABBREV = {"pcs": "pieces", "pc": "pieces", "in": "inch", "inches": "inch", '"': "inch", "notebook": "laptop",
           "co": "company", "ltd": "limited", "pvt": "private", "intl": "international", "mfg": "manufacturing"}
_STOP = {"the", "of", "and", "a", "an", "for", "with", "s"}


def _tokens(text: str) -> frozenset[str]:
    t = unicodedata.normalize("NFKC", text).casefold()
    t = re.sub(r"(\d)\s*(in|inch|\")\b", r"\1 inch", t)
    t = re.sub(r"[^\w\s]", " ", t)
    words = (_ABBREV.get(w, w) for w in t.split() if w not in _STOP)
    # crude plural folding: "computers" == "computer"
    return frozenset(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in words)


def _similar(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    # token-set ratio approximation: overlap relative to the smaller set
    return inter / min(len(a), len(b))


def _group(field_key: str, present: list[ai.ReconcileFieldIn]) -> tuple[Verdict, str | None, list[ai.ValueGroup]]:
    def groups_from(buckets: dict[str, list[str]]) -> list[ai.ValueGroup]:
        return [ai.ValueGroup(normalized_value=v, document_ids=ids) for v, ids in buckets.items()]

    if field_key in DATES and any((f.normalized_value or "").startswith("AMBIGUOUS:") for f in present):
        return Verdict.CANNOT_VERIFY, "A date is ambiguous between DD/MM and MM/DD; both readings were recorded.", \
            groups_from({f.normalized_value: [f.document_id] for f in present})

    if field_key == "hs_code":
        norm = [(f, re.sub(r"[^0-9]", "", f.normalized_value or "")) for f in present]
        if any(len(n) < 6 for _, n in norm):
            return Verdict.CANNOT_VERIFY, "An HS code shorter than six digits is not a valid heading.", \
                groups_from(_bucket(norm))
        roots = {n[:6] for _, n in norm}
        buckets = _bucket(norm)
        if len(roots) > 1:
            return Verdict.DISAGREE, f"Different HS headings: {', '.join(sorted(roots))}.", groups_from(buckets)
        if len(buckets) == 1:
            return Verdict.AGREE, None, groups_from(buckets)
        root = next(iter(roots))
        return (Verdict.AGREE_AT_HS_ROOT,
                f"All documents agree on heading {root[:4]}.{root[4:]}. National extensions differ "
                f"({', '.join(sorted(buckets))}), which is expected across jurisdictions.",
                groups_from(buckets))

    if field_key in TOLERANCE:
        vals = [(f, Decimal(f.normalized_value)) for f in present if _is_decimal(f.normalized_value)]
        if len(vals) < len(present):
            return Verdict.CANNOT_VERIFY, "A value could not be read as a number.", groups_from(_bucket([(f, f.normalized_value or "") for f in present]))
        units = {f.normalized_unit for f, _ in vals if f.normalized_unit}
        buckets = _bucket([(f, str(v)) for f, v in vals])
        if len(units) > 1:
            return Verdict.DISAGREE, f"Values are stated in different units: {', '.join(sorted(units))}. Not converted.", groups_from(buckets)
        if len(buckets) == 1:
            return Verdict.AGREE, None, groups_from(buckets)
        rel, abs_ = TOLERANCE[field_key]
        lo, hi = min(v for _, v in vals), max(v for _, v in vals)
        if hi - lo <= max(abs_, rel * hi):
            return Verdict.TOLERANCE_MATCH, f"Values differ by {hi - lo}, inside the tolerance for this field.", groups_from(buckets)
        return Verdict.DISAGREE, f"Values differ by {hi - lo}, outside the tolerance for this field.", groups_from(buckets)

    if field_key in FUZZY:
        reps: list[tuple[frozenset[str], list[ai.ReconcileFieldIn]]] = []
        for f in present:
            tok = _tokens(f.normalized_value or f.raw_value or "")
            for r_tok, members in reps:
                if r_tok == tok or _similar(r_tok, tok) >= 0.82:
                    members.append(f)
                    break
            else:
                reps.append((tok, [f]))
        groups = [ai.ValueGroup(normalized_value=m[0].normalized_value, document_ids=[x.document_id for x in m]) for _, m in reps]
        if len(groups) == 1:
            exact = len({f.normalized_value for f in present}) == 1
            return Verdict.AGREE, None if exact else "Wording differs but the descriptions match after canonicalisation.", groups
        return Verdict.DISAGREE, f"{len(groups)} materially different values across documents.", groups

    buckets = _bucket([(f, f.normalized_value or "") for f in present])
    if len(buckets) == 1:
        return Verdict.AGREE, None, groups_from(buckets)
    return Verdict.DISAGREE, f"{len(buckets)} different values across documents.", groups_from(buckets)


def _is_decimal(v: str | None) -> bool:
    try:
        Decimal(v or "x")
        return True
    except InvalidOperation:
        return False


def _bucket(pairs) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for f, v in pairs:
        out[v].append(f.document_id)
    return dict(out)


def reconcile(req: ai.ReconcileRequest) -> ai.ReconcileResponse:
    floor = req.options.confidence_floor
    doc_types = {d.document_id: d.doc_type for d in req.documents}
    by_field: dict[str, list[ai.ReconcileFieldIn]] = defaultdict(list)
    for f in req.fields:
        by_field[f.field_key].append(f)

    verdicts = []
    for key in CANONICAL_FIELDS:
        applicable = [d for d, t in doc_types.items() if APPLICABILITY[key].get(t) in ("R", "O")]
        if not applicable:
            verdicts.append(ai.FieldVerdictOut(field_key=key, verdict=Verdict.NOT_APPLICABLE))
            continue
        cells = by_field.get(key, [])
        present = [f for f in cells if f.cell_status == CellStatus.PRESENT and f.confidence >= floor and f.normalized_value]
        if not present:
            required = [d for d in applicable if APPLICABILITY[key].get(doc_types[d]) == "R"]
            unreadable = [f for f in cells if f.cell_status in (CellStatus.UNREADABLE, CellStatus.LOW_CONFIDENCE)]
            if required or unreadable:
                verdicts.append(ai.FieldVerdictOut(
                    field_key=key, verdict=Verdict.CANNOT_VERIFY,
                    verdict_reason=f"Expected in {len(required or unreadable)} document(s), readable in none."))
            else:
                verdicts.append(ai.FieldVerdictOut(
                    field_key=key, verdict=Verdict.NOT_APPLICABLE,
                    verdict_reason="Optional in the uploaded document types and present in none."))
            continue
        if len(present) == 1:
            verdicts.append(ai.FieldVerdictOut(
                field_key=key, verdict=Verdict.SINGLE_SOURCE,
                verdict_reason="Only one document carries this field, so it was not cross-checked.",
                value_groups=[ai.ValueGroup(normalized_value=present[0].normalized_value, document_ids=[present[0].document_id])]))
            continue
        verdict, reason, groups = _group(key, present)
        verdicts.append(ai.FieldVerdictOut(field_key=key, verdict=verdict, verdict_reason=reason, value_groups=groups))

    missing = []
    types = set(doc_types.values())
    pref = next((f for f in by_field.get("preference_claim", []) if (f.normalized_value or "").casefold() in {"yes", "y", "true", "claimed"}), None)
    if pref and DocType.CERTIFICATE_OF_ORIGIN not in types:
        missing.append(ai.MissingDocument(
            doc_type=DocType.CERTIFICATE_OF_ORIGIN, severity="WARNING",
            reason=f"A preferential duty claim was detected on the {doc_types.get(pref.document_id, 'document').replace('_', ' ').lower()} but no certificate of origin was uploaded."))
    return ai.ReconcileResponse(request_id=req.request_id, verdicts=verdicts, missing_documents=missing)
