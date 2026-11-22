/**
 * Offline unit tests — no network access required.
 *
 * Run with: npm run test:unit
 */
import {
  normalizeProblemId,
  normalizeProblemset,
  searchProblems,
  parseRatingToken,
  matchScore,
  ratingTier,
  slug,
} from "../src/normalize.js";
import {
  isValidHandle,
  readTextCapped,
  isRateLimitComment,
  buildUrl,
  throttle,
  MIN_REQUEST_INTERVAL_MS,
} from "../src/http.js";
import { CodeforcesError, errorLayer, isRetryableCode } from "../src/errors.js";
import { getCapabilities } from "../src/api.js";
import { TOOL_NAMES } from "../src/tools.js";

let pass = 0;
let fail = 0;

const eq = (label, actual, expected) => {
  const good = JSON.stringify(actual) === JSON.stringify(expected);
  good ? pass++ : fail++;
  console.log(
    `${good ? "PASS" : "FAIL"}  ${label}` +
      (good ? "" : `  (got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)})`),
  );
};

const ok = (label, value) => eq(label, Boolean(value), true);

/* ── Fixture mirroring the shape of problemset.problems ── */

const FIXTURE = {
  problems: [
    {
      contestId: 158,
      index: "A",
      name: "Next Round",
      type: "PROGRAMMING",
      rating: 800,
      tags: ["*special", "implementation"],
    },
    {
      contestId: 4,
      index: "A",
      name: "Watermelon",
      type: "PROGRAMMING",
      rating: 800,
      tags: ["brute force", "math"],
    },
    {
      contestId: 1700,
      index: "C",
      name: "Helping the Nature",
      type: "PROGRAMMING",
      rating: 1500,
      tags: ["dp", "greedy"],
    },
    {
      problemsetName: "acmsguru",
      index: "101",
      name: "Domino",
      type: "PROGRAMMING",
      tags: ["graphs"],
    },
  ],
  problemStatistics: [
    { contestId: 158, index: "A", solvedCount: 500000 },
    { contestId: 4, index: "A", solvedCount: 900000 },
    { contestId: 1700, index: "C", solvedCount: 12000 },
    { index: "101", solvedCount: 1500 },
  ],
};

const summaries = normalizeProblemset(FIXTURE);

/* ── normalizeProblemset ── */

eq("normalizes four problems", summaries.length, 4);
eq("builds nativeId from contestId + index", summaries[0].nativeId, "158/A");
eq("builds canonicalId", summaries[0].canonicalId, "codeforces:158/A");
eq("builds problemset URL", summaries[0].url, "https://codeforces.com/problemset/problem/158/A");
eq("joins solvedCount from statistics", summaries[0].solvedCount, 500000);
eq("carries rating through", summaries[2].rating, 1500);
eq("carries tags through", summaries[2].tags, ["dp", "greedy"]);
eq("falls back to problemsetName when contestId is absent", summaries[3].nativeId, "acmsguru/101");
eq("builds acmsguru URL", summaries[3].url, "https://codeforces.com/problemsets/acmsguru");
eq("joins statistics for problemsetName entries", summaries[3].solvedCount, 1500);
eq("missing rating becomes null", summaries[3].rating, null);

/* ── normalizeProblemId ── */

eq("normalizes 158A", normalizeProblemId("158A"), "158/A");
eq("normalizes 158/A", normalizeProblemId("158/A"), "158/A");
eq("normalizes 158-A", normalizeProblemId("158-A"), "158/A");
eq("normalizes lowercase 158a", normalizeProblemId("158a"), "158/A");
eq("normalizes spaced '158 a'", normalizeProblemId("158 a"), "158/A");
eq("normalizes multi-char index 1700C1", normalizeProblemId("1700C1"), "1700/C1");
eq("passes non-ids through trimmed", normalizeProblemId("  watermelon "), "watermelon");
eq("tolerates non-strings", normalizeProblemId(null), "");

/* ── parseRatingToken ── */

