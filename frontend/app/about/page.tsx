import type { Metadata } from "next";
import Link from "next/link";
import { JsonLd } from "@/components/public/JsonLd";
import { PublicShell } from "@/components/public/PublicShell";
import { site } from "@/lib/public/site";

export const metadata: Metadata = {
  title: "基地介绍",
  description:
    "广东省AI数字人才就业实训基地由广东省成才人工智能产业孵化有限公司运营，位于广州番禺，拥有1500㎡线下实训场地，聚焦AIGC与AI大模型两条就业实训路径。",
  alternates: {
    canonical: "/about/",
  },
  openGraph: {
    url: `${site.url}/about/`,
    title: `基地介绍｜${site.shortName}`,
    description:
      "了解基地的运营主体、线下场地、课程方向与教学交付方式。",
  },
};

const aboutJsonLd = {
  "@context": "https://schema.org",
  "@type": "AboutPage",
  name: `基地介绍｜${site.shortName}`,
  url: `${site.url}/about/`,
  mainEntity: {
    "@type": "EducationalOrganization",
    name: site.name,
    legalName: site.legalName,
    url: site.url,
    telephone: "+86 199 2754 7288",
    address: {
      "@type": "PostalAddress",
      streetAddress: site.address,
      addressLocality: "广州市",
      addressRegion: "广东省",
      addressCountry: "CN",
    },
  },
};

function Arrow() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M7 17 17 7M9 7h8v8" />
    </svg>
  );
}

export default function AboutPage() {
  return (
    <PublicShell>
      <JsonLd data={aboutJsonLd} />

      <section className="site-page-hero">
        <div className="site-page-hero-inner">
          <p className="site-breadcrumb">
            <Link href="/">首页</Link> <span>/</span> 基地介绍
          </p>
          <h1>一个把 AI 实训、<br />项目交付和就业衔接放在一起的线下基地</h1>
          <p className="site-page-lead">
            基地落地在广州番禺，面向内容创作与工程开发两条路径。
            我们不把课程做成“听完就算”，而是要求学员在真实项目里产出可展示、可复盘的作品。
          </p>
          <div className="site-page-meta">
            <div>
              <span>运营主体</span>
              <strong>广东省成才人工智能产业孵化有限公司</strong>
            </div>
            <div>
              <span>线下场地</span>
              <strong>{site.area}</strong>
            </div>
            <div>
              <span>基地位置</span>
              <strong>广州 · 番禺</strong>
            </div>
          </div>
        </div>
      </section>

      <section className="site-content">
        <div className="site-content-inner">
          <div className="site-two-col">
            <aside className="site-aside">
              <p className="site-kicker">WHAT WE DO</p>
              <h2>两条课程线，<br />一个交付标准</h2>
              <p>
                一条把 AI 工具链用于内容生产，一条把大模型能力用于应用开发。
                方向不同，但都要求线下投入、项目产出和可验证的交付结果。
              </p>
              <Link className="site-button site-button-outline" href="/contact/">
                预约到访 <Arrow />
              </Link>
            </aside>

            <div>
              <div className="site-modules">
                <article className="site-module">
                  <span className="site-module-index">01</span>
                  <div>
                    <h3>线下实训，不是只看录播</h3>
                    <p>
                      课程在基地线下完成。工具操作、项目评审、改稿和成片/部署，
                      都在同一套实训节奏里推进，便于及时发现问题。
                    </p>
                  </div>
                </article>
                <article className="site-module">
                  <span className="site-module-index">02</span>
                  <div>
                    <h3>按项目交付，不按课时堆叠</h3>
                    <p>
                      AIGC 方向要求完成短片、漫剧片段、视觉物料或账号作品；
                      AI 大模型方向要求完成可演示、可部署的应用或 Agent 项目。
                    </p>
                  </div>
                </article>
                <article className="site-module">
                  <span className="site-module-index">03</span>
                  <div>
                    <h3>就业衔接写进咨询与协议</h3>
                    <p>
                      基地公开说明包含就业保障、薪资合同和再就业陪伴。
                      具体条件、退款规则和适用岗位，需要在报名前逐条确认。
                    </p>
                  </div>
                </article>
                <article className="site-module">
                  <span className="site-module-index">04</span>
                  <div>
                    <h3>入学前先做基础评估</h3>
                    <p>
                      两条线对基础的要求不同。先沟通学历、专业、时间投入和目标岗位，
                      再决定适合的方向，避免“先报名再发现不匹配”。
                    </p>
                  </div>
                </article>
              </div>

              <div className="site-source-note">
                <strong>事实口径：</strong>
                本页的运营主体、地址、场地面积与课程方向，依据基地公开资料整理；
                课程排期、费用、就业保障条件以当期咨询和双方签署协议为准。
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="site-cta">
        <div className="site-cta-inner">
          <div>
            <p className="site-kicker">VISIT THE BASE</p>
            <h2>到现场看一次，<br />比看十页介绍更直接</h2>
            <p>地址：{site.address}</p>
          </div>
          <div className="site-cta-actions">
            <a className="site-button site-button-dark" href={site.phoneHref}>
              电话预约 {site.phoneDisplay}
            </a>
            <Link className="site-button site-button-outline" href="/contact/">
              地址与到访说明 <Arrow />
            </Link>
          </div>
        </div>
      </section>
    </PublicShell>
  );
}
