import { z } from "zod";
import {
  AuditDetailSchema,
  AuditSummarySchema,
  TokenSchema,
  UserSchema,
  type AuditInput,
  type LoginInput,
  type RegisterInput,
} from "./schemas";

const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function errorMessage(payload: unknown, fallback: string): string {
  if (typeof payload === "string" && payload.trim()) return payload;
  if (!payload || typeof payload !== "object") return fallback;

  const detail = "detail" in payload ? payload.detail : undefined;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0];
    if (first && typeof first === "object" && "msg" in first && typeof first.msg === "string") {
      return first.msg;
    }
  }
  if ("message" in payload && typeof payload.message === "string") return payload.message;
  return fallback;
}

async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  options: RequestInit = {},
  token?: string | null,
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.body) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { ...options, headers });
  } catch (error) {
    throw new ApiError(
      "Could not reach the API. Make sure FastAPI is running and VITE_API_URL is correct.",
      0,
      error,
    );
  }

  const raw = await response.text();
  let payload: unknown = null;
  if (raw) {
    try {
      payload = JSON.parse(raw);
    } catch {
      payload = raw;
    }
  }

  if (!response.ok) {
    throw new ApiError(errorMessage(payload, `Request failed with status ${response.status}.`), response.status, payload);
  }

  const parsed = schema.safeParse(payload);
  if (!parsed.success) {
    throw new ApiError("The API returned data in an unexpected format.", response.status, parsed.error.flatten());
  }
  return parsed.data;
}

export const api = {
  register(input: Omit<RegisterInput, "confirmPassword">) {
    return request("/auth/register", UserSchema, {
      method: "POST",
      body: JSON.stringify(input),
    });
  },

  login(input: LoginInput) {
    return request("/auth/login", TokenSchema, {
      method: "POST",
      body: JSON.stringify(input),
    });
  },

  me(token: string) {
    return request("/auth/me", UserSchema, {}, token);
  },

  listAudits(token: string) {
    return request("/audits?limit=50&offset=0", z.array(AuditSummarySchema), {}, token);
  },

  getAudit(token: string, auditId: number) {
    return request(`/audits/${auditId}`, AuditDetailSchema, {}, token);
  },

  createAudit(token: string, input: AuditInput) {
    return request("/audits", AuditDetailSchema, {
      method: "POST",
      body: JSON.stringify(input),
    }, token);
  },
};

export function getReadableError(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong. Please try again.";
}
