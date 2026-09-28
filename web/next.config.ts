import type { NextConfig } from "next";

// Production builds are plain files (`out/`) that Nginx serves next to the API: no Node
// server runs anywhere. `next dev` instead proxies /api to a running stack (default: the
// local Compose stack on :8080), so the browser still sees one origin.
const api = process.env.GRS_API_ORIGIN ?? "http://localhost:8080";

// Every page is a folder with an index.html, so Nginx serves /requests/ without rewrites.
const shared: NextConfig = { trailingSlash: true, turbopack: { root: import.meta.dirname } };

const config: NextConfig =
  process.env.NODE_ENV === "production"
    ? { ...shared, output: "export", images: { unoptimized: true } }
    : {
        ...shared,
        async rewrites() {
          return [
            { source: "/api/:path*", destination: `${api}/api/:path*` },
            { source: "/health/:path*", destination: `${api}/health/:path*` },
          ];
        },
      };

export default config;
