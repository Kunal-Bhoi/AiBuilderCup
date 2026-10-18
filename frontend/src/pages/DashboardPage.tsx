import { useState } from "react"
import { useNavigate, useSearchParams, useLocation } from "react-router-dom"
import {
  Package,
  Clock,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Plus,
  Search,
  MoreHorizontal,
  ArrowUpRight,
  TrendingUp,
  RefreshCw,
} from "lucide-react"
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { ShipmentStatusBadge } from "@/components/ui/status-badges"
import { CardSkeleton, TableSkeleton } from "@/components/ui/skeleton"
import { useShipments, useDashboardStats } from "@/hooks/useShipments"
import { formatDate, formatDateTime } from "@/lib/utils"
import { USE_MOCK } from "@/services/shipmentService"
import { hasResults, canEditDocuments } from "@/lib/workflow"
import { ErrorState } from "@/components/ui/error-state"
import type { Shipment } from "@/types"

// Theme-aware tooltip box. Recharts gives pie-slice items no colour, so their text
// falls back to #000 and disappears on the dark background unless itemStyle sets one.
const chartTooltipStyle: React.CSSProperties = {
  background: "hsl(var(--popover))",
  color: "hsl(var(--popover-foreground))",
  border: "1px solid hsl(var(--border))",
  borderRadius: "8px",
  fontSize: "12px",
}

// ─── Stat Card ────────────────────────────────────────────────────────────────

interface StatCardProps {
  title: string
  value: number | string
  description: string
  icon: React.ElementType
  iconClass: string
  trend?: string
}

