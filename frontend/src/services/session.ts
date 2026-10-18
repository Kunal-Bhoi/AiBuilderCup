import { USE_MOCK } from "./config";
// No login: the workspace is directly usable. The only choice is the review role, which the server enforces.
export type Role = "VIEWER" | "APPROVER" | "OWNER";
export interface Session { userId: string; orgId: string; role: Role; mode: string }
const ROLE_KEY = "tradeguard-role";
export function getSession(): Session {
  let role: Role = "APPROVER";
  try { const saved = localStorage.getItem(ROLE_KEY); if (saved === "VIEWER" || saved === "APPROVER" || saved === "OWNER") role = saved; } catch { /* Storage unavailable: default role. */ }
  if (USE_MOCK) return { userId: "demo-reviewer", orgId: "demo", role: "APPROVER", mode: "demo" };
  return { userId: "user_dev", orgId: "org_dev", role, mode: "workspace" };
}
export function canReview() { return ["OWNER", "APPROVER"].includes(getSession().role); }
export function saveRole(role: Role) { try { localStorage.setItem(ROLE_KEY, role); } catch { /* Storage unavailable: role stays default. */ } }
