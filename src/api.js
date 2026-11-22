import { callApi, assertHandle, healthSnapshot } from "./http.js";
import { CodeforcesError, errorLayer } from "./errors.js";
import { normalizeProblemset, searchProblems, normalizeProblemId, ratingTier } from "./normalize.js";

const ADAPTER_VERSION = "1.0.0";
const now = () => new Date().toISOString();

/**
 * Compact a raw Codeforces submission into the fields an LLM actually needs.
 * The raw objects embed the entire problem + author team and are very large.
 */
function compactSubmission(s) {
  return {
    id: s.id,
    contestId: s.contestId ?? null,
    problem: s.problem ? `${s.problem.contestId ?? s.problem.problemsetName}/${s.problem.index}` : null,
    problemName: s.problem?.name ?? null,
    problemRating: s.problem?.rating ?? null,
    tags: s.problem?.tags ?? [],
    handle: s.author?.members?.map((m) => m.handle) ?? [],
    participantType: s.author?.participantType ?? null,
    language: s.programmingLanguage ?? null,
    verdict: s.verdict ?? "TESTING",
    passedTestCount: s.passedTestCount ?? null,
    timeConsumedMillis: s.timeConsumedMillis ?? null,
    memoryConsumedBytes: s.memoryConsumedBytes ?? null,
    creationTime: s.creationTimeSeconds ? new Date(s.creationTimeSeconds * 1000).toISOString() : null,
  };
}

function compactContest(c) {
  return {
    id: c.id,
    name: c.name,
    type: c.type,
    phase: c.phase,
    frozen: c.frozen ?? false,
    durationMinutes: c.durationSeconds ? Math.round(c.durationSeconds / 60) : null,
    startTime: c.startTimeSeconds ? new Date(c.startTimeSeconds * 1000).toISOString() : null,
    relativeTimeSeconds: c.relativeTimeSeconds ?? null,
    difficulty: c.difficulty ?? null,
    url: `https://codeforces.com/contest/${c.id}`,
  };
}

function compactUser(u) {
  return {
    handle: u.handle,
    firstName: u.firstName ?? null,
    lastName: u.lastName ?? null,
    country: u.country ?? null,
    city: u.city ?? null,
    organization: u.organization ?? null,
    rating: u.rating ?? null,
    maxRating: u.maxRating ?? null,
    rank: u.rank ?? null,
    maxRank: u.maxRank ?? null,
    tier: ratingTier(u.rating)?.tier ?? null,
    contribution: u.contribution ?? 0,
    friendOfCount: u.friendOfCount ?? 0,
    registrationTime: u.registrationTimeSeconds
      ? new Date(u.registrationTimeSeconds * 1000).toISOString()
      : null,
    lastOnline: u.lastOnlineTimeSeconds ? new Date(u.lastOnlineTimeSeconds * 1000).toISOString() : null,
    avatar: u.titlePhoto ?? u.avatar ?? null,
    profileUrl: `https://codeforces.com/profile/${u.handle}`,
  };
}

const clamp = (value, min, max, fallback) => {
  const n = Number(value ?? fallback);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, Math.trunc(n)));
};

/* ─────────────────────────── Problemset ─────────────────────────── */

/**
 * The full problemset is ~20MB and rarely changes, so it is fetched once and
 * memoized behind the HTTP TTL cache. Concurrent callers share one in-flight
 * request instead of stampeding the upstream rate limit.
 */
let problemsetPromise = null;
let problemsetCache = null;
const PROBLEMSET_TTL_MS = 30 * 60 * 1000;

export async function loadProblemset({ force = false } = {}) {
  if (!force && problemsetCache && Date.now() - problemsetCache.at < PROBLEMSET_TTL_MS) {
    return problemsetCache.summaries;
  }
  if (!force && problemsetPromise) return problemsetPromise;

  problemsetPromise = callApi("problemset.problems", {}, { force, ttlMs: PROBLEMSET_TTL_MS })
    .then(({ result }) => {
      const summaries = normalizeProblemset(result);
      problemsetCache = { summaries, at: Date.now() };
      return summaries;
    })
    .finally(() => {
      problemsetPromise = null;
    });

  return problemsetPromise;
}

export function resetProblemsetCache() {
  problemsetCache = null;
  problemsetPromise = null;
}

/** Full-text + id + tag + rating search over the official problemset. */
export async function searchProblemset(query, { limit = 10 } = {}) {
  if (typeof query !== "string" || !query.trim()) {
    throw new CodeforcesError("Search query must be a non-empty string.", { code: "INVALID_INPUT" });
  }
  const summaries = await loadProblemset();
  const items = searchProblems(summaries, query, clamp(limit, 1, 50, 10));
  return {
    query,
    totalIndexed: summaries.length,
    returned: items.length,
    items,
    source: "https://codeforces.com/api/problemset.problems",
    fetchedAt: now(),
  };
}

