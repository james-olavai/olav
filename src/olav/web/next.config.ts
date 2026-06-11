import type { NextConfig } from "next";

const isProd = process.env.NODE_ENV === "production";

const nextConfig: NextConfig = {
  output: isProd ? "export" : undefined,
  trailingSlash: true,
  images: { unoptimized: true },
  // Dev: proxy API calls to local OLAV server so we can run `next dev` without CORS issues
  ...(!isProd && {
    async rewrites() {
      const olavBase = process.env.OLAV_API_URL ?? "http://localhost:2280";
      return [
        { source: "/threads/:path*", destination: `${olavBase}/threads/:path*` },
        { source: "/runs/:path*",    destination: `${olavBase}/runs/:path*` },
        { source: "/agents",         destination: `${olavBase}/agents` },
        { source: "/assistants/:path*", destination: `${olavBase}/assistants/:path*` },
        { source: "/health",         destination: `${olavBase}/health` },
        { source: "/memory/:path*",  destination: `${olavBase}/memory/:path*` },
        { source: "/login",          destination: `${olavBase}/login` },
      ];
    },
  }),
};

export default nextConfig;
