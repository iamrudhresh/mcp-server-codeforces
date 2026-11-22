/**
 * Error taxonomy shared by every Codeforces MCP code path.
 *
 * `code` is a stable, machine-readable string the LLM (and the tests) can branch
 * on. `retryable` tells the HTTP layer whether a backoff retry is worthwhile.
 */
export class CodeforcesError extends Error {
  constructor(message, { code = "ERROR", status, retryable = false, retryAfterMs } = {}) {
    super(message);
    this.name = "CodeforcesError";
    this.code = code;
    this.status = status;
    this.retryable = retryable;
    this.retryAfterMs = retryAfterMs;
  }
}

/**
 * Which "layer" an error belongs to, so `get_health` can report something
 * meaningful.
 */
export function errorLayer(code) {
  if (code === "NETWORK_TIMEOUT") return "transport";
  if (code === "RATE_LIMITED" || code === "NOT_FOUND" || code === "UPSTREAM" || code === "SCHEMA_CHANGED") {
    return "upstream";
  }
  return "broker";
}

export function isRetryableCode(code) {
  return code === "RATE_LIMITED" || code === "NETWORK_TIMEOUT" || code === "UPSTREAM";
}