/** Resolve one problem's metadata by `158A`, `158/A` or `158-A`. */
export async function getProblemMetadata(nativeId) {
  const normalized = normalizeProblemId(nativeId).toUpperCase();
  if (!normalized) {
    throw new CodeforcesError("Problem id must be a non-empty string.", { code: "INVALID_INPUT" });
  }
  const summaries = await loadProblemset();
  const found = summaries.find((s) => s.nativeId.toUpperCase() === normalized);
  if (!found) {
    throw new CodeforcesError(`Codeforces problem "${nativeId}" was not found.`, { code: "NOT_FOUND" });
  }
  return { ...found, fetchedAt: now() };
}

/** Filter the problemset by tag / rating range without a free-text query. */
export async function listProblemsByFilter({ tags = [], minRating, maxRating, limit = 25 } = {}) {
  const summaries = await loadProblemset();
  const wanted = tags.map((t) => String(t).toLowerCase());
  const bounded = minRating !== undefined || maxRating !== undefined;
  const lo = minRating ?? 0;
  const hi = maxRating ?? Infinity;

  const matched = summaries
    .filter((p) => {
      if (wanted.length && !wanted.every((t) => p.tags.some((tag) => tag.toLowerCase() === t))) return false;
      // Unrated problems only qualify when no rating bound was requested.
      if (p.rating === null) return !bounded;
      return p.rating >= lo && p.rating <= hi;
    })
    .sort((a, b) => (b.solvedCount ?? 0) - (a.solvedCount ?? 0));
  const items = matched.slice(0, clamp(limit, 1, 100, 25));

  return {
    filters: { tags, minRating: minRating ?? null, maxRating: maxRating ?? null },
    totalIndexed: summaries.length,
    matched: matched.length,
    returned: items.length,
    items,
    fetchedAt: now(),
  };
}

/* ───────────────────────────── Users ───────────────────────────── */

/** Profile(s) for 1..10 handles. Codeforces accepts a semicolon-separated list. */
export async function getUserInfo(handles) {
  const list = (Array.isArray(handles) ? handles : String(handles).split(/[;,]/))
    .map((h) => String(h).trim())
    .filter(Boolean);

  if (!list.length) {
    throw new CodeforcesError("At least one handle is required.", { code: "INVALID_INPUT" });
  }
  if (list.length > 10) {
    throw new CodeforcesError("At most 10 handles can be requested at once.", { code: "INVALID_INPUT" });
  }
  list.forEach(assertHandle);

  const { result } = await callApi("user.info", { handles: list.join(";") });
  return { users: result.map(compactUser), fetchedAt: now() };
}

/** Rating history with per-contest deltas, newest first. */
export async function getUserRating(handle, { limit = 50 } = {}) {
  assertHandle(handle);
  const { result } = await callApi("user.rating", { handle });

  const history = result.map((entry) => ({
    contestId: entry.contestId,
    contestName: entry.contestName,
    rank: entry.rank,
    oldRating: entry.oldRating,
    newRating: entry.newRating,
    ratingChange: entry.newRating - entry.oldRating,
    tier: ratingTier(entry.newRating)?.tier ?? null,
    date: entry.ratingUpdateTimeSeconds
      ? new Date(entry.ratingUpdateTimeSeconds * 1000).toISOString()
      : null,
  }));

  const best = history.reduce((acc, h) => (!acc || h.newRating > acc.newRating ? h : acc), null);
  const current = history.at(-1) ?? null;

  return {
    handle,
    totalContests: history.length,
    currentRating: current?.newRating ?? null,
    currentTier: current ? ratingTier(current.newRating)?.tier ?? null : null,
    bestRating: best ? { rating: best.newRating, contest: best.contestName, date: best.date } : null,
    biggestGain: history.reduce((acc, h) => (!acc || h.ratingChange > acc.ratingChange ? h : acc), null),
    biggestDrop: history.reduce((acc, h) => (!acc || h.ratingChange < acc.ratingChange ? h : acc), null),
    contests: history.slice(-clamp(limit, 1, 500, 50)).reverse(),
    profileUrl: `https://codeforces.com/profile/${handle}`,
    fetchedAt: now(),
  };
}

