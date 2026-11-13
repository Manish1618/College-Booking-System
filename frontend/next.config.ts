import type { NextConfig } from "next";

// In development Next.js proxies the API to Django. In production Caddy routes /api itself.
const apiOrigin = process.env.API_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  output: "standalone",
  poweredByHeader: false,
  skipTrailingSlashRedirect: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    // The catch-all passes the rest of the path through exactly as it came. ":path*" would drop a trailing
    // slash, and Django answers a missing slash with a redirect back to it, which loops for the admin.
    return [
      { source: "/django-admin", destination: `${apiOrigin}/django-admin/` },
      ...["api", "media", "django-admin", "static"].map((prefix) => ({
        source: `/${prefix}/:rest(.*)`,
        destination: `${apiOrigin}/${prefix}/:rest`,
      })),
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "same-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
