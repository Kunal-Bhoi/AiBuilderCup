import { useCallback, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useDropzone, type FileRejection } from "react-dropzone";
import { Upload, FileText, X, ArrowRight, Loader2, Eye } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { ErrorState } from "@/components/ui/error-state";
import { DocumentViewer } from "@/components/documents/DocumentViewer";
import { useCreateShipment, useShipment, useUploadDocuments, useStartValidation, useRemoveDocument } from "@/hooks/useShipments";
import { USE_MOCK } from "@/services/shipmentService";
import { generateSampleDocument } from "@/services/sampleDocuments";
import { MOCK_SHIPMENTS, MOCK_VALIDATION_RESULTS } from "@/mocks/fixtures";
import { formatBytes } from "@/lib/utils";
const COUNTRIES = ["Australia", "Brazil", "Canada", "China", "France", "Germany", "India", "Japan", "Netherlands", "Singapore", "South Korea", "United Kingdom", "United States", "Vietnam"];
interface SelectedFile { id: string; file: File; error?: string }
export default function CreateShipmentPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data: shipment, error: loadError, refetch } = useShipment(id ?? "");
  const create = useCreateShipment();
  const upload = useUploadDocuments(id ?? "");
  const start = useStartValidation(id ?? "");
  const remove = useRemoveDocument(id ?? "");
  const [reference, setReference] = useState(() => "TG-" + new Date().getFullYear() + "-" + crypto.randomUUID().slice(0, 6).toUpperCase());
  const [origin, setOrigin] = useState("");
  const [destination, setDestination] = useState("");
  const [duty, setDuty] = useState(false);
  const [files, setFiles] = useState<SelectedFile[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [activeFile, setActiveFile] = useState("");
  const [preview, setPreview] = useState<{ id: string; filename: string } | null>(null);
  const onDrop = useCallback((accepted: File[], rejected: FileRejection[]) => {
    setFiles(previous => [...previous, ...accepted.map(file => ({ id: crypto.randomUUID(), file, error: file.size === 0 ? "File is empty" : undefined })), ...rejected.map(item => ({ id: crypto.randomUUID(), file: item.file, error: item.errors.map(e => e.message).join(". ") }))]);
  }, []);
  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop, disabled: busy, maxSize: 20 * 1024 * 1024, accept: { "application/pdf": [".pdf"], "image/png": [".png"], "image/jpeg": [".jpg", ".jpeg"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"] } });
  const run = async (validate: boolean, leave = false) => {
    setBusy(true); setError("");
    try {
      for (const entry of files.filter(item => !item.error)) {
        setActiveFile(entry.id);
        await upload.mutateAsync([entry.file]);
        setFiles(previous => previous.filter(item => item.id !== entry.id));
      }
      setActiveFile("");
      if (leave) navigate("/dashboard");
      if (validate) { await start.mutateAsync(); navigate("/shipments/" + id + "/processing"); }
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to save documents."); }
    finally { setBusy(false); setActiveFile(""); }
  };
  const addSamples = async () => {
    setBusy(true);
    try { onDrop(await Promise.all(MOCK_SHIPMENTS[0].documents.map(async document => new File([await generateSampleDocument(document, MOCK_VALIDATION_RESULTS)], document.filename, { type: "application/pdf" }))), []); }
    catch { setError("Unable to prepare sample documents."); } finally { setBusy(false); }
  };
  if (loadError) return <ErrorState error={loadError} retry={() => refetch()} />;
  if (id && !shipment) return <p className="p-6">Loading shipment...</p>;
  if (shipment && !["draft", "failed"].includes(shipment.status)) return <div className="p-6"><p>This shipment has already started validation.</p><Button className="mt-4" onClick={() => navigate("/shipments/" + id + "/processing")}>Open shipment</Button></div>;
  return <div className="mx-auto max-w-3xl p-6 space-y-6 animate-fade-in-up">
    <div><p className="text-xs font-medium uppercase tracking-widest text-primary">Shipment workspace</p><h1 className="mt-2 text-2xl font-semibold">{id ? "Add shipment documents" : "New Shipment"}</h1><p className="mt-1 text-sm text-muted-foreground">{shipment ? shipment.reference + " | " + shipment.originCountry + " to " + shipment.destinationCountry : "Create a shipment, add documents, and prepare for review."}</p></div>
    {!id ? <Card><CardHeader><CardTitle>Shipment details</CardTitle><CardDescription>Start with your reference and shipping route.</CardDescription></CardHeader><CardContent><form className="space-y-5" onSubmit={async event => { event.preventDefault(); setError(""); try { const created = await create.mutateAsync({ reference, originCountry: origin, destinationCountry: destination, preferentialDutyClaim: duty }); navigate("/shipments/" + created.id + "/edit"); } catch (e) { setError(e instanceof Error ? e.message : "Unable to create shipment."); } }}>
      <div><label htmlFor="reference" className="text-sm font-medium">Shipment reference</label><Input className="mt-2" id="reference" value={reference} onChange={e => setReference(e.target.value)} required maxLength={100} /></div>
      <div className="grid gap-4 sm:grid-cols-2">{[{ label: "Origin country", value: origin, set: setOrigin }, { label: "Destination country", value: destination, set: setDestination }].map(item => <div key={item.label}><label className="text-sm font-medium" htmlFor={item.label}>{item.label}</label><select required id={item.label} value={item.value} onChange={e => item.set(e.target.value)} className="mt-2 h-10 w-full rounded-md border bg-background px-3 text-sm"><option value="">Select country</option>{COUNTRIES.map(country => <option key={country}>{country}</option>)}</select></div>)}</div>
      <div className="flex gap-3 rounded-lg border p-4"><Switch id="duty" checked={duty} onCheckedChange={setDuty} /><div><label htmlFor="duty" className="text-sm font-medium">Preferential duty claim</label><p className="text-xs text-muted-foreground mt-1">Claim reduced import taxes under a trade agreement. Include a Certificate of Origin.</p></div></div>
      <Button disabled={create.isPending || !reference.trim() || !origin || !destination || origin === destination} type="submit">{create.isPending ? "Creating..." : "Continue to documents"}<ArrowRight /></Button>
    </form></CardContent></Card> : <>
      <Card><CardHeader><CardTitle>Trade documents</CardTitle><CardDescription>PDF, PNG, JPG, or XLSX. Up to 20 MB per file. The future backend classifies documents from their content.</CardDescription></CardHeader><CardContent className="space-y-4">
        <div {...getRootProps()} className={"cursor-pointer rounded-xl border-2 border-dashed p-10 text-center " + (isDragActive ? "border-primary bg-primary/5" : "hover:bg-muted/40")}><input {...getInputProps()} aria-label="Upload trade documents" /><Upload className="mx-auto mb-3 h-8 w-8 text-primary" /><p className="text-sm font-medium">Drop documents here, or click to browse</p><p className="mt-1 text-xs text-muted-foreground">Invoices, packing lists, transport documents, and certificates.</p></div>
        {USE_MOCK && <Button variant="outline" size="sm" disabled={busy} onClick={addSamples}>Use three sample PDFs</Button>}
        {shipment?.documents.map(document => <div key={document.id} className="flex items-center gap-3 rounded-lg border p-3"><FileText className="h-4 w-4 text-primary" /><div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{document.filename}</p><p className="text-xs text-muted-foreground">{formatBytes(document.sizeBytes)} | Saved {USE_MOCK ? "locally" : "to server"} | {document.typeLabel}</p></div><Button variant="ghost" size="icon-sm" aria-label={"Preview " + document.filename} onClick={() => setPreview({ id: document.id, filename: document.filename })}><Eye /></Button><Button variant="ghost" size="icon-sm" aria-label={"Remove " + document.filename} disabled={busy || remove.isPending} onClick={async () => { try { await remove.mutateAsync(document.id) } catch (e) { setError(e instanceof Error ? e.message : "Unable to remove file.") } }}><X /></Button></div>)}
        {files.map(entry => <div key={entry.id} className="rounded-lg border p-3"><div className="flex items-center gap-3"><FileText className="h-4 w-4 text-muted-foreground" /><div className="min-w-0 flex-1"><p className="truncate text-sm">{entry.file.name}</p><p className={"text-xs " + (entry.error ? "text-destructive" : "text-muted-foreground")}>{entry.error ?? formatBytes(entry.file.size) + " | Ready to save"}</p></div><Button variant="ghost" size="icon-sm" aria-label={"Remove " + entry.file.name} disabled={busy} onClick={() => setFiles(previous => previous.filter(item => item.id !== entry.id))}><X /></Button></div>{activeFile === entry.id && <div role="progressbar" aria-label={"Saving " + entry.file.name} className="mt-2 h-1 bg-muted overflow-hidden"><div className="h-full w-2/3 bg-primary animate-pulse" /></div>}</div>)}
      </CardContent></Card>
      <div className="flex flex-wrap items-center justify-between gap-3"><Button variant="outline" onClick={() => run(false, true)} disabled={busy}>Save draft & leave</Button><div className="flex gap-2"><Button variant="outline" disabled={busy || !files.some(file => !file.error)} onClick={() => run(false)}>Save documents</Button><Button disabled={busy || remove.isPending || (!(shipment?.documents.length) && !files.some(file => !file.error)) || files.some(file => !!file.error)} onClick={() => run(true)}>{busy ? <Loader2 className="animate-spin" /> : <ArrowRight />}Start Validation</Button></div></div>
      <Dialog open={!!preview} onOpenChange={open => !open && setPreview(null)}><DialogContent className="max-w-3xl"><DialogTitle>Document preview</DialogTitle><DialogDescription>Inspect the original document before validation.</DialogDescription>{preview && <div className="h-[65vh]"><DocumentViewer documentId={preview.id} filename={preview.filename} /></div>}</DialogContent></Dialog>
    </>}
    {error && <p role="alert" className="rounded-lg border border-destructive/30 p-3 text-sm text-destructive">{error}</p>}
  </div>;
}
