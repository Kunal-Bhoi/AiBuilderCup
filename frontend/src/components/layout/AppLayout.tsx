import { USE_MOCK } from "@/services/shipmentService"
import { Outlet } from "react-router-dom"
import { Sidebar } from "./Sidebar"
import { Header } from "./Header"
import { TooltipProvider } from "@/components/ui/tooltip"

export function AppLayout() {
  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex h-screen overflow-hidden bg-background">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <Header />
          {USE_MOCK && <div className="border-b bg-blue-50/60 px-4 py-2 text-[11px] text-blue-800 dark:bg-blue-950/30 dark:text-blue-200">Demo workspace | Files stay in your browser. Results use a predefined sample and do not analyse uploaded content.</div>}
          <main className="flex-1 overflow-y-auto">
            <Outlet />
          </main>
        </div>
      </div>
    </TooltipProvider>
  )
}
