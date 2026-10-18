import { useState } from "react"
import { useParams, useNavigate, useSearchParams } from "react-router-dom"
import {
  ChevronLeft,
  ChevronRight,
  AlertTriangle,
  CheckCircle2,
  MessageSquare,
  RotateCcw,
  FileText,
  ZoomIn,
  ZoomOut,
  ChevronUp,
  ChevronDown,
  Filter,
  ArrowLeft,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import { SeverityBadge, ValidationStatusBadge } from "@/components/ui/status-badges"
import { Skeleton } from "@/components/ui/skeleton"
import { useValidationResults, useReviewFinding, useShipment } from "@/hooks/useShipments"
import { cn, formatDateTime } from "@/lib/utils"
import { DocumentViewer } from "@/components/documents/DocumentViewer"
import { ErrorState } from "@/components/ui/error-state"
import { canReview } from "@/services/session"
import type { Finding, ReviewDecision, ReviewFindingPayload } from "@/types"

const DECISIONS: Record<ReviewDecision, { label: string; description: string }> = {
  ACCEPT_SUGGESTION: { label: "Accept suggestion", description: "Use the suggested source value when one is available." },
  OVERRIDE: { label: "Override value", description: "Choose a source document or enter a corrected value. A reason is required." },
  FLAG_FOR_FOLLOW_UP: { label: "Flag for follow-up", description: "Record a follow-up decision. This does not send a message to the shipper." },
  DISMISS_AS_NOT_AN_ISSUE: { label: "Dismiss as not an issue", description: "Record why this finding is not an issue. A reason is required." },
};
function ReviewDialog({ finding, documents, open, onClose, onSubmit, isPending, error }: {
  finding: Finding | null; documents: { id: string; filename: string }[]; open: boolean; onClose: () => void;
  onSubmit: (payload: ReviewFindingPayload) => void; isPending: boolean; error: Error | null;
}) {
  const [decision, setDecision] = useState<ReviewDecision | null>(null);
  const [reason, setReason] = useState("");
  const [chosenDocumentId, setChosenDocumentId] = useState("");
  const [chosenValue, setChosenValue] = useState("");
  const needsReason = decision === "OVERRIDE" || decision === "DISMISS_AS_NOT_AN_ISSUE";
  const valid = !!decision && (!needsReason || reason.trim().length >= 10) && (decision !== "OVERRIDE" || !!chosenDocumentId || !!chosenValue.trim()) && (decision !== "ACCEPT_SUGGESTION" || finding?.suggestedValue != null);
  return <Dialog open={open} onOpenChange={value => { if (!value && !isPending) onClose(); }}><DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto"><DialogHeader><DialogTitle>Review Finding</DialogTitle><DialogDescription>{finding?.label} · current version {finding?.version ?? 1}</DialogDescription></DialogHeader>
    <div className="space-y-2">{(Object.entries(DECISIONS) as [ReviewDecision, typeof DECISIONS[ReviewDecision]][]).map(([action, config]) => <button key={action} disabled={isPending || (action === "ACCEPT_SUGGESTION" && finding?.suggestedValue == null)} onClick={() => setDecision(action)} className={cn("w-full rounded-lg border p-3 text-left disabled:opacity-40", decision === action && "border-primary bg-primary/5 ring-1 ring-primary")}><p className="text-sm font-semibold">{config.label}</p><p className="mt-1 text-xs text-muted-foreground">{config.description}</p></button>)}</div>
    {decision === "ACCEPT_SUGGESTION" && <p className="rounded-md bg-muted p-3 text-sm">Suggested value: <strong>{finding?.suggestedValue}</strong></p>}
    {decision === "OVERRIDE" && <div className="space-y-3"><div><label className="text-sm font-medium" htmlFor="chosen-document">Source document</label><select id="chosen-document" value={chosenDocumentId} onChange={event => setChosenDocumentId(event.target.value)} className="mt-1 h-9 w-full rounded border bg-background px-2 text-sm"><option value="">Select a source, or enter a corrected value below</option>{documents.map(doc => <option key={doc.id} value={doc.id}>{doc.filename}</option>)}</select></div><div><label className="text-sm font-medium" htmlFor="chosen-value">Corrected value</label><Input id="chosen-value" className="mt-1" value={chosenValue} onChange={event => setChosenValue(event.target.value)} placeholder="Enter the value you verified" /></div></div>}
    {decision && <div><label htmlFor="review-reason" className="text-sm font-medium">{needsReason ? "Reason (at least 10 characters)" : "Notes (optional)"}</label><Textarea id="review-reason" className="mt-1" value={reason} onChange={event => setReason(event.target.value)} rows={3} /></div>}
    {error && <p role="alert" className="rounded border border-destructive/30 p-3 text-sm text-destructive">{error.message} If this finding changed, close this dialog and review the refreshed values before trying again.</p>}
    <DialogFooter><Button variant="outline" disabled={isPending} onClick={onClose}>Cancel</Button><Button disabled={!valid || isPending} onClick={() => decision && onSubmit({ decision, reason: reason.trim() || undefined, chosenDocumentId: chosenDocumentId || undefined, chosenValue: chosenValue.trim() || undefined, expectedVersion: finding?.version ?? 1 })}>{isPending ? "Saving decision…" : "Submit Review"}</Button></DialogFooter>
  </DialogContent></Dialog>;
}

export default function DiscrepancyReviewPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data: results, isLoading, error, refetch } = useValidationResults(id!)
  const { data: shipment } = useShipment(id!)
  const reviewFinding = useReviewFinding(id!)

  const [params] = useSearchParams()
  const [selectedId, setSelectedId] = useState(params.get("finding"))
  const [severityFilter, setSeverityFilter] = useState<string>("all")
  const [reviewDialogOpen, setReviewDialogOpen] = useState(false)
  const [leftId, setLeftId] = useState("")
  const [rightId, setRightId] = useState("")

  const findings = (results?.findings ?? []).filter((f) =>
    severityFilter === "all" || f.severity === severityFilter
  )
  const currentIdx = Math.max(0, findings.findIndex(finding => finding.id === selectedId))
  const setCurrentIdx = (index: number) => setSelectedId(findings[index]?.id ?? null)
  const currentFinding = findings[currentIdx] ?? null

  const handleReview = async (payload: ReviewFindingPayload) => {
    if (!currentFinding) return
    try {
      await reviewFinding.mutateAsync({ findingId: currentFinding.id, payload })
    } catch { return }
    setReviewDialogOpen(false)
    // Auto-advance to next pending
    const nextPendingIdx = findings.findIndex(
      (f, i) => i > currentIdx && f.reviewStatus === "pending"
    )
    if (nextPendingIdx !== -1) setCurrentIdx(nextPendingIdx)
  }

  const pendingCount = findings.filter((f) => f.reviewStatus === "pending").length

  // Find two documents that differ for the current field
  const affectedDocs = currentFinding
    ? (results?.documents ?? []).filter((d) => currentFinding.affectedDocuments.includes(d.id))
    : []
  const doc1 = affectedDocs.find(doc => doc.id === leftId) ?? affectedDocs[0]
  const doc2 = affectedDocs.find(doc => doc.id === rightId && doc.id !== doc1?.id) ?? affectedDocs.find(doc => doc.id !== doc1?.id && currentFinding?.cells?.find(cell => cell.documentId === doc.id)?.rawValue !== currentFinding?.cells?.find(cell => cell.documentId === doc1?.id)?.rawValue) ?? affectedDocs.find(doc => doc.id !== doc1?.id)

  // Get cell values for current finding
  const getCellValue = (docId: string) => {
    if (!currentFinding || !results) return null
    const field = results.matrix.find((m) => m.fieldKey === currentFinding.fieldKey)
    return field?.cells.find((c) => c.documentId === docId) ?? currentFinding.cells?.find(c => c.documentId === docId) ?? null
  }

  if (error) return <ErrorState error={error} retry={() => refetch()} />

  if (isLoading) {
    return (
      <div className="p-6 space-y-4">
        <Skeleton className="h-8 w-64" />
        <div className="grid grid-cols-3 gap-4">
          <Skeleton className="h-[500px]" />
          <Skeleton className="h-[500px]" />
          <Skeleton className="h-[500px]" />
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col min-h-[calc(100vh-56px)]">
      {/* Top bar */}
      <div className="shrink-0 flex flex-wrap gap-3 items-center justify-between border-b px-6 py-3 bg-background">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => navigate(`/shipments/${id}/results`)} className="gap-1.5">
            <ArrowLeft className="h-3.5 w-3.5" /> Results
          </Button>
          <div className="h-4 w-px bg-border" />
          <div>
            <h1 className="text-sm font-semibold">{shipment?.reference} — Discrepancy Review</h1>
            <p className="text-xs text-muted-foreground">{pendingCount} of {findings.length} findings pending</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1">
            <Filter className="h-3.5 w-3.5 text-muted-foreground" />
            {["all", "high", "medium", "low"].map((s) => (
              <button
                key={s}
                onClick={() => { setSeverityFilter(s); setCurrentIdx(0) }}
                className={cn(
                  "px-2 py-0.5 rounded text-xs font-medium transition-colors",
                  severityFilter === s ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:bg-muted/80"
                )}
              >
                {s === "all" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)}
              </button>
            ))}
          </div>
          <Button size="sm" variant="outline" onClick={() => navigate(`/shipments/${id}/report`)} className="gap-1.5">
            View Report <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {findings.length === 0 ? (
        <div className="flex flex-col items-center justify-center flex-1 gap-3">
          <CheckCircle2 className="h-12 w-12 text-green-400" />
          <p className="text-sm font-medium">No findings to review</p>
          <p className="text-xs text-muted-foreground">All findings have been reviewed or there are none for this filter</p>
        </div>
      ) : (
        <div className="flex flex-1 flex-col xl:flex-row min-w-0">
          {/* Finding Navigator */}
          <div className="w-full xl:w-40 shrink-0 border-r overflow-y-auto bg-muted/20 max-h-44 xl:max-h-none">
            <div className="p-3 border-b">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Findings</p>
            </div>
            {findings.map((f, i) => (
              <button
                key={f.id}
                onClick={() => setCurrentIdx(i)}
                className={cn(
                  "w-full text-left px-3 py-2.5 border-b transition-colors",
                  currentIdx === i
                    ? "bg-primary/10 border-l-2 border-l-primary"
                    : "hover:bg-muted/40"
                )}
              >
                <div className="flex items-center justify-between gap-1 mb-0.5">
                  <span className="text-xs font-medium truncate">{f.label}</span>
                  {f.reviewStatus === "reviewed" ? (
                    <CheckCircle2 className="h-3.5 w-3.5 text-green-500 shrink-0" />
                  ) : (
                    <AlertTriangle className="h-3.5 w-3.5 text-amber-500 shrink-0" />
                  )}
                </div>
                <SeverityBadge severity={f.severity} />
              </button>
            ))}
          </div>

          {/* Main Content */}
          {currentFinding ? (
            <div className="flex flex-1 flex-col xl:flex-row min-w-0">
              {/* Doc 1 Viewer */}
              {doc1 && (
                <div className="flex-1 min-w-0 border-r flex flex-col h-[600px]">
                  <select aria-label="Left comparison document" className="h-9 shrink-0 border-b bg-background px-2 text-xs" value={doc1.id} onChange={event => setLeftId(event.target.value)}>{affectedDocs.map(doc => <option key={doc.id} value={doc.id}>{doc.filename}</option>)}</select><DocumentViewer documentId={doc1.id} filename={doc1.filename} pageCount={doc1.pageCount ?? 0} source={getCellValue(doc1.id)?.source} />
                </div>
              )}

              {/* Doc 2 Viewer */}
              {doc2 && (
                <div className="flex-1 min-w-0 border-r flex flex-col h-[600px]">
                  <select aria-label="Right comparison document" className="h-9 shrink-0 border-b bg-background px-2 text-xs" value={doc2.id} onChange={event => setRightId(event.target.value)}>{affectedDocs.filter(doc => doc.id !== doc1?.id).map(doc => <option key={doc.id} value={doc.id}>{doc.filename}</option>)}</select><DocumentViewer documentId={doc2.id} filename={doc2.filename} pageCount={doc2.pageCount ?? 0} source={getCellValue(doc2.id)?.source} />
                </div>
              )}

              {/* Right Panel: Finding details & review actions */}
              <div className="w-full xl:w-80 shrink-0 flex flex-col">
                <div className="flex-1 overflow-y-auto p-4 space-y-4">
                  {/* Finding header */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <p className="text-xs text-muted-foreground font-medium">Finding {currentIdx + 1} of {findings.length}</p>
                      <div className="flex gap-1">
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          onClick={() => setCurrentIdx(Math.max(0, currentIdx - 1))}
                          disabled={currentIdx === 0}
                        >
                          <ChevronLeft className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          onClick={() => setCurrentIdx(Math.min(findings.length - 1, currentIdx + 1))}
                          disabled={currentIdx === findings.length - 1}
                        >
                          <ChevronRight className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </div>

                    <h2 className="text-base font-semibold">{currentFinding.label}</h2>
                    <div className="flex flex-wrap gap-1.5">
                      <ValidationStatusBadge status={currentFinding.status} />
                      <SeverityBadge severity={currentFinding.severity} />
                      {currentFinding.reviewStatus === "reviewed" && (
                        <Badge variant="success" className="gap-1">
                          <CheckCircle2 className="h-2.5 w-2.5" /> Reviewed
                        </Badge>
                      )}
                    </div>
                  </div>

                  {/* Conflicting values */}
                  <div className="space-y-2">
                    <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Conflicting Values</p>
                    {affectedDocs.map((doc) => {
                      const cell = getCellValue(doc.id)
                      return (
                        <div key={doc.id} className="rounded-md border p-2.5 space-y-1">
                          <div className="flex items-center gap-1.5">
                            <FileText className="h-3 w-3 text-muted-foreground" />
                            <span className="text-xs font-medium">{doc.typeLabel}</span>
                            {cell?.source?.confidence != null && (
                              <span className="text-[10px] text-muted-foreground ml-auto">
                                {Math.round(cell.source.confidence * 100)}% conf.
                              </span>
                            )}
                          </div>
                          <p className={cn(
                            "text-sm font-mono font-medium",
                            !cell?.rawValue && "text-muted-foreground italic"
                          )}>
                            {cell?.rawValue ?? "Not found"}
                          </p>
                          {cell?.source?.excerpt && (
                            <p className="text-[10px] text-muted-foreground italic">
                              "{cell.source.excerpt}"
                            </p>
                          )}
                        </div>
                      )
                    })}
                  </div>

                  {/* AI Explanation */}
                  <div className="rounded-lg border bg-muted/20 p-3 space-y-1.5">
                    <p className="text-xs font-semibold text-muted-foreground">AI Explanation</p>
                    <p className="text-xs leading-relaxed">{currentFinding.explanation}</p>
                  </div>

                  {/* Suggestion */}
                  {currentFinding.suggestion && (
                    <div className="rounded-lg border border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950 p-3 space-y-1.5">
                      <p className="text-xs font-semibold text-amber-700 dark:text-amber-300">Suggested Action</p>
                      <p className="text-xs leading-relaxed text-amber-800 dark:text-amber-200">{currentFinding.suggestion}</p>
                    </div>
                  )}

                  {/* Reviewed action */}
                  {currentFinding.reviewStatus === "reviewed" && currentFinding.reviewAction && (
                    <div className="rounded-lg border border-green-200 bg-green-50 dark:border-green-800 dark:bg-green-950 p-3 space-y-1.5">
                      <p className="text-xs font-semibold text-green-700 dark:text-green-300">Review Decision</p>
                      <p className="text-xs capitalize font-medium">{currentFinding.reviewAction.decision.replace(/_/g, " ")}</p>
                      {currentFinding.reviewAction.reason && (
                        <p className="text-xs text-muted-foreground">"{currentFinding.reviewAction.reason}"</p>
                      )}
                      <p className="text-[10px] text-muted-foreground">
                        {currentFinding.reviewAction.reviewerName} · {formatDateTime(currentFinding.reviewAction.reviewedAt)}
                      </p>
                    </div>
                  )}
                </div>

                {/* Review Actions */}
                <div className="shrink-0 border-t p-4 space-y-2">
                  <p className="text-xs text-muted-foreground text-center mb-2">
                    TradeGuard AI assists human review. Do not submit until reviewed by a qualified customs professional.
                  </p>
                  <Button
                    className="w-full gap-1.5"
                    disabled={!canReview() || !["ready_for_review", "reviewed"].includes(shipment?.status ?? "")}
                    onClick={() => setReviewDialogOpen(true)}
                    variant={currentFinding.reviewStatus === "reviewed" ? "outline" : "default"}
                  >
                    {currentFinding.reviewStatus === "reviewed" ? (
                      <><RotateCcw className="h-3.5 w-3.5" /> Re-review</>
                    ) : (
                      <><MessageSquare className="h-3.5 w-3.5" /> Review Finding</>
                    )}
                  </Button>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      )}

      {reviewFinding.error && <p role="alert" className="p-4 text-sm text-destructive">{reviewFinding.error.message}</p>}
      <ReviewDialog key={String(reviewDialogOpen) + currentFinding?.id + currentFinding?.version}
        documents={results?.documents ?? []}
        error={reviewFinding.error}
        finding={currentFinding}
        open={reviewDialogOpen}
        onClose={() => setReviewDialogOpen(false)}
        onSubmit={handleReview}
        isPending={reviewFinding.isPending}
      />
    </div>
  )
}
