/**
 * RFC 9457 Problem Details — the single error shape the backend emits for every
 * failure (see backend/app/api/errors.py). `code` is the stable machine string
 * the UI branches on; `detail` is safe to show a user.
 */
export interface ProblemDetails {
  type?: string;
  title?: string;
  status: number;
  detail?: string;
  /** Request id — quotable in a support ticket. */
  instance?: string;
  /** Stable machine code, e.g. "NOT_FOUND", "VALIDATION_ERROR". */
  code?: string;
  /** Field-level errors from FastAPI/Pydantic validation failures. */
  errors?: Array<{ field?: string; loc?: (string | number)[]; message?: string; msg?: string }>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly instance?: string;
  readonly problem: ProblemDetails;

  constructor(problem: ProblemDetails) {
    super(problem.detail || problem.title || `Request failed (${problem.status})`);
    this.name = "ApiError";
    this.status = problem.status;
    this.code = problem.code ?? "UNKNOWN";
    this.instance = problem.instance;
    this.problem = problem;
  }

  get isUnauthorized() {
    return this.status === 401;
  }

  get isForbidden() {
    return this.status === 403;
  }

  get isNotFound() {
    return this.status === 404;
  }

  get isValidation() {
    return this.status === 422 || this.code === "VALIDATION_ERROR";
  }

  /**
   * Map backend field errors onto react-hook-form field names.
   * Pydantic reports `loc: ["body", "email"]`; we want `email`.
   */
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const err of this.problem.errors ?? []) {
      const field =
        err.field ?? (err.loc ?? []).filter((p) => p !== "body" && p !== "query").join(".");
      const message = err.message ?? err.msg;
      if (field && message) out[field] = message;
    }
    return out;
  }
}

/** Normalise any thrown value into a user-presentable message. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}

/** Parse a fetch Response into a ProblemDetails, tolerating non-JSON bodies. */
export async function toProblem(response: Response): Promise<ProblemDetails> {
  const fallback: ProblemDetails = {
    status: response.status,
    title: response.statusText,
    detail: `Request failed with status ${response.status}.`,
  };
  try {
    const body = await response.json();
    if (body && typeof body === "object") {
      return { ...fallback, ...body, status: body.status ?? response.status };
    }
    return fallback;
  } catch {
    return fallback;
  }
}
