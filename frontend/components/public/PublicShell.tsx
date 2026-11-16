import Link from "next/link";
import type { ReactNode } from "react";
import { nav, site } from "@/lib/public/site";

function ArrowUpRight() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M7 17 17 7M9 7h8v8" />
    </svg>
  );
}

function PhoneIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M8.4 4.8 6.3 3.7c-.7-.4-1.6-.2-2 .5L3 6.5c-.4.8-.3 1.8.2 2.5 3.4 4.9 7.5 9 12.4 12.4.7.5 1.7.6 2.5.2l2.3-1.3c.7-.4.9-1.3.5-2l-1.1-2.1c-.3-.6-.9-.9-1.6-.9h-2.4c-.4 0-.8-.2-1-.5-1-1.4-2.4-2.8-3.8-3.8-.3-.2-.5-.6-.5-1V6.4c0-.7-.3-1.3-.9-1.6Z" />
    </svg>
  );
}

function MenuIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 7h16M4 12h16M4 17h16" />
    </svg>
  );
}

export function PublicShell({ children }: { children: ReactNode }) {
  return (
    <div className="site-shell">
      <a className="site-skip" href="#site-main">
        跳到主要内容
      </a>

      <header className="site-header">
        <div className="site-header-inner">
          <Link className="site-brand" href="/" aria-label={`${site.name} 首页`}>
            <span className="site-brand-mark" aria-hidden="true">
              <span>G</span>
            </span>
            <span className="site-brand-copy">
              <strong>AI 数字人才实训基地</strong>
              <small>GUANGZHOU · AI TRAINING</small>
            </span>
          </Link>

          <nav className="site-nav" aria-label="主导航">
            {nav.map((item) => (
              <Link href={item.href} key={item.href}>
                {item.label}
              </Link>
            ))}
          </nav>

          <a className="site-header-phone" href={site.phoneHref}>
            <PhoneIcon />
            <span>{site.phoneDisplay}</span>
          </a>

          <details className="site-mobile-menu">
            <summary aria-label="打开导航菜单">
              <MenuIcon />
            </summary>
            <nav aria-label="移动导航">
              {nav.map((item) => (
                <Link href={item.href} key={item.href}>
                  {item.label}
                </Link>
              ))}
              <a href={site.phoneHref}>电话咨询 {site.phoneDisplay}</a>
            </nav>
          </details>
        </div>
      </header>

      <main id="site-main">{children}</main>

      <footer className="site-footer">
        <div className="site-footer-main">
          <div className="site-footer-brand">
            <p className="site-kicker">GUANGZHOU · AI DIGITAL TALENT</p>
            <h2>{site.name}</h2>
            <p>{site.legalName} 运营</p>
          </div>
          <div className="site-footer-links">
            <div>
              <h3>课程方向</h3>
              <Link href="/courses/aigc/">AIGC 定向就业班</Link>
              <Link href="/courses/ai-large-model/">AI 大模型领航就业班</Link>
            </div>
            <div>
              <h3>了解基地</h3>
              <Link href="/about/">基地介绍</Link>
              <Link href="/facts/">公开事实页</Link>
              <Link href="/faq/">常见问题</Link>
            </div>
            <div>
              <h3>联系</h3>
              <a href={site.phoneHref}>{site.phoneDisplay}</a>
              <Link href="/contact/">地址与到访</Link>
              <a href={site.officialUrl} target="_blank" rel="noreferrer">
                原官网 <ArrowUpRight />
              </a>
            </div>
          </div>
        </div>
        <div className="site-footer-bottom">
          <p>
            内容依据基地公开资料整理，课程排期、费用与就业保障条款以当期咨询和双方协议为准。
          </p>
          <p>最后更新：{site.updated}</p>
        </div>
      </footer>
    </div>
  );
}