eq("parses exact round rating", parseRatingToken("1500"), { min: 1500, max: 1500 });
eq("parses rating: prefix", parseRatingToken("rating:800"), { min: 800, max: 800 });
eq("parses rating range", parseRatingToken("1200-1600"), { min: 1200, max: 1600 });
eq("rejects non-round exact rating", parseRatingToken("1550"), undefined);
eq("rejects out-of-band rating", parseRatingToken("100"), undefined);
eq("rejects inverted range", parseRatingToken("1600-1200"), undefined);
eq("rejects plain words", parseRatingToken("greedy"), undefined);

/* ── search scoring ── */

eq("exact id match scores 100", matchScore(summaries[0], "158/a", "158/a", ["158/a"]), 100);
eq("exact title match scores 70", matchScore(summaries[1], "watermelon", "watermelon", ["watermelon"]), 70);
eq("tag match scores 40", matchScore(summaries[2], "dp", "dp", ["dp"]), 40);
eq("rating match scores 35", matchScore(summaries[2], "1500", "1500", ["1500"]), 35);
eq("unrelated query scores 0", matchScore(summaries[2], "zzzz", "zzzz", ["zzzz"]), 0);

/* ── searchProblems ── */

eq(
  "search by id returns the exact problem",
  searchProblems(summaries, "158A", 5).map((p) => p.nativeId),
  ["158/A"],
);
eq(
  "search by title works",
  searchProblems(summaries, "watermelon", 5).map((p) => p.nativeId),
  ["4/A"],
);
eq(
  "search by tag returns tagged problems",
  searchProblems(summaries, "greedy", 5).map((p) => p.nativeId),
  ["1700/C"],
);
eq(
  "search by rating returns all matching",
  searchProblems(summaries, "800", 5)
    .map((p) => p.nativeId)
    .sort(),
  ["158/A", "4/A"],
);
eq(
  "multi-token search uses AND semantics",
  searchProblems(summaries, "dp 1500", 5).map((p) => p.nativeId),
  ["1700/C"],
);
eq("multi-token search rejects partial matches", searchProblems(summaries, "dp 800", 5).length, 0);
eq("limit is honoured", searchProblems(summaries, "800", 1).length, 1);
eq("no match returns empty", searchProblems(summaries, "nonexistentproblem", 5).length, 0);
eq("ties break by solvedCount descending", searchProblems(summaries, "800", 2)[0].nativeId, "4/A");

// Regression: "1500" is a rating, not a partial id. Contest 1500's problems
// (rated 2000 here) must not outrank genuinely 1500-rated problems.
const withContest1500 = normalizeProblemset({
  problems: [...FIXTURE.problems, { contestId: 1500, index: "A", name: "Other", rating: 2000, tags: [] }],
  problemStatistics: FIXTURE.problemStatistics,
});
eq(
  "rating query ignores contests whose id merely contains the number",
  searchProblems(withContest1500, "1500", 5).map((p) => p.nativeId),
  ["1700/C"],
);
eq("exact contest id still resolves", searchProblems(withContest1500, "1500A", 5)[0].nativeId, "1500/A");
eq("rating token in multi-word query is strict", searchProblems(withContest1500, "dp 2000", 5).length, 0);

/* ── ratingTier ── */

eq("1100 is newbie", ratingTier(1100).tier, "newbie");
eq("1300 is pupil", ratingTier(1300).tier, "pupil");
eq("1600 is expert", ratingTier(1600).tier, "expert");
eq("2400 is grandmaster", ratingTier(2400).tier, "grandmaster");
eq("3500 is legendary grandmaster", ratingTier(3500).tier, "legendary grandmaster");
eq("null rating has no tier", ratingTier(null), null);
eq("undefined rating has no tier", ratingTier(undefined), null);
eq("slug lowercases and hyphenates", slug("Binary Search"), "binary-search");

/* ── handle validation ── */

eq("accepts a normal handle", isValidHandle("tourist"), true);
eq("accepts dots, dashes and underscores", isValidHandle("a.b-c_d"), true);
eq("rejects empty handles", isValidHandle(""), false);
eq("rejects spaces", isValidHandle("bad handle"), false);
eq("rejects injection characters", isValidHandle("a;b"), false);
eq("rejects non-strings", isValidHandle(null), false);
// Codeforces enforces 3-24 characters server-side; we mirror that locally.
eq("rejects too-short handles", isValidHandle("ab"), false);
eq("accepts a 3-character handle", isValidHandle("abc"), true);
eq("accepts a 24-character handle", isValidHandle("x".repeat(24)), true);
eq("rejects over-long handles", isValidHandle("x".repeat(25)), false);

