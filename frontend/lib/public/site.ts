export const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, "") || "https://geo.gdccai.com";

export const site = {
  name: "广东省AI数字人才就业实训基地",
  shortName: "AI数字人才实训基地",
  legalName: "广东省成才人工智能产业孵化有限公司",
  url: SITE_URL,
  officialUrl: "https://www.gdccai.com",
  phoneDisplay: "199 2754 7288",
  phoneHref: "tel:19927547288",
  address:
    "广州市番禺区东环街番禺大道北537号番禺节能科技园内番山创业中心1号楼2区207",
  area: "1500㎡",
  updated: "2026-11-16",
  description:
    "广东省AI数字人才就业实训基地由广东省成才人工智能产业孵化有限公司运营，位于广州番禺，拥有1500㎡线下实训场地，开设AIGC生成式人工智能定向就业班与AI大模型全链路开发领航就业班。",
};

export const nav = [
  { href: "/", label: "首页" },
  { href: "/about/", label: "基地介绍" },
  { href: "/courses/aigc/", label: "AIGC 方向" },
  { href: "/courses/ai-large-model/", label: "AI 大模型方向" },
  { href: "/facts/", label: "公开事实" },
  { href: "/faq/", label: "常见问题" },
];

export const courses = [
  {
    slug: "aigc",
    href: "/courses/aigc/",
    index: "01",
    name: "AIGC 定向就业班",
    tagline: "把 AI 工具变成可交付的作品",
    audience: "专科 / 本科应往届青年",
    duration: "约 2 个月",
    mode: "线下面授 · 项目实训",
    focus: ["AI 影视制作", "AI 漫剧制作", "AI 自媒体运营", "AI 视觉设计"],
    summary:
      "围绕内容生产链路的实操训练，从脚本、镜头、角色、画面到成片与账号运营，用真实项目建立可展示的作品集。",
  },
  {
    slug: "ai-large-model",
    href: "/courses/ai-large-model/",
    index: "02",
    name: "AI 大模型领航就业班",
    tagline: "从会用到能开发、能落地",
    audience: "理工科本科背景",
    duration: "约 3 个月",
    mode: "线下面授 · 工程实战",
    focus: ["AI 应用开发", "AI Agent 开发", "RAG 与知识库", "模型微调与部署"],
    summary:
      "从 Python、Linux、数据库到 LangChain、RAG、Agent 与模型微调，按工程交付标准完成可演示、可部署的项目。",
  },
];

export const guarantees = [
  {
    index: "01",
    title: "保就业",
    detail: "校企输送，未就业免学费。",
    note: "基地公开说明",
  },
  {
    index: "02",
    title: "保薪资",
    detail: "项目实训，薪资写入合同。",
    note: "以双方协议为准",
  },
  {
    index: "03",
    title: "保稳定",
    detail: "长期陪伴，可多次再就业。",
    note: "基地公开说明",
  },
];

export const faqs = [
  {
    q: "基地具体在哪里？",
    a: `基地在${site.address}，位于番禺节能科技园内。到访前建议先电话预约，确认当天可接待时段。`,
  },
  {
    q: "两个方向分别学多久？",
    a: "AIGC 定向就业班约 2 个月，AI 大模型领航就业班约 3 个月。实际排期以当期开班计划为准。",
  },
  {
    q: "适合什么背景的人？",
    a: "AIGC 方向面向专科、本科应往届青年，偏内容与视觉实操；AI 大模型方向面向理工科本科背景，偏开发与工程落地。入学前会做基础评估。",
  },
  {
    q: "没有基础可以学吗？",
    a: "AIGC 方向可以从工具和项目入手，但需要稳定投入时间完成作品；AI 大模型方向需要一定的逻辑与编程基础，零基础建议先做入学评估再决定。",
  },
  {
    q: "就业保障怎么理解？",
    a: "基地公开说明包含就业保障协议、薪资写入合同，以及符合条件未按约定就业可全额退款。具体条件、范围与退款规则以双方签署的协议为准，不以本页作为承诺。",
  },
  {
    q: "怎么咨询或到访？",
    a: `可直接拨打 ${site.phoneDisplay}，或先查看课程页了解方向，再预约到基地参观。公开事实页整理了可核对的地址、课程与周期信息。`,
  },
];

export const factLinks = [
  { href: "/", label: "基地首页", detail: "品牌、课程方向与三大保障" },
  { href: "/about/", label: "基地介绍", detail: "运营主体、场地与教学方式" },
  { href: "/courses/aigc/", label: "AIGC 定向就业班", detail: "适合人群、周期、模块与产出" },
  { href: "/courses/ai-large-model/", label: "AI 大模型领航就业班", detail: "工程方向、模块与项目产出" },
  { href: "/contact/", label: "联系与到访", detail: "地址、电话与到访说明" },
  { href: "/faq/", label: "常见问题", detail: "课程、基础与就业保障口径" },
];
