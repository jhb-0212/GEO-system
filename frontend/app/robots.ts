import type { MetadataRoute } from "next";

/** 内部系统：整站不允许抓取。对外公开页归公司官网。 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", disallow: "/" }],
  };
}
