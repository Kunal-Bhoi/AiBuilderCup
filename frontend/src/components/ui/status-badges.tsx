import { type ValidationStatus, type ShipmentStatus, type FindingSeverity } from "@/types"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import {
  CheckCircle2,
  XCircle,
  HelpCircle,
  Minus,
  AlertCircle,
  Clock,
  Loader2,
  CheckCheck,
  AlertTriangle,
  Ban,
} from "lucide-react"

// ─── Validation Status Badge ──────────────────────────────────────────────────

const STATUS_CONFIG: Record<
  ValidationStatus,
  { label: string; variant: "success" | "destructive" | "muted" | "warning" | "secondary"; icon: React.ElementType }
> = {
  match: { label: "Match", variant: "success", icon: CheckCircle2 },
  mismatch: { label: "Mismatch", variant: "destructive", icon: XCircle },
  cannot_verify: { label: "Cannot Verify", variant: "muted", icon: HelpCircle },
  not_applicable: { label: "N/A", variant: "secondary", icon: Minus },
  not_checked: { label: "Not Checked", variant: "warning", icon: AlertCircle },
}

export function ValidationStatusBadge({
  status,
  showIcon = true,
  size = "default",
}: {
  status: ValidationStatus
  showIcon?: boolean
  size?: "default" | "sm"
}) {
  const config = STATUS_CONFIG[status]
  const Icon = config.icon
  return (
    <Badge
      variant={config.variant}
      className={cn("gap-1", size === "sm" && "text-[10px] px-1.5 py-0")}
    >
      {showIcon && <Icon className={cn("shrink-0", size === "sm" ? "h-2.5 w-2.5" : "h-3 w-3")} />}
      {config.label}
    </Badge>
  )
}

// ─── Shipment Status Badge ────────────────────────────────────────────────────

const SHIPMENT_STATUS_CONFIG: Record<
  ShipmentStatus,
  { label: string; variant: "default" | "success" | "destructive" | "warning" | "info" | "muted" | "secondary"; icon: React.ElementType }
> = {
  uploading: { label: "Uploading", variant: "info", icon: Clock },
  reviewed: { label: "Reviewed · report pending", variant: "info", icon: CheckCheck },
  archived: { label: "Archived", variant: "muted", icon: Ban },
  draft: { label: "Draft", variant: "muted", icon: Minus },
  queued: { label: "Queued", variant: "secondary", icon: Clock },
  processing: { label: "Processing", variant: "info", icon: Loader2 },
  ready_for_review: { label: "Ready for Review", variant: "warning", icon: AlertTriangle },
  finalized: { label: "Finalized", variant: "success", icon: CheckCheck },
  failed: { label: "Failed", variant: "destructive", icon: Ban },
}

export function ShipmentStatusBadge({
  status,
  showIcon = true,
}: {
  status: ShipmentStatus
  showIcon?: boolean
}) {
  const config = SHIPMENT_STATUS_CONFIG[status]
  const Icon = config.icon
  return (
    <Badge variant={config.variant} className="gap-1">
      {showIcon && (
        <Icon
          className={cn(
            "h-3 w-3 shrink-0",
            status === "processing" && "animate-spin"
          )}
        />
      )}
      {config.label}
    </Badge>
  )
}

// ─── Severity Badge ───────────────────────────────────────────────────────────

export function SeverityBadge({ severity }: { severity: FindingSeverity }) {
  const config = {
    high: { label: "High", className: "border-red-200 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300" },
    medium: { label: "Medium", className: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-300" },
    low: { label: "Low", className: "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-300" },
  }[severity]

  return (
    <span className={cn("inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium", config.className)}>
      {config.label}
    </span>
  )
}

// ─── Cell Status ──────────────────────────────────────────────────────────────

export function getCellStatusClass(status: ValidationStatus): string {
  const map: Record<ValidationStatus, string> = {
    match: "cell-match",
    mismatch: "cell-mismatch",
    cannot_verify: "cell-cannot-verify",
    not_applicable: "cell-not-applicable",
    not_checked: "cell-not-checked",
  }
  return map[status]
}
