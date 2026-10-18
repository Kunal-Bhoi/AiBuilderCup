import { lazy, Suspense } from "react";
import { Navigate, createBrowserRouter, useRouteError, Link } from "react-router-dom";
import { AppLayout } from "@/components/layout/AppLayout";
const DashboardPage = lazy(() => import("@/pages/DashboardPage"));
const CreateShipmentPage = lazy(() => import("@/pages/CreateShipmentPage"));
const ProcessingPage = lazy(() => import("@/pages/ProcessingPage"));
const ValidationResultsPage = lazy(() => import("@/pages/ValidationResultsPage"));
const DiscrepancyReviewPage = lazy(() => import("@/pages/DiscrepancyReviewPage"));
const FinalReportPage = lazy(() => import("@/pages/FinalReportPage"));
const DocumentsPage = lazy(() => import("@/pages/WorkspacePages").then(module => ({ default: module.DocumentsPage })));
const SettingsPage = lazy(() => import("@/pages/WorkspacePages").then(module => ({ default: module.SettingsPage })));
const HelpPage = lazy(() => import("@/pages/WorkspacePages").then(module => ({ default: module.HelpPage })));
function RouteError() {
  const error = useRouteError();
  return <div className="p-8"><h1 className="text-xl font-semibold">Unable to open this page</h1><p className="mt-2 text-sm">{error instanceof Error ? error.message : "An unexpected error occurred."}</p><Link to="/dashboard" className="mt-4 block text-primary">Return to Dashboard</Link></div>;
}
const page = (element: React.ReactNode) => <Suspense fallback={<div className="p-8 text-sm text-muted-foreground">Loading workspace…</div>}>{element}</Suspense>;
export const router = createBrowserRouter([{
  path: "/", element: <AppLayout />, errorElement: <RouteError />, children: [
    { index: true, element: <Navigate to="/dashboard" replace /> },
    { path: "dashboard", element: page(<DashboardPage />) },
    { path: "shipments", element: page(<DashboardPage />) },
    { path: "shipments/new", element: page(<CreateShipmentPage />) },
    { path: "shipments/:id/edit", element: page(<CreateShipmentPage />) },
    { path: "shipments/:id/processing", element: page(<ProcessingPage />) },
    { path: "shipments/:id/results", element: page(<ValidationResultsPage />) },
    { path: "shipments/:id/review", element: page(<DiscrepancyReviewPage />) },
    { path: "shipments/:id/report", element: page(<FinalReportPage />) },
    { path: "documents", element: page(<DocumentsPage />) },
    { path: "analytics", element: page(<DashboardPage />) },
    { path: "settings", element: page(<SettingsPage />) },
    { path: "help", element: page(<HelpPage />) },
    { path: "*", element: <div className="p-8"><h1 className="text-xl font-semibold">Page not found</h1><Link className="mt-4 block text-primary" to="/dashboard">Return to Dashboard</Link></div> },
  ],
}]);