/** Recent submissions for a handle, compacted to keep the context small. */
export async function getUserSubmissions(handle, { from = 1, count = 25 } = {}) {
  assertHandle(handle);
  const { result } = await callApi("user.status", {
    handle,
    from: clamp(from, 1, 1_000_000, 1),
    count: clamp(count, 1, 200, 25),
  });
  return {
    handle,
    returned: result.length,
    submissions: result.map(compactSubmission),
    fetchedAt: now(),
  };
}

/**
 * Derived analytics over a user's submission history: solve counts, verdict
 * spread, language usage, tag strengths and rating distribution.
 */
export async function getUserStats(handle, { sampleSize = 2000 } = {}) {
  assertHandle(handle);
  const { result } = await callApi("user.status", {
    handle,
    from: 1,
    count: clamp(sampleSize, 100, 10_000, 2000),
  });

  const solved = new Set();
  const attempted = new Set();
  const verdicts = {};
  const languages = {};
  const tags = {};
  const ratings = {};

  for (const s of result) {
    const key = s.problem ? `${s.problem.contestId ?? s.problem.problemsetName}/${s.problem.index}` : null;
    if (key) attempted.add(key);

    const verdict = s.verdict ?? "TESTING";
    verdicts[verdict] = (verdicts[verdict] ?? 0) + 1;
    if (s.programmingLanguage) {
      languages[s.programmingLanguage] = (languages[s.programmingLanguage] ?? 0) + 1;
    }

    if (verdict === "OK" && key && !solved.has(key)) {
      solved.add(key);
      for (const tag of s.problem?.tags ?? []) tags[tag] = (tags[tag] ?? 0) + 1;
      if (typeof s.problem?.rating === "number") {
        ratings[s.problem.rating] = (ratings[s.problem.rating] ?? 0) + 1;
      }
    }
  }

  const top = (obj, n) =>
    Object.entries(obj)
      .sort((a, b) => b[1] - a[1])
      .slice(0, n)
      .map(([name, count]) => ({ name, count }));

  const solvedRatingKeys = Object.keys(ratings).map(Number);

  return {
    handle,
    submissionsAnalyzed: result.length,
    uniqueProblemsAttempted: attempted.size,
    uniqueProblemsSolved: solved.size,
    acceptanceRate: result.length
      ? Number((((verdicts.OK ?? 0) / result.length) * 100).toFixed(1))
      : 0,
    verdicts,
    topLanguages: top(languages, 5),
    topTags: top(tags, 12),
    solvedByRating: Object.fromEntries(
      Object.entries(ratings).sort((a, b) => Number(a[0]) - Number(b[0])),
    ),
    hardestSolvedRating: solvedRatingKeys.length ? Math.max(...solvedRatingKeys) : null,
    profileUrl: `https://codeforces.com/profile/${handle}`,
    fetchedAt: now(),
  };
}

/** Side-by-side comparison of 2-5 handles. */
export async function compareUsers(handles) {
  if (!Array.isArray(handles) || handles.length < 2 || handles.length > 5) {
    throw new CodeforcesError("Provide between 2 and 5 handles to compare.", { code: "INVALID_INPUT" });
  }
  const { users } = await getUserInfo(handles);
  const ranked = [...users].sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0));
  return { users: ranked, highestRated: ranked[0]?.handle ?? null, fetchedAt: now() };
}

/**
 * The rated user list is enormous (hundreds of thousands of users), so it is
 * always truncated; unbounded it would blow past any model's context window.
 */
export async function getRatedUsers({ activeOnly = true, limit = 100, minRating } = {}) {
  const cap = clamp(limit, 1, 1000, 100);
  const { result } = await callApi(
    "user.ratedList",
    { activeOnly: activeOnly ? "true" : "false" },
    { ttlMs: 60 * 60 * 1000 },
  );
  const filtered = minRating ? result.filter((u) => (u.rating ?? 0) >= minRating) : result;
  const page = filtered.slice(0, cap);
  return {
    activeOnly,
    minRating: minRating ?? null,
    totalRatedUsers: result.length,
    matched: filtered.length,
    returned: page.length,
    users: page.map(compactUser),
    fetchedAt: now(),
  };
}

/* ──────────────────────────── Contests ──────────────────────────── */

/**
 * Contest list, optionally filtered by phase (BEFORE / CODING / FINISHED).
 * `contest.list` returns ~1800 contests, so the result is always capped.
 */
export async function getContestList({ gym = false, phase, limit = 25 } = {}) {
  const { result } = await callApi("contest.list", { gym: gym ? "true" : undefined });
  const wanted = phase ? String(phase).toUpperCase() : null;
  const filtered = wanted ? result.filter((c) => c.phase === wanted) : result;
  const page = filtered.slice(0, clamp(limit, 1, 200, 25));
  return {
    gym,
    phase: wanted,
    totalContests: result.length,
    matched: filtered.length,
    returned: page.length,
    contests: page.map(compactContest),
    fetchedAt: now(),
  };
}

