import axios from "axios";
import { API_BASE_URL } from "./config";
import { getSession } from "./session";
export class ApiError extends Error {
  constructor(message: string, public status?: number, public code?: string, public retryable = false, public details?: Record<string, unknown>, public requestId?: string) { super(message); this.name = "ApiError"; }
}
export const apiClient = axios.create({ baseURL: API_BASE_URL, timeout: 30000 });
apiClient.interceptors.request.use(config => {
  // No login: the workspace identity and the selected review role travel as headers; the server enforces the role.
  const session = getSession();
  config.headers.set("X-Dev-User", session.userId); config.headers.set("X-Dev-Org", session.orgId); config.headers.set("X-Dev-Role", session.role);
  return config;
});
apiClient.interceptors.response.use(response => response, async error => {
  let data = error.response?.data;
  if (data instanceof Blob) { try { data = JSON.parse(await data.text()); } catch { data = undefined; } }
  const envelope = data?.error;
  const message = envelope?.message || (typeof data?.detail === "string" ? data.detail : undefined) || error.message || "The server could not complete this request.";
  return Promise.reject(new ApiError(message, error.response?.status, envelope?.code, envelope?.retryable ?? false, envelope?.details, envelope?.request_id));
});
