/**
 * Live integration smoke test — hits the real Codeforces API.
 *
 * Exercises every network-backed API function once and prints a compact
 * summary so regressions in the upstream schema surface immediately.
 *
 * Run with: npm run test:live
 */
import {
  searchProblemset,
  getProblemMetadata,
  listProblemsByFilter,
  getUserInfo,
  getUserRating,
  getUserSubmissions,
  getUserStats,
  compareUsers,
  getRatedUsers,
  getContestList,
  getUpcomingContests,
  getContestStandings,
  getContestRatingChanges,
  getContestStatus,
  getRecentSubmissions,
  getHealth,
} from "../src/api.js";

let pass = 0;
let fail = 0;

async function probe(label, fn, assertion) {
  try {
    const result = await fn();
    const good = assertion(result);
    good ? pass++ : fail++;
    console.log(`${good ? "PASS" : "FAIL"}  ${label}`);
    if (!good) console.log(`       got: ${JSON.stringify(result).slice(0, 220)}`);
    return result;
  } catch (err) {
    fail++;
    console.log(`FAIL  ${label}  -> ${err.code ?? "ERROR"}: ${err.message}`);
    return null;
  }
}

console.log("Running live Codeforces API smoke tests...\n");

await probe(
  "search_problems('dp 1500')",
  () => searchProblemset("dp 1500", { limit: 5 }),
  (r) => r.items.length > 0 && r.items.every((p) => p.rating === 1500),
);

await probe(
  "search_problems('1500') returns 1500-rated problems, not contest 1500",
  () => searchProblemset("1500", { limit: 10 }),
  (r) => r.items.length === 10 && r.items.every((p) => p.rating === 1500),
);

await probe(
  "get_problem_metadata('4A') returns Watermelon",
  () => getProblemMetadata("4A"),
  (r) => r.nativeId === "4/A" && r.name === "Watermelon",
);

await probe(
  "get_problem_metadata accepts '1700/C' form",
  () => getProblemMetadata("1700/C"),
  (r) => r.nativeId === "1700/C",
);

await probe(
  "list_problems(tags=['dp'], 1200-1400)",
  () => listProblemsByFilter({ tags: ["dp"], minRating: 1200, maxRating: 1400, limit: 5 }),
  (r) =>
    r.items.length > 0 &&
    r.items.every((p) => p.tags.includes("dp") && p.rating >= 1200 && p.rating <= 1400),
);

await probe(
  "get_user_info(['tourist','Benq'])",
  () => getUserInfo(["tourist", "Benq"]),
  (r) => r.users.length === 2 && r.users.every((u) => typeof u.rating === "number"),
);

await probe(
  "get_user_rating('tourist')",
  () => getUserRating("tourist", { limit: 5 }),
  (r) => r.totalContests > 50 && r.contests.length === 5 && r.bestRating?.rating > 3000,
);

await probe(
  "get_user_submissions('tourist')",
  () => getUserSubmissions("tourist", { count: 5 }),
  (r) => r.submissions.length === 5 && r.submissions.every((s) => typeof s.id === "number"),
);

await probe(
  "get_user_stats('tourist')",
  () => getUserStats("tourist", { sampleSize: 200 }),
  (r) => r.uniqueProblemsSolved > 0 && r.topTags.length > 0 && r.acceptanceRate > 0,
);

await probe(
  "compare_users(['tourist','Benq'])",
  () => compareUsers(["tourist", "Benq"]),
  (r) => r.users.length === 2 && r.users[0].rating >= r.users[1].rating,
);

await probe(
  "get_rated_users(limit=10)",
  () => getRatedUsers({ limit: 10, minRating: 3000 }),
  (r) => r.users.length === 10 && r.users.every((u) => u.rating >= 3000),
);

await probe(
  "get_contest_list(phase=FINISHED)",
  () => getContestList({ phase: "FINISHED", limit: 5 }),
  (r) => r.contests.length === 5 && r.contests.every((c) => c.phase === "FINISHED"),
);

await probe(
  "get_upcoming_contests()",
  () => getUpcomingContests({ limit: 5 }),
  (r) => Array.isArray(r.contests),
);

await probe(
  "get_contest_standings(1700)",
  () => getContestStandings(1700, { count: 5 }),
  (r) => r.contest.id === 1700 && r.problems.length > 0 && r.rows.length === 5,
);

await probe(
  "get_contest_rating_changes(1700)",
  () => getContestRatingChanges(1700, { limit: 5 }),
  (r) => r.changes.length === 5 && r.changes.every((c) => typeof c.ratingChange === "number"),
);

await probe(
  "get_contest_status(1700)",
  () => getContestStatus(1700, { count: 5 }),
  (r) => r.submissions.length === 5,
);

await probe(
  "get_recent_submissions()",
  () => getRecentSubmissions({ count: 5 }),
  (r) => r.submissions.length === 5,
);

await probe("get_health()", () => getHealth(), (r) => r.overall === "healthy");

/* ── Error paths ── */

await probe(
  "unknown handle raises NOT_FOUND",
  async () => {
    try {
      // Valid shape (3-24 chars) but no such user, so the API itself 404s.
      await getUserRating("zzz_not_real_9f3a7x");
      return { code: "NONE" };
    } catch (err) {
      return { code: err.code };
    }
  },
  (r) => r.code === "NOT_FOUND",
);

await probe(
  "invalid handle raises INVALID_HANDLE",
  async () => {
    try {
      await getUserRating("bad handle;");
      return { code: "NONE" };
    } catch (err) {
      return { code: err.code };
    }
  },
  (r) => r.code === "INVALID_HANDLE",
);

await probe(
  "unknown problem raises NOT_FOUND",
  async () => {
    try {
      await getProblemMetadata("999999Z");
      return { code: "NONE" };
    } catch (err) {
      return { code: err.code };
    }
  },
  (r) => r.code === "NOT_FOUND",
);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
