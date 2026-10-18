import { useQuery, useMutation } from "@tanstack/react-query";
import { realService, USE_MOCK } from "@/services/shipmentService";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import DashboardPage from "./DashboardPage";
export default function AnalyticsPage() {
  const query = useQuery({ queryKey: ["effectiveness"], queryFn: () => realService.getEffectiveness(), enabled: !USE_MOCK });
  const verify = useMutation({ mutationFn: () => realService.verifyAudit() });
  if (USE_MOCK) return <DashboardPage />;
  if (query.error) return <ErrorState error={query.error} retry={() => query.refetch()} />;
  const data = query.data;
  const rate = (value: number | null | undefined) => value == null ? "No decisions yet" : Math.round(value * 100) + "%";
  return <div className="p-6 space-y-6"><div><h1 className="text-2xl font-semibold">Review Analytics</h1><p className="mt-1 text-sm text-muted-foreground">Human decisions and processing cost from the backend.</p></div>{!data ? <p>Loading analytics…</p> : <>
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{[{ label: "Shipments analysed", value: data.shipments_analyzed }, { label: "Decisions recorded", value: data.decisions_total }, { label: "Findings still open", value: data.undecided_discrepancies }, { label: "Processing cost", value: "$" + (data.cost.total_usd ?? 0).toFixed(4) }].map(item => <Card key={item.label}><CardContent className="pt-6"><p className="text-xs text-muted-foreground">{item.label}</p><p className="mt-2 text-2xl font-semibold">{item.value}</p></CardContent></Card>)}</div>
    <div className="grid gap-4 md:grid-cols-2"><Card><CardHeader><CardTitle>How suggestions are reviewed</CardTitle></CardHeader><CardContent className="space-y-3 text-sm"><p>Suggestion acceptance: {rate(data.suggestion_acceptance_rate)}</p><p>Override rate: {rate(data.override_rate)}</p><p>Overrides against suggested assessment: {rate(data.override_against_assessment_rate)}</p><p>Median time to decide: {data.median_seconds_to_decision == null ? "No decisions yet" : Math.round(data.median_seconds_to_decision) + " seconds"}</p></CardContent></Card><Card><CardHeader><CardTitle>Decision history check</CardTitle></CardHeader><CardContent className="space-y-3 text-sm"><p className="text-muted-foreground">Verify that the saved audit history—records of user and system actions—is consistent.</p><Button variant="outline" disabled={verify.isPending} onClick={() => verify.mutate()}>{verify.isPending ? "Checking…" : "Verify audit history"}</Button>{verify.data && <p role="status" className={verify.data.valid ? "text-green-700" : "text-destructive"}>{verify.data.valid ? "History verified" : "History check failed"} · {verify.data.events_checked} records checked</p>}{verify.error && <p role="alert" className="text-destructive">{verify.error.message}</p>}</CardContent></Card></div>
    <Card><CardHeader><CardTitle>Decisions by field</CardTitle></CardHeader><CardContent className="overflow-auto"><table className="w-full text-sm"><thead><tr className="border-b text-left"><th className="py-2">Field</th><th>Total decisions</th><th>Actions</th></tr></thead><tbody>{data.by_field.map(field => <tr key={field.field_key} className="border-b"><td className="py-3">{field.field_key.replace(/_/g, " ")}</td><td>{field.total}</td><td>{Object.entries(field.by_action).map(([action, count]) => action.toLowerCase().replace(/_/g, " ") + ": " + count).join(" · ")}</td></tr>)}</tbody></table>{data.by_field.length === 0 && <p className="py-4 text-muted-foreground">No decisions recorded yet.</p>}</CardContent></Card>
  </>}</div>;
}
