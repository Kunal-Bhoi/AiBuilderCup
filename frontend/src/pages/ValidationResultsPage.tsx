import { useState } from "react"
import { useParams, useNavigate, Link } from "react-router-dom"
import {
  CheckCircle2,
  XCircle,
  HelpCircle,
  Minus,
  AlertCircle,
  Search,
  Filter,
  FileText,
  ChevronRight,
  ArrowRight,
  Info,
  Eye,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import {
  ValidationStatusBadge,
  ShipmentStatusBadge,
  SeverityBadge,
  getCellStatusClass,
} from "@/components/ui/status-badges"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import { useValidationResults, useShipment } from "@/hooks/useShipments"
import { ErrorState } from "@/components/ui/error-state"
import { cn } from "@/lib/utils"
import type { MatrixField, MatrixCell, Finding, ValidationStatus } from "@/types"

// ─── Summary Card ─────────────────────────────────────────────────────────────
function SummaryCard({
  label, value, icon: Icon, colorClass,
}: {
  label: string; value: number; icon: React.ElementType; colorClass: string
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border p-4">
      <div className={cn("flex h-9 w-9 items-center justify-center rounded-lg", colorClass)}>
        <Icon className="h-4 w-4" />
      </div>
      <div>
        <p className="text-2xl font-bold">{value}</p>
        <p className="text-xs text-muted-foreground">{label}</p>
      </div>
    </div>
  )
}

// ─── Matrix Cell Component ────────────────────────────────────────────────────
function MatrixCellView({ cell, fieldStatus, onClick }: { cell: MatrixCell; fieldStatus: ValidationStatus; onClick?: () => void }) {
  const missing = !cell.rawValue?.trim() || cell.source === null;
  const status = fieldStatus === "not_checked" || fieldStatus === "not_applicable" ? fieldStatus : missing ? "cannot_verify" : fieldStatus;
  return <td className={cn("border p-0 min-w-[175px]", getCellStatusClass(status))}><button className="w-full h-full min-h-24 px-3 py-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary" onClick={onClick}>
    <p className="text-xs font-medium leading-relaxed">{cell.rawValue ?? (status === "not_checked" ? "Not checked" : status === "not_applicable" ? "Not applicable" : "Missing / cannot verify")}</p>
    <p className="mt-1 text-[10px] opacity-80">{status.replace(/_/g, " ")}{cell.source?.confidence != null ? ` | ${Math.round(cell.source.confidence * 100)}% confidence` : ""}</p>
  </button></td>;
}

function FindingPanel({
  finding,
  open,
  onClose,
  onReview,
}: {
  finding: Finding | null
  open: boolean
  onClose: () => void
  onReview: (id: string) => void
}) {
  if (!finding) return null
  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <XCircle className="h-5 w-5 text-destructive" />
            Discrepancy Detail
          </DialogTitle>
          <DialogDescription>
            Field: <strong>{finding.label}</strong>
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <SeverityBadge severity={finding.severity} />
            <ValidationStatusBadge status={finding.status} />
            {finding.reviewStatus === "reviewed" && (
              <Badge variant="success" className="gap-1">
                <CheckCircle2 className="h-2.5 w-2.5" /> Reviewed
              </Badge>
            )}
          </div>

          <div className="rounded-lg border bg-muted/20 p-4 space-y-2">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
              AI Explanation
            </p>
            <p className="text-sm leading-relaxed">{finding.explanation}</p>
          </div>

          {finding.suggestion && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950 p-4 space-y-2">
              <p className="text-xs font-semibold text-amber-700 dark:text-amber-300 uppercase tracking-wide">
                Suggested Action
              </p>
              <p className="text-sm text-amber-800 dark:text-amber-200 leading-relaxed">
                {finding.suggestion}
              </p>
            </div>
          )}

          <div className="flex gap-2 pt-1">
            <Button
              size="sm"
              variant="outline"
              onClick={onClose}
            >
              Close
            </Button>
            <Button
              size="sm"
              onClick={() => {
                onClose()
                onReview(finding.id)
              }}
              className="gap-1.5"
            >
              <Eye className="h-3.5 w-3.5" />
              Review Finding
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ─── Validation Results Page ──────────────────────────────────────────────────
export default function ValidationResultsPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data: results, isLoading: resultsLoading, error, refetch } = useValidationResults(id!)
  const { data: shipment } = useShipment(id!)

  const [fieldSearch, setFieldSearch] = useState("")
  const [statusFilter, setStatusFilter] = useState<ValidationStatus | "all">("all")
  const [selectedFinding, setSelectedFinding] = useState<Finding | null>(null)
  const [panelOpen, setPanelOpen] = useState(false)
  const [selectedCell, setSelectedCell] = useState<{ field: MatrixField; cell: MatrixCell } | null>(null)

  const filteredMatrix = (results?.matrix ?? []).filter((field) => {
    const matchSearch =
      !fieldSearch ||
      field.label.toLowerCase().includes(fieldSearch.toLowerCase()) ||
      field.fieldKey.toLowerCase().includes(fieldSearch.toLowerCase())
    const matchStatus = statusFilter === "all" || field.status === statusFilter
    return matchSearch && matchStatus
  })

  const handleCellClick = (field: MatrixField) => {
    if (field.status !== "mismatch" && field.status !== "cannot_verify") return
    const finding = results?.findings.find((f) => f.fieldKey === field.fieldKey)
    if (finding) {
      setSelectedFinding(finding)
      setPanelOpen(true)
    }
  }

  const pendingCount = results?.findings.filter((f) => f.reviewStatus === "pending").length ?? 0

  if (error) return <ErrorState error={error} retry={() => refetch()} />

  return (
    <div className="p-6 space-y-6 animate-fade-in-up">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
            <Link to="/dashboard" className="hover:text-foreground transition-colors">Dashboard</Link>
            <ChevronRight className="h-3.5 w-3.5" />
            <span className="font-medium text-foreground">{shipment?.reference ?? id}</span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight">Validation Results</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Cross-document field comparison matrix
          </p>
        </div>
        <div className="flex items-center gap-2">
          {shipment && <ShipmentStatusBadge status={shipment.status} />}
          {pendingCount > 0 && (
            <Badge variant="warning" className="gap-1">
              <AlertCircle className="h-3 w-3" />
              {pendingCount} pending review{pendingCount !== 1 ? "s" : ""}
            </Badge>
          )}
          <Button
            size="sm"
            onClick={() => navigate(`/shipments/${id}/review`)}
            className="gap-1.5"
          >
            <Eye className="h-3.5 w-3.5" />
            Review Discrepancies
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => navigate(`/shipments/${id}/report`)}
            className="gap-1.5"
          >
            View Report <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Summary Cards */}
      {resultsLoading ? (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-20 rounded-lg" />
          ))}
        </div>
      ) : results ? (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
          <SummaryCard label="Documents Analysed" value={results.documents.length} icon={FileText} colorClass="bg-blue-50 text-blue-600 dark:bg-blue-950 dark:text-blue-400" />
          <SummaryCard label="Matched Fields" value={results.summary.matched} icon={CheckCircle2} colorClass="bg-green-50 text-green-600 dark:bg-green-950 dark:text-green-400" />
          <SummaryCard label="Mismatched Fields" value={results.summary.mismatched} icon={XCircle} colorClass="bg-red-50 text-red-600 dark:bg-red-950 dark:text-red-400" />
          <SummaryCard label="Cannot Verify" value={results.summary.cannotVerify} icon={HelpCircle} colorClass="bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400" />
          <SummaryCard label="Not Checked" value={results.summary.notChecked} icon={Minus} colorClass="bg-amber-50 text-amber-600 dark:bg-amber-950 dark:text-amber-400" />
        </div>
      ) : null}

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <span className="text-muted-foreground font-medium">Legend:</span>
        {(["match", "mismatch", "cannot_verify", "not_applicable", "not_checked"] as ValidationStatus[]).map((s) => (
          <ValidationStatusBadge key={s} status={s} size="sm" />
        ))}
        <span className="text-muted-foreground ml-1">· Click a mismatch cell to view details</span>
      </div>

      {/* Filters */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="relative flex-1 min-w-[200px]">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                placeholder="Search fields..."
                value={fieldSearch}
                onChange={(e) => setFieldSearch(e.target.value)}
                className="pl-8 h-8 text-sm"
              />
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <Filter className="h-3.5 w-3.5 text-muted-foreground" />
              {(["all", "match", "mismatch", "cannot_verify", "not_checked", "not_applicable"] as const).map((s) => (
                <button
                  key={s}
                  onClick={() => setStatusFilter(s)}
                  className={cn(
                    "px-2.5 py-1 rounded-md text-xs font-medium transition-colors",
                    statusFilter === s
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-muted-foreground hover:bg-muted/80"
                  )}
                >
                  {s === "all" ? "All" : s === "match" ? "Match" : s === "mismatch" ? "Mismatch" : s === "cannot_verify" ? "Cannot Verify" : s === "not_applicable" ? "Not Applicable" : "Not Checked"}
                </button>
              ))}
            </div>
          </div>
        </CardHeader>

        {/* Matrix Table */}
        <CardContent className="p-0">
          {resultsLoading ? (
            <div className="p-6">
              <Skeleton className="h-64 w-full rounded-lg" />
            </div>
          ) : !results ? (
            <div className="flex flex-col items-center justify-center py-16">
              <AlertCircle className="h-10 w-10 text-muted-foreground/40 mb-3" />
              <p className="text-sm text-muted-foreground">No validation results available</p>
            </div>
          ) : (
            <div className="overflow-auto max-h-[600px]">
              <table className="min-w-full border-collapse text-sm" aria-label="Document validation matrix">
                <thead className="sticky top-0 z-20"><tr className="bg-muted">
                  <th className="sticky left-0 z-30 min-w-[200px] border bg-muted p-4 text-left text-xs">Document / extracted field</th>
                  {filteredMatrix.map(field => <th key={field.fieldKey} className="min-w-[175px] border p-3 text-left"><div className="text-xs font-semibold mb-2">{field.label}</div><ValidationStatusBadge status={field.status} size="sm" />{results.findings.find(f => f.fieldKey === field.fieldKey)?.reviewStatus === "reviewed" && <p className="text-[10px] text-muted-foreground mt-1">Reviewed</p>}</th>)}
                </tr></thead>
                <tbody>{filteredMatrix.length === 0 ? <tr><td className="p-8 text-muted-foreground">No fields match your filters.</td></tr> : results.documents.map(doc => <tr key={doc.id}>
                  <th scope="row" className="sticky left-0 z-10 border bg-background p-4 text-left"><div className="flex items-center gap-2"><FileText className="h-4 w-4 shrink-0 text-primary" /><span className="text-xs font-semibold">{doc.typeLabel ?? doc.type}</span></div><p className="mt-2 max-w-[190px] break-all text-[10px] font-normal text-muted-foreground">{doc.filename}</p></th>
                  {filteredMatrix.map(field => { const cell = field.cells.find(item => item.documentId === doc.id) ?? { documentId: doc.id, rawValue: null, normalizedValue: null, source: null }; return <MatrixCellView key={field.fieldKey} cell={cell} fieldStatus={field.status} onClick={() => { if (results.findings.some(f => f.fieldKey === field.fieldKey)) handleCellClick(field); else setSelectedCell({ field, cell }); }} />; })}
                </tr>)}</tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Coverage Info */}
      {results && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Validation Coverage</CardTitle>
            <CardDescription>Fields examined and fields outside current validation scope</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <p className="text-xs font-medium text-muted-foreground mb-1.5">Checked Fields ({results.coverage.checkedFields.length})</p>
                <div className="flex flex-wrap gap-1">
                  {results.coverage.checkedFields.map((f) => (
                    <Badge key={f} variant="secondary" className="text-[10px]">{f.replace(/_/g, " ")}</Badge>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-xs font-medium text-muted-foreground mb-1.5">Not Checked ({results.coverage.notCheckedFields.length})</p>
                <div className="flex flex-wrap gap-1">
                  {results.coverage.notCheckedFields.map((f) => (
                    <Badge key={f} variant="warning" className="text-[10px]">{f.replace(/_/g, " ")}</Badge>
                  ))}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Finding Detail Panel */}
      <Dialog open={!!selectedCell} onOpenChange={open => !open && setSelectedCell(null)}><DialogContent><DialogHeader><DialogTitle>{selectedCell?.field.label}</DialogTitle><DialogDescription>Extracted value and source evidence</DialogDescription></DialogHeader><p className="text-sm">{selectedCell?.cell.rawValue ?? "No readable value available. This cell is not a verified match."}</p>{selectedCell?.cell.source ? <div className="space-y-2 text-sm text-muted-foreground"><p>Page {selectedCell.cell.source.page}</p><p>{selectedCell.cell.source.excerpt}</p><p>Confidence: {selectedCell.cell.source.confidence === null ? "Unavailable" : `${Math.round(selectedCell.cell.source.confidence * 100)}%`}</p><p>Recorded by: {selectedCell.cell.source.modelId ?? "Unknown"} {selectedCell.cell.source.modelVersion}</p><p>{selectedCell.cell.source.extractedAt}</p></div> : <p className="text-sm text-muted-foreground">No source evidence is available.</p>}</DialogContent></Dialog>
      <FindingPanel
        finding={selectedFinding}
        open={panelOpen}
        onClose={() => setPanelOpen(false)}
        onReview={(findingId) => navigate(`/shipments/${id}/review?finding=${encodeURIComponent(findingId)}`)}
      />
    </div>
  )
}
