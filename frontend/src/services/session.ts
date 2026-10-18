import { AUTH_MODE, USE_MOCK } from "./config";
export interface Session { userId: string; orgId: string; role: "VIEWER" | "APPROVER" | "OWNER"; token: string; mode: string }
export function getSession(): Session {
  let saved: Partial<Session> = {};
  try { saved = JSON.parse(localStorage.getItem("tradeguard-session") || "{}"); } catch { /* Ignore invalid local preferences. */ }
  const token = sessionStorage.getItem("tradeguard-token") || "";
  if (USE_MOCK) return { userId: "demo-reviewer", orgId: "demo", role: "APPROVER", token: "", mode: "demo" };
  if (AUTH_MODE === "dev") return { userId: saved.userId || "user_dev", orgId: saved.orgId || "org_dev", role: saved.role || "APPROVER", token: "", mode: "dev" };
  let claims: Record<string, unknown> = {};
  try { const payload = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"); claims = JSON.parse(atob(payload.padEnd(Math.ceil(payload.length / 4) * 4, "="))); } catch { /* Server verifies the token; absent claims grant no review controls. */ }
  return { userId: String(claims.user_id || claims.sub || "Not signed in"), orgId: String(claims.org_id || ""), role: claims.role === "OWNER" || claims.role === "APPROVER" ? claims.role : "VIEWER", token, mode: "firebase" };
}
export function canReview() { return ["OWNER", "APPROVER"].includes(getSession().role); }
export function saveSession(session: Pick<Session, "userId" | "orgId" | "role">, token: string) {
  localStorage.setItem("tradeguard-session", JSON.stringify(session));
  if (token.trim()) sessionStorage.setItem("tradeguard-token", token.trim()); else sessionStorage.removeItem("tradeguard-token");
}
