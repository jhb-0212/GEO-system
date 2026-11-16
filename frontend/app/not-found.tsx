import Link from "next/link";
import { PublicShell } from "@/components/public/PublicShell";

export default function NotFound() {
  return (
    <PublicShell>
      <section className="site-not-found">
        <span>404 / PAGE NOT FOUND</span>
        <h1>这个页面还没有内容</h1>
        <p>链接可能已经调整。可以回到首页，或直接查看公开事实页。</p>
        <div className="site-cta-actions" style={{ justifyContent: "center" }}>
          <Link className="site-button site-button-dark" href="/">
            返回首页
          </Link>
          <Link className="site-button site-button-outline" href="/facts/">
            查看公开事实
          </Link>
        </div>
      </section>
    </PublicShell>
  );
}
