export const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true";
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api/v1";
export const AUTH_MODE = import.meta.env.VITE_AUTH_MODE || (import.meta.env.DEV ? "dev" : "firebase");
export const MAX_FILE_BYTES = 50 * 1024 * 1024;
export const MAX_DOCUMENTS = 20;
