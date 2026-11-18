import type { NextConfig } from "next";

const extraDevOrigins = (process.env.GEO_ALLOWED_DEV_ORIGINS ?? "")
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean);

const nextConfig: NextConfig = {
  /* config options here */
  distDir: process.env.GEO_NEXT_DIST_DIR || ".next",
  cacheComponents: true,
  partialPrefetching: true,
  devIndicators: false,
  allowedDevOrigins: ["127.0.0.1", ...extraDevOrigins],
};

export default nextConfig;
