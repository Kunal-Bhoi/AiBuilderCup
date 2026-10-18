import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Document, Page, pdfjs } from "react-pdf";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut, Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { realService, shipmentService, USE_MOCK } from "@/services/shipmentService";
import type { SourceEvidence } from "@/types";
pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

function LocalDocumentViewer({ documentId, filename, source }: { documentId: string; filename: string; source?: SourceEvidence | null }) {
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

export function DocumentViewer(props: { documentId: string; filename: string; pageCount?: number; source?: SourceEvidence | null }) {
  return USE_MOCK ? <LocalDocumentViewer {...props} /> : <BackendDocumentViewer key={props.documentId} {...props} />;
}
function BackendDocumentViewer({ documentId, filename, source, pageCount = 0 }: { documentId: string; filename: string; pageCount?: number; source?: SourceEvidence | null }) {
  const [page, setPage] = useState(source?.pageKnown === false ? 1 : source?.page ?? 1);
  const [zoom, setZoom] = useState(0.75);
  const [imageError, setImageError] = useState(false);
  const pages = Math.max(0, pageCount);
  const { data, error, isLoading, refetch } = useQuery({ queryKey: ["document-page", documentId, page], queryFn: () => realService.getDocumentPage(documentId, page), enabled: pages > 0, staleTime: 60000, refetchInterval: query => query.state.data ? Math.max(1000, new Date(query.state.data.expires_at).getTime() - Date.now() - 30000) : false });
  useEffect(() => { setPage(Math.min(Math.max(1, source?.pageKnown === false ? 1 : source?.page ?? 1), pages || 1)); }, [source?.page, source?.pageKnown, source?.excerpt, pages]);
  useEffect(() => { setImageError(false); }, [data?.url]);
  const box = source?.pageKnown !== false && source?.page === page ? source.bbox : null;
  return <div className="flex h-full min-w-0 flex-col overflow-hidden rounded-lg border">
    <div className="flex flex-wrap items-center gap-1 border-b p-2"><p className="min-w-0 flex-1 truncate text-xs font-medium" title={filename}>{filename}</p><Button size="icon-sm" variant="ghost" aria-label="Zoom out" onClick={() => setZoom(value => Math.max(0.35, value - 0.1))}><ZoomOut /></Button><span className="text-[10px]">{Math.round(zoom * 100)}%</span><Button size="icon-sm" variant="ghost" aria-label="Zoom in" onClick={() => setZoom(value => Math.min(2, value + 0.1))}><ZoomIn /></Button></div>
    <div className="min-h-[320px] flex-1 overflow-auto bg-slate-100 p-3 dark:bg-slate-900">
      {!pages && <p className="p-4 text-sm text-muted-foreground">Pages are not available yet. Start analysis to render this document. Failed or unreadable documents may have no preview.</p>}
      {isLoading && <p className="text-sm">Loading page…</p>}
      {(error || imageError) && <div role="alert" className="space-y-3 p-3 text-sm"><p>{error?.message ?? "The page link expired or could not be loaded."}</p><Button variant="outline" size="sm" onClick={() => { setImageError(false); refetch(); }}>Retry preview</Button></div>}
      {data && <div className="relative mx-auto bg-white shadow-sm" style={{ width: 595 * zoom, aspectRatio: data.width_px + " / " + data.height_px }}><img src={data.url} alt={filename + " page " + page} className="block h-full w-full" onError={() => setImageError(true)} />{box && <div aria-label="Source evidence region" className="pointer-events-none absolute border-2 border-amber-500 bg-amber-300/25" style={{ left: box[0] * 100 + "%", top: box[1] * 100 + "%", width: box[2] * 100 + "%", height: box[3] * 100 + "%" }} />}</div>}
    </div><div className="flex items-center justify-between border-t p-2"><Button size="icon-sm" variant="ghost" aria-label="Previous page" disabled={page <= 1} onClick={() => setPage(value => value - 1)}><ChevronLeft /></Button><span className="text-xs text-muted-foreground">{pages ? `Page ${page} of ${pages}` : "No rendered pages"}</span><Button size="icon-sm" variant="ghost" aria-label="Next page" disabled={page >= pages} onClick={() => setPage(value => value + 1)}><ChevronRight /></Button></div><p className="border-t p-2 text-[10px] text-muted-foreground">Server-rendered original page. Highlights use the recorded source region.</p>
  </div>;
}
