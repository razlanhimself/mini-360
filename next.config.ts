import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  partialPrefetching: true,
  // Prototyping: serve the editable POC (public/poc/index.html) at the home page.
  // Remove when the production viewer takes over `/`.
  async rewrites() {
    return {
      beforeFiles: [{ source: "/", destination: "/poc/index.html" }],
    };
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
