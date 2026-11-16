import type { Metadata } from "next";
import Link from "next/link";
import { JsonLd } from "@/components/public/JsonLd";
import { PublicShell } from "@/components/public/PublicShell";
import { courses, guarantees, site } from "@/lib/public/site";

export const metadata: Metadata = {
  title: {
    absolute: `${site.name}｜AIGC 与 AI 大模型就业实训`,
  },
  description: site.description,
  alternates: {
    canonical: "/",
  },
  openGraph: {
    type: "website",
    url: site.url,
    title: `${site.name}｜AIGC 与 AI 大模型就业实训`,
    description: site.description,
  },
};

const organizationJsonLd = {
  "@context": "https://schema.org",
  "@type": "EducationalOrganization",
  name: site.name,
  alternateName: site.shortName,
  url: site.url,
  sameAs: [site.officialUrl],
  description: site.description,
  telephone: "+86 199 2754 7288",
  address: {
    "@type": "PostalAddress",
    streetAddress: site.address,
    addressLocality: "广州市",
    addressRegion: "广东省",
    addressCountry: "CN",
  },
  areaServed: "广州",
  knowsAbout: [
    "AIGC 内容生产",
    "AI 影视制作",
    "AI 漫剧制作",
    "AI 视觉设计",
    "AI 大模型应用开发",
    "AI Agent 开发",
  ],
};

function Arrow() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M7 17 17 7M9 7h8v8" />
    </svg>
  );
}

