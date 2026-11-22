import { z } from "zod";
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
  getCapabilities,
  getHealth,
} from "./api.js";

// Codeforces enforces 3-24 characters for handles.
const handleSchema = z
  .string()
  .min(3)
  .max(24)
  .describe("Codeforces handle, e.g. 'tourist' or 'Benq'.");

const contestIdSchema = z
  .number()
  .int()
  .positive()
  .describe("Numeric Codeforces contest id, e.g. 1700.");

const json = (data) => ({
  content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
});

const fail = (err) => ({
  isError: true,
  content: [
    {
      type: "text",
      text: `Codeforces MCP error (${err.code ?? "ERROR"}): ${err.message}`,
    },
  ],
});

/** Every tool shares the same success/error envelope. */
const wrap = (fn) => async (args) => {
  try {
    return json(await fn(args ?? {}));
  } catch (err) {
    return fail(err);
  }
};

const readOnly = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: true };

export function registerTools(server) {
  /* ── Problemset ───────────────────────────────────────────── */

  server.registerTool(
    "search_problems",
    {
      title: "Search Codeforces problems",
      description:
        "Search the official Codeforces problemset by problem id ('158A', '158/A'), title, tag " +
        "('dp', 'greedy', 'binary search') or rating ('1500', '1200-1600'). Multi-word queries must " +
        "match every token, so 'dp 1500' returns 1500-rated dynamic programming problems. " +
        "Prefer this over scraping codeforces.com.",
      inputSchema: {
        query: z.string().min(1).max(256).describe("Free-text query: id, title, tag, or rating."),
        limit: z.number().int().min(1).max(50).optional().describe("Max results (default 10)."),
      },
      annotations: readOnly,
    },
    wrap(({ query, limit }) => searchProblemset(query, { limit: limit ?? 10 })),
  );

  server.registerTool(
    "get_problem_metadata",
    {
      title: "Get Codeforces problem metadata",
      description:
        "Fetch official metadata for one problem by id ('158A', '158/A' or '158-A'): name, rating, " +
        "tags, solved count and canonical URL. Note: the Codeforces API does not expose the full " +
        "problem statement, so this returns metadata only.",
      inputSchema: {
        problemId: z.string().min(2).max(64).describe("Problem id such as '158A', '158/A' or '158-A'."),
      },
      annotations: readOnly,
    },
    wrap(({ problemId }) => getProblemMetadata(problemId)),
  );

  server.registerTool(
    "list_problems",
    {
      title: "List Codeforces problems by tag and rating",
      description:
        "Browse the problemset with structured filters instead of a text query. Returns the most-solved " +
        "problems matching ALL given tags within the rating range. Ideal for building practice ladders.",
      inputSchema: {
        tags: z.array(z.string().min(1)).max(8).optional().describe("Tags that must ALL be present, e.g. ['dp','greedy']."),
        minRating: z.number().int().min(0).max(4000).optional().describe("Minimum problem rating."),
        maxRating: z.number().int().min(0).max(4000).optional().describe("Maximum problem rating."),
        limit: z.number().int().min(1).max(100).optional().describe("Max results (default 25)."),
      },
      annotations: readOnly,
    },
    wrap(({ tags, minRating, maxRating, limit }) =>
      listProblemsByFilter({ tags: tags ?? [], minRating, maxRating, limit: limit ?? 25 }),
    ),
  );

  /* ── Users ────────────────────────────────────────────────── */

  server.registerTool(
    "get_user_info",
    {
      title: "Get Codeforces user profile",
      description:
        "Fetch structured profile data for 1-10 Codeforces handles: rating, max rating, rank/tier, " +
        "country, organization, contribution and registration date.",
      inputSchema: {
        handles: z.array(handleSchema).min(1).max(10).describe("One to ten Codeforces handles."),
      },
      annotations: readOnly,
    },
    wrap(({ handles }) => getUserInfo(handles)),
  );

  server.registerTool(
    "get_user_rating",
    {
      title: "Get Codeforces rating history",
      description:
        "Return a user's full contest rating history (newest first) with per-contest rating deltas, " +
        "ranks, tier labels, best rating, biggest gain and biggest drop. Use for trend questions.",
      inputSchema: {
        handle: handleSchema,
        limit: z.number().int().min(1).max(500).optional().describe("Recent contests to return (default 50)."),
      },
      annotations: readOnly,
    },
    wrap(({ handle, limit }) => getUserRating(handle, { limit: limit ?? 50 })),
  );

  server.registerTool(
    "get_user_submissions",
    {
      title: "Get Codeforces user submissions",
      description:
        "Return a user's recent submissions, compacted to verdict, problem, language, runtime and " +
        "memory. Raw Codeforces submission objects are very large; this trims them for LLM context.",
      inputSchema: {
        handle: handleSchema,
        from: z.number().int().min(1).optional().describe("1-based index of the first submission (default 1)."),
        count: z.number().int().min(1).max(200).optional().describe("How many to return (default 25)."),
      },
      annotations: readOnly,
    },
    wrap(({ handle, from, count }) => getUserSubmissions(handle, { from: from ?? 1, count: count ?? 25 })),
  );

  server.registerTool(
    "get_user_stats",
    {
      title: "Analyze Codeforces user performance",
      description:
        "Compute derived analytics from a user's submission history: unique problems solved vs attempted, " +
        "acceptance rate, verdict breakdown, favourite languages, strongest tags, solved-by-rating " +
        "distribution and hardest solved problem. Answers 'how good is X' in one call.",
      inputSchema: {
        handle: handleSchema,
        sampleSize: z
          .number()
          .int()
          .min(100)
          .max(10000)
          .optional()
          .describe("How many recent submissions to analyze (default 2000)."),
      },
      annotations: readOnly,
    },
    wrap(({ handle, sampleSize }) => getUserStats(handle, { sampleSize: sampleSize ?? 2000 })),
  );

  server.registerTool(
    "compare_users",
    {
      title: "Compare Codeforces users",
      description:
        "Fetch compact side-by-side profiles for 2-5 handles sorted by rating. Handy for " +
        "'who is stronger' or team-selection questions.",
      inputSchema: {
        handles: z.array(handleSchema).min(2).max(5).describe("Two to five handles to compare."),
      },
      annotations: readOnly,
    },
    wrap(({ handles }) => compareUsers(handles)),
  );

  server.registerTool(
    "get_rated_users",
    {
      title: "Get Codeforces leaderboard",
      description:
        "Return the top rated Codeforces users, optionally only currently-active users or above a " +
        "minimum rating. The upstream list has hundreds of thousands of entries, so results are always " +
        "capped to protect context size.",
      inputSchema: {
        activeOnly: z.boolean().optional().describe("Only users active in the last month (default true)."),
        minRating: z.number().int().min(0).max(4000).optional().describe("Only users at or above this rating."),
        limit: z.number().int().min(1).max(1000).optional().describe("Max users to return (default 100)."),
      },
      annotations: readOnly,
    },
    wrap(({ activeOnly, minRating, limit }) =>
      getRatedUsers({ activeOnly: activeOnly ?? true, minRating, limit: limit ?? 100 }),
    ),
  );

  /* ── Contests ─────────────────────────────────────────────── */

  server.registerTool(
    "get_contest_list",
    {
      title: "List Codeforces contests",
      description:
        "List Codeforces contests with start time, duration, type and phase. Filter by phase " +
        "(BEFORE = upcoming, CODING = running, FINISHED = past) or switch to the gym archive.",
      inputSchema: {
        gym: z.boolean().optional().describe("List gym contests instead of regular ones (default false)."),
        phase: z
          .enum(["BEFORE", "CODING", "PENDING_SYSTEM_TEST", "SYSTEM_TEST", "FINISHED"])
          .optional()
          .describe("Only contests in this phase."),
        limit: z.number().int().min(1).max(200).optional().describe("Max contests to return (default 25)."),
      },
      annotations: readOnly,
    },
    wrap(({ gym, phase, limit }) => getContestList({ gym: gym ?? false, phase, limit: limit ?? 25 })),
  );

  server.registerTool(
    "get_upcoming_contests",
    {
      title: "Get upcoming Codeforces contests",
      description:
        "Return the next scheduled Codeforces contests, soonest first, including how many hours away " +
        "each one starts. Use for 'when is the next contest' questions.",
      inputSchema: {
        limit: z.number().int().min(1).max(50).optional().describe("Max contests to return (default 10)."),
      },
      annotations: readOnly,
    },
    wrap(({ limit }) => getUpcomingContests({ limit: limit ?? 10 })),
  );

  server.registerTool(
    "get_contest_standings",
    {
      title: "Get Codeforces contest standings",
      description:
        "Fetch the standings table for a contest: contest metadata, the problem list, and a bounded " +
        "window of ranked rows with points, penalty, hacks and per-problem results. Pass 'handles' to " +
        "look up specific competitors instead of the top of the table.",
      inputSchema: {
        contestId: contestIdSchema,
        from: z.number().int().min(1).optional().describe("1-based rank to start from (default 1)."),
        count: z.number().int().min(1).max(200).optional().describe("How many rows to return (default 20)."),
        handles: z.array(handleSchema).max(10).optional().describe("Only these handles' rows."),
        showUnofficial: z
          .boolean()
          .optional()
          .describe(
            "Keep non-CONTESTANT rows if present (default false). Note: anonymous Codeforces access " +
              "only serves the official table, so unofficial/virtual rows are normally absent.",
          ),
      },
      annotations: readOnly,
    },
    wrap(({ contestId, from, count, handles, showUnofficial }) =>
      getContestStandings(contestId, {
        from: from ?? 1,
        count: count ?? 20,
        handles,
        showUnofficial: showUnofficial ?? false,
      }),
    ),
  );

  server.registerTool(
    "get_contest_rating_changes",
    {
      title: "Get Codeforces contest rating changes",
      description:
        "Return the rating deltas applied after a rated contest: handle, rank, old rating, new rating " +
        "and the computed change. Only available once the contest has been rated.",
      inputSchema: {
        contestId: contestIdSchema,
        limit: z.number().int().min(1).max(500).optional().describe("Max participants to return (default 50)."),
      },
      annotations: readOnly,
    },
    wrap(({ contestId, limit }) => getContestRatingChanges(contestId, { limit: limit ?? 50 })),
  );

  server.registerTool(
    "get_contest_status",
    {
      title: "Get Codeforces contest submissions",
      description:
        "Return submissions made in a specific contest, optionally narrowed to a single handle. " +
        "Useful for reviewing what a competitor submitted and which verdicts they received.",
      inputSchema: {
        contestId: contestIdSchema,
        handle: handleSchema.optional().describe("Only this participant's submissions."),
        from: z.number().int().min(1).optional().describe("1-based start index (default 1)."),
        count: z.number().int().min(1).max(200).optional().describe("How many to return (default 25)."),
      },
      annotations: readOnly,
    },
    wrap(({ contestId, handle, from, count }) =>
      getContestStatus(contestId, { handle, from: from ?? 1, count: count ?? 25 }),
    ),
  );

  server.registerTool(
    "get_recent_submissions",
    {
      title: "Get recent Codeforces submissions",
      description:
        "Return the most recent submissions across the whole Codeforces platform, compacted to verdict, " +
        "problem, language and runtime. Useful for sampling live activity.",
      inputSchema: {
        count: z.number().int().min(1).max(1000).optional().describe("How many to return (default 25)."),
      },
      annotations: readOnly,
    },
    wrap(({ count }) => getRecentSubmissions({ count: count ?? 25 })),
  );

  /* ── Meta ─────────────────────────────────────────────────── */

  server.registerTool(
    "get_capabilities",
    {
      title: "Get Codeforces provider capabilities",
      description:
        "Report which Codeforces operations this server supports, which are degraded, and which are " +
        "deliberately unsupported (this adapter is strictly read-only and never submits code or " +
        "accepts credentials). Call this first to discover the safe surface area.",
      inputSchema: {},
      annotations: { ...readOnly, openWorldHint: false },
    },
    wrap(() => getCapabilities("local_stdio")),
  );

  server.registerTool(
    "get_health",
    {
      title: "Get Codeforces provider health",
      description:
        "Probe the official Codeforces API and report transport, schema, auth and upstream health, " +
        "plus the last observed error and request latency. Use this to diagnose failing tool calls.",
      inputSchema: {
        probe: z.boolean().optional().describe("Perform a live upstream probe (default true)."),
      },
      annotations: readOnly,
    },
    wrap(({ probe }) => getHealth({ probe: probe ?? true })),
  );
}

/** Canonical tool list, used by the test suite and the docs page. */
export const TOOL_NAMES = [
  "search_problems",
  "get_problem_metadata",
  "list_problems",
  "get_user_info",
  "get_user_rating",
  "get_user_submissions",
  "get_user_stats",
  "compare_users",
  "get_rated_users",
  "get_contest_list",
  "get_upcoming_contests",
  "get_contest_standings",
  "get_contest_rating_changes",
  "get_contest_status",
  "get_recent_submissions",
  "get_capabilities",
  "get_health",
];

