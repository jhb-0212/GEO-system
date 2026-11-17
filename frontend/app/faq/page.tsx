import type { Metadata } from "next";
import Link from "next/link";
import { connection } from "next/server";
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

export const instant = false;

interface FaqItem { q: string; a: string }

interface FaqLoad {
  items: FaqItem[];
  source: "api" | "static" | "empty";
}

async function loadFaqs(): Promise<FaqLoad> {
  await connection();
  const base = process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
  const projectCode = process.env.PUBLIC_FAQ_PROJECT_CODE ?? "gz-base";
  try {
    const response = await fetch(new URL(`/api/v1/public/projects/${projectCode}/faqs`, base), { cache: "no-store" });
    // 接口不可达才回退静态 FAQ；接口可达但没有已上架条目时显示空态，
    // 避免运营全部下架/删除后公开页仍展示旧内容。
    if (!response.ok) return { items: faqs, source: "static" };
    const payload = await response.json();
    const rows = Array.isArray(payload?.data) ? payload.data : [];
    if (!rows.length) return { items: [], source: "empty" };
    return {
      items: rows.map((row: { question: string; answer: string }) => ({ q: row.question, a: row.answer })),
      source: "api",
    };
  } catch {
    return { items: faqs, source: "static" };
  }
}

function faqJsonLd(items: FaqItem[]) {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    url: `${site.url}/faq/`,
    mainEntity: items.map((item) => ({
      "@type": "Question",
      name: item.q,
      acceptedAnswer: {
        "@type": "Answer",
        text: item.a,
      },
    })),
  };
}

function Arrow() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M7 17 17 7M9 7h8v8" />
    </svg>
  );
}

export default async function FaqPage() {
  const { items, source } = await loadFaqs();
  return (
    <PublicShell>
      {source !== "empty" && <JsonLd data={faqJsonLd(items)} />}

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
                {items.map((item, index) => (
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
                {source === "empty" && (
                  <div className="site-faq-empty">
                    <strong>当前没有对外的常见问题</strong>
                    <p>
                      课程周期、报名条件和就业口径，可以直接电话确认，我们会按最新协议口径答复。
                    </p>
                    <a className="site-button site-button-dark" href={site.phoneHref}>
                      电话咨询 {site.phoneDisplay}
                    </a>
                  </div>
                )}
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
