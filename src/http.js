import { CodeforcesError } from "./errors.js";

/**
 * Hardened HTTP layer for the official Codeforces API.
 *
 * Codeforces enforces roughly "one request per two seconds" per client and
 * answers with `status: "FAILED"` + "call limit exceeded" when you exceed it,
 * so everything funnels through a single global throttle + TTL cache.
 */
const API_BASE = "https://codeforces.com/api";
const ALLOWED_HOST = "codeforces.com";
const USER_AGENT = "codeforces-mcp/1.0 (+https://github.com/iamrudhresh/mcp-server-codeforces)";

export const CACHE_TTL_MS = 10 * 60 * 1000;
const MIN_INTERVAL_MS = 1_100;
const REQUEST_TIMEOUT_MS = 30_000;
const MAX_RETRIES = 3;
const MAX_RESPONSE_BYTES = 96 * 1024 * 1024; // problemset.problems alone is ~20MB
const MAX_CACHE_ENTRIES = 64;

const cache = new Map();
let lastRequestAt = 0;
let lastError = null;
let lastLatencyMs = null;
let throttleChain = Promise.resolve();

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Serialize outbound requests. Concurrent tool calls queue on a promise chain,
 * so two callers can never read the same `lastRequestAt` and fire together.
 */
export function throttle() {
  const turn = throttleChain.then(async () => {
    const wait = MIN_INTERVAL_MS - (Date.now() - lastRequestAt);
    if (wait > 0) await sleep(wait);
    lastRequestAt = Date.now();
  });
  throttleChain = turn.catch(() => {});
  return turn;
}

/** Exposed for tests: the minimum spacing between upstream requests. */
export const MIN_REQUEST_INTERVAL_MS = MIN_INTERVAL_MS;

/**
 * Codeforces handles: letters, digits, underscore, dot, hyphen, 3-24 chars.
 * The length bounds mirror the server-side rule ("Field should contain between
 * 3 and 24 characters"), so malformed handles fail locally instead of burning
 * a rate-limited upstream request.
 */
export function isValidHandle(handle) {
  return typeof handle === "string" && /^[A-Za-z0-9._-]{3,24}$/.test(handle);
}

export function assertHandle(handle) {
  if (!isValidHandle(handle)) {
    throw new CodeforcesError(`Invalid Codeforces handle: ${JSON.stringify(handle)}`, {
      code: "INVALID_HANDLE",
    });
  }
  return handle;
}

/**
 * `contest.standings` is special: for anonymous (non-admin) callers Codeforces
 * ONLY accepts a bare `?contestId=<id>` request and rejects every extra
 * parameter — including `lang`. Paging therefore has to happen client-side.
 */
const BARE_ENDPOINTS = new Set(["contest.standings"]);

/**
 * Build an API URL.
 *
 * IMPORTANT: Codeforces defaults to Russian for problem and contest names.
 * Without `lang` the API silently returns Cyrillic titles, so we always pin
 * `lang=en`.
 */
export function buildUrl(endpoint, params = {}) {
  const url = new URL(`${API_BASE}/${endpoint}`);

  if (BARE_ENDPOINTS.has(endpoint)) {
    if (params.contestId !== undefined) url.searchParams.set("contestId", String(params.contestId));
    return url.toString();
  }

  url.searchParams.set("lang", "en");
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    url.searchParams.set(key, String(value));
  }
  return url.toString();
}

/**
 * Read a response body with a hard byte ceiling so a pathological upstream
 * response can never exhaust memory.
 */
export async function readTextCapped(res, maxBytes) {
  const declared = Number(res.headers.get("content-length") ?? 0);
  if (declared > maxBytes) {
    throw new CodeforcesError(`Response too large (${declared} bytes).`, {
      code: "RESPONSE_TOO_LARGE",
    });
  }
  if (!res.body) return res.text();

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let total = 0;
  let out = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > maxBytes) {
        await reader.cancel().catch(() => {});
        throw new CodeforcesError(`Response exceeded ${maxBytes} bytes; aborted to protect memory.`, {
          code: "RESPONSE_TOO_LARGE",
        });
      }
      out += decoder.decode(value, { stream: true });
    }
    out += decoder.decode();
    return out;
  } finally {
    try {
      reader.releaseLock();
    } catch {
      /* reader already released */
    }
  }
}

/** Detect the Codeforces "call limit exceeded" soft rate-limit. */
export function isRateLimitComment(comment) {
  return typeof comment === "string" && /call limit exceeded|limit exceeded/i.test(comment);
}

function pruneCache() {
  if (cache.size <= MAX_CACHE_ENTRIES) return;
  const oldest = [...cache.entries()].sort((a, b) => a[1].at - b[1].at);
  for (const [key] of oldest.slice(0, cache.size - MAX_CACHE_ENTRIES)) cache.delete(key);
}

