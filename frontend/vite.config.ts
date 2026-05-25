import { fileURLToPath, URL } from "node:url";
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { join, extname } from "node:path";
import type { IncomingMessage, ServerResponse } from "node:http";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import type { Plugin } from "vite";

// Serve Monaco editor locally — avoids CDN timeout in China.
function monacoLocalPlugin(): Plugin {
  const MONACO_ROOT = "node_modules/monaco-editor/min/vs";
  const MIME: Record<string, string> = {
    ".js": "text/javascript",
    ".css": "text/css",
    ".ttf": "font/ttf",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".html": "text/html",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
  };
  return {
    name: "monaco-local",
    configureServer(server) {
      server.middlewares.use("/monaco-vs/", async (req: IncomingMessage, res: ServerResponse) => {
        const rel = (req.url || "/").replace(/^\/monaco-vs\//, "").replace(/[?#].*/, "");
        const abs = join(MONACO_ROOT, rel);
        try {
          const info = await stat(abs);
          if (!info.isFile()) { res.statusCode = 404; res.end(); return; }
          res.statusCode = 200;
          res.setHeader("Content-Type", MIME[extname(rel)] || "application/octet-stream");
          res.setHeader("Content-Length", info.size);
          res.setHeader("Cache-Control", "public, max-age=86400");
          createReadStream(abs).pipe(res);
        } catch {
          res.statusCode = 404;
          res.end();
        }
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  const apiBase = mode === "production" ? "" : "http://127.0.0.1:8000";

  return {
    plugins: [react(), tailwindcss(), monacoLocalPlugin()],
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    server: {
      host: "127.0.0.1",
      port: 5173,
      proxy: {
        "/api": {
          target: apiBase || "http://127.0.0.1:8000",
          changeOrigin: true,
          ws: false,
        },
      },
    },
    build: {
      outDir: "dist",
      sourcemap: false,
      target: "es2022",
    },
  };
});
