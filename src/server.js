#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { registerTools, TOOL_NAMES } from "./tools.js";

const server = new McpServer(
  {
    name: "codeforces-mcp",
    version: "1.0.0",
  },
  {
    instructions:
      "Codeforces MCP Server — read-only access to the official Codeforces API.\n\n" +
      "Capabilities: problemset search by id/title/tag/rating, problem metadata, practice-ladder " +
      "filtering, user profiles and rating history, submission history, derived performance analytics, " +
      "head-to-head comparison, the rated leaderboard, contest listings and standings, rating changes, " +
      "and live platform activity.\n\n" +
      "This server never submits code, never executes code, and never accepts Codeforces credentials. " +
      "Call get_capabilities to enumerate the supported surface and get_health to diagnose failures.",
  },
);

registerTools(server);

const transport = new StdioServerTransport();
await server.connect(transport);

// stdout is reserved for the MCP JSON-RPC framing; diagnostics must go to stderr.
console.error(`[codeforces-mcp] running on stdio with ${TOOL_NAMES.length} tools`);
