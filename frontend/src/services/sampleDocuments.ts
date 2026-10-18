import type { ShipmentDocument, ValidationResults } from "@/types";
export async function generateSampleDocument(document: ShipmentDocument, results: ValidationResults): Promise<Blob> {
  const { jsPDF } = await import("jspdf");
  const pdf = new jsPDF({ unit: "pt", format: "a4" });
  const pageCount = Math.max(document.pageCount ?? 1, ...results.matrix.flatMap(field => field.cells.filter(cell => cell.documentId === document.id).map(cell => cell.source?.page ?? 1)));
  for (let page = 1; page <= pageCount; page++) {
    if (page > 1) pdf.addPage();
    pdf.setFontSize(11); pdf.setTextColor(100);
    pdf.text("TRADEGUARD / DEMONSTRATION SOURCE", 30, 24);
    pdf.setFontSize(8);
    pdf.text(document.typeLabel + " | Page " + page + " | Sample content, not a shipping original", 30, 38);
    results.matrix.forEach(field => {
      const cell = field.cells.find(item => item.documentId === document.id);
      if (cell?.source?.page !== page || !cell.source.bbox) return;
      const [x, y, width, height] = cell.source.bbox;
      pdf.setFillColor(248, 250, 252);
      pdf.rect(x * 595.28, y * 841.89, width * 595.28, height * 841.89, "F");
      pdf.setFontSize(6); pdf.setTextColor(100);
      pdf.text(field.label.toUpperCase(), x * 595.28 + 3, y * 841.89 + 7);
      pdf.setFontSize(7); pdf.setTextColor(25);
      pdf.text(pdf.splitTextToSize(cell.rawValue ?? "Unavailable", Math.max(20, width * 595.28 - 6)).slice(0, 2), x * 595.28 + 3, y * 841.89 + 16);
    });
    pdf.setFontSize(9); pdf.setTextColor(110);
    pdf.text("Sample evidence is positioned at the fixture's recorded source coordinates.", 30, 815);
  }
  return pdf.output("blob");
}
