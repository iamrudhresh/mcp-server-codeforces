# Changelog

## 1.0.0 — 2026-11-22

First release: Node.js and Python runtimes that expose the same 17 read-only tools.

### Added
- Problemset tools: `search_problems`, `get_problem_metadata`, `list_problems`.
- User tools: `get_user_info`, `get_user_rating`, `get_user_submissions`, `get_user_stats`,
  `compare_users`, `get_rated_users`.
- Contest tools: `get_contest_list`, `get_upcoming_contests`, `get_contest_standings`,
  `get_contest_rating_changes`, `get_contest_status`, `get_recent_submissions`.
- `get_capabilities` / `get_health` reporting a strict read-only contract.
- Python runtime (FastMCP) with STDIO and Streamable HTTP transports, Docker image.
- Test suites for both runtimes (offline, mocked, MCP end-to-end, opt-in live) and CI.
- GitHub Pages documentation site.

### Notes
- Every request sends `lang=en` so names come back in English.
- `contest.standings` is fetched bare (anonymous callers may not pass other params) and windowed
  locally.
- Large payloads (rated list, contest list, submissions) are compacted and capped.
- Requests are serialized through a throttle with caching and retries.
- Handle validation matches Codeforces' 3–24 character rule.
- A bare rating query (e.g. `1500`) matches 1500-rated problems, not contest 1500.
