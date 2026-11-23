import type { MetadataRoute } from "next";

/** 内部系统整站不抓，只放行公开微站 /s/ 与站点索引。 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      { userAgent: "*", allow: ["/s/", "/sitemap.xml"], disallow: "/" },
      // 国内 AI 爬虫按 UA 分别声明；未识别的 UA 落到上面的默认规则
      { userAgent: ["Bytespider", "Baiduspider", "Sogou web spider", "YisouSpider"], allow: ["/s/", "/sitemap.xml"], disallow: "/" },
    ],
    sitemap: `${baseUrl()}/sitemap.xml`,
  };
}

function baseUrl() {
  return (process.env.NEXT_PUBLIC_SITE_URL ?? "https://geo.gdccai.com").replace(/\/$/, "");
}
