/**
 * Read-only MCP admin client (M-MCP).
 *
 * Mirrors `backend/api/routers/mcp.py`:
 *
 *   GET /api/v1/mcp/servers
 *   GET /api/v1/mcp/servers/{name}/tools
 *
 * No write endpoints in v1 — the source of truth is the YAML config
 * file (`AAF_MCP_CONFIG`); editing it requires a backend restart on
 * purpose.  See PLAN.md §10.8.
 */
import { api } from "@/lib/api";
import type { McpServersResponse, McpToolsResponse } from "@/types/api";

const enc = encodeURIComponent;

export const mcpApi = {
  servers(): Promise<McpServersResponse> {
    return api<McpServersResponse>("/api/v1/mcp/servers");
  },
  tools(serverName: string): Promise<McpToolsResponse> {
    return api<McpToolsResponse>(`/api/v1/mcp/servers/${enc(serverName)}/tools`);
  },
};
