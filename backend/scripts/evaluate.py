"""Evaluation harness (AI-SPEC §15): run classify -> extract -> reconcile over labelled shipments
and report what a panel will ask about. No database; the same AI client and rules as production.

    uv run python samples/generate.py
    AI_MODE=stub   uv run python scripts/evaluate.py                    # harness sanity check
    AI_MODE=vertex GCP_PROJECT=aibuildercup-512008 uv run python scripts/evaluate.py
    ... --extra eval/photographed                                       # real photos, reported separately

Ground truth for the generated scenarios comes from samples/generate.py itself. Expected verdicts
are what the deterministic reconciler returns on the TRUE values, so a verdict error is always an
extraction or classification error, never a rules disagreement.

An --extra directory holds real scans or photos plus a labels.json:
    {"shipment": "photographed_bl",
     "documents": {"bl_photo.jpg": {"doc_type": "BILL_OF_LADING", "fields": {"gross_weight": "520 kg", ...}}}}

Reported separately, never blended (§15.2):
  false agreement  labelled DISAGREE, reported AGREE / AGREE_AT_HS_ROOT / TOLERANCE_MATCH  (dangerous)
  false alarm      labelled agree, reported DISAGREE                                        (costs 30 s)
Writes eval/out/<timestamp>-<mode>.jsonl and .md."""

import argparse
import asyncio
import importlib.util
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from ai_harness import AGREE_FAMILY, ROOT, cells, cost_usd, get_ai_client, get_settings, load, primaries

from app.domain.enums import CellStatus
from app.domain.fields import applicable_fields
from app.errors import AppError
from app.schemas import ai
from app.services import rules

_LINE_H, _TOP = 0.0215, 0.0855   # samples/generate.py layout, as in app/services/ai_stub.py


