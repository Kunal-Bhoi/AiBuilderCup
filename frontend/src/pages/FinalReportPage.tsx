import { useState } from "react"
import { useParams, useNavigate, Link } from "react-router-dom"
import {
  FileText,
  CheckCircle2,
  XCircle,
  Download,
  Printer,
  ArrowLeft,
  AlertTriangle,
  Loader2,
  Lock,
  Shield,
  RotateCcw,
  ChevronRight,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import { ValidationStatusBadge, SeverityBadge, ShipmentStatusBadge } from "@/components/ui/status-badges"
import { Skeleton } from "@/components/ui/skeleton"
import { useReport, useFinalizeReview } from "@/hooks/useShipments"
import { formatDate, formatDateTime } from "@/lib/utils"

import { exportReport } from "@/lib/exportReport"
import { shipmentService, USE_MOCK } from "@/services/shipmentService"
import { ErrorState } from "@/components/ui/error-state"

// ─── Final Report Page ────────────────────────────────────────────────────────
export default function FinalReportPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [finalizeDialog, setFinalizeDialog] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [actionError, setActionError] = useState("")

  const { data: report, isLoading, error, refetch } = useReport(id!)
  const finalizeReview = useFinalizeReview(id!)

  const handleFinalize = async () => {
    try { await finalizeReview.mutateAsync(); setFinalizeDialog(false) } catch { /* mutation error appears in the dialog */ }
  }

  const handleExportPDF = async () => {
    if (!report) return
    setExporting(true)
    try {
      setActionError("")
      if (USE_MOCK) await exportReport(report)
      else {
        const blob = await shipmentService.downloadReport(id!)
        const url = URL.createObjectURL(blob)
        const link = document.createElement("a"); link.href = url; link.download = `tradeguard-report-${report.reference}.pdf`; link.click()
        setTimeout(() => URL.revokeObjectURL(url), 1000)
      }
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Report export failed")
    } finally {
      setExporting(false)
    }
  }

  const handlePrint = () => {
    window.print()
  }

  if (error) return <ErrorState error={error} retry={() => refetch()} />
  if (isLoading) {
    return (
      <div className="p-6 space-y-4 max-w-4xl mx-auto">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-32 rounded-lg" />
        <Skeleton className="h-64 rounded-lg" />
        <Skeleton className="h-48 rounded-lg" />
      </div>
    )
  }

  if (!report) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <AlertTriangle className="h-10 w-10 text-muted-foreground/40 mb-3" />
        <p className="text-sm text-muted-foreground">Report not available for this shipment</p>
        <Button variant="ghost" size="sm" className="mt-3" onClick={() => navigate(`/shipments/${id}/results`)}>
          Back to Results
        </Button>
      </div>
    )
  }

  const isFinalized = report.status === "finalized"
  const canFinalize = report.canFinalize && !isFinalized

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6 animate-fade-in-up">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
            <Link to="/dashboard" className="hover:text-foreground transition-colors">Dashboard</Link>
            <ChevronRight className="h-3.5 w-3.5" />
            <Link to={`/shipments/${id}/results`} className="hover:text-foreground transition-colors">Results</Link>
            <ChevronRight className="h-3.5 w-3.5" />
            <span className="font-medium text-foreground">Report</span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight">Pre-Submission Validation Report</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {report.reference} · Generated {formatDateTime(report.generatedAt)}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Button variant="outline" size="sm" onClick={() => navigate(`/shipments/${id}/review`)} className="gap-1.5">
            <ArrowLeft className="h-3.5 w-3.5" /> Review
          </Button>
          <Button variant="outline" size="sm" onClick={handlePrint} className="gap-1.5">
            <Printer className="h-3.5 w-3.5" /> Print
          </Button>
          <Button variant="outline" size="sm" onClick={handleExportPDF} disabled={exporting} className="gap-1.5">
            {exporting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
            Export PDF
          </Button>
          {!isFinalized && (
            <Button
              size="sm"
              onClick={() => setFinalizeDialog(true)}
              disabled={!canFinalize}
              className="gap-1.5"
              title={!canFinalize ? `${report.pendingReviews} review(s) still pending` : undefined}
            >
              <Lock className="h-3.5 w-3.5" />
              Finalise Review
            </Button>
          )}
        </div>
      </div>

      {/* Pending reviews warning */}
      {report.pendingReviews > 0 && !isFinalized && (
        <div className="flex items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950 p-4">
          <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0" />
          <div>
            <p className="text-sm font-medium text-amber-800 dark:text-amber-200">
              {report.pendingReviews} finding{report.pendingReviews !== 1 ? "s" : ""} pending review
            </p>
            <p className="text-xs text-amber-700 dark:text-amber-300 mt-0.5">
              All discrepancies must be reviewed before the report can be finalised.{" "}
              <Link to={`/shipments/${id}/review`} className="underline hover:no-underline">
                Review now →
              </Link>
            </p>
          </div>
        </div>
      )}

      {/* Finalized banner */}
      {isFinalized && (
        <div className="flex items-center gap-3 rounded-lg border border-green-200 bg-green-50 dark:border-green-800 dark:bg-green-950 p-4">
          <Shield className="h-5 w-5 text-green-600 shrink-0" />
          <div>
            <p className="text-sm font-medium text-green-800 dark:text-green-200">Report Finalised</p>
            <p className="text-xs text-green-700 dark:text-green-300 mt-0.5">
              This validation report has been finalised on {formatDate(report.shipment.finalizedAt ?? "")}.
              It may now be used as a pre-submission audit record.
            </p>
          </div>
        </div>
      )}

      {actionError && <p role="alert" className="text-sm text-destructive">{actionError}</p>}
      {/* Report Status Bar */}
      <Card>
        <CardContent className="p-5">
          <div className="flex flex-wrap items-center gap-6">
            <div>
              <p className="text-xs text-muted-foreground">Reference</p>
              <p className="font-mono font-semibold">{report.reference}</p>
            </div>
            <Separator orientation="vertical" className="h-8 hidden sm:block" />
            <div>
              <p className="text-xs text-muted-foreground">Status</p>
              <ShipmentStatusBadge status={report.shipment.status} />
            </div>
            <Separator orientation="vertical" className="h-8 hidden sm:block" />
            <div>
              <p className="text-xs text-muted-foreground">Documents</p>
              <p className="text-sm font-medium">{report.results.documents.length}</p>
            </div>
            <Separator orientation="vertical" className="h-8 hidden sm:block" />
            <div>
              <p className="text-xs text-muted-foreground">Findings</p>
              <p className="text-sm font-medium">{report.results.findings.length}</p>
            </div>
            <Separator orientation="vertical" className="h-8 hidden sm:block" />
            <div>
              <p className="text-xs text-muted-foreground">Route</p>
              <p className="text-sm font-medium">
                {report.shipment.originCountry} → {report.shipment.destinationCountry}
              </p>
            </div>
            <Separator orientation="vertical" className="h-8 hidden sm:block" />
            <div>
              <p className="text-xs text-muted-foreground">Prepared by</p>
              <p className="text-sm font-medium">{report.generatedBy}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Documents Analysed */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-4 w-4" />
            Documents Analysed
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {report.results.documents.map((doc) => (
              <div key={doc.id} className="flex items-center gap-3 rounded-md border p-3">
                <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{doc.filename}</p>
                  <p className="text-xs text-muted-foreground">{doc.typeLabel}</p>
                </div>
                <Badge variant="success" className="gap-1 shrink-0">
                  <CheckCircle2 className="h-2.5 w-2.5" /> Processed
                </Badge>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Validation Summary */}
      <Card>
        <CardHeader>
          <CardTitle>Overall Validation Summary</CardTitle>
          <CardDescription>Field-level comparison outcomes across all documents</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
            {[
              { label: "Matched", value: report.results.summary.matched, icon: CheckCircle2, colorClass: "text-green-600 bg-green-50 dark:bg-green-950" },
              { label: "Mismatch", value: report.results.summary.mismatched, icon: XCircle, colorClass: "text-red-600 bg-red-50 dark:bg-red-950" },
              { label: "Cannot Verify", value: report.results.summary.cannotVerify, icon: AlertTriangle, colorClass: "text-slate-600 bg-slate-50 dark:bg-slate-900" },
              { label: "Not Checked", value: report.results.summary.notChecked, icon: AlertTriangle, colorClass: "text-amber-600 bg-amber-50 dark:bg-amber-950" },
              { label: "N/A", value: report.results.summary.notApplicable, icon: AlertTriangle, colorClass: "text-gray-400 bg-gray-50 dark:bg-gray-900" },
            ].map(({ label, value, icon: Icon, colorClass }) => (
              <div key={label} className={`flex flex-col items-center rounded-lg p-4 ${colorClass}`}>
                <Icon className="h-5 w-5 mb-1" />
                <span className="text-2xl font-bold">{value}</span>
                <span className="text-xs font-medium mt-0.5">{label}</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card><CardHeader><CardTitle>Field values and original source references</CardTitle></CardHeader><CardContent className="space-y-4">{report.results.matrix.map(field => <div key={field.fieldKey} className="border-b pb-3"><div className="flex items-center gap-2"><span className="text-sm font-medium">{field.label}</span><ValidationStatusBadge status={field.status} /></div><div className="mt-2 space-y-1">{field.cells.map(cell => <p key={cell.documentId} className="text-xs text-muted-foreground">{report.results.documents.find(doc => doc.id === cell.documentId)?.filename}: <strong>{cell.rawValue ?? "Missing / unavailable"}</strong>{cell.source && <> · Page {cell.source.page} · Confidence {cell.source.confidence === null ? "unknown" : `${Math.round(cell.source.confidence * 100)}%`} · {cell.source.excerpt}</>}</p>)}</div></div>)}</CardContent></Card>
      {/* Findings */}
      <Card>
        <CardHeader>
          <CardTitle>Findings & Discrepancies</CardTitle>
          <CardDescription>All identified discrepancies with AI explanations and reviewer decisions</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {report.results.findings.length === 0 ? (
            <div className="text-center py-8">
              <CheckCircle2 className="h-8 w-8 text-green-400 mx-auto mb-2" />
              <p className="text-sm text-muted-foreground">No discrepancies found</p>
            </div>
          ) : (
            report.results.findings.map((finding, i) => (
              <div key={finding.id} className="rounded-lg border p-4 space-y-3">
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div>
                    <p className="text-sm font-semibold">{finding.label}</p>
                    <p className="text-xs text-muted-foreground mt-0.5">Finding #{i + 1}</p>
                  </div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <ValidationStatusBadge status={finding.status} />
                    <SeverityBadge severity={finding.severity} />
                    {finding.reviewStatus === "reviewed" ? (
                      <Badge variant="success" className="gap-1">
                        <CheckCircle2 className="h-2.5 w-2.5" /> Reviewed
                      </Badge>
                    ) : (
                      <Badge variant="warning" className="gap-1">
                        <AlertTriangle className="h-2.5 w-2.5" /> Pending
                      </Badge>
                    )}
                  </div>
                </div>

                <p className="text-sm text-muted-foreground leading-relaxed">{finding.explanation}</p>

                {finding.suggestion && (
                  <div className="rounded-md bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-800 p-3">
                    <p className="text-xs font-semibold text-amber-700 dark:text-amber-300 mb-1">Suggested Action</p>
                    <p className="text-xs text-amber-800 dark:text-amber-200">{finding.suggestion}</p>
                  </div>
                )}

                {finding.reviewStatus === "reviewed" && finding.reviewAction && (
                  <div className="rounded-md bg-green-50 dark:bg-green-950 border border-green-200 dark:border-green-800 p-3 space-y-1">
                    <p className="text-xs font-semibold text-green-700 dark:text-green-300">Reviewer Decision</p>
                    <p className="text-sm font-medium capitalize">{finding.reviewAction.decision.replace(/_/g, " ")}</p>
                    {finding.reviewAction.reason && (
                      <p className="text-xs text-muted-foreground italic">"{finding.reviewAction.reason}"</p>
                    )}
                    <p className="text-[10px] text-muted-foreground">
                      {finding.reviewAction.reviewerName} · {formatDateTime(finding.reviewAction.reviewedAt)}
                    </p>
                  </div>
                )}
              </div>
            ))
          )}
        </CardContent>
      </Card>

      {/* Fields Not Checked */}
      {report.results.coverage.notCheckedFields.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Fields Outside Validation Scope</CardTitle>
            <CardDescription>These fields were not examined in this validation run</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-1.5">
              {report.results.coverage.notCheckedFields.map((f) => (
                <Badge key={f} variant="warning" className="text-xs">{f.replace(/_/g, " ")}</Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Audit Trail */}
      {report.reviewerDecisions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Human Review Audit Trail</CardTitle>
            <CardDescription>All reviewer decisions recorded for compliance purposes</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {report.reviewerDecisions.map((d, i) => (
              <div key={i} className="flex items-start gap-3 text-sm border-b last:border-0 pb-3 last:pb-0">
                <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="font-medium">{d.field}</p>
                  <p className="text-xs text-muted-foreground capitalize mt-0.5">{d.decision.replace(/_/g, " ")}</p>
                  {d.reason && <p className="text-xs italic mt-0.5">"{d.reason}"</p>}
                </div>
                <div className="text-right shrink-0">
                  <p className="text-xs font-medium">{d.reviewerName}</p>
                  <p className="text-[10px] text-muted-foreground">{formatDateTime(d.reviewedAt)}</p>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Disclaimer */}
      <div className="rounded-lg border bg-muted/20 p-4 text-xs text-muted-foreground leading-relaxed">
        <strong>Important Disclaimer:</strong> This report is produced by TradeGuard AI for pre-submission
        review purposes only. It is not a customs declaration, does not constitute legal advice, and must
        be reviewed by a qualified customs professional before submission to any customs authority.
        TradeGuard AI does not automatically submit filings and makes no guarantee of compliance.
      </div>

      {/* Finalize Dialog */}
      <Dialog open={finalizeDialog} onOpenChange={setFinalizeDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Lock className="h-5 w-5" />
              Finalise Review
            </DialogTitle>
            <DialogDescription>
              This will lock the validation report. No further changes can be made after finalisation.
            </DialogDescription>
          </DialogHeader>
          <div className="rounded-lg bg-muted/30 p-4 text-sm space-y-1">
            <p><strong>Shipment:</strong> {report.reference}</p>
            <p><strong>Findings reviewed:</strong> {report.results.findings.length}</p>
            <p><strong>Account:</strong> Sarah Chen</p>
          </div>
          <p className="text-xs text-muted-foreground">
            By finalising, you confirm that all discrepancies have been reviewed and this document
            is ready for pre-submission use.
          </p>
          {finalizeReview.error && <p role="alert" className="text-sm text-destructive">{finalizeReview.error.message}</p>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setFinalizeDialog(false)}>Cancel</Button>
            <Button onClick={handleFinalize} disabled={finalizeReview.isPending} className="gap-1.5">
              {finalizeReview.isPending ? (
                <><Loader2 className="h-4 w-4 animate-spin" /> Finalising...</>
              ) : (
                <><Lock className="h-4 w-4" /> Confirm Finalise</>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <div className="flex justify-between items-center pt-2">
        <Button variant="ghost" size="sm" onClick={() => navigate("/dashboard")} className="gap-1.5">
          <ArrowLeft className="h-3.5 w-3.5" /> Dashboard
        </Button>
        <p className="text-xs text-muted-foreground">
          Report generated by TradeGuard AI · {formatDateTime(report.generatedAt)}
        </p>
      </div>
    </div>
  )
}
