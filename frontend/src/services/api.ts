import axios from "axios";
import { API_BASE_URL } from "./config";
import { getSession } from "./session";
export class ApiError extends Error {
  constructor(message: string, public status?: number, public code?: string, public retryable = false, public details?: Record<string, unknown>, public requestId?: string) { super(message); this.name = "ApiError"; }
}
export const apiClient = axios.create({ baseURL: API_BASE_URL, timeout: 30000 });
apiClient.interceptors.request.use(config => {
  const session = getSession();
  if (session.mode === "dev") {
    config.headers.set("X-Dev-User", session.userId); config.headers.set("X-Dev-Org", session.orgId); config.headers.set("X-Dev-Role", session.role);
  } else if (session.token) config.headers.set("Authorization", "Bearer " + session.token);
  return config;
});
apiClient.interceptors.response.use(response => response, async error => {
  let data = error.response?.data;
  if (data instanceof Blob) { try { data = JSON.parse(await data.text()); } catch { data = undefined; } }
  const envelope = data?.error;
  const message = envelope?.message || (typeof data?.detail === "string" ? data.detail : undefined) || (error.response?.status === 401 ? "Sign in again in Settings. Your session is missing or expired." : error.message) || "The server could not complete this request.";
  return Promise.reject(new ApiError(message, error.response?.status, envelope?.code, envelope?.retryable ?? false, envelope?.details, envelope?.request_id));
});