/* ── URL building ── */

eq(
  "pins lang=en and drops empty params",
  buildUrl("user.status", { handle: "tourist", from: 1, count: undefined, x: "" }),
  "https://codeforces.com/api/user.status?lang=en&handle=tourist&from=1",
);
eq(
  "contest.standings is sent bare (anonymous API rejects extra params)",
  buildUrl("contest.standings", { contestId: 1700, from: 1, count: 5 }),
  "https://codeforces.com/api/contest.standings?contestId=1700",
);

/* ── throttle serializes concurrent callers ── */

{
  const stamps = [];
  await Promise.all([1, 2, 3].map(() => throttle().then(() => stamps.push(Date.now()))));
  const gaps = stamps.slice(1).map((t, i) => t - stamps[i]);
  ok(
    "concurrent requests are spaced by the minimum interval",
    gaps.every((g) => g >= MIN_REQUEST_INTERVAL_MS - 20),
  );
}

/* ── rate-limit detection ── */

eq("detects call limit comment", isRateLimitComment("Call limit exceeded"), true);
eq("ignores unrelated comments", isRateLimitComment("handle: User not found"), false);
eq("tolerates undefined", isRateLimitComment(undefined), false);

/* ── error taxonomy ── */

eq("timeout maps to transport layer", errorLayer("NETWORK_TIMEOUT"), "transport");
eq("rate limit maps to upstream layer", errorLayer("RATE_LIMITED"), "upstream");
eq("not found maps to upstream layer", errorLayer("NOT_FOUND"), "upstream");
eq("invalid input maps to broker layer", errorLayer("INVALID_INPUT"), "broker");
eq("rate limit is retryable", isRetryableCode("RATE_LIMITED"), true);
eq("invalid handle is not retryable", isRetryableCode("INVALID_HANDLE"), false);

const err = new CodeforcesError("boom", { code: "UPSTREAM", status: 503, retryable: true });
eq("error carries its code", err.code, "UPSTREAM");
eq("error carries its status", err.status, 503);
eq("error carries retryable flag", err.retryable, true);
ok("error is an Error instance", err instanceof Error);

/* ── response size guard ── */

eq("readTextCapped returns a normal body", await readTextCapped(new Response("hello"), 100), "hello");

let capCode = null;
try {
  await readTextCapped(new Response("x".repeat(200)), 50);
} catch (e) {
  capCode = e.code;
}
eq("readTextCapped stops an oversized stream", capCode, "RESPONSE_TOO_LARGE");

capCode = null;
try {
  await readTextCapped(new Response("abc", { headers: { "content-length": "999999" } }), 50);
} catch (e) {
  capCode = e.code;
}
eq("readTextCapped honours content-length", capCode, "RESPONSE_TOO_LARGE");

/* ── capabilities ── */

const caps = getCapabilities("local_stdio");
eq("capabilities report the provider id", caps.providerId, "codeforces-official-api");
eq("capabilities declare read-only", caps.readOnly, true);
eq("capabilities list no languages", caps.languages, []);
ok(
  "search is advertised as available",
  caps.operations.find((o) => o.name === "searchProblems")?.status === "available",
);
ok(
  "submission is advertised as unsupported",
  caps.operations.find((o) => o.name === "commitSubmission")?.status === "unsupported",
);
ok(
  "every operation is R0 public read",
  caps.operations.every((o) => o.risk === "R0_public_read"),
);

/* ── tool registry ── */

eq("exposes 17 tools", TOOL_NAMES.length, 17);
eq("tool names are unique", new Set(TOOL_NAMES).size, TOOL_NAMES.length);
ok(
  "no tool name hints at writing",
  TOOL_NAMES.every((n) => !/submit|run|execute|delete/.test(n)),
);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
