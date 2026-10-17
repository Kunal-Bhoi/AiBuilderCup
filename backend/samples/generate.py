"""Generate sample shipment document sets (original assets, created for this project).

    uv run python samples/generate.py            # writes samples/out/<scenario>/*.pdf

Each document is a one-page A4 PDF with a real text layer: a title line, then "Label: value"
lines on an 18pt grid starting 72pt from the top. app/services/ai_stub.py relies on that
layout for its approximate bounding boxes. The scenarios mirror the shared fixture set (§8.1)."""

import copy
import io
import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent / "out"

BASE = {
    "COMMERCIAL INVOICE": {
        "Invoice number": "INV-2026-0141",
        "Invoice date": "2026-10-02",
        "Seller name": "Shenzhen Brightway Electronics Co., Ltd.",
        "Buyer name": "Harbourline Trading Pte Ltd",
        "Consignee name": "Harbourline Trading Pte Ltd",
        "Incoterm": "FOB Shenzhen",
        "Currency": "USD",
        "Invoice total": "USD 48,250.00",
        "Product description": "Laptop computer 14 inch, 16GB RAM",
        "HS code": "8471.30.0100",
        "Country of origin": "China",
        "Quantity": "100 PCS",
        "Unit price": "USD 482.50",
        "Gross weight": "520 kg",
        "Net weight": "480 kg",
        "Port of loading": "Shenzhen, China",
        "Port of discharge": "Singapore",
        "PO number": "PO-88213",
    },
    "PACKING LIST": {
        "Invoice number": "INV-2026-0141",
        "Seller name": "Shenzhen Brightway Electronics Co., Ltd.",
        "Buyer name": "Harbourline Trading Pte Ltd",
        "Product description": "Laptop computer 14 inch, 16GB RAM",
        "HS code": "8471.30.0100",
        "Quantity": "100 PCS",
        "Net weight": "480 kg",
        "Gross weight": "520 kg",
        "Package count": "10",
        "Package type": "Cartons",
        "Marks and numbers": "HTL/SG/1-10",
        "Container numbers": "MSKU 1234565",
    },
    "BILL OF LADING": {
        "B/L number": "MAEU 246810357",
        "B/L date": "2026-10-05",
        "Shipper name": "Shenzhen Brightway Electronics Co., Ltd.",
        "Consignee name": "Harbourline Trading Pte Ltd",
        "Notify party": "Harbourline Trading Pte Ltd",
        "Vessel name": "MAERSK KOWLOON",
        "Port of loading": "Shenzhen, China",
        "Port of discharge": "Singapore",
        "Product description": "Laptop computers 14in",
        "Package count": "10",
        "Package type": "Cartons",
        "Gross weight": "520 kg",
        "Marks and numbers": "HTL/SG/1-10",
        "Container numbers": "MSKU1234565",
    },
    "CUSTOMS DECLARATION": {
        "Invoice number": "INV-2026-0141",
        "Invoice date": "2026-10-02",
        "Seller name": "Shenzhen Brightway Electronics Co., Ltd.",
        "Buyer name": "Harbourline Trading Pte Ltd",
        "Consignee name": "Harbourline Trading Pte Ltd",
        "Incoterm": "FOB",
        "Currency": "USD",
        "Invoice total": "48250.00",
        "Product description": "Laptop computer 14 inch, 16GB RAM",
        "HS code": "8471.30.0100",
        "Country of origin": "CN",
        "Quantity": "100 PCS",
        "Net weight": "480 kg",
        "Gross weight": "520 kg",
        "Package count": "10",
        "B/L number": "MAEU246810357",
        "Port of loading": "Shenzhen",
        "Port of discharge": "Singapore",
        "Preference claim": "No",
    },
    "PURCHASE ORDER": {
        "PO number": "PO-88213",
        "Seller name": "Shenzhen Brightway Electronics Co., Ltd.",
        "Buyer name": "Harbourline Trading Pte Ltd",
        "Incoterm": "FOB",
        "Currency": "USD",
        "Invoice total": "USD 48,250.00",
        "Product description": "Laptop computer 14 inch, 16GB RAM",
        "Quantity": "100 PCS",
        "Unit price": "USD 482.50",
    },
    "CERTIFICATE OF ORIGIN": {
        "Certificate number": "CO-SZ-2026-77120",
        "Seller name": "Shenzhen Brightway Electronics Co., Ltd.",
        "Buyer name": "Harbourline Trading Pte Ltd",
        "Product description": "Laptop computer 14 inch",
        "HS code": "8471.30",
        "Country of origin": "China",
        "Preference claim": "Yes",
        "Package count": "10",
    },
}