export default function HomePage() {
  return (
    <PublicShell>
      <JsonLd data={organizationJsonLd} />

      <section className="site-hero">
        <div className="site-hero-inner">
          <div>
            <p className="site-kicker">广州 · 番禺 · AI 数字人才实训</p>
            <h1>
              <strong>让 AI 能力</strong>
              <em>落到就业上</em>
            </h1>
            <p className="site-hero-lead">
              广东省AI数字人才就业实训基地，面向内容创作与工程开发两条路径，
              用线下项目实训把工具使用、作品产出和岗位衔接连起来。
            </p>
            <div className="site-hero-actions">
              <Link className="site-button site-button-gold" href="/contact/">
                预约到访 <Arrow />
              </Link>
              <Link className="site-button site-button-ghost" href="/courses/aigc/">
                查看两条课程线
              </Link>
            </div>
            <p className="site-hero-note">
              <span aria-hidden="true" />
              广州番禺 · 1500㎡ 线下实训场地 · 到访前请先电话预约
            </p>
          </div>

          <aside className="site-hero-card" aria-label="基地速览">
            <div className="site-card-label">
              <strong>基地速览</strong>
              <span>FACT SHEET / 2026</span>
            </div>
            <div className="site-card-facts">
              <div className="site-card-fact">
                <span>线下实训场地</span>
                <strong>1500㎡</strong>
              </div>
              <div className="site-card-fact">
                <span>课程方向</span>
                <strong>2 条</strong>
              </div>
              <div className="site-card-fact">
                <span>实训周期</span>
                <strong>2–3 个月</strong>
              </div>
              <div className="site-card-fact">
                <span>基地位置</span>
                <strong>广州番禺</strong>
              </div>
            </div>
            <div className="site-card-foot">
              <span>公开事实可核对</span>
              <Link href="/facts/">
                查看事实页 <Arrow />
              </Link>
            </div>
          </aside>
        </div>
      </section>

      <div className="site-proof-strip" aria-label="课程关键词">
        <div className="site-proof-inner">
          {[
            ["AIGC", "内容生产"],
            ["AI 影视", "镜头与成片"],
            ["AI 漫剧", "角色与叙事"],
            ["AI 视觉", "商业设计"],
            ["AI 应用", "RAG / Agent"],
            ["线下实训", "项目交付"],
          ].map(([title, detail]) => (
            <div className="site-proof-item" key={title}>
              <strong>{title}</strong>
              {detail}
            </div>
          ))}
        </div>
      </div>

      <section className="site-section">
        <div className="site-section-inner">
          <div className="site-section-head">
            <div>
              <p className="site-kicker">TWO PATHWAYS</p>
              <h2>两条路径，<br />按目标选方向</h2>
            </div>
            <p>
              一条偏内容与视觉，把 AI 工具变成作品；一条偏开发与工程，
              把大模型能力变成可运行的应用。两条线都强调线下实训和项目产出，
              <strong>不把“学会工具”当成终点</strong>。
            </p>
          </div>

          <div className="site-course-grid">
            {courses.map((course) => (
              <Link className="site-course-card" href={course.href} key={course.slug}>
                <div className="site-course-card-top">
                  <span className="site-course-index">{course.index}</span>
                  <span>{course.duration}</span>
                </div>
                <h3>{course.name}</h3>
                <p className="site-course-tagline">{course.tagline}</p>
                <p className="site-course-summary">{course.summary}</p>
                <div className="site-course-meta">
                  <div>
                    <span>适合人群</span>
                    <strong>{course.audience}</strong>
                  </div>
                  <div>
                    <span>实训形式</span>
                    <strong>{course.mode}</strong>
                  </div>
                </div>
                <div className="site-tags">
                  {course.focus.map((item) => (
                    <span key={item}>{item}</span>
                  ))}
                </div>
                <span className="site-course-link">
                  查看课程结构 <Arrow />
                </span>
              </Link>
            ))}
          </div>
        </div>
      </section>

      <section className="site-section site-dark-section">
        <div className="site-section-inner">
          <div className="site-section-head">
            <div>
              <p className="site-kicker">THREE COMMITMENTS</p>
              <h2>三大保障，<br />写进交付规则</h2>
            </div>
            <p>
              基地公开说明包含“保就业、保薪资、保稳定”。这三项不是海报口号，
              而是需要在咨询阶段逐条确认条件、范围和协议文本的交付条款。
            </p>
          </div>

          <div className="site-guarantees">
            {guarantees.map((item) => (
              <article className="site-guarantee" key={item.index}>
                <div className="site-guarantee-top">
                  <span>{item.index}</span>
                  <small>{item.note}</small>
                </div>
                <h3>{item.title}</h3>
                <p>{item.detail}</p>
                <span className="site-guarantee-note">具体以双方协议为准</span>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="site-section">
        <div className="site-section-inner">
          <div className="site-fact-layout">
            <div className="site-fact-copy">
              <p className="site-kicker">THE PLACE</p>
              <h2>不是线上课，<br />是一个可到访的实训场</h2>
              <p>
                基地由广东省成才人工智能产业孵化有限公司运营，位于广州番禺节能科技园，
                拥有 1500㎡ 线下实训场地。课程咨询、入学评估、项目实训和就业衔接，
                都围绕这个线下场景展开。
              </p>
              <Link className="site-button site-button-outline" href="/about/">
                了解基地与运营主体 <Arrow />
              </Link>
            </div>

            <div className="site-fact-grid">
              <div className="site-fact-cell">
                <span>运营主体</span>
                <strong>广东省成才人工智能产业孵化有限公司</strong>
                <p>基地对外运营与课程交付主体。</p>
              </div>
              <div className="site-fact-cell">
                <span>实训场地</span>
                <strong>1500㎡</strong>
                <p>线下实训空间，支持课程、项目与到访接待。</p>
              </div>
              <div className="site-fact-cell">
                <span>基地地址</span>
                <strong>广州番禺 · 番山创业中心</strong>
                <p>{site.address}</p>
              </div>
              <div className="site-fact-cell">
                <span>咨询电话</span>
                <strong>{site.phoneDisplay}</strong>
                <p>到访前建议先电话确认接待时段。</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="site-section" style={{ paddingTop: 0 }}>
        <div className="site-section-inner">
          <div className="site-section-head">
            <div>
              <p className="site-kicker">WHO IT IS FOR</p>
              <h2>先看背景，<br />再定路径</h2>
            </div>
            <p>
              两条课程线对基础和时间投入的要求不同。先确认自己的起点，
              比直接问“哪个更好”更有用。
            </p>
          </div>

          <div className="site-audience-grid">
            <article className="site-audience-card">
              <h3>AIGC 方向</h3>
              <p>适合愿意做内容、视觉、短片和账号作品的应往届青年。</p>
              <div className="site-check-list">
                <span><i aria-hidden="true" />专科 / 本科应往届，专业不限</span>
                <span><i aria-hidden="true" />能投入约 2 个月线下实训</span>
                <span><i aria-hidden="true" />愿意按项目要求反复改稿、出成片</span>
              </div>
            </article>
            <article className="site-audience-card">
              <h3>AI 大模型方向</h3>
              <p>适合有理工科背景、想进入 AI 应用开发与 Agent 落地的学习者。</p>
              <div className="site-check-list">
                <span><i aria-hidden="true" />理工科本科背景，逻辑与编程基础更好</span>
                <span><i aria-hidden="true" />能投入约 3 个月线下工程实训</span>
                <span><i aria-hidden="true" />愿意完成可运行、可部署的项目</span>
              </div>
            </article>
          </div>
        </div>
      </section>

      <section className="site-cta">
        <div className="site-cta-inner">
          <div>
            <p className="site-kicker">NEXT STEP</p>
            <h2>先确认方向，<br />再约一次到访</h2>
            <p>电话沟通背景与目标，或直接查看课程结构和公开事实页。</p>
          </div>
          <div className="site-cta-actions">
            <a className="site-button site-button-dark" href={site.phoneHref}>
              电话咨询 {site.phoneDisplay}
            </a>
            <Link className="site-button site-button-outline" href="/facts/">
              查看公开事实 <Arrow />
            </Link>
          </div>
        </div>
      </section>
    </PublicShell>
  );
}
