"""The signed pre-submission report: what was checked, what was found, what the human decided,
and when. This is the artefact the broker keeps for their own liability file."""

import io
from dataclasses import dataclass, field
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape


@dataclass
class ReportData:
    report_id: str
    shipment_reference: str
    shipment_id: str
    run_id: str
    issued_at: str
    issued_by: str
    documents: list[dict[str, Any]]
    verdict_counts: dict[str, int]
    findings: list[dict[str, Any]]
    single_source: list[str]
    cannot_verify: list[str]
    missing_documents: list[dict[str, Any]]
    out_of_scope: list[dict[str, str]]
    models: list[dict[str, Any]]
    audit_head: str | None
    cost_usd: float
    extra: dict[str, Any] = field(default_factory=dict)


def _p(text: Any, style) -> Paragraph:
    return Paragraph(escape("" if text is None else str(text)), style)


def build_pdf(r: ReportData) -> bytes:
    ss = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=ss["Normal"], fontSize=7.5, leading=9.5)
    body = ParagraphStyle("body", parent=ss["Normal"], fontSize=9, leading=12)
    h2 = ss["Heading2"]
    grid = TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#999999")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEEEEE")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ])

    def table(header: list[str], rows: list[list[Any]], widths: list[float]) -> Table:
        data = [[_p(h, small) for h in header]] + [[_p(c, small) for c in row] for row in rows]
        t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
        t.setStyle(grid)
        return t

    story: list[Any] = [
        Paragraph("Pre-submission cross-document check", ss["Title"]),
        _p(f"Shipment {r.shipment_reference} ({r.shipment_id}) · run {r.run_id}", body),
        _p(f"Report {r.report_id} · issued {r.issued_at} by {r.issued_by}", body),
        Spacer(1, 4 * mm),
        _p("This report records a consistency check across the shipment's own documents, reviewed and decided "
           "by the named approver. Nothing was filed with any customs authority or bank. The approver, not this "
           "system, is accountable for the declaration.", body),
        Spacer(1, 4 * mm),
        Paragraph("Documents examined", h2),
        table(["Document", "Type", "Status", "SHA-256"],
              [[d["filename"], d["doc_type"], d["status"] + (f" ({d['error_code']})" if d.get("error_code") else ""),
                d["sha256"][:16] + "…"] for d in r.documents], [55, 40, 35, 45]),
        Spacer(1, 3 * mm),
        Paragraph("Summary", h2),
        _p(" · ".join(f"{k}: {v}" for k, v in sorted(r.verdict_counts.items())) or "No fields compared.", body),
        Paragraph("Findings and decisions", h2),
    ]
    if r.findings:
        story.append(table(
            ["Field", "Verdict", "Values by document", "Assessment", "Decision", "Reason", "Decided"],
            [[f["label"], f"{f['verdict']} / {f['severity']}", f["values"], f.get("assessment") or "-",
              f.get("action") or "UNDECIDED", f.get("reason") or "-", f.get("decided") or "-"] for f in r.findings],
            [24, 22, 42, 32, 22, 22, 22]))
    else:
        story.append(_p("No findings required a decision.", body))

    def bullet_section(title: str, items: list[str], empty: str) -> None:
        story.append(Paragraph(title, h2))
        story.append(_p("; ".join(items) if items else empty, body))

    bullet_section("Single source (not cross-checked)", r.single_source, "None.")
    bullet_section("Cannot verify", r.cannot_verify, "None.")
    bullet_section("Missing documents",
                   [f"{m['doc_type']} ({m['severity']}): {m['reason']}" for m in r.missing_documents], "None reported.")
    story.append(KeepTogether([
        Paragraph("Not checked by this system", h2),
        table(["Item", "Why"], [[o["label"], o["reason"]] for o in r.out_of_scope], [55, 120]),
    ]))
    story.append(Paragraph("Re-performance record", h2))
    story.append(table(["Stage", "Model", "Model version", "Prompt version", "Calls"],
                       [[m["stage"], m["model"], m["model_version"], m["prompt_version"], m["calls"]] for m in r.models],
                       [25, 40, 35, 55, 20]))
    story.append(Spacer(1, 2 * mm))
    story.append(_p(f"Model cost for this shipment: US${r.cost_usd:.4f}. Audit chain head at issue: {r.audit_head or 'n/a'}.", small))

    out = io.BytesIO()
    SimpleDocTemplate(out, pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
                      title=f"Pre-submission report {r.shipment_reference}", author="TradeCheck",
                      ).build(story)
    return out.getvalue()
