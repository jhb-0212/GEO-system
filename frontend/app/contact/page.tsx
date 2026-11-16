import type { Metadata } from "next";
import Link from "next/link";
import { JsonLd } from "@/components/public/JsonLd";
import { PublicShell } from "@/components/public/PublicShell";
import { site } from "@/lib/public/site";

export const metadata: Metadata = {
  title: "联系与到访",
  description:
    "广东省AI数字人才就业实训基地地址：广州市番禺区东环街番禺大道北537号番禺节能科技园内番山创业中心1号楼2区207；咨询电话199 2754 7288。到访前建议先电话预约。",
  alternates: {
    canonical: "/contact/",
  },
  openGraph: {
    url: `${site.url}/contact/`,
    title: `联系与到访｜${site.shortName}`,
    description: "基地地址、咨询电话与到访说明。",
  },
};

const contactJsonLd = {
  "@context": "https://schema.org",
  "@type": "ContactPage",
  name: `联系与到访｜${site.shortName}`,
  url: `${site.url}/contact/`,
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

export default function ContactPage() {
  return (
    <PublicShell>
      <JsonLd data={contactJsonLd} />

      <section className="site-page-hero">
        <div className="site-page-hero-inner">
          <p className="site-breadcrumb">
            <Link href="/">首页</Link> <span>/</span> 联系与到访
          </p>
          <h1>先电话沟通，<br />再约一次到访</h1>
          <p className="site-page-lead">
            课程方向、入学基础、开班时间和就业保障条件，建议先在电话里确认。
            到基地看实训环境、了解项目交付方式，再决定是否报名。
          </p>
        </div>
      </section>

      <section className="site-content">
        <div className="site-content-inner">
          <div className="site-contact-grid">
            <article className="site-contact-card">
              <p className="site-kicker">CALL</p>
              <h2>电话咨询</h2>
              <p>适合先确认课程方向、基础要求、开班排期与到访时间。</p>
              <a className="site-contact-line" href={site.phoneHref}>
                {site.phoneDisplay}
              </a>
              <span className="site-contact-label">咨询时间以电话沟通为准</span>
              <div className="site-contact-actions">
                <a className="site-button site-button-dark" href={site.phoneHref}>
                  拨打电话 <Arrow />
                </a>
              </div>
              <div className="site-contact-note">
                如果电话未接通，可通过原官网了解基地公开信息，或在工作时间再次拨打。
              </div>
            </article>

            <article className="site-contact-card">
              <p className="site-kicker">VISIT</p>
              <h2>基地地址</h2>
              <p>{site.address}</p>
              <span className="site-contact-label">线下实训场地</span>
              <strong className="site-contact-line">{site.area}</strong>
              <div className="site-contact-actions">
                <a
                  className="site-button site-button-outline"
                  href={site.officialUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  原官网 <Arrow />
                </a>
                <Link className="site-button site-button-outline" href="/about/">
                  基地介绍
                </Link>
              </div>
              <div className="site-contact-note">
                到访前请先电话预约，确认当天可接待时段；园区内具体楼栋以现场指引为准。
              </div>
            </article>
          </div>

          <div className="site-two-col" style={{ marginTop: 56 }}>
            <aside className="site-aside">
              <p className="site-kicker">BEFORE YOU COME</p>
              <h2>到访前，<br />先准备三件事</h2>
              <p>
                带着具体问题来，比只听介绍更容易判断是否适合。
                如果目标还不清楚，也可以先电话做一次方向梳理。
              </p>
            </aside>

            <div>
              <div className="site-modules">
                <article className="site-module">
                  <span className="site-module-index">01</span>
                  <div>
                    <h3>确认自己的背景与时间</h3>
                    <p>
                      学历、专业、是否能脱产投入 2–3 个月，是选择课程方向的前提。
                      到访前先把这些条件想清楚，现场沟通会更高效。
                    </p>
                  </div>
                </article>
                <article className="site-module">
                  <span className="site-module-index">02</span>
                  <div>
                    <h3>明确想去的岗位方向</h3>
                    <p>
                      内容制作、视觉设计、AI 应用开发、Agent 开发，对应的课程线不同。
                      可以先看两门课程的模块与产出，再带着问题到现场。
                    </p>
                  </div>
                </article>
                <article className="site-module">
                  <span className="site-module-index">03</span>
                  <div>
                    <h3>逐条确认协议条款</h3>
                    <p>
                      就业保障、薪资约定、退款条件都以协议文本为准。
                      咨询时把适用条件、岗位范围、兑现方式问清楚，再决定是否签署。
                    </p>
                  </div>
                </article>
              </div>

              <div className="site-source-note">
                <strong>说明：</strong>
                本页地址与电话依据基地公开资料整理；接待安排、课程排期与协议条款以当期咨询为准。
                本页不构成报名承诺或就业承诺。
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="site-cta">
        <div className="site-cta-inner">
          <div>
            <p className="site-kicker">FACT SHEET</p>
            <h2>想先自己核对信息？</h2>
            <p>公开事实页整理了运营主体、地址、课程周期和可引用页面。</p>
          </div>
          <div className="site-cta-actions">
            <Link className="site-button site-button-dark" href="/facts/">
              查看公开事实 <Arrow />
            </Link>
            <a className="site-button site-button-outline" href={site.phoneHref}>
              电话咨询
            </a>
          </div>
        </div>
      </section>
    </PublicShell>
  );
}