export function clearCache() {
  cache.clear();
  lastError = null;
  lastLatencyMs = null;
}

/** Snapshot used by the `get_health` tool. */
export function healthSnapshot() {
  return { lastError, lastLatencyMs, cachedEntries: cache.size };
}

/**
 * Call a Codeforces API method and return its unwrapped `result` payload.
 *
 * Handles throttling, TTL caching, bounded reads, redirect pinning, exponential
 * backoff on transient failures, and the Codeforces `status: FAILED` envelope.
 */
export async function callApi(endpoint, params = {}, { force = false, ttlMs = CACHE_TTL_MS } = {}) {
  const url = buildUrl(endpoint, params);
  const cached = cache.get(url);
  if (!force && cached && Date.now() - cached.at < ttlMs) {
    return { result: cached.result, fromCache: true, url };
  }

  let lastErr;
  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    await throttle();
    const startedAt = Date.now();
    try {
      const res = await fetch(url, {
        headers: { Accept: "application/json", "User-Agent": USER_AGENT },
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
        redirect: "follow",
      });

      // Never accept a response that was redirected off Codeforces.
      if (new URL(res.url).hostname.replace(/^www\./, "") !== ALLOWED_HOST) {
        throw new CodeforcesError(
          `Refusing response redirected to unexpected host: ${new URL(res.url).hostname}`,
          { code: "UNEXPECTED_REDIRECT" },
        );
      }

      if (res.status === 429) {
        const retryAfter = Number(res.headers.get("retry-after"));
        lastErr = new CodeforcesError("Codeforces API rate limit exceeded.", {
          code: "RATE_LIMITED",
          status: 429,
          retryable: true,
          retryAfterMs: Number.isFinite(retryAfter) ? retryAfter * 1000 : 2_000,
        });
        await sleep(lastErr.retryAfterMs ?? 2_000);
        continue;
      }

      // HTTP 400 still carries a real Codeforces envelope (bad handle/contest),
      // so only 403/5xx are treated as transport-level failures.
      if (res.status >= 500 || res.status === 403) {
        lastErr = new CodeforcesError(`Codeforces responded with HTTP ${res.status}.`, {
          code: "UPSTREAM",
          status: res.status,
          retryable: true,
        });
        await sleep(600 * 2 ** attempt);
        continue;
      }

      const text = await readTextCapped(res, MAX_RESPONSE_BYTES);

      let payload;
      try {
        payload = JSON.parse(text);
      } catch {
        throw new CodeforcesError("Codeforces API returned invalid JSON.", {
          code: "SCHEMA_CHANGED",
          retryable: true,
        });
      }

      if (payload?.status === "FAILED") {
        const comment = payload.comment ?? "Codeforces API returned status FAILED.";
        if (isRateLimitComment(comment)) {
          lastErr = new CodeforcesError(comment, {
            code: "RATE_LIMITED",
            retryable: true,
            retryAfterMs: 2_000,
          });
          await sleep(2_000);
          continue;
        }
        throw new CodeforcesError(comment, {
          code: /not found|does not exist|incorrect|invalid/i.test(comment) ? "NOT_FOUND" : "UPSTREAM",
          status: res.status,
        });
      }

      if (payload?.status !== "OK" || payload.result === undefined) {
        throw new CodeforcesError("Codeforces API response did not match the expected envelope.", {
          code: "SCHEMA_CHANGED",
        });
      }

      lastLatencyMs = Date.now() - startedAt;
      lastError = null;
      cache.set(url, { result: payload.result, at: Date.now() });
      pruneCache();
      return { result: payload.result, fromCache: false, url };
    } catch (err) {
      const normalized = normalizeError(err);
      if (!normalized.retryable) {
        lastError = { code: normalized.code, message: normalized.message };
        throw normalized;
      }
      lastErr = normalized;
      await sleep(600 * 2 ** attempt);
    }
  }

  const finalError =
    lastErr instanceof CodeforcesError
      ? lastErr
      : new CodeforcesError(`Codeforces request failed after ${MAX_RETRIES} attempts.`, {
          code: "FETCH_FAILED",
          retryable: true,
        });
  lastError = { code: finalError.code, message: finalError.message };
  throw finalError;
}

function normalizeError(err) {
  if (err instanceof CodeforcesError) return err;
  if (err?.name === "TimeoutError" || err?.name === "AbortError") {
    return new CodeforcesError("Codeforces API request timed out.", {
      code: "NETWORK_TIMEOUT",
      retryable: true,
    });
  }
  return new CodeforcesError(err?.message ?? "Codeforces request failed.", {
    code: "UPSTREAM",
    retryable: true,
  });
}