FILENAMES = {
    "COMMERCIAL INVOICE": "commercial_invoice.pdf",
    "PACKING LIST": "packing_list.pdf",
    "BILL OF LADING": "bill_of_lading.pdf",
    "CUSTOMS DECLARATION": "customs_declaration.pdf",
    "PURCHASE ORDER": "purchase_order.pdf",
    "CERTIFICATE OF ORIGIN": "certificate_of_origin.pdf",
}

CORE = ["COMMERCIAL INVOICE", "PACKING LIST", "BILL OF LADING", "CUSTOMS DECLARATION"]


def scenario(docs: list[str], **overrides: dict[str, str]) -> dict[str, dict[str, str]]:
    out = {d: copy.deepcopy(BASE[d]) for d in docs}
    for doc, changes in overrides.items():
        out[doc.replace("_", " ")].update(changes)
    return out


SCENARIOS = {
    "clean_fcl": scenario(CORE),
    "hs_digit_mismatch": scenario(CORE, CUSTOMS_DECLARATION={"HS code": "8471.30.010000"},
                                  PACKING_LIST={"HS code": "8471.30.01"}),
    "description_drift": scenario(CORE, PACKING_LIST={"Product description": "Notebook PC 14\" 16G"},
                                  BILL_OF_LADING={"Product description": "Computer accessories and parts"}),
    "quantity_weight_conflict": scenario(CORE, PACKING_LIST={"Quantity": "95 PCS", "Gross weight": "48 kg",
                                                             "Net weight": "45 kg"},
                                         COMMERCIAL_INVOICE={"Gross weight": "50 kg", "Net weight": "47 kg"},
                                         CUSTOMS_DECLARATION={"Gross weight": "50 kg", "Net weight": "47 kg"},
                                         BILL_OF_LADING={"Gross weight": "50 kg"}),
    "missing_coo": scenario(CORE, CUSTOMS_DECLARATION={"Preference claim": "Yes"}),
    "currency_mismatch": scenario(CORE + ["PURCHASE ORDER"], PURCHASE_ORDER={"Currency": "EUR",
                                                                            "Invoice total": "EUR 44,390.00"}),
    "single_document": scenario(["COMMERCIAL INVOICE"]),
    "duplicate_doc_type": scenario(CORE),
    "with_certificate_of_origin": scenario(CORE + ["CERTIFICATE OF ORIGIN"],
                                           CUSTOMS_DECLARATION={"Preference claim": "Yes"}),
}


def render(title: str, fields: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    y = height - 72
    c.setFont("Helvetica-Bold", 14)
    c.drawString(72, y, title)
    c.setFont("Helvetica", 10)
    for label, value in fields.items():
        y -= 18
        c.drawString(72, y, f"{label}: {value}")
    c.setFont("Helvetica-Oblique", 7)
    c.drawString(72, 40, "Sample document generated for TradeCheck testing. Not a real shipment.")
    c.showPage()
    c.save()
    return buf.getvalue()


def encrypted(pdf: bytes) -> bytes:
    from pypdf import PdfReader, PdfWriter

    w = PdfWriter()
    for page in PdfReader(io.BytesIO(pdf)).pages:
        w.add_page(page)
    w.encrypt(user_password="secret", owner_password="owner")
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def main() -> None:
    for name, docs in SCENARIOS.items():
        d = OUT / name
        d.mkdir(parents=True, exist_ok=True)
        for title, fields in docs.items():
            (d / FILENAMES[title]).write_bytes(render(title, fields))
        if name == "duplicate_doc_type":
            revised = dict(BASE["COMMERCIAL INVOICE"], **{"Invoice number": "INV-2026-0141-R1"})
            (d / "commercial_invoice_revised.pdf").write_bytes(render("COMMERCIAL INVOICE", revised))
    bad = OUT / "corrupt_and_protected"
    bad.mkdir(parents=True, exist_ok=True)
    for title in ("COMMERCIAL INVOICE", "PACKING LIST"):
        (bad / FILENAMES[title]).write_bytes(render(title, BASE[title]))
    (bad / "bill_of_lading_corrupt.pdf").write_bytes(b"%PDF-1.7\n" + b"\x00garbage" * 200)
    (bad / "customs_declaration_protected.pdf").write_bytes(encrypted(render("CUSTOMS DECLARATION",
                                                                             BASE["CUSTOMS DECLARATION"])))
    print(f"wrote samples to {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
