import type { Metadata } from "next";
import Link from "next/link";
import { JsonLd } from "@/components/public/JsonLd";
import { PublicShell } from "@/components/public/PublicShell";
import { site } from "@/lib/public/site";

const course = {
  name: "AIGC 定向就业班",
  description:
    "围绕 AI 影视、AI 漫剧、AI 自媒体与 AI 视觉设计的线下项目实训，周期约 2 个月，以作品集和成片交付为核心。",
  audience: "专科 / 本科应往届青年",
  duration: "约 2 个月",
  mode: "线下面授 · 项目实训",
};

export const metadata: Metadata = {
  title: "AIGC 定向就业班",
  description:
    "AIGC 定向就业班约 2 个月，线下实训，覆盖 AI 影视、AI 漫剧、AI 自媒体与 AI 视觉设计，以短片、漫剧片段和视觉物料作为项目产出。",
  alternates: {
    canonical: "/courses/aigc/",
  },
  openGraph: {
    url: `${site.url}/courses/aigc/`,
    title: `AIGC 定向就业班｜${site.shortName}`,
    description:
      "用 AI 工具完成短片、漫剧片段、视觉物料与账号作品，适合专科 / 本科应往届青年。",
  },
};

const courseJsonLd = {
  "@context": "https://schema.org",
  "@type": "Course",
  name: course.name,
  description: course.description,
  url: `${site.url}/courses/aigc/`,
  inLanguage: "zh-CN",
  courseMode: "onsite",
  timeRequired: "P2M",
  educationalLevel: "入门至项目实训",
  coursePrerequisites: "专科或本科应往届，专业不限；能投入约 2 个月线下实训。",
  teaches: [
    "AI 内容生产工作流",
    "AI 影视脚本与分镜",
    "AI 漫剧角色与叙事",
    "AI 视觉设计与商业物料",
    "账号运营与作品集整理",
  ],
  provider: {
    "@type": "EducationalOrganization",
    name: site.name,
    sameAs: site.officialUrl,
    address: {
      "@type": "PostalAddress",
      streetAddress: site.address,
      addressLocality: "广州市",
      addressRegion: "广东省",
      addressCountry: "CN",
    },
  },
};

const modules = [
  {
    index: "01",
    title: "AI 工具与内容工作流",
    body:
      "从文本、图像到视频工具，建立一套可复用的内容生产流程。重点不是记住按钮，而是知道什么任务该用什么工具、如何控制风格和返工成本。",
    tags: ["提示词", "素材管理", "风格控制"],
  },
  {
    index: "02",
    title: "AI 影视与镜头表达",
    body:
      "围绕脚本、分镜、镜头、剪辑、配音和成片，完成一支可发布的短片。训练重点在叙事节奏、画面一致性和成片完成度。",
    tags: ["脚本", "分镜", "剪辑", "配音"],
  },
  {
    index: "03",
    title: "AI 漫剧与角色叙事",
    body:
      "从角色设定、场景拆分到分镜连贯性，完成漫剧片段。训练角色一致性、镜头衔接和短剧节奏，避免只生成单张图。",
    tags: ["角色设定", "分镜连贯", "短剧片段"],
  },
  {
    index: "04",
    title: "AI 视觉与商业物料",
    body:
      "完成海报、封面、电商图或品牌视觉物料。训练版式、信息层级、画面质感和不同平台的尺寸适配。",
    tags: ["海报", "封面", "电商图", "版式"],
  },
  {
    index: "05",
    title: "账号运营与作品集",
    body:
      "把项目产出整理成作品集，完成选题、发布与数据复盘。目标是让招聘方能在短时间内看懂你会做什么。",
    tags: ["选题", "发布", "数据复盘", "作品集"],
  },
];

const outcomes = [
  ["短片成片", "完成一支可用于作品集的 AI 影视短片。"],
  ["漫剧片段", "完成角色设定与分镜连贯的漫剧片段。"],
  ["视觉物料", "完成一组海报、封面或电商视觉物料。"],
  ["账号作品", "形成可展示的账号内容与作品集页面。"],
];

function Arrow() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M7 17 17 7M9 7h8v8" />
    </svg>
  );
}

export default function AigcCoursePage() {
  return (
    <PublicShell>
      <JsonLd data={courseJsonLd} />

      <section className="site-page-hero">
        <div className="site-page-hero-inner">
          <p className="site-breadcrumb">
            <Link href="/">首页</Link> <span>/</span>
            <Link href="/courses/aigc/">课程方向</Link> <span>/</span> AIGC 定向就业班
          </p>
          <h1>AIGC 定向就业班</h1>
          <p className="site-page-lead">
            把 AI 工具变成可交付的作品。围绕 AI 影视、AI 漫剧、AI 自媒体和 AI 视觉设计，
            用约 2 个月完成从脚本到成片、从单图到视觉物料的项目训练。
          </p>
          <div className="site-page-meta">
            <div>
              <span>适合人群</span>
              <strong>{course.audience}</strong>
            </div>
            <div>
              <span>实训周期</span>
              <strong>{course.duration}</strong>
            </div>
            <div>
              <span>实训形式</span>
              <strong>{course.mode}</strong>
            </div>
          </div>
        </div>
      </section>

      <section className="site-content">
        <div className="site-content-inner">
          <div className="site-two-col">
            <aside className="site-aside">
              <p className="site-kicker">PROJECT FIRST</p>
              <h2>不是学工具，<br />是完成作品</h2>
              <p>
                课程以项目交付推进：每个模块都要出可检查的中间产物，
                最后汇总成作品集。适合愿意持续改稿、对内容和视觉有耐心的人。
              </p>
              <Link className="site-button site-button-dark" href="/contact/">
                咨询开班与到访 <Arrow />
              </Link>
            </aside>

            <div>
              <div className="site-modules">
                {modules.map((module) => (
                  <article className="site-module" key={module.index}>
                    <span className="site-module-index">{module.index}</span>
                    <div>
                      <h3>{module.title}</h3>
                      <p>{module.body}</p>
                      <div className="site-module-tags">
                        {module.tags.map((tag) => (
                          <span key={tag}>{tag}</span>
                        ))}
                      </div>
                    </div>
                  </article>
                ))}
              </div>

              <div className="site-outcome-grid">
                {outcomes.map(([title, body]) => (
                  <article className="site-outcome" key={title}>
                    <span>DELIVERABLE</span>
                    <strong>{title}</strong>
                    <p>{body}</p>
                  </article>
                ))}
              </div>

              <div className="site-source-note">
                <strong>说明：</strong>
                课程周期与方向依据基地公开资料整理；具体开班时间、费用、工具清单、
                就业保障条件以当期咨询和双方签署协议为准。作品产出取决于个人投入与项目完成情况。
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="site-cta">
        <div className="site-cta-inner">
          <div>
            <p className="site-kicker">NEXT STEP</p>
            <h2>确认你是否适合<br />AIGC 方向</h2>
            <p>电话沟通学历、时间投入和目标岗位，再约到基地看实训环境。</p>
          </div>
          <div className="site-cta-actions">
            <a className="site-button site-button-dark" href={site.phoneHref}>
              电话咨询 {site.phoneDisplay}
            </a>
            <Link className="site-button site-button-outline" href="/courses/ai-large-model/">
              对比 AI 大模型方向 <Arrow />
            </Link>
          </div>
        </div>
      </section>
    </PublicShell>
  );
}
