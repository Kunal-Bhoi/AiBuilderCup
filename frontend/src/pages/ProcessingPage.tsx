import { useEffect } from "react"
import { useParams, useNavigate } from "react-router-dom"
import {
  CheckCircle2,
  Loader2,
  Circle,
  XCircle,
  ArrowRight,
  RefreshCw,
  FileText,
  AlertTriangle,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { ShipmentStatusBadge } from "@/components/ui/status-badges"
import { Skeleton } from "@/components/ui/skeleton"
import { useProcessingStatus, useShipment, useStartValidation } from "@/hooks/useShipments"
import { ErrorState } from "@/components/ui/error-state"
import { useQueryClient } from "@tanstack/react-query"
import { formatDateTime } from "@/lib/utils"
import type { ProcessingStageStatus } from "@/types"

function StageIcon({ status }: { status: ProcessingStageStatus }) {
  if (status === "done") return <CheckCircle2 className="h-5 w-5 text-green-500 shrink-0" />
  if (status === "running") return <Loader2 className="h-5 w-5 text-primary animate-spin shrink-0" />
  if (status === "failed") return <XCircle className="h-5 w-5 text-destructive shrink-0" />
  return <Circle className="h-5 w-5 text-muted-foreground/40 shrink-0" />
}

export default function ProcessingPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data: shipment } = useShipment(id!)
  const {
    data: processing,
    isLoading,
    refetch, error,
  } = useProcessingStatus(id!, true)

  const restart = useStartValidation(id!)
  const qc = useQueryClient()

  // Auto-navigate when processing completes
  useEffect(() => {
    if (
      processing?.shipmentStatus === "ready_for_review" ||
      processing?.shipmentStatus === "finalized"
    ) {
      qc.invalidateQueries({ queryKey: ["shipments"] })
      qc.invalidateQueries({ queryKey: ["dashboard-stats"] })
      const timer = setTimeout(() => {
        navigate(`/shipments/${id}/results`)
      }, 1500)
      return () => clearTimeout(timer)
    }
  }, [processing?.shipmentStatus, id, navigate, qc])

  const completedStages = processing?.stages.filter((s) => s.status === "done").length ?? 0
  const totalStages = processing?.stages.length ?? 6
  const progressPct = Math.round((completedStages / totalStages) * 100)

  const isComplete =
    processing?.shipmentStatus === "ready_for_review" ||
    processing?.shipmentStatus === "finalized"

  const isFailed = processing?.shipmentStatus === "failed"

  if (error) return <ErrorState error={error} retry={() => refetch()} />

  return (
    <div className="p-6 max-w-2xl mx-auto space-y-6 animate-fade-in-up">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">AI Validation</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {shipment?.reference ?? id} · Processing documents
          </p>
        </div>
        {shipment && <ShipmentStatusBadge status={shipment.status} />}
      </div>

      {/* Overall Progress */}
      <Card>
        <CardContent className="p-6 space-y-4">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium">
              {isComplete
                ? "Validation complete"
                : isFailed
                ? "Validation failed"
                : processing?.currentStageIndex === -1 ? "Waiting for processing details"
                : `Stage ${Math.min(completedStages + 1, totalStages)} of ${totalStages}`}
            </span>
            <span className="text-muted-foreground">{progressPct}%</span>
          </div>
          <Progress
            value={progressPct}
            className={isComplete ? "[&>div]:bg-green-500" : isFailed ? "[&>div]:bg-destructive" : ""}
          />
          {isComplete && (
            <div className="flex items-center gap-2 text-sm text-green-600 font-medium">
              <CheckCircle2 className="h-4 w-4" />
              Redirecting to validation results...
            </div>
          )}
        </CardContent>
      </Card>

      {/* Processing Stages */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
            Processing Pipeline
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-1 pt-0">
          {isLoading
            ? Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="flex items-center gap-3 p-3">
                  <Skeleton className="h-5 w-5 rounded-full" />
                  <div className="flex-1 space-y-1">
                    <Skeleton className="h-4 w-40" />
                    <Skeleton className="h-3 w-64" />
                  </div>
                </div>
              ))
            : processing?.stages.map((stage, i) => (
                <div
                  key={stage.id}
                  className={`flex items-start gap-3 rounded-lg p-3 transition-colors ${
                    stage.status === "running"
                      ? "bg-primary/5 stage-running"
                      : stage.status === "done"
                      ? "opacity-70"
                      : ""
                  }`}
                >
                  <div className="mt-0.5">
                    <StageIcon status={stage.status} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className={`text-sm font-medium ${stage.status === "running" ? "text-primary" : ""}`}>
                        {stage.label}
                      </p>
                      {stage.status === "running" && (
                        <span className="text-[10px] text-primary bg-primary/10 px-1.5 py-0.5 rounded-full font-medium">
                          IN PROGRESS
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">{stage.description}</p>
                    {stage.completedAt && (
                      <p className="text-[10px] text-muted-foreground mt-1">
                        Completed {formatDateTime(stage.completedAt)}
                      </p>
                    )}
                  </div>
                  <div className="shrink-0 text-xs text-muted-foreground font-mono">{i + 1}</div>
                </div>
              ))}
        </CardContent>
      </Card>

      {/* Document Statuses */}
      {processing?.documentStatuses && processing.documentStatuses.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
              Document Processing
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 pt-0">
            {processing.documentStatuses.map((doc) => (
              <div key={doc.documentId} className="flex items-center gap-3 rounded-md border p-3">
                <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
                <p className="text-sm flex-1 truncate">{doc.filename}</p>
                <div className="flex items-center gap-1.5">
                  {doc.status === "done" && <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />}
                  {doc.status === "processing" && <Loader2 className="h-3.5 w-3.5 text-primary animate-spin" />}
                  {doc.status === "queued" && <Circle className="h-3.5 w-3.5 text-muted-foreground/40" />}
                  {doc.status === "failed" && <XCircle className="h-3.5 w-3.5 text-destructive" />}
                  <span className="text-xs text-muted-foreground capitalize">{doc.status}</span>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Error / Retry State */}
      {isFailed && (
        <Card className="border-destructive/40 bg-destructive/5">
          <CardContent className="p-5 flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="text-sm font-medium text-destructive">Validation Failed</p>
              <p className="text-xs text-muted-foreground mt-1">
                The AI pipeline encountered an error. This may be due to unsupported document formats or
                illegible document content. Please review your uploaded files and try again.
              </p>
              <div className="mt-3 flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-1.5"
                  onClick={async () => { try { await restart.mutateAsync(); await refetch() } catch { /* visible below */ } }}
                  disabled={restart.isPending}
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  Retry
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => navigate("/dashboard")}
                >
                  Back to Dashboard
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Complete CTA */}
      {isComplete && (
        <div className="flex justify-end">
          <Button
            onClick={() => navigate(`/shipments/${id}/results`)}
            className="gap-2"
          >
            View Results <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
      )}

      {restart.error && <p role="alert" className="text-sm text-destructive">{restart.error.message}</p>}
      {/* Disclaimer */}
      <p className="text-xs text-muted-foreground text-center leading-relaxed">
        TradeGuard AI assists human review and does not automatically submit customs filings.
        All findings must be reviewed by a qualified customs professional before submission.
      </p>
    </div>
  )
}
