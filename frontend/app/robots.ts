import type { MetadataRoute } from "next";

/** 内部系统整站不抓：工作台、公开接口（FAQ / 报告分享）都不需要被搜索引擎索引。 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", disallow: "/" }],
  };
}