def _generator():
    spec = importlib.util.spec_from_file_location("generate", ROOT / "samples" / "generate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def synthetic_shipments() -> list[dict]:
    """[{name, split, files: [{path, doc_type, fields{key: raw}, lines{key: line index}}]}] from the generator."""
    gen = _generator()
    by_filename = {v: k for k, v in gen.FILENAMES.items()}
    out = []
    for name in [*gen.SCENARIOS, "corrupt_and_protected"]:
        folder = gen.OUT / name
        docs = gen.SCENARIOS.get(name, {t: gen.BASE[t] for t in ("COMMERCIAL INVOICE", "PACKING LIST")})
        files = []
        for path in sorted(folder.glob("*.pdf")):
            title = by_filename.get(path.name)
            if path.name == "commercial_invoice_revised.pdf":   # written by generate.main for duplicate_doc_type
                title, labelled = "COMMERCIAL INVOICE", dict(gen.BASE["COMMERCIAL INVOICE"], **{"Invoice number": "INV-2026-0141-R1"})
            elif title in docs:
                labelled = docs[title]
            else:
                files.append({"path": path, "doc_type": None, "fields": {}, "lines": {}})   # corrupt / protected
                continue
            fields, lines = {}, {}
            for i, (label, value) in enumerate(labelled.items(), start=1):
                key = rules.LABEL_TO_FIELD.get(label.casefold())
                if key:
                    fields[key], lines[key] = value, i
            # "Quantity: 100 PCS" prints the unit of measure too, so it is ground truth for quantity_uom.
            unit = rules.normalise("quantity", fields["quantity"])[1] if "quantity" in fields else None
            if unit and "quantity_uom" not in fields:
                fields["quantity_uom"], lines["quantity_uom"] = unit, lines["quantity"]
            files.append({"path": path, "doc_type": title.replace(" ", "_"), "fields": fields, "lines": lines})
        out.append({"name": name, "split": "synthetic", "files": files})
    return out


def extra_shipments(folder: Path) -> list[dict]:
    labels = json.loads((folder / "labels.json").read_text())
    files = [{"path": folder / fn, "doc_type": d["doc_type"], "fields": d["fields"], "lines": {}}
             for fn, d in labels["documents"].items()]
    return [{"name": labels.get("shipment", folder.name), "split": "photographed", "files": files}]


def _norm(key: str, raw: str | None) -> str | None:
    return rules.normalise(key, raw)[0] if raw else None


async def run_shipment(sh: dict, client) -> dict:
    loaded = []
    for i, f in enumerate(sh["files"]):
        loaded.append((f, await load(f["path"], f"doc_{sh['name']}_{i}")))
    usages: list[ai.Usage] = []
    readable = [(f, d) for f, d in loaded if not d.error]
    record = {"shipment": sh["name"], "split": sh["split"], "documents": [], "fields": [], "verdicts": [], "errors": []}

    types: dict[str, str] = {}
    if readable:
        c = await client.classify(ai.ClassifyRequest(request_id="eval", documents=[ai.ClassifyDocumentIn(
            document_id=d.document_id, filename=d.filename, page_count=len(d.pages), pages=d.pages[:1],
            text_layer_excerpt=(d.text_layer or "")[:2000] or None) for _, d in readable]))
        usages += [c.usage] if c.usage else []
        types = {x.document_id: x.doc_type for x in c.documents}
    for f, d in loaded:
        record["documents"].append({"file": d.filename, "true_type": f["doc_type"], "predicted_type": types.get(d.document_id),
                                    "ingest_error": d.error})

    order = [d.document_id for _, d in readable]
    keep = primaries(types, order)
    predicted_cells, true_cells = [], []
    true_types = {d.document_id: f["doc_type"] for f, d in readable if f["doc_type"]}
    keep_true = primaries(true_types, [x for x in order if x in true_types])
    for f, d in readable:
        doc_type = types.get(d.document_id)
        if d.document_id in keep and doc_type:
            try:
                e = await client.extract(ai.ExtractRequest(request_id="eval", document_id=d.document_id, doc_type=doc_type,
                                                           pages=d.pages, text_layer=d.text_layer), d.filename)
            except AppError as exc:
                record["errors"].append({"file": d.filename, "stage": "extract", "code": exc.code.value})
                e = ai.ExtractResponse(request_id="eval", document_id=d.document_id)
            usages.append(e.usage)
            predicted_cells += cells(e, doc_type)
            got = {x.field_key: x for x in e.fields}
            for key in applicable_fields(f["doc_type"]) if f["doc_type"] == doc_type else []:
                truth = _norm(key, f["fields"].get(key))
                x = got.get(key)
                pred = x.normalized_value if x and x.confidence >= get_settings().confidence_floor else None
                line_ok = None
                if x and x.provenance.bbox and key in f["lines"]:
                    y_mid = (x.provenance.bbox[1] + x.provenance.bbox[3]) / 2
                    expected = _TOP + f["lines"][key] * _LINE_H - 0.0045
                    line_ok = abs(y_mid - expected) <= _LINE_H * 0.75
                record["fields"].append({"file": d.filename, "field": key, "truth": truth, "predicted": pred,
                                         "confidence": x.confidence if x else None, "page": x.provenance.page if x else None,
                                         "line_ok": line_ok})
        if d.document_id in keep_true:
            for key in applicable_fields(f["doc_type"]):
                raw = f["fields"].get(key)
                true_cells.append(ai.ReconcileFieldIn(
                    document_id=d.document_id, field_key=key, raw_value=raw, normalized_value=_norm(key, raw), normalized_unit=None,
                    confidence=1.0 if raw else 0.0, cell_status=CellStatus.PRESENT if raw else CellStatus.ABSENT))

    def verdicts(docs: dict[str, str], keep_ids: set[str], cs: list) -> dict[str, str]:
        r = rules.reconcile(ai.ReconcileRequest(request_id="eval", shipment_id=sh["name"], fields=cs, documents=[
            ai.ReconcileDocumentIn(document_id=i, doc_type=t) for i, t in docs.items() if i in keep_ids]))
        return {v.field_key: v.verdict for v in r.verdicts}

    expected = verdicts(true_types, keep_true, true_cells)
    got = verdicts(types, keep, predicted_cells)
    for key, want in expected.items():
        record["verdicts"].append({"field": key, "expected": want, "predicted": got.get(key)})
    record["input_tokens"] = sum(u.input_tokens for u in usages)
    record["output_tokens"] = sum(u.output_tokens for u in usages)
    record["cost_usd"] = round(sum(cost_usd(u) for u in usages), 6)
    return record


def summarise(records: list[dict], mode: str, model: str) -> str:
    lines = [f"# Evaluation: AI_MODE={mode}, model {model}", "", f"Run {datetime.now(UTC).isoformat(timespec='seconds')}.", ""]
    for split in ("synthetic", "photographed"):
        rs = [r for r in records if r["split"] == split]
        if not rs:
            continue
        docs = [d for r in rs for d in r["documents"] if d["true_type"]]
        type_ok = sum(d["true_type"] == d["predicted_type"] for d in docs)
        fields = [f for r in rs for f in r["fields"] if f["truth"] is not None]
        correct = sum(f["predicted"] == f["truth"] for f in fields)
        missed = sum(f["predicted"] is None for f in fields)
        spurious = sum(1 for r in rs for f in r["fields"] if f["truth"] is None and f["predicted"] is not None)
        lined = [f for r in rs for f in r["fields"] if f["line_ok"] is not None]
        vs = [v for r in rs for v in r["verdicts"] if v["expected"] != "NOT_APPLICABLE"]
        disagree = [v for v in vs if v["expected"] == "DISAGREE"]
        agree = [v for v in vs if v["expected"] in AGREE_FAMILY]
        false_agreement = sum(v["predicted"] in AGREE_FAMILY for v in disagree)
        false_alarm = sum(v["predicted"] == "DISAGREE" for v in agree)
        per_field = defaultdict(Counter)
        for f in fields:
            per_field[f["field"]]["ok" if f["predicted"] == f["truth"] else ("missed" if f["predicted"] is None else "wrong")] += 1
        pct = lambda n, d: f"{100 * n / d:.1f}% ({n}/{d})" if d else "n/a"  # noqa: E731
        cost = sum(r["cost_usd"] for r in rs)
        lines += [
            f"## {split.title()} ({len(rs)} shipments)", "",
            "| Metric | Value |", "|---|---|",
            f"| Document type accuracy | {pct(type_ok, len(docs))} |",
            f"| Field extraction exact (normalised) | {pct(correct, len(fields))} |",
            f"| Fields missed (absent, unreadable or below confidence floor) | {pct(missed, len(fields))} |",
            f"| Spurious values (field not printed, value reported) | {spurious} |",
            f"| Provenance on the correct printed line | {pct(sum(f['line_ok'] for f in lined), len(lined))} |",
            f"| Verdict accuracy | {pct(sum(v['expected'] == v['predicted'] for v in vs), len(vs))} |",
            f"| **False agreement** (labelled DISAGREE, reported agree) | **{pct(false_agreement, len(disagree))}** |",
            f"| False alarm (labelled agree, reported DISAGREE) | {pct(false_alarm, len(agree))} |",
            f"| Tokens per shipment (in / out) | {sum(r['input_tokens'] for r in rs) // len(rs)} / {sum(r['output_tokens'] for r in rs) // len(rs)} |",
            f"| Model cost per shipment | US${cost / len(rs):.4f} |",
            "",
            "| Field | ok | wrong | missed |", "|---|---|---|---|",
            *[f"| {k} | {c['ok']} | {c['wrong']} | {c['missed']} |" for k, c in sorted(per_field.items())],
            "",
        ]
        errors = [e for r in rs for e in r["errors"]]
        if errors:
            lines += ["Errors: " + "; ".join(f"{e['file']} {e['stage']} {e['code']}" for e in errors), ""]
    return "\n".join(lines)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extra", action="append", default=[], help="folder of real scans/photos with labels.json")
    ap.add_argument("--only", help="comma-separated scenario names")
    a = ap.parse_args()
    s = get_settings()
    if not (ROOT / "samples" / "out").exists():
        print("Run `uv run python samples/generate.py` first.", file=sys.stderr)
        return 2
    shipments = synthetic_shipments() + [x for d in a.extra for x in extra_shipments(Path(d))]
    if a.only:
        shipments = [x for x in shipments if x["name"] in a.only.split(",")]
    client = get_ai_client()
    records = []
    for sh in shipments:
        t0 = time.monotonic()
        records.append(await run_shipment(sh, client))
        print(f"  {sh['split']:12} {sh['name']:28} {time.monotonic() - t0:5.1f}s", file=sys.stderr)
    model = s.gemini_model if s.ai_mode == "vertex" else s.ai_mode
    out = ROOT / "eval" / "out"
    out.mkdir(parents=True, exist_ok=True)
    stem = out / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{s.ai_mode}"
    stem.with_suffix(".jsonl").write_text("".join(json.dumps(r, default=str) + "\n" for r in records))
    report = summarise(records, s.ai_mode, model)
    stem.with_suffix(".md").write_text(report)
    print(report)
    print(f"\nwrote {stem}.jsonl and .md", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
