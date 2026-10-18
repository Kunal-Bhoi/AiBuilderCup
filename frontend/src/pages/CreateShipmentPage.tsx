import { useCallback, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useDropzone, type FileRejection } from "react-dropzone";
import { Upload, FileText, X, ArrowRight, Loader2, Eye } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { ErrorState } from "@/components/ui/error-state";
import { DocumentViewer } from "@/components/documents/DocumentViewer";
import { DocumentTypeSelect } from "@/components/documents/DocumentTypeSelect";
import { useCreateShipment, useShipment, useUploadDocuments, useStartValidation, useRemoveDocument } from "@/hooks/useShipments";
import { USE_MOCK } from "@/services/shipmentService";
import { MAX_FILE_BYTES, MAX_DOCUMENTS } from "@/services/config";
import { canEditDocuments, hasResults } from "@/lib/workflow";
import { generateSampleDocument } from "@/services/sampleDocuments";
import { MOCK_SHIPMENTS, MOCK_VALIDATION_RESULTS } from "@/mocks/fixtures";
import { formatBytes } from "@/lib/utils";
import type { ShipmentDocument } from "@/types";
interface SelectedFile { id: string; file: File; error?: string }
export default function CreateShipmentPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data: shipment, error: loadError, refetch } = useShipment(id ?? "");
  const create = useCreateShipment(), upload = useUploadDocuments(id ?? ""), start = useStartValidation(id ?? ""), remove = useRemoveDocument(id ?? "");
  const [reference, setReference] = useState(() => "TG-" + new Date().getFullYear() + "-" + crypto.randomUUID().slice(0, 6).toUpperCase());
  const [files, setFiles] = useState<SelectedFile[]>([]), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [activeFile, setActiveFile] = useState(""), [progress, setProgress] = useState(0);
  const [preview, setPreview] = useState<ShipmentDocument | null>(null);
  const onDrop = useCallback((accepted: File[], rejected: FileRejection[]) => setFiles(previous => [...previous,
    ...accepted.map(file => ({ id: crypto.randomUUID(), file, error: file.size === 0 ? "File is empty" : undefined })),
    ...rejected.map(item => ({ id: crypto.randomUUID(), file: item.file, error: item.errors.map(e => e.message).join(". ") }))]), []);
  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop, disabled: busy, maxSize: MAX_FILE_BYTES, accept: { "application/pdf": [".pdf"], "image/png": [".png"], "image/jpeg": [".jpg", ".jpeg"], "image/webp": [".webp"], "image/tiff": [".tif", ".tiff"], "image/heic": [".heic"], "image/heif": [".heif"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"] } });
  const selectedCount = files.filter(file => !file.error).length;
  const overLimit = (shipment?.documents.length ?? 0) + selectedCount > MAX_DOCUMENTS;
  const run = async (validate: boolean, leave = false) => {
    setBusy(true); setError("");
    try {
      if (overLimit) throw new Error("A shipment can contain at most 20 documents.");
      for (const entry of files.filter(item => !item.error)) {
        setActiveFile(entry.id); setProgress(0);
        await upload.mutateAsync({ files: [entry.file], onProgress: (_file, percent) => setProgress(percent) });
        setFiles(previous => previous.filter(item => item.id !== entry.id));
      }
      if (leave) navigate("/dashboard");
      if (validate) { await start.mutateAsync(); navigate("/shipments/" + id + "/processing"); }
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to save documents."); await refetch(); }
    finally { setBusy(false); setActiveFile(""); }
  };
  const addSamples = async () => {
    setBusy(true);
    try { onDrop(await Promise.all(MOCK_SHIPMENTS[0].documents.map(async document => new File([await generateSampleDocument(document, MOCK_VALIDATION_RESULTS)], document.filename, { type: "application/pdf" }))), []); }
    catch { setError("Unable to prepare sample documents."); } finally { setBusy(false); }
  };
  if (loadError) return <ErrorState error={loadError} retry={() => refetch()} />;
  if (id && !shipment) return <p className="p-6">Loading shipment…</p>;
  if (shipment && !canEditDocuments(shipment.status)) return <div className="p-6"><p>Documents are locked while processing or after report issue.</p><Button className="mt-4" onClick={() => navigate("/shipments/" + id + (hasResults(shipment.status) ? "/results" : "/processing"))}>Open shipment</Button></div>;
  return <div className="mx-auto max-w-3xl p-6 space-y-6">
    <div><p className="text-xs font-medium uppercase tracking-widest text-primary">Shipment workspace</p><h1 className="mt-2 text-2xl font-semibold">{id ? "Shipment documents" : "New Shipment"}</h1><p className="mt-1 text-sm text-muted-foreground">{shipment?.reference ?? "Create a shipment reference, then add documents for analysis."}</p></div>
    {!id ? <Card><CardHeader><CardTitle>Shipment details</CardTitle><CardDescription>The shipment reference is saved by the server. Country and preference information are read from the documents during analysis.</CardDescription></CardHeader><CardContent><form className="space-y-5" onSubmit={async event => { event.preventDefault(); setError(""); try { const created = await create.mutateAsync({ reference }); navigate("/shipments/" + created.id + "/edit"); } catch (e) { setError(e instanceof Error ? e.message : "Unable to create shipment."); } }}>
      <div><label htmlFor="reference" className="text-sm font-medium">Shipment reference</label><Input className="mt-2" id="reference" value={reference} onChange={e => setReference(e.target.value)} required maxLength={120} /></div>
      <Button disabled={create.isPending || !reference.trim()} type="submit">{create.isPending ? "Creating…" : "Continue to documents"}<ArrowRight /></Button>
    </form></CardContent></Card> : <>
      {hasResults(shipment!.status) && <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">After changing documents or their types, run analysis again before reviewing the updated shipment.</p>}
      <Card><CardHeader><CardTitle>Trade documents</CardTitle><CardDescription>PDF, images, or XLSX. Up to 50 MB per file, 20 documents per shipment. Types are classified from document content; you can correct a type if needed.</CardDescription></CardHeader><CardContent className="space-y-4">
        <div {...getRootProps()} className={"cursor-pointer rounded-xl border-2 border-dashed p-10 text-center " + (isDragActive ? "border-primary bg-primary/5" : "hover:bg-muted/40")}><input {...getInputProps()} aria-label="Upload trade documents" /><Upload className="mx-auto mb-3 h-8 w-8 text-primary" /><p className="text-sm font-medium">Drop documents here, or click to browse</p><p className="mt-1 text-xs text-muted-foreground">Files upload directly to document storage before registration.</p></div>
        {USE_MOCK && <Button variant="outline" size="sm" disabled={busy} onClick={addSamples}>Use three sample PDFs</Button>}
        {shipment?.documents.map(document => <div key={document.id} className="flex items-start gap-3 rounded-lg border p-3"><FileText className="mt-1 h-4 w-4 shrink-0 text-primary" /><div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{document.filename}</p><p className="text-xs text-muted-foreground">{formatBytes(document.sizeBytes)} · {document.backendStatus ?? document.status}{document.errorCode ? " · " + document.errorCode : ""}</p><DocumentTypeSelect shipmentId={id!} document={document} disabled={busy} /></div><Button variant="ghost" size="icon-sm" aria-label={"Preview " + document.filename} onClick={() => setPreview(document)}><Eye /></Button><Button variant="ghost" size="icon-sm" aria-label={"Remove " + document.filename} disabled={busy || remove.isPending} onClick={async () => { try { await remove.mutateAsync(document.id) } catch (e) { setError(e instanceof Error ? e.message : "Unable to remove file.") } }}><X /></Button></div>)}
        {files.map(entry => <div key={entry.id} className="rounded-lg border p-3"><div className="flex items-center gap-3"><FileText className="h-4 w-4 text-muted-foreground" /><div className="min-w-0 flex-1"><p className="truncate text-sm">{entry.file.name}</p><p className={"text-xs " + (entry.error ? "text-destructive" : "text-muted-foreground")}>{entry.error ?? formatBytes(entry.file.size) + (activeFile === entry.id ? " · Uploading " + progress + "%" : " · Ready to save")}</p></div><Button variant="ghost" size="icon-sm" aria-label={"Remove " + entry.file.name} disabled={busy} onClick={() => setFiles(previous => previous.filter(item => item.id !== entry.id))}><X /></Button></div>{activeFile === entry.id && <div role="progressbar" aria-label={"Saving " + entry.file.name} aria-valuenow={progress} className="mt-2 h-1 overflow-hidden bg-muted"><div className="h-full bg-primary transition-all" style={{ width: Math.max(2, progress) + "%" }} /></div>}</div>)}
        {overLimit && <p role="alert" className="text-sm text-destructive">Remove files to stay within the 20-document limit.</p>}
      </CardContent></Card>
      <div className="flex flex-wrap items-center justify-between gap-3"><Button variant="outline" onClick={() => run(false, true)} disabled={busy || overLimit}>Save draft & leave</Button><div className="flex gap-2"><Button variant="outline" disabled={busy || !selectedCount || overLimit} onClick={() => run(false)}>Save documents</Button><Button disabled={busy || remove.isPending || (!shipment?.documents.length && !selectedCount) || files.some(file => !!file.error) || overLimit} onClick={() => run(true)}>{busy ? <Loader2 className="animate-spin" /> : <ArrowRight />}Start Validation</Button></div></div>
      <Dialog open={!!preview} onOpenChange={open => !open && setPreview(null)}><DialogContent className="max-w-3xl"><DialogTitle>Document preview</DialogTitle><DialogDescription>Rendered pages become available after document ingestion.</DialogDescription>{preview && <div className="h-[65vh]"><DocumentViewer documentId={preview.id} filename={preview.filename} pageCount={preview.pageCount ?? 0} /></div>}</DialogContent></Dialog>
    </>}
    {error && <p role="alert" className="rounded-lg border border-destructive/30 p-3 text-sm text-destructive">{error}</p>}
  </div>;
}