/** Upcoming contests (phase BEFORE), soonest first. */
export async function getUpcomingContests({ limit = 10 } = {}) {
  const { result } = await callApi("contest.list", {}, { ttlMs: 5 * 60 * 1000 });
  const upcoming = result
    .filter((c) => c.phase === "BEFORE")
    .sort((a, b) => (a.startTimeSeconds ?? 0) - (b.startTimeSeconds ?? 0))
    .slice(0, clamp(limit, 1, 50, 10))
    .map((c) => ({
      ...compactContest(c),
      startsInHours:
        c.relativeTimeSeconds !== undefined ? Number((-c.relativeTimeSeconds / 3600).toFixed(1)) : null,
    }));
  return { returned: upcoming.length, contests: upcoming, fetchedAt: now() };
}

/** Standings for a contest, with problem list and a bounded row window. */
export async function getContestStandings(contestId, { from = 1, count = 20, handles, showUnofficial = false } = {}) {
  const id = Number(contestId);
  if (!Number.isInteger(id) || id <= 0) {
    throw new CodeforcesError("contestId must be a positive integer.", { code: "INVALID_INPUT" });
  }
  const handleList = Array.isArray(handles) ? handles.filter(Boolean) : null;
  if (handleList?.length) handleList.forEach(assertHandle);

  // Anonymous callers may only request `?contestId=<id>`; Codeforces rejects
  // from/count/handles/showUnofficial outright. So we fetch the full standings
  // once (cached) and apply the window locally.
  const { result } = await callApi("contest.standings", { contestId: id }, { ttlMs: 10 * 60 * 1000 });

  const wanted = handleList?.length ? new Set(handleList.map((h) => h.toLowerCase())) : null;
  const start = clamp(from, 1, 1_000_000, 1) - 1;
  const size = clamp(count, 1, 200, 20);

  const allRows = (result.rows ?? []).filter((row) => {
    if (!showUnofficial && row.party?.participantType && row.party.participantType !== "CONTESTANT") {
      return false;
    }
    if (!wanted) return true;
    return (row.party?.members ?? []).some((m) => wanted.has(String(m.handle).toLowerCase()));
  });

  const rows = allRows.slice(start, start + size);

  return {
    contest: compactContest(result.contest),
    totalRows: (result.rows ?? []).length,
    matchedRows: allRows.length,
    from: start + 1,
    problems: (result.problems ?? []).map((p) => ({
      index: p.index,
      name: p.name,
      rating: p.rating ?? null,
      points: p.points ?? null,
      tags: p.tags ?? [],
    })),
    returned: rows.length,
    rows: rows.map((row) => ({
      rank: row.rank,
      party: row.party?.members?.map((m) => m.handle) ?? [],
      participantType: row.party?.participantType ?? null,
      points: row.points,
      penalty: row.penalty,
      successfulHacks: row.successfulHackCount ?? 0,
      unsuccessfulHacks: row.unsuccessfulHackCount ?? 0,
      problemResults: (row.problemResults ?? []).map((pr) => ({
        points: pr.points,
        rejectedAttempts: pr.rejectedAttemptCount ?? 0,
        type: pr.type,
        bestSubmissionTimeSeconds: pr.bestSubmissionTimeSeconds ?? null,
      })),
    })),
    fetchedAt: now(),
  };
}

/** Rating deltas applied after a rated contest. */
export async function getContestRatingChanges(contestId, { limit = 50 } = {}) {
  const id = Number(contestId);
  if (!Number.isInteger(id) || id <= 0) {
    throw new CodeforcesError("contestId must be a positive integer.", { code: "INVALID_INPUT" });
  }
  const { result } = await callApi("contest.ratingChanges", { contestId: id });
  const page = result.slice(0, clamp(limit, 1, 500, 50));
  return {
    contestId: id,
    totalParticipants: result.length,
    returned: page.length,
    changes: page.map((c) => ({
      handle: c.handle,
      rank: c.rank,
      oldRating: c.oldRating,
      newRating: c.newRating,
      ratingChange: c.newRating - c.oldRating,
      date: c.ratingUpdateTimeSeconds ? new Date(c.ratingUpdateTimeSeconds * 1000).toISOString() : null,
    })),
    fetchedAt: now(),
  };
}

