/**
 * Pure, dependency-free normalizers and scoring helpers.

 * Everything here is synchronous and side-effect free, which makes it trivially
 * unit-testable without touching the network.
 */

/** Codeforces rating tiers, used to label users and problems consistently. */
export const RANK_TIERS = [
  { max: 1199, tier: "newbie", color: "gray" },
  { max: 1399, tier: "pupil", color: "green" },
  { max: 1599, tier: "specialist", color: "cyan" },
  { max: 1899, tier: "expert", color: "blue" },
  { max: 2099, tier: "candidate master", color: "violet" },
  { max: 2299, tier: "master", color: "orange" },
  { max: 2399, tier: "international master", color: "orange" },
  { max: 2599, tier: "grandmaster", color: "red" },
  { max: 2999, tier: "international grandmaster", color: "red" },
  { max: Infinity, tier: "legendary grandmaster", color: "red" },
];

export function ratingTier(rating) {
  if (typeof rating !== "number" || Number.isNaN(rating)) return null;
  const tier = RANK_TIERS.find((t) => rating <= t.max);
  return { tier: tier.tier, color: tier.color };
}

/**
 * Accept `158A`, `158/A`, `158-A`, `158 a` and canonicalize to `158/A`.
 * Anything unrecognized is returned trimmed so callers can still match on it.
 */
export function normalizeProblemId(value) {
  if (typeof value !== "string") return "";
  const trimmed = value.trim();
  const match = /^(\d+)\s*(?:[/\-_]\s*)?([a-z][a-z0-9]*)$/i.exec(trimmed);
  return match ? `${match[1]}/${match[2].toUpperCase()}` : trimmed;
}

export function slug(value) {
  return String(value).trim().toLowerCase().replace(/\s+/g, "-");
}

/** `problemset.problems` returns problems and statistics as two parallel lists. */
function statisticsKey(entry) {
  return entry.contestId === undefined ? entry.index : `${entry.contestId}/${entry.index}`;
}

function problemIdentity(problem) {
  return problem.contestId === undefined ? problem.problemsetName : String(problem.contestId);
}

/**
 * Flatten the raw `problemset.problems` envelope into compact, LLM-friendly
 * problem summaries with a stable `nativeId`, a canonical URL, tags and the
 * solved count joined in from `problemStatistics`.
 */
export function normalizeProblemset(result) {
  const problems = result?.problems ?? [];
  const statistics = result?.problemStatistics ?? [];
  const solvedByKey = new Map(statistics.map((s) => [statisticsKey(s), s.solvedCount]));

  return problems.map((problem) => {
    const identity = problemIdentity(problem);
    const nativeId = `${identity}/${problem.index}`;
    return {
      nativeId,
      canonicalId: `codeforces:${nativeId}`,
      contestId: problem.contestId ?? null,
      index: problem.index,
      name: problem.name,
      type: problem.type ?? "PROGRAMMING",
      rating: problem.rating ?? null,
      points: problem.points ?? null,
      tags: Array.isArray(problem.tags) ? problem.tags : [],
      solvedCount: solvedByKey.get(statisticsKey(problem)) ?? null,
      url:
        problem.contestId !== undefined
          ? `https://codeforces.com/problemset/problem/${problem.contestId}/${problem.index}`
          : `https://codeforces.com/problemsets/${encodeURIComponent(problem.problemsetName ?? "acmsguru")}`,
    };
  });
}

/**
 * Parse `1500`, `rating:1500` or `1200-1600` into an inclusive rating window.
 * Returns undefined for anything that is not a plausible Codeforces rating.
 */
export function parseRatingToken(token) {
  const normalized = String(token).replace(/^rating:/i, "").trim();
  const range = /^(\d{3,4})\s*[-–]\s*(\d{3,4})$/.exec(normalized);
  if (range) {
    const min = Number(range[1]);
    const max = Number(range[2]);
    return min >= 800 && max <= 3500 && min <= max ? { min, max } : undefined;
  }
  const exact = /^(\d{3,4})$/.exec(normalized);
  if (exact) {
    const rating = Number(exact[1]);
    if (rating >= 800 && rating <= 3500 && rating % 100 === 0) return { min: rating, max: rating };
  }
  return undefined;
}

function matchesRating(value, filter) {
  return typeof value === "number" && value >= filter.min && value <= filter.max;
}

function matchSingleToken(summary, id, title, token) {
  const tokenId = normalizeProblemId(token).toLowerCase();
  if (id === tokenId) return 55;
  if (title.includes(token)) return 45;
  if (summary.tags.some((tag) => tag.toLowerCase().includes(token))) return 40;
  const ratingFilter = parseRatingToken(token);
  if (ratingFilter) return matchesRating(summary.rating, ratingFilter) ? 35 : 0;
  if (tokenId.length >= 2 && id.includes(tokenId)) return 30;
  return 0;
}

/**
 * Relevance score: exact id > id substring > exact title > title substring >
 * tag > rating filter. Multi-word queries must match *every* token (AND), which
 * is what makes "beginner implementation 800" behave intuitively.
 */
export function matchScore(summary, query, idQuery, tokens) {
  const id = summary.nativeId.toLowerCase();
  if (id === idQuery) return 100;

  // A bare rating such as "1500" must not be read as a partial id, otherwise
  // contest 1500's problems would outrank genuinely 1500-rated problems.
  const ratingFilter = parseRatingToken(query);
  if (!ratingFilter && idQuery.length >= 2 && id.includes(idQuery)) return 80;

  const title = String(summary.name ?? "").toLowerCase();
  if (title === query) return 70;
  if (title.includes(query)) return 60;
  if (summary.tags.some((tag) => tag.toLowerCase().includes(query))) return 40;

  if (ratingFilter && matchesRating(summary.rating, ratingFilter)) return 35;

  if (tokens.length > 1) {
    let total = 0;
    for (const token of tokens) {
      const score = matchSingleToken(summary, id, title, token);
      if (score === 0) return 0; // AND semantics
      total += score;
    }
    return Math.min(55, Math.round(total / tokens.length));
  }
  return 0;
}

/** Rank problem summaries against a free-text query and cap the result set. */
export function searchProblems(summaries, query, limit) {
  const normalizedQuery = String(query).trim().toLowerCase();
  const normalizedIdQuery = normalizeProblemId(query).toLowerCase();
  const tokens = normalizedQuery.split(/\s+/).filter(Boolean);

  return summaries
    .map((summary) => ({ summary, score: matchScore(summary, normalizedQuery, normalizedIdQuery, tokens) }))
    .filter((candidate) => candidate.score > 0)
    .sort(
      (a, b) =>
        b.score - a.score ||
        (b.summary.solvedCount ?? 0) - (a.summary.solvedCount ?? 0) ||
        a.summary.nativeId.localeCompare(b.summary.nativeId),
    )
    .slice(0, limit)
    .map((candidate) => candidate.summary);
}
