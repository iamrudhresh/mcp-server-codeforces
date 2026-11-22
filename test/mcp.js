/**
 * End-to-end MCP protocol test.
 *
 * Boots the real stdio server as a child process, speaks MCP over the wire,
 * verifies every tool is discoverable with a valid schema, and exercises both
 * the success and error paths. Requires network access for the live calls.
 *
 * Run with: npm run test:mcp
 */
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { TOOL_NAMES } from "../src/tools.js";

let pass = 0;
let fail = 0;
const check = (label, condition, detail = "") => {
  condition ? pass++ : fail++;
  console.log(`${condition ? "PASS" : "FAIL"}  ${label}${condition ? "" : `  ${detail}`}`);
};

const serverPath = fileURLToPath(new URL("../src/server.js", import.meta.url));

const transport = new StdioClientTransport({
  command: process.execPath,
  args: [serverPath],
});

const client = new Client({ name: "codeforces-mcp-test", version: "1.0.0" });
await client.connect(transport);
console.log("Connected to codeforces-mcp over stdio.\n");

/* ── Tool discovery ── */

const { tools } = await client.listTools();
check(`discovers ${TOOL_NAMES.length} tools`, tools.length === TOOL_NAMES.length, `got ${tools.length}`);

for (const name of TOOL_NAMES) {
  check(`tool '${name}' is registered`, tools.some((t) => t.name === name));
}

for (const tool of tools) {
  check(
    `tool '${tool.name}' has a description`,
    typeof tool.description === "string" && tool.description.length > 40,
  );
  check(
    `tool '${tool.name}' has an object input schema`,
    tool.inputSchema?.type === "object",
  );
  check(
    `tool '${tool.name}' is annotated read-only`,
    tool.annotations?.readOnlyHint === true,
  );
}

/* ── Offline tool call ── */

const caps = await client.callTool({ name: "get_capabilities", arguments: {} });
const capsText = caps.content.find((c) => c.type === "text")?.text ?? "";
const capsJson = JSON.parse(capsText);
check("get_capabilities returns valid JSON", typeof capsJson === "object");
check("get_capabilities reports read-only", capsJson.readOnly === true);
check("get_capabilities names the provider", capsJson.providerId === "codeforces-official-api");

/* ── Validation error path ── */

const badArgs = await client.callTool({
  name: "get_user_rating",
  arguments: { handle: "has spaces and ; semicolons" },
});
check("invalid handle is rejected", badArgs.isError === true, JSON.stringify(badArgs).slice(0, 160));

/* ── Live calls ── */

const live = process.env.SKIP_LIVE !== "1";

if (live) {
  const search = await client.callTool({
    name: "search_problems",
    arguments: { query: "watermelon", limit: 3 },
  });
  const searchJson = JSON.parse(search.content.find((c) => c.type === "text").text);
  check("search_problems succeeds", !search.isError, searchJson?.message ?? "");
  check("search_problems finds Watermelon", searchJson.items?.some((p) => p.nativeId === "4/A"));
  check("search_problems indexed the problemset", (searchJson.totalIndexed ?? 0) > 1000);

  const meta = await client.callTool({
    name: "get_problem_metadata",
    arguments: { problemId: "158A" },
  });
  const metaJson = JSON.parse(meta.content.find((c) => c.type === "text").text);
  check("get_problem_metadata resolves 158A", metaJson.nativeId === "158/A");
  check("get_problem_metadata returns the title", metaJson.name === "Next Round");

  const user = await client.callTool({
    name: "get_user_info",
    arguments: { handles: ["tourist"] },
  });
  const userJson = JSON.parse(user.content.find((c) => c.type === "text").text);
  check("get_user_info returns tourist", userJson.users?.[0]?.handle === "tourist");
  check("get_user_info includes a rating", typeof userJson.users?.[0]?.rating === "number");
  check("get_user_info derives a tier", typeof userJson.users?.[0]?.tier === "string");

  const upcoming = await client.callTool({ name: "get_upcoming_contests", arguments: { limit: 3 } });
  const upcomingJson = JSON.parse(upcoming.content.find((c) => c.type === "text").text);
  check("get_upcoming_contests succeeds", !upcoming.isError);
  check("get_upcoming_contests returns an array", Array.isArray(upcomingJson.contests));

  const health = await client.callTool({ name: "get_health", arguments: {} });
  const healthJson = JSON.parse(health.content.find((c) => c.type === "text").text);
  check("get_health reports healthy", healthJson.overall === "healthy", JSON.stringify(healthJson));

  const missing = await client.callTool({
    name: "get_problem_metadata",
    arguments: { problemId: "999999Z" },
  });
  check("unknown problem returns an error result", missing.isError === true);

  const badUser = await client.callTool({
    name: "get_user_rating",
    arguments: { handle: "zzz_not_real_9f3a7x" },
  });
  check("unknown handle returns an error result", badUser.isError === true);
} else {
  console.log("\n(SKIP_LIVE=1 — live network assertions skipped)");
}

await client.close();

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
