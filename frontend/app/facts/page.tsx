import type { Metadata } from "next";
import Link from "next/link";
import { JsonLd } from "@/components/public/JsonLd";
import { PublicShell } from "@/components/public/PublicShell";
import { factLinks, site } from "@/lib/public/site";

export const metadata: Metadata = {
  title: "公开事实页",
  description:
    "广东省AI数字人才就业实训基地的公开事实索引：运营主体、地址、1500㎡线下场地、课程方向、周期与咨询电话，附可引用的规范页面。",
  alternates: {
    canonical: "/facts/",
  },
  openGraph: {
    url: `${site.url}/facts/`,
    title: `公开事实页｜${site.shortName}`,
    description: "基地公开信息索引与可引用页面。",
  },
};

const factsJsonLd = {
  "@context": "https://schema.org",
  "@type": "WebPage",
  name: `公开事实页｜${site.shortName}`,
  url: `${site.url}/facts/`,
  description:
    "基地运营主体、地址、场地面积、课程方向、周期与联系方式的公开事实索引。",
  about: {
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
  mainEntity: {
    "@type": "ItemList",
    itemListElement: factLinks.map((item, index) => ({
      "@type": "ListItem",
      position: index + 1,
      name: item.label,
      url: `${site.url}${item.href}`,
    })),
  },
};

const coreFacts = [
  ["运营主体", site.legalName],
  ["基地地址", site.address],
  ["线下场地", `${site.area} 实训场地`],
  ["课程方向", "AIGC 定向就业班；AI 大模型领航就业班"],
  ["实训周期", "AIGC 约 2 个月；AI 大模型约 3 个月"],
  ["咨询电话", site.phoneDisplay],
  ["原官网", site.officialUrl],
  ["内容更新", site.updated],
];

function Arrow() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M7 17 17 7M9 7h8v8" />
    </svg>
  );
}

export default function FactsPage() {
  return (
    <PublicShell>
      <JsonLd data={factsJsonLd} />

      <section className="site-page-hero">
        <div className="site-page-hero-inner">
          <p className="site-breadcrumb">
            <Link href="/">首页</Link> <span>/</span> 公开事实页
          </p>
          <h1>基地公开事实，<br />集中放在一页</h1>
          <p className="site-page-lead">
            给需要核对信息的人一个稳定入口：运营主体、地址、场地面积、课程方向、
            周期和联系方式，以及每个主题对应的规范页面。
          </p>
          <div className="site-page-meta">
            <div>
              <span>页面性质</span>
              <strong>公开事实索引</strong>
            </div>
            <div>
              <span>最后更新</span>
              <strong>{site.updated}</strong>
            </div>
            <div>
              <span>适用站点</span>
              <strong>geo.gdccai.com</strong>
            </div>
          </div>
        </div>
      </section>

      <section className="site-content">
        <div className="site-content-inner">
          <div className="site-two-col">
            <aside className="site-aside">
              <p className="site-kicker">REFERENCE PAGE</p>
              <h2>可核对，<br />也可引用</h2>
              <p>
                本页只放可公开核对的事实，不放未经确认的排名、薪资数字或就业承诺。
                课程排期、费用和保障条款，以当期咨询与协议为准。
              </p>
              <a className="site-button site-button-dark" href={site.phoneHref}>
                电话核对 {site.phoneDisplay}
              </a>
            </aside>

            <div>
              <div className="site-fact-table-wrap">
                <table className="site-fact-table">
                  <colgroup>
                    <col />
                    <col />
                    <col />
                    <col />
                  </colgroup>
                  <thead>
                    <tr>
                      <th>主题</th>
                      <th>公开事实</th>
                      <th>说明</th>
                      <th>规范页面</th>
                    </tr>
                  </thead>
                  <tbody>
                    {factLinks.map((item) => (
                      <tr key={item.href}>
                        <td>
                          <strong>{item.label}</strong>
                        </td>
                        <td>{item.detail}</td>
                        <td>
                          {item.href === "/"
                            ? "基地首页，含课程方向、三大保障与到访入口。"
                            : "可独立引用的事实页，页面内附口径说明。"}
                        </td>
                        <td>
                          <a href={item.href}>
                            {site.url}
                            {item.href}
                          </a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="site-fact-grid" style={{ marginTop: 30 }}>
                {coreFacts.map(([label, value]) => (
                  <div className="site-fact-cell" key={label}>
                    <span>{label}</span>
                    <strong>{value}</strong>
                  </div>
                ))}
              </div>

              <div className="site-source-note">
                <strong>来源与维护：</strong>
                以上信息依据基地公开资料整理，最后更新于 {site.updated}。
                当前为静态公开站首版，后续接入内容后台后会保留本页 URL 与事实口径。
                如发现信息过期，请通过电话反馈更正。
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="site-cta">
        <div className="site-cta-inner">
          <div>
            <p className="site-kicker">CONTACT</p>
            <h2>需要确认具体班期？</h2>
            <p>电话沟通当前开班时间、入学评估和到访安排。</p>
          </div>
          <div className="site-cta-actions">
            <a className="site-button site-button-dark" href={site.phoneHref}>
              电话咨询 {site.phoneDisplay}
            </a>
            <Link className="site-button site-button-outline" href="/contact/">
              地址与到访 <Arrow />
            </Link>
          </div>
        </div>
      </section>
    </PublicShell>
  );
}
