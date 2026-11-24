/** 公开站点绝对 URL：必须由部署环境显式配置；本地默认 localhost，避免写死某个客户域名。 */
export function siteBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_SITE_URL?.trim();
  return (configured || "http://localhost:3200").replace(/\/$/, "");
}
