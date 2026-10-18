/**
 * Axios HTTP client for real backend integration.
 * Switch VITE_USE_MOCK=false to use real endpoints.
 */

import axios from "axios";

const BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

export const apiClient = axios.create({
  baseURL: BASE_URL,
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
  },
});

// Request interceptor – attach auth token if present
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem("auth_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor – normalise errors
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const message =
      error.response?.data?.detail ??
      error.response?.data?.message ??
      error.message ??
      "An unexpected error occurred";
    const readable = typeof message === "string" ? message : Array.isArray(message)
      ? message.map((item: { msg?: string }) => item.msg ?? "Invalid request field").join(". ")
      : "The backend could not complete this request.";
    return Promise.reject(new Error(readable));
  }
);
