# mcp-server-codeforces

[![CI](https://github.com/iamrudhresh/mcp-server-codeforces/actions/workflows/ci.yml/badge.svg)](https://github.com/iamrudhresh/mcp-server-codeforces/actions/workflows/ci.yml)
[![npm](https://img.shields.io/npm/v/@iamrudhresh/mcp-server-codeforces)](https://www.npmjs.com/package/@iamrudhresh/mcp-server-codeforces)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![node](https://img.shields.io/badge/node-%3E%3D20-brightgreen)](package.json)
[![python](https://img.shields.io/badge/python-%3E%3D3.10-blue)](requirements.txt)

**Docs & showcase:** https://iamrudhresh.github.io/mcp-server-codeforces/

A read-only **Model Context Protocol (MCP)** server for the official
[Codeforces API](https://codeforces.com/apiHelp). It gives AI assistants (Claude Desktop,
Claude Code, Cursor, Cline, Gemini and others) structured, context-friendly JSON for
**problems, users, contests and performance analytics**.

It ships in two interchangeable runtimes that expose the **same 17 tools with the same output
shapes**:

* **Node.js (ESM)** — zero-config `npx` STDIO server.
* **Python (FastMCP)** — STDIO or Streamable HTTP, Docker-ready.

> Unofficial project, not affiliated with or endorsed by Codeforces. It never submits or runs code
> and never accepts Codeforces credentials.

---

## Tools

### Problemset
| Tool | Description |
| --- | --- |
| `search_problems` | Search by id (`158A`, `158/A`), title, tag (`dp`, `binary search`) or rating (`1500`, `1200-1600`). Multi-word queries use AND semantics: `dp 1500`. |
| `get_problem_metadata` | Name, rating, tags, solved count and canonical URL for one problem. |
| `list_problems` | Practice ladder: most-solved problems carrying **all** given tags within a rating range. |

### Users & analytics
| Tool | Description |
| --- | --- |
| `get_user_info` | Profiles for 1–10 handles: rating, max rating, rank, tier, country, organization, contribution. |
| `get_user_rating` | Rating history (newest first) with deltas, best rating, biggest gain and drop. |
| `get_user_submissions` | Recent submissions compacted to verdict / problem / language / time / memory. |
| `get_user_stats` | Derived analytics: solved vs attempted, acceptance rate, verdicts, languages, top tags, solved-by-rating curve. |
| `compare_users` | 2–5 handles side by side, highest rated first. |
| `get_rated_users` | The rated leaderboard, optionally active-only or above a rating — always capped. |

### Contests
| Tool | Description |
| --- | --- |
| `get_contest_list` | Contests filtered by phase (`BEFORE`, `CODING`, `FINISHED`, …) or from the gym. |
| `get_upcoming_contests` | Next scheduled contests, soonest first, with hours until start. |
| `get_contest_standings` | Contest info, problem list and a window of ranked rows; filter by handles. |
| `get_contest_rating_changes` | Old/new rating and delta per participant after a rated contest. |
| `get_contest_status` | Submissions in a contest, optionally for one handle. |
| `get_recent_submissions` | Live platform-wide submission feed. |

### Meta
| Tool | Description |
| --- | --- |
| `get_capabilities` | Supported / degraded / unsupported operations (read-only contract). |
| `get_health` | Live probe plus layered health: transport, schema, auth, upstream. |

**Argument naming:** the Node runtime uses camelCase (`problemId`, `minRating`, `contestId`,
`from`, `sampleSize`); the Python runtime uses snake_case (`problem_id`, `min_rating`,
`contest_id`, `from_rank` / `from_index`, `sample_size`). Outputs are identical.

---

## Quick start

### Node.js (recommended)

```bash
npx -y @iamrudhresh/mcp-server-codeforces
```

Claude Desktop (`claude_desktop_config.json`), Cursor (`.cursor/mcp.json`) or Cline:

```json
{
  "mcpServers": {
    "codeforces": {
      "command": "npx",
      "args": ["-y", "@iamrudhresh/mcp-server-codeforces"]
    }
  }
}
```

Claude Code:

```bash
claude mcp add codeforces -- npx -y @iamrudhresh/mcp-server-codeforces
```

### Python

```bash
python -m venv venv
# Windows: .\venv\Scripts\activate     Linux/macOS: source venv/bin/activate
pip install -r requirements.txt

python run_server.py                        # STDIO
python run_server.py --http --port 8000     # Streamable HTTP at http://localhost:8000/mcp
```

```json
{
  "mcpServers": {
    "codeforces": {
      "command": "/absolute/path/venv/bin/python",
      "args": ["/absolute/path/mcp-server-codeforces/run_server.py"]
    }
  }
}
```

### Docker (HTTP)

```bash
docker compose up --build        # MCP endpoint: http://localhost:8000/mcp
```

Remote clients then use `{ "url": "http://localhost:8000/mcp" }`.

### Example prompts

```text
Find five 1200-1400 rated dp problems I can practice.
How has tourist's rating changed over his last 10 contests?
Compare Benq, jiangly and tourist.
When is the next Codeforces round?
Show the top 10 of contest 1700 and how my_handle placed.
```

---

## Design notes

* **English names.** Codeforces returns Russian titles unless `lang=en` is sent, so every request
  pins `lang=en`.
* **Standings are fetched bare.** For anonymous callers Codeforces only accepts
  `contest.standings?contestId=<id>` and rejects any extra parameter. The server fetches the
  official table once, caches it, and applies `from` / `count` / `handles` locally.
* **Rate limiting.** Codeforces allows about one call every two seconds. All requests go through a
  single serialized throttle (1.1 s), a TTL cache, and exponential backoff on
  `Call limit exceeded`, HTTP 429/403/5xx and timeouts.
* **Context safety.** Large payloads (the ~20 MB problemset, the 26 MB rated list, full
  standings) are normalized and always capped before they reach the model. Submissions are
  compacted to the fields an LLM needs.
* **Strict input validation.** Handles must match `^[A-Za-z0-9._-]{3,24}$`, so malformed input
  fails locally instead of spending a rate-limited request.
* **Hardened transport.** Responses redirected off `codeforces.com` are refused; bodies are read
  with a 96 MB ceiling; errors carry stable codes (`NOT_FOUND`, `INVALID_HANDLE`,
  `RATE_LIMITED`, `SCHEMA_CHANGED`, `NETWORK_TIMEOUT`, `UPSTREAM`, …).
* **Read-only by construction.** No tool authenticates, executes code or submits solutions.

---

## Project structure

```text
mcp-server-codeforces/
├── src/                    # Node.js runtime
│   ├── server.js           # STDIO entrypoint (bin)
│   ├── tools.js            # 17 tool registrations (zod schemas)
│   ├── api.js              # Codeforces operations & analytics
│   ├── http.js             # Throttle, cache, retries, envelope handling
│   ├── normalize.js        # Pure normalizers and search scoring
│   └── errors.js           # Error taxonomy
├── app/                    # Python runtime (FastMCP)
│   ├── client/             # http.py, api.py, normalize.py (mirrors src/)
│   ├── tools/              # problems, users, contests, meta
│   ├── utils/              # logger (stderr only), errors
│   ├── config.py           # Env-driven settings
│   ├── main.py             # Streamable HTTP ASGI app
│   └── mcp_server.py       # FastMCP instance
├── test/                   # Node tests: unit, live smoke, MCP stdio
├── tests/                  # Python tests: unit, mocked API, server/stdio, live
├── docs/index.html         # GitHub Pages site
├── run_server.py           # Python CLI (STDIO / --http)
├── Dockerfile, docker-compose.yml
└── server.json             # MCP Registry metadata
```

---

## Testing

```bash
# Node
npm run test:unit      # offline unit tests
npm run test:live      # live smoke test against codeforces.com
npm run test:mcp       # boots the stdio server and speaks MCP to it
npm test               # all three

# Python
pytest                       # offline: unit, mocked API, MCP in-process + stdio end-to-end
CF_LIVE=1 pytest tests/test_live.py   # live suite against codeforces.com
```

CI runs the offline suites on Node 20/22/24 and Python 3.10/3.12/3.13.

---

## Configuration (Python, optional)

See [`.env.example`](.env.example). Nothing is required; there are no credentials.

| Variable | Default | Purpose |
| --- | --- | --- |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | HTTP transport bind |
| `CODEFORCES_LANG` | `en` | Language for names |
| `MIN_REQUEST_INTERVAL` | `1.1` | Seconds between upstream calls |
| `REQUEST_TIMEOUT` | `30` | Per-request timeout (s) |
| `MAX_RETRIES` | `3` | Retry attempts for transient failures |
| `CACHE_TTL` / `PROBLEMSET_TTL` | `600` / `1800` | Cache lifetimes (s) |

---

## Releasing

1. Bump `version` in `package.json`, `server.json`, `src/server.js` and `app/__init__.py`.
2. Tag and push: `git tag v1.0.1 && git push --tags`.
3. The **Publish** workflow publishes to npm via trusted publishing (OIDC, no token).

## License

MIT — see [LICENSE](LICENSE). Codeforces data and trademarks belong to Codeforces.
