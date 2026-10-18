import { Link, useLocation, useNavigate } from "react-router-dom";
import { Bell, Search, Sun, Moon, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { useShipments } from "@/hooks/useShipments";
export function Header() {
  const location = useLocation();
  const navigate = useNavigate();
  const [dark, setDark] = useState(() => localStorage.getItem("tradeguard-theme") === "dark");
  const [search, setSearch] = useState("");
  const [notifications, setNotifications] = useState(false);
  const { data: shipments } = useShipments();
  const pending = (shipments ?? []).filter(shipment => ["ready_for_review", "failed"].includes(shipment.status));
  useEffect(() => { document.documentElement.classList.toggle("dark", dark); localStorage.setItem("tradeguard-theme", dark ? "dark" : "light"); }, [dark]);
  const parts = location.pathname.split("/").filter(Boolean);
  const labels: Record<string, string> = { dashboard: "Dashboard", shipments: "Shipments", new: "New Shipment", edit: "Documents", processing: "Processing", results: "Validation Results", review: "Discrepancy Review", report: "Final Report", documents: "Documents", analytics: "Analytics", settings: "Settings", help: "Help" };
  const shipment = shipments?.find(item => item.id === parts[1]);
  return <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b bg-background/95 px-4 backdrop-blur-sm">
    <nav aria-label="Breadcrumbs" className="flex min-w-0 flex-1 items-center gap-2 text-xs"><Link to="/dashboard" className="text-muted-foreground hidden sm:block">TradeGuard AI</Link><ChevronRight className="h-3 w-3 text-muted-foreground hidden sm:block" /><span className="truncate font-medium">{shipment ? shipment.reference + " / " : ""}{labels[parts[parts.length - 1] ?? "dashboard"] ?? "Workspace"}</span></nav>
    <form className="relative hidden md:block w-56" onSubmit={event => { event.preventDefault(); navigate("/dashboard?q=" + encodeURIComponent(search)); }}><Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-muted-foreground" /><Input aria-label="Search shipments" placeholder="Search shipments, press Enter" value={search} onChange={e => setSearch(e.target.value)} className="h-8 pl-8 text-xs bg-muted/40" /></form>
    <Button variant="ghost" size="icon-sm" aria-label="Notifications" onClick={() => setNotifications(true)} className="relative"><Bell />{pending.length > 0 && <span className="absolute top-1 right-1 h-1.5 w-1.5 rounded-full bg-primary" />}</Button>
    <Button variant="ghost" size="icon-sm" aria-label="Toggle theme" onClick={() => setDark(value => !value)}>{dark ? <Sun /> : <Moon />}</Button>
    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary" title="Sarah Chen · Customs Broker">SC</div>
    <Dialog open={notifications} onOpenChange={setNotifications}><DialogContent><DialogHeader><DialogTitle>Needs your attention</DialogTitle><DialogDescription>Current shipments awaiting review or a retry.</DialogDescription></DialogHeader><div className="space-y-2">{pending.length === 0 ? <p className="text-sm text-muted-foreground">You're all caught up.</p> : pending.map(item => <Link key={item.id} to={"/shipments/" + item.id + (item.status === "failed" ? "/processing" : "/results")} onClick={() => setNotifications(false)} className="block rounded-lg border p-3 hover:bg-muted"><p className="text-sm font-medium">{item.reference}</p><p className="text-xs text-muted-foreground">{item.status === "failed" ? "Validation failed. Retry processing." : "Ready for human review."}</p></Link>)}</div></DialogContent></Dialog>
  </header>;
}
