import type { Metadata } from "next";
import Link from "next/link";
import { JsonLd } from "@/components/public/JsonLd";
import { PublicShell } from "@/components/public/PublicShell";
import { faqs, site } from "@/lib/public/site";

export const metadata: Metadata = {
  title: "常见问题",
  description:
    "关于广东省AI数字人才就业实训基地的常见问题：地址、课程周期、适合背景、基础要求、就业保障口径与咨询方式。",
  alternates: {
    canonical: "/faq/",
  },
  openGraph: {
    url: `${site.url}/faq/`,
    title: `常见问题｜${site.shortName}`,
    description: "课程、周期、基础要求与就业保障口径。",
  },
};

const faqJsonLd = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  url: `${site.url}/faq/`,
  mainEntity: faqs.map((item) => ({
    "@type": "Question",
    name: item.q,
    acceptedAnswer: {
      "@type": "Answer",
      text: item.a,
    },
  })),
};

function Arrow() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M7 17 17 7M9 7h8v8" />
    </svg>
  );
}

export default function FaqPage() {
  return (
    <PublicShell>
      <JsonLd data={faqJsonLd} />

      <section className="site-page-hero">
        <div className="site-page-hero-inner">
          <p className="site-breadcrumb">
            <Link href="/">首页</Link> <span>/</span> 常见问题
          </p>
          <h1>先把关键口径<br />问清楚</h1>
          <p className="site-page-lead">
            下面这些问题，是咨询时最容易被跳过、但最应该先确认的部分。
            涉及就业保障的表述，均以双方签署的协议为准。
          </p>
        </div>
      </section>

      <section className="site-content">
        <div className="site-content-inner">
          <div className="site-two-col">
            <aside className="site-aside">
              <p className="site-kicker">FAQ</p>
              <h2>课程、基础<br />与就业口径</h2>
              <p>
                如果下面没有你要问的问题，直接电话沟通更快。
                到访前也可以先看公开事实页，核对地址、周期和运营主体。
              </p>
              <a className="site-button site-button-dark" href={site.phoneHref}>
                电话咨询 {site.phoneDisplay}
              </a>
            </aside>

            <div>
              <div className="site-faq-list">
                {faqs.map((item, index) => (
                  <details
                    className="site-faq-item"
                    key={item.q}
                    open={index === 0}
                  >
                    <summary>
                      {item.q}
                      <span aria-hidden="true">+</span>
                    </summary>
                    <p>{item.a}</p>
                  </details>
                ))}
              </div>

              <div className="site-source-note">
                <strong>口径说明：</strong>
                本页回答依据基地公开资料整理，用于帮助理解课程与咨询边界；
                不替代正式协议，也不构成就业或薪资承诺。报名前请逐条核对协议文本。
              </div>

              <div className="site-cta-actions" style={{ marginTop: 24 }}>
                <Link className="site-button site-button-outline" href="/courses/aigc/">
                  AIGC 课程结构 <Arrow />
                </Link>
                <Link className="site-button site-button-outline" href="/courses/ai-large-model/">
                  AI 大模型课程结构
                </Link>
              </div>
            </div>
          </div>
        </div>
      </section>
    </PublicShell>
  );
}
