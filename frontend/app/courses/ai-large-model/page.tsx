import type { Metadata } from "next";
import Link from "next/link";
import { JsonLd } from "@/components/public/JsonLd";
import { PublicShell } from "@/components/public/PublicShell";
import { site } from "@/lib/public/site";

const course = {
  name: "AI 大模型领航就业班",
  description:
    "面向理工科本科背景的 AI 大模型应用与 Agent 开发实训，周期约 3 个月，覆盖 Python、Linux、数据库、LangChain、RAG、Agent 与模型微调部署。",
  audience: "理工科本科背景",
  duration: "约 3 个月",
  mode: "线下面授 · 工程实战",
};

export const metadata: Metadata = {
  title: "AI 大模型领航就业班",
  description:
    "AI 大模型领航就业班约 3 个月，面向理工科本科背景，线下实训覆盖 Python、Linux、数据库、LangChain、RAG、Agent 开发与模型微调部署。",
  alternates: {
    canonical: "/courses/ai-large-model/",
  },
  openGraph: {
    url: `${site.url}/courses/ai-large-model/`,
    title: `AI 大模型领航就业班｜${site.shortName}`,
    description:
      "从会用到能开发：完成可演示、可部署的 RAG 知识库与 Agent 应用。",
  },
};

const courseJsonLd = {
  "@context": "https://schema.org",
  "@type": "Course",
  name: course.name,
  description: course.description,
  url: `${site.url}/courses/ai-large-model/`,
  inLanguage: "zh-CN",
  courseMode: "onsite",
  timeRequired: "P3M",
  educationalLevel: "工程实战",
  coursePrerequisites:
    "理工科本科背景，具备一定逻辑与编程基础；能投入约 3 个月线下实训。",
  teaches: [
    "Python 与 Linux 工程基础",
    "数据库与后端接口",
    "大模型 API 与 LangChain",
    "RAG 知识库",
    "AI Agent 开发",
    "模型微调与部署",
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
    title: "工程基础：Python、Linux、数据库",
    body:
      "先把开发环境、命令行、接口和数据库打通。后续所有大模型项目都建立在这层工程能力上，避免只会调用现成页面。",
    tags: ["Python", "Linux", "MySQL", "API"],
  },
  {
    index: "02",
    title: "大模型 API 与 LangChain",
    body:
      "理解模型调用、上下文、结构化输出和链式编排。用 LangChain 把提示词、工具和数据源组织成可维护的应用。",
    tags: ["模型 API", "LangChain", "结构化输出"],
  },
  {
    index: "03",
    title: "RAG 与知识库",
    body:
      "完成文档切分、向量化、检索、重排和答案生成，搭建一个可演示的企业知识库问答应用，并处理召回与幻觉问题。",
    tags: ["Embedding", "向量检索", "RAG", "评测"],
  },
  {
    index: "04",
    title: "AI Agent 开发",
    body:
      "从工具调用、任务拆解到多步执行，完成一个能处理真实业务流程的 Agent。重点在可控性、错误处理和可观测性。",
    tags: ["Tool Calling", "任务编排", "Agent"],
  },
  {
    index: "05",
    title: "模型微调与部署",
    body:
      "了解微调数据准备、训练与评测的基本流程，完成接口服务化、容器化与部署，让项目从本地 Demo 变成可访问的应用。",
    tags: ["微调", "评测", "容器化", "部署"],
  },
  {
    index: "06",
    title: "项目答辩与作品集",
    body:
      "按工程交付标准整理代码、接口文档、部署说明和演示材料，完成项目答辩。目标是让面试官能直接运行和理解你的项目。",
    tags: ["项目文档", "答辩", "作品集"],
  },
];

const outcomes = [
  ["RAG 知识库", "完成一个可检索、可问答的知识库应用。"],
  ["Agent 应用", "完成一个可处理多步任务的 Agent 项目。"],
  ["可部署服务", "完成接口服务化与容器化部署。"],
  ["工程作品集", "形成代码、文档、演示与答辩材料。"],
];

function Arrow() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M7 17 17 7M9 7h8v8" />
    </svg>
  );
}

export default function AiLargeModelCoursePage() {
  return (
    <PublicShell>
      <JsonLd data={courseJsonLd} />

      <section className="site-page-hero">
        <div className="site-page-hero-inner">
          <p className="site-breadcrumb">
            <Link href="/">首页</Link> <span>/</span>
            <Link href="/courses/ai-large-model/">课程方向</Link> <span>/</span>
            AI 大模型领航就业班
          </p>
          <h1>AI 大模型领航就业班</h1>
          <p className="site-page-lead">
            从会用到能开发、能落地。用约 3 个月完成 Python 工程基础、大模型 API、
            RAG 知识库、Agent 开发与模型微调部署，最终交付可运行、可演示的项目。
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
              <p className="site-kicker">ENGINEERING FIRST</p>
              <h2>不是会调用，<br />是能交付项目</h2>
              <p>
                课程按工程交付标准推进：代码、接口、文档、部署和演示都要完成。
                适合愿意补工程基础、能持续投入项目开发的理工科学习者。
              </p>
              <Link className="site-button site-button-dark" href="/contact/">
                咨询入学评估 <Arrow />
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
                课程周期与方向依据基地公开资料整理；具体开班时间、费用、技术栈版本、
                就业保障条件以当期咨询和双方签署协议为准。项目产出取决于个人投入与完成情况。
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="site-cta">
        <div className="site-cta-inner">
          <div>
            <p className="site-kicker">NEXT STEP</p>
            <h2>确认你是否适合<br />AI 大模型方向</h2>
            <p>电话沟通专业背景、编程基础和目标岗位，再安排入学评估。</p>
          </div>
          <div className="site-cta-actions">
            <a className="site-button site-button-dark" href={site.phoneHref}>
              电话咨询 {site.phoneDisplay}
            </a>
            <Link className="site-button site-button-outline" href="/courses/aigc/">
              对比 AIGC 方向 <Arrow />
            </Link>
          </div>
        </div>
      </section>
    </PublicShell>
  );
}
