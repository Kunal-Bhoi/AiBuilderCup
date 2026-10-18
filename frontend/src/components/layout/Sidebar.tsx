import { useState } from "react";
import { NavLink } from "react-router-dom";
import { LayoutDashboard, Ship, FileSearch, BarChart3, Settings, HelpCircle, ChevronLeft, ChevronRight, ShieldCheck, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
const NAV_ITEMS = [
  { icon: LayoutDashboard, label: "Dashboard", to: "/dashboard" },
  { icon: Ship, label: "Shipments", to: "/shipments" },
  { icon: FileSearch, label: "Documents", to: "/documents" },
  { icon: BarChart3, label: "Analytics", to: "/analytics" },
];
const BOTTOM_ITEMS = [{ icon: Settings, label: "Settings", to: "/settings" }, { icon: HelpCircle, label: "Help", to: "/help" }];
export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const renderLink = (item: typeof NAV_ITEMS[number]) => <NavLink key={item.to} to={item.to} title={item.label} aria-label={item.label} className={({ isActive }) => cn("my-0.5 flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors", isActive ? "bg-primary/10 text-primary font-medium" : "text-muted-foreground hover:bg-accent hover:text-foreground")}><item.icon className="h-4 w-4 shrink-0" />{!collapsed && <span className="hidden lg:inline">{item.label}</span>}</NavLink>;
  return <aside className={cn("relative flex shrink-0 flex-col border-r bg-background transition-all duration-200 print:hidden", collapsed ? "w-[60px]" : "w-[60px] lg:w-[220px]")}>
    <NavLink to="/dashboard" aria-label="TradeGuard AI dashboard" className="flex h-[73px] shrink-0 items-center gap-2.5 border-b px-4"><div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground"><ShieldCheck className="h-4 w-4" /></div>{!collapsed && <div className="hidden lg:block"><p className="text-sm font-bold">TradeGuard</p><p className="text-[10px] text-muted-foreground">AI</p></div>}</NavLink>
    <div className="px-3 pt-4 pb-2"><NavLink to="/shipments/new" aria-label="New Shipment" title="New Shipment" className="flex h-8 items-center justify-center gap-2 overflow-hidden rounded-md bg-primary text-xs font-medium text-primary-foreground hover:bg-primary/90"><Plus className="h-4 w-4 shrink-0" />{!collapsed && <span className="hidden lg:inline">New Shipment</span>}</NavLink></div>
    <nav aria-label="Main navigation" className="flex-1 overflow-y-auto px-2 py-2">{NAV_ITEMS.map(renderLink)}</nav>
    <nav aria-label="Workspace support" className="border-t px-2 py-2">{BOTTOM_ITEMS.map(renderLink)}</nav>
    <button aria-label={collapsed ? "Expand navigation" : "Collapse navigation"} onClick={() => setCollapsed(value => !value)} className="absolute -right-3 top-20 z-40 hidden h-6 w-6 items-center justify-center rounded-full border bg-background hover:bg-muted lg:flex">{collapsed ? <ChevronRight className="h-3 w-3" /> : <ChevronLeft className="h-3 w-3" />}</button>
  </aside>;
}
