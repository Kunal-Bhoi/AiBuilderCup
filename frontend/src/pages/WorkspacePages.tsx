import { useState } from "react";
import { Link } from "react-router-dom";
import { FileText, ExternalLink } from "lucide-react";
import { useDocumentLibrary } from "@/hooks/useShipments";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { DocumentViewer } from "@/components/documents/DocumentViewer";
import { ErrorState } from "@/components/ui/error-state";
import { USE_MOCK } from "@/services/shipmentService";
import { mockShipmentService } from "@/services/mockShipmentService";
import { API_BASE_URL } from "@/services/config";
import { getSession, saveRole, type Role } from "@/services/session";
import { apiClient } from "@/services/api";
import { useQuery } from "@tanstack/react-query";
import { canEditDocuments } from "@/lib/workflow";
import { formatBytes } from "@/lib/utils";
export function DocumentsPage() {
  const { data, error, isLoading, refetch } = useDocumentLibrary();
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<{ id: string; filename: string; pageCount?: number } | null>(null);
  const documents = (data ?? []).filter(doc => (doc.filename + doc.shipment.reference).toLowerCase().includes(search.toLowerCase()));
  if (error) return <ErrorState error={error} retry={() => refetch()} />;
  return <div className="p-6 space-y-6"><div><h1 className="text-2xl font-semibold">Documents</h1><p className="text-sm text-muted-foreground mt-1">Original files across your shipments.</p></div><Input aria-label="Search documents" placeholder="Search filename or shipment reference…" value={search} onChange={e => setSearch(e.target.value)} className="max-w-md" /><Card><CardContent className="pt-6">{isLoading ? <p>Loading documents…</p> : documents.length === 0 ? <p className="text-sm text-muted-foreground">No documents found. Add documents to a shipment to get started.</p> : <div className="divide-y">{documents.map(doc => <div key={doc.id} className="flex flex-wrap items-center gap-3 py-3"><FileText className="h-5 w-5 text-primary" /><div className="min-w-0 flex-1"><p className="break-all text-sm font-medium">{doc.filename}</p><Link className="text-xs text-primary" to={"/shipments/" + doc.shipment.id + (canEditDocuments(doc.shipment.status) ? "/edit" : "/processing")}>{doc.shipment.reference} · {formatBytes(doc.sizeBytes)} · {doc.typeLabel}</Link></div><Button variant="outline" size="sm" onClick={() => setSelected(doc)}>Preview<ExternalLink /></Button></div>)}</div>}</CardContent></Card><Dialog open={!!selected} onOpenChange={open => !open && setSelected(null)}><DialogContent className="max-w-3xl"><DialogHeader><DialogTitle>Original document</DialogTitle><DialogDescription>View the document stored for this shipment.</DialogDescription></DialogHeader>{selected && <div className="h-[65vh]"><DocumentViewer documentId={selected.id} filename={selected.filename} pageCount={selected.pageCount ?? 0} /></div>}</DialogContent></Dialog></div>;
}
export function SettingsPage() {
  const session = getSession();
  const [confirm, setConfirm] = useState(false);
  const [role, setRole] = useState<Role>(session.role);
  const health = useQuery({ queryKey: ["backend-health"], queryFn: async () => (await apiClient.get<{ status: string }>("/health")).data, enabled: !USE_MOCK, retry: false });
  return <div className="mx-auto max-w-3xl p-6 space-y-6"><h1 className="text-2xl font-semibold">Settings</h1>
    <Card><CardHeader><CardTitle>Workspace connection</CardTitle></CardHeader><CardContent className="space-y-3 text-sm"><p>Mode: <strong>{USE_MOCK ? "Local demo" : "Backend connection"}</strong></p><p className="break-all">API address: {API_BASE_URL}</p>{!USE_MOCK && <div><p role="status">Server: {health.isLoading ? "Checking…" : health.error ? "Unavailable" : health.data?.status}</p>{health.error && <p className="text-xs text-destructive">{health.error.message}</p>}<Button size="sm" variant="outline" className="mt-2" onClick={() => health.refetch()}>Check connection</Button></div>}<p className="text-muted-foreground">Use the moon or sun button in the header to change the theme.</p></CardContent></Card>
    {!USE_MOCK && <Card><CardHeader><CardTitle>Review role</CardTitle></CardHeader><CardContent><form className="space-y-4" onSubmit={event => { event.preventDefault(); saveRole(role); window.location.assign("/dashboard"); }}>
      <p className="text-xs text-muted-foreground">No sign-in is needed. Choose the role to work as: approvers and owners record decisions and issue reports; viewers can only read. The server enforces the role.</p>
      <div><label htmlFor="review-role" className="text-sm font-medium">Review role</label><select id="review-role" value={role} onChange={e => setRole(e.target.value as Role)} className="ml-3 h-9 rounded border bg-background px-2"><option>VIEWER</option><option>APPROVER</option><option>OWNER</option></select></div>
      <Button type="submit">Apply role</Button>
    </form></CardContent></Card>}
    {USE_MOCK && <Card><CardHeader><CardTitle>Demo data</CardTitle></CardHeader><CardContent><p className="mb-3 text-sm text-muted-foreground">Demo records are local to this browser. They are not sent to the backend.</p><Button variant="destructive" onClick={() => setConfirm(true)}>Reset demo shipments</Button></CardContent></Card>}
    <Dialog open={confirm} onOpenChange={setConfirm}><DialogContent><DialogHeader><DialogTitle>Reset demo shipments?</DialogTitle><DialogDescription>This restores sample shipment records and review decisions. Stored local file contents remain in this browser.</DialogDescription></DialogHeader><DialogFooter><Button variant="outline" onClick={() => setConfirm(false)}>Cancel</Button><Button variant="destructive" onClick={() => mockShipmentService.resetStore()}>Reset demo</Button></DialogFooter></DialogContent></Dialog>
  </div>;
}
export function HelpPage() {
  return <div className="mx-auto max-w-3xl p-6 space-y-6"><h1 className="text-2xl font-semibold">Help & documentation</h1><Card><CardHeader><CardTitle>Your review workflow</CardTitle></CardHeader><CardContent className="space-y-4 text-sm">{["Create a shipment with a unique reference. Routing and preference details are read from source documents.", "Add PDFs, images, or spreadsheets. In demo mode, use the sample PDF button. Save documents to preview or replace them before validation.", "Start validation. Progress follows the backend run and can be reopened after a reload.", "Open the results table. Documents are rows, fields are columns. Select any value to inspect its evidence or related finding.", "Review every finding. Accept a suggestion, override a value with a verified source, flag for follow-up, or dismiss a finding with a reason.", "Issue the server-signed report once every finding has a decision, then download or print it. Follow-up issues may still need correction."].map((step, i) => <p key={step}><span className="mr-2 font-semibold text-primary">{i + 1}.</span>{step}</p>)}</CardContent></Card><Card><CardHeader><CardTitle>Understanding results</CardTitle></CardHeader><CardContent className="space-y-3 text-sm"><p><strong>Match:</strong> readable values agree across at least two sources.</p><p><strong>Mismatch:</strong> source documents contain conflicting values.</p><p><strong>Cannot verify:</strong> information is missing, uncertain, or has insufficient supporting evidence.</p><p><strong>Not checked:</strong> this field is outside the current checks. <strong>Not applicable:</strong> this comparison does not apply.</p><p className="text-muted-foreground">TradeGuard supports an accountable customs professional. It does not submit customs filings. Demo PDFs and results are examples and do not establish the contents of your own uploaded files.</p></CardContent></Card></div>;
}