/** Submissions made in a contest, optionally narrowed to one handle. */
export async function getContestStatus(contestId, { handle, from = 1, count = 25 } = {}) {
  const id = Number(contestId);
  if (!Number.isInteger(id) || id <= 0) {
    throw new CodeforcesError("contestId must be a positive integer.", { code: "INVALID_INPUT" });
  }
  if (handle) assertHandle(handle);

  const { result } = await callApi("contest.status", {
    contestId: id,
    handle: handle || undefined,
    from: clamp(from, 1, 1_000_000, 1),
    count: clamp(count, 1, 200, 25),
  });
  return {
    contestId: id,
    handle: handle ?? null,
    returned: result.length,
    submissions: result.map(compactSubmission),
    fetchedAt: now(),
  };
}

/** Most recent submissions across the whole platform. */
export async function getRecentSubmissions({ count = 25 } = {}) {
  const { result } = await callApi(
    "problemset.recentStatus",
    { count: clamp(count, 1, 1000, 25) },
    { ttlMs: 60 * 1000 },
  );
  return { returned: result.length, submissions: result.map(compactSubmission), fetchedAt: now() };
}

/* ──────────────────── Capabilities & Health ──────────────────── */

/**
 * Describe what this adapter can and cannot do. Deliberately explicit about
 * the *unsupported* operations so an agent never tries to submit code.
 */
export function getCapabilities(transport = "local_stdio") {
  const checkedAt = now();
  const op = (name, status, toolName, reason) => ({
    name,
    status,
    toolName: toolName ?? null,
    transport,
    auth: "none",
    risk: "R0_public_read",
    compliance: "official",
    reason: reason ?? null,
    checkedAt,
  });

  return {
    providerId: "codeforces-official-api",
    providerVersion: ADAPTER_VERSION,
    platform: "codeforces",
    transport,
    readOnly: true,
    operations: [
      op("searchProblems", "available", "search_problems"),
      op("listProblems", "available", "list_problems"),
      op(
        "fetchProblem",
        "degraded",
        "get_problem_metadata",
        "The official API exposes metadata only; full statements are not available.",
      ),
      op("fetchProfile", "available", "get_user_info"),
      op("listSubmissions", "available", "get_user_submissions"),
      op("fetchContests", "available", "get_contest_list"),
      op("fetchStandings", "available", "get_contest_standings"),
      op(
        "localRun",
        "unsupported",
        null,
        "This adapter never executes code; it is a read-only data provider.",
      ),
      op("prepareSubmission", "unsupported", null, "The official API does not expose submission."),
      op("commitSubmission", "unsupported", null, "The official API does not expose submission."),
    ],
    languages: [],
    source: {
      kind: "official_api",
      adapterId: "codeforces-official-api",
      adapterVersion: ADAPTER_VERSION,
      sourceUrl: "https://codeforces.com/api",
      confidence: "authoritative",
      fetchedAt: checkedAt,
    },
  };
}

/**
 * Passive health report. Performs one cheap live probe and folds in the last
 * observed upstream error recorded by the HTTP layer.
 */
export async function getHealth({ probe = true } = {}) {
  let probeOk = null;
  let probeError = null;

  if (probe) {
    try {
      await callApi("contest.list", {}, { ttlMs: 5 * 60 * 1000 });
      probeOk = true;
    } catch (err) {
      probeOk = false;
      probeError = { code: err.code ?? "ERROR", message: err.message };
    }
  }

  const snapshot = healthSnapshot();
  const code = probeError?.code ?? snapshot.lastError?.code ?? null;

  const overall = !code ? "healthy" : code === "NETWORK_TIMEOUT" || code === "UPSTREAM" ? "unavailable" : "degraded";

  return {
    providerId: "codeforces-official-api",
    platform: "codeforces",
    checkedAt: now(),
    overall,
    layers: {
      transport: code === "NETWORK_TIMEOUT" ? "fail" : "pass",
      protocol: "pass",
      schema: code === "SCHEMA_CHANGED" ? "drift" : code ? "unknown" : "pass",
      auth: "not_required",
      upstream:
        code === "NETWORK_TIMEOUT"
          ? "timeout"
          : code === "RATE_LIMITED"
            ? "rate_limited"
            : code
              ? "fail"
              : "pass",
    },
    liveProbe: probeOk,
    errorLayer: code ? errorLayer(code) : null,
    latencyMs: snapshot.lastLatencyMs,
    cachedEntries: snapshot.cachedEntries,
    lastError: probeError ?? snapshot.lastError,
    message: code
      ? "Codeforces upstream is degraded; retry a public read shortly."
      : "Codeforces official API provider is healthy.",
  };
}
