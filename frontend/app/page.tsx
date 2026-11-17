import { redirect } from "next/navigation";

/**
 * 公开站已归公司官网（https://www.gdccai.com）。
 * 本域名只作内部系统入口，根路径直接进工作台。
 */
export default function HomePage() {
  redirect("/workbench");
}