function StatCard({ title, value, description, icon: Icon, iconClass, trend }: StatCardProps) {
  return (
    <Card className="hover:shadow-md transition-shadow">
      <CardContent className="p-6">
        <div className="flex items-start justify-between">
          <div className="space-y-1">
            <p className="text-sm text-muted-foreground font-medium">{title}</p>
            <p className="text-3xl font-bold tracking-tight">{value}</p>
            <p className="text-xs text-muted-foreground">{description}</p>
          </div>
          <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${iconClass}`}>
            <Icon className="h-5 w-5" />
          </div>
        </div>
        {trend && (
          <div className="mt-3 flex items-center gap-1 text-xs text-green-600">
            <TrendingUp className="h-3 w-3" />
            {trend}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ─── Shipment Row ─────────────────────────────────────────────────────────────

function ShipmentRow({ shipment, onClick }: { shipment: Shipment; onClick: () => void }) {
  return (
    <tr
      className="border-b last:border-0 hover:bg-muted/30 cursor-pointer transition-colors group"
      onClick={onClick}
    >
      <td className="py-3 px-4">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm font-medium text-primary">
            {shipment.reference}
          </span>
        </div>
      </td>
      <td className="py-3 px-4 text-sm text-muted-foreground">{shipment.originCountry || "—"}</td>
      <td className="py-3 px-4 text-sm text-muted-foreground">{shipment.destinationCountry || "—"}</td>
      <td className="py-3 px-4">
        <span className="text-sm">{(shipment.documentCount ?? shipment.documents.length)}</span>
        <span className="text-xs text-muted-foreground ml-1">
          {(shipment.documentCount ?? shipment.documents.length) === 1 ? "doc" : "docs"}
        </span>
      </td>
      <td className="py-3 px-4">
        <ShipmentStatusBadge status={shipment.status} />
      </td>
      <td className="py-3 px-4">
        {shipment.discrepancyCount > 0 ? (
          <Badge variant="destructive" className="gap-1">
            <XCircle className="h-2.5 w-2.5" />
            {shipment.discrepancyCount}
          </Badge>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        )}
      </td>
      <td className="py-3 px-4 text-sm text-muted-foreground">{formatDate(shipment.createdAt)}</td>
      <td className="py-3 px-4">
        <Button
          aria-label={`Open ${shipment.reference}`}
          variant="ghost"
          size="icon-sm"
          className="opacity-70 group-hover:opacity-100 transition-opacity"
          onClick={(e) => {
            e.stopPropagation()
            onClick()
          }}
        >
          <ArrowUpRight className="h-4 w-4" />
        </Button>
      </td>
    </tr>
  )
}

// ─── Dashboard Page ───────────────────────────────────────────────────────────

export default function DashboardPage() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const search = params.get("q") ?? ""
  const setSearch = (value: string) => setParams(value ? { q: value } : {})
  const location = useLocation()
  const [statusFilter, setStatusFilter] = useState<string>("all")
  const [page, setPage] = useState(1)

  const { data: stats, isLoading: statsLoading } = useDashboardStats()
  const { data: shipments, isLoading: shipmentsLoading, refetch, error } = useShipments()

  const PAGE_SIZE = 10
  const filtered = (shipments ?? []).filter((s) => {
    const matchSearch =
      !search ||
      s.reference.toLowerCase().includes(search.toLowerCase()) ||
      s.originCountry.toLowerCase().includes(search.toLowerCase()) ||
      s.destinationCountry.toLowerCase().includes(search.toLowerCase())
    const matchStatus = statusFilter === "all" || s.status === statusFilter
    return matchSearch && matchStatus
  })
  const totalPages = Math.ceil(filtered.length / PAGE_SIZE)
  const paged = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  const STAT_CARDS: StatCardProps[] = [
    {
      title: "Total Shipments",
      value: stats?.totalShipments ?? 0,
      description: "All saved shipments",
      icon: Package,
      iconClass: "bg-blue-50 text-blue-600 dark:bg-blue-950 dark:text-blue-400",
    },
    {
      title: "Pending Validation",
      value: stats?.pendingValidations ?? 0,
      description: "Currently processing",
      icon: Clock,
      iconClass: "bg-amber-50 text-amber-600 dark:bg-amber-950 dark:text-amber-400",
    },
    {
      title: "Requires Review",
      value: stats?.requiresReview ?? 0,
      description: "Awaiting human review",
      icon: AlertTriangle,
      iconClass: "bg-orange-50 text-orange-600 dark:bg-orange-950 dark:text-orange-400",
    },
    {
      title: "Completed",
      value: stats?.completedValidations ?? 0,
      description: "Finalized validations",
      icon: CheckCircle2,
      iconClass: "bg-green-50 text-green-600 dark:bg-green-950 dark:text-green-400",

    },
    {
      title: USE_MOCK ? "Total Discrepancies" : "Open Findings",
      value: stats?.totalDiscrepancies ?? 0,
      description: "Across all shipments",
      icon: XCircle,
      iconClass: "bg-red-50 text-red-600 dark:bg-red-950 dark:text-red-400",
    },
  ]

  const handleRowClick = (shipment: Shipment) => {
    if (hasResults(shipment.status)) {
      navigate(`/shipments/${shipment.id}/results`)
    } else if (shipment.status === "processing" || shipment.status === "queued") {
      navigate(`/shipments/${shipment.id}/processing`)
    } else if (shipment.status === "failed") {
      navigate(`/shipments/${shipment.id}/processing`)
    } else if (canEditDocuments(shipment.status)) {
      navigate(`/shipments/${shipment.id}/edit`)
    } else { navigate(`/shipments/${shipment.id}/results`) }
  }

  const activity = Array.from({ length: 7 }, (_, index) => {
    const day = new Date(); day.setHours(0, 0, 0, 0); day.setDate(day.getDate() - (6 - index));
    const records = (shipments ?? []).filter(shipment => new Date(shipment.createdAt).toDateString() === day.toDateString());
    return { name: day.toLocaleDateString("en", { weekday: "short" }), validated: records.length, discrepancies: records.reduce((sum, shipment) => sum + shipment.discrepancyCount, 0) };
  });
  const distribution = [{ name: "Uploading", status: "uploading", color: "#60a5fa" }, { name: "Reviewed", status: "reviewed", color: "#06b6d4" }, { name: "Archived", status: "archived", color: "#64748b" }, { name: "Draft", status: "draft", color: "#94a3b8" }, { name: "Queued", status: "queued", color: "#eab308" }, { name: "Processing", status: "processing", color: "#3b82f6" }, { name: "Needs review", status: "ready_for_review", color: "#f97316" }, { name: "Finalized", status: "finalized", color: "#22c55e" }, { name: "Failed", status: "failed", color: "#ef4444" }].map(item => ({ ...item, value: (shipments ?? []).filter(shipment => shipment.status === item.status).length })).filter(item => item.value > 0);
  if (error) return <ErrorState error={error} retry={() => refetch()} />;
  return (
    <div className="p-6 space-y-6 animate-fade-in-up">
      {/* Page Header */}
      <div className="flex flex-wrap gap-3 items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{location.pathname === "/analytics" ? "Analytics" : location.pathname === "/shipments" ? "Shipments" : "Dashboard"}</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Monitor and manage your trade document validations
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()} className="gap-1.5">
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
          <Button size="sm" onClick={() => navigate("/shipments/new")} className="gap-1.5">
            <Plus className="h-3.5 w-3.5" />
            New Shipment
          </Button>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-5">
        {statsLoading
          ? Array.from({ length: 5 }).map((_, i) => <CardSkeleton key={i} />)
          : STAT_CARDS.map((card) => <StatCard key={card.title} {...card} />)}
      </div>

      {/* Charts Row */}
      <div className="grid gap-4 lg:grid-cols-3">
        {/* Area Chart */}
        <Card className="lg:col-span-2">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>Shipment Activity</CardTitle>
                <CardDescription>Shipments created each day and their current findings</CardDescription>
              </div>
              <Badge variant="secondary" className="gap-1">
                <ArrowUpRight className="h-3 w-3" />
                This week
              </Badge>
            </div>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={activity}>
                <defs>
                  <linearGradient id="validatedGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="hsl(221, 83%, 53%)" stopOpacity={0.15} />
                    <stop offset="95%" stopColor="hsl(221, 83%, 53%)" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="discrepancyGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#ef4444" stopOpacity={0.15} />
                    <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="name" tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                <YAxis tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                <Tooltip
                  contentStyle={chartTooltipStyle}
                  labelStyle={{ color: "hsl(var(--popover-foreground))" }}
                />
                <Area isAnimationActive={false}
                  type="monotone"
                  dataKey="validated"
                  name="Shipments created"
                  stroke="hsl(221, 83%, 53%)"
                  strokeWidth={2}
                  fill="url(#validatedGrad)"
                />
                <Area isAnimationActive={false}
                  type="monotone"
                  dataKey="discrepancies"
                  name="Current findings"
                  stroke="#ef4444"
                  strokeWidth={2}
                  fill="url(#discrepancyGrad)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Pie Chart */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle>Validation Distribution</CardTitle>
            <CardDescription>Current shipment statuses</CardDescription>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie isAnimationActive={false}
                  data={distribution}
                  cx="50%"
                  cy="45%"
                  innerRadius={55}
                  outerRadius={80}
                  paddingAngle={3}
                  dataKey="value"
                >
                  {distribution.map((entry, idx) => (
                    <Cell key={idx} fill={entry.color} />
                  ))}
                </Pie>
                <Legend
                  iconType="circle"
                  iconSize={8}
                  wrapperStyle={{ fontSize: "11px", paddingTop: "8px" }}
                />
                <Tooltip
                  contentStyle={chartTooltipStyle}
                  itemStyle={{ color: "hsl(var(--popover-foreground))" }}
                />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* Shipments Table */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div>
              <CardTitle>Recent Shipments</CardTitle>
              <CardDescription>Click a row to view validation details</CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  aria-label="Filter shipments"
                  placeholder="Search..."
                  value={search}
                  onChange={(e) => { setSearch(e.target.value); setPage(1) }}
                  className="pl-8 h-8 w-48 text-sm"
                />
              </div>
              <select
                className="h-8 rounded-md border border-input bg-background px-2 text-xs focus:ring-1 focus:ring-ring"
                aria-label="Shipment status"
                value={statusFilter}
                onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }}
              >
                <option value="all">All statuses</option>
                <option value="draft">Draft</option><option value="uploading">Uploading</option><option value="reviewed">Reviewed</option><option value="archived">Archived</option>
                <option value="queued">Queued</option>
                <option value="processing">Processing</option>
                <option value="ready_for_review">Ready for Review</option>
                <option value="finalized">Finalized</option>
                <option value="failed">Failed</option>
              </select>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {shipmentsLoading ? (
            <div className="p-6">
              <TableSkeleton rows={5} cols={7} />
            </div>
          ) : paged.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <Package className="h-10 w-10 text-muted-foreground/40 mb-3" />
              <p className="text-sm font-medium text-muted-foreground">No shipments found</p>
              <p className="text-xs text-muted-foreground mt-1">
                {search || statusFilter !== "all"
                  ? "Try adjusting your filters"
                  : "Create your first shipment to get started"}
              </p>
              {!search && statusFilter === "all" && (
                <Button
                  size="sm"
                  className="mt-4 gap-1.5"
                  onClick={() => navigate("/shipments/new")}
                >
                  <Plus className="h-3.5 w-3.5" />
                  New Shipment
                </Button>
              )}
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b bg-muted/30">
                      <th className="py-2.5 px-4 text-left text-xs font-medium text-muted-foreground">Reference</th>
                      <th className="py-2.5 px-4 text-left text-xs font-medium text-muted-foreground">Origin</th>
                      <th className="py-2.5 px-4 text-left text-xs font-medium text-muted-foreground">Destination</th>
                      <th className="py-2.5 px-4 text-left text-xs font-medium text-muted-foreground">Documents</th>
                      <th className="py-2.5 px-4 text-left text-xs font-medium text-muted-foreground">Status</th>
                      <th className="py-2.5 px-4 text-left text-xs font-medium text-muted-foreground">Discrepancies</th>
                      <th className="py-2.5 px-4 text-left text-xs font-medium text-muted-foreground">Created</th>
                      <th className="py-2.5 px-4 w-10" />
                    </tr>
                  </thead>
                  <tbody>
                    {paged.map((shipment) => (
                      <ShipmentRow
                        key={shipment.id}
                        shipment={shipment}
                        onClick={() => handleRowClick(shipment)}
                      />
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between border-t px-4 py-3">
                  <p className="text-xs text-muted-foreground">
                    Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, filtered.length)} of {filtered.length} shipments
                  </p>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPage(p => p - 1)}
                      disabled={page === 1}
                    >
                      Previous
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPage(p => p + 1)}
                      disabled={page === totalPages}
                    >
                      Next
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {/* Last Updated */}
      <p className="text-xs text-muted-foreground text-center">
        Last updated: {formatDateTime(new Date().toISOString())} · {USE_MOCK ? "Demonstration data" : "Loaded from the backend"}
      </p>
    </div>
  )
}
