import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Document, Page, pdfjs } from "react-pdf";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut, Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { shipmentService, USE_MOCK } from "@/services/shipmentService";
import type { SourceEvidence } from "@/types";
pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

export function DocumentViewer({ documentId, filename, source }: { documentId: string; filename: string; source?: SourceEvidence | null }) {
  const { data: blob, error, isLoading, refetch } = useQuery({ queryKey: ["document-content", documentId], queryFn: () => shipmentService.getDocumentContent(documentId), staleTime: Infinity });
  const [url, setUrl] = useState("");
  const [page, setPage] = useState(source?.page ?? 1);
  const [pages, setPages] = useState(1);
  const [zoom, setZoom] = useState(0.65);
  const [renderError, setRenderError] = useState("");
  useEffect(() => {
    if (!blob) return;
    const next = URL.createObjectURL(blob); setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [blob]);
  useEffect(() => { setPage(source?.page ?? 1); setRenderError(""); }, [documentId, source?.page, source?.excerpt]);
  const isImage = /\.(png|jpe?g)$/i.test(filename);
  const isPdf = /\.pdf$/i.test(filename);
  const isSample = USE_MOCK && /^doc-00\d[a-z]$/.test(documentId);
  const highlight = source?.bbox && source.page === page && (!USE_MOCK || isSample);
  return <div className="flex min-w-0 h-full flex-col rounded-lg border overflow-hidden">
    <div className="flex flex-wrap items-center gap-1 border-b bg-background px-2 py-2">
      <p className="min-w-0 flex-1 truncate text-xs font-medium" title={filename}>{filename}</p>
      <Button variant="ghost" size="icon-sm" aria-label="Zoom out" onClick={() => setZoom(value => Math.max(0.35, value - 0.1))}><ZoomOut /></Button>
      <span className="text-[10px] w-8">{Math.round(zoom * 100)}%</span>
      <Button variant="ghost" size="icon-sm" aria-label="Zoom in" onClick={() => setZoom(value => Math.min(2, value + 0.1))}><ZoomIn /></Button>
      {url && <Button variant="ghost" size="icon-sm" asChild><a href={url} download={filename} aria-label="Download original"><Download /></a></Button>}
    </div>
    <div className="flex-1 overflow-auto bg-slate-100 p-3 dark:bg-slate-900 min-h-[360px]">
      {isLoading && <p className="text-sm text-muted-foreground">Loading document…</p>}
      {error && <div role="alert" className="text-sm text-destructive">{error.message}<Button variant="outline" size="sm" onClick={() => refetch()}>Retry</Button></div>}
      {renderError && <p role="alert" className="text-sm text-destructive">{renderError} Download the original to inspect it.</p>}
      {url && isPdf && <Document file={url} onLoadSuccess={({ numPages }) => { setPages(numPages); setPage(value => Math.min(value, numPages)); }} onLoadError={() => setRenderError("This PDF could not be opened.")} loading={<p className="text-sm">Opening PDF…</p>}>
        <div className="relative mx-auto w-fit bg-white shadow-sm">
          <Page pageNumber={page} width={Math.round(595 * zoom)} renderTextLayer={false} renderAnnotationLayer={false} />
          {highlight && source?.bbox && <div aria-label="Source evidence region" className="absolute border-2 border-amber-500 bg-amber-300/25 pointer-events-none" style={{ left: source.bbox[0] * 100 + "%", top: source.bbox[1] * 100 + "%", width: source.bbox[2] * 100 + "%", height: source.bbox[3] * 100 + "%" }} />}
        </div>
      </Document>}
      {url && isImage && <div className="relative mx-auto w-fit"><img src={url} alt={filename} style={{ width: 595 * zoom, maxWidth: "none" }} className="bg-white" />{highlight && source?.bbox && <div aria-label="Source evidence region" className="absolute border-2 border-amber-500 bg-amber-300/25 pointer-events-none" style={{ left: source.bbox[0] * 100 + "%", top: source.bbox[1] * 100 + "%", width: source.bbox[2] * 100 + "%", height: source.bbox[3] * 100 + "%" }} />}</div>}
      {url && !isPdf && !isImage && <p className="text-sm text-muted-foreground">Spreadsheet preview is unavailable. Download the original workbook to inspect its sheets and cells.</p>}
    </div>
    <div className="flex items-center justify-between border-t px-2 py-2">
      <Button size="icon-sm" variant="ghost" aria-label="Previous page" disabled={page <= 1} onClick={() => setPage(value => value - 1)}><ChevronLeft /></Button>
      <span className="text-xs text-muted-foreground">Page {page} of {pages}</span>
      <Button size="icon-sm" variant="ghost" aria-label="Next page" disabled={page >= pages} onClick={() => setPage(value => value + 1)}><ChevronRight /></Button>
    </div>
    {USE_MOCK && <p className="border-t p-2 text-[10px] text-muted-foreground">{isSample ? "Generated sample PDF. Highlight shows the predefined evidence location." : "Your original local file. Demo values are predefined and were not extracted from this file."}</p>}
  </div>;
}
