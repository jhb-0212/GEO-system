"use client";

import { useState, type CSSProperties } from "react";

import styles from "./media-matrix.module.css";

type Tone = "red" | "blue" | "dark" | "yellow" | "green" | "orange" | "pink" | "purple";
type LogoStyle = "text" | "square" | "china" | "circle" | "play" | "bili";

type MediaBrand = {
  name: string;
  domain: string;
  tone: Tone;
  logoStyle?: LogoStyle;
  mark?: string;
  sub?: string;
};

type MediaSection = {
  title: string;
  note: string;
  items: MediaBrand[];
};

type MediaCategory = {
  id: string;
  label: string;
  title: string;
  description: string;
  sections: MediaSection[];
};

const TONE_COLOR: Record<Tone, string> = {
  red: "#d71920",
  blue: "#1a73e8",
  dark: "#222838",
  yellow: "#ffd400",
  green: "#07a35a",
  orange: "#ff6900",
  pink: "#fb7299",
  purple: "#6b35f5",
};

const CATEGORIES: MediaCategory[] = [
  {
    id: "news",
    label: "新闻媒体",
    title: "新闻媒体",
    description: "主流新闻门户、权威新闻网站与地方新闻资源，适合品牌背书、事件发布与区域声量。",
    sections: [
      {
        title: "第三方新闻媒体",
        note: "商业门户与综合资讯平台",
        items: [
          { name: "网易", domain: "163.com", tone: "red", mark: "网易", sub: "NETEASE" },
          { name: "腾讯网", domain: "qq.com", tone: "blue", logoStyle: "circle", mark: "腾讯网" },
          { name: "新浪", domain: "sina.com.cn", tone: "dark", mark: "sina", sub: "新浪" },
          { name: "搜狐", domain: "sohu.com", tone: "yellow", logoStyle: "square", mark: "搜狐", sub: "SOHU.COM" },
          { name: "凤凰网", domain: "ifeng.com", tone: "red", mark: "凤凰网", sub: "IFENG.COM" },
          { name: "China.com", domain: "china.com", tone: "red", logoStyle: "china", mark: "China" },
          { name: "澎湃新闻", domain: "thepaper.cn", tone: "dark", logoStyle: "play", mark: "澎湃新闻" },
          { name: "界面新闻", domain: "jiemian.com", tone: "dark", mark: "界面新闻" },
          { name: "财新网", domain: "caixin.com", tone: "red", mark: "财新网" },
          { name: "第一财经", domain: "yicai.com", tone: "red", mark: "第一财经" },
          { name: "环球网", domain: "huanqiu.com", tone: "blue", mark: "环球网" },
          { name: "观察者网", domain: "guancha.cn", tone: "red", mark: "观察者网" },
        ],
      },
      {
        title: "权威新闻网站",
        note: "中央与地方新闻网站",
        items: [
          { name: "新华网", domain: "news.cn", tone: "red", logoStyle: "circle", mark: "新华网" },
          { name: "人民网", domain: "people.com.cn", tone: "red", mark: "人民网" },
          { name: "央视网", domain: "cctv.com", tone: "blue", logoStyle: "circle", mark: "央视网" },
          { name: "中国新闻网", domain: "chinanews.com.cn", tone: "red", mark: "中国新闻网" },
          { name: "光明网", domain: "gmw.cn", tone: "blue", mark: "光明网" },
          { name: "中国网", domain: "china.org.cn", tone: "red", mark: "中国网" },
          { name: "中国经济网", domain: "ce.cn", tone: "red", mark: "中国经济网" },
          { name: "南方网", domain: "southcn.com", tone: "red", mark: "南方网" },
          { name: "金羊网", domain: "ycwb.com", tone: "red", mark: "金羊网" },
          { name: "大洋网", domain: "dayoo.com", tone: "blue", mark: "大洋网" },
          { name: "广州日报", domain: "gzdaily.dayoo.com", tone: "red", mark: "广州日报" },
          { name: "羊城晚报", domain: "ycwb.com", tone: "red", mark: "羊城晚报" },
        ],
      },
    ],
  },
  {
    id: "business",
    label: "商业媒体",
    title: "商业媒体",
    description: "科技、财经与行业垂直媒体，适合产品发布、行业观点、案例拆解与商业合作背书。",
    sections: [
      {
        title: "科技与财经媒体",
        note: "新经济、科技与商业报道",
        items: [
          { name: "36氪", domain: "36kr.com", tone: "blue", mark: "36氪" },
          { name: "虎嗅", domain: "huxiu.com", tone: "yellow", logoStyle: "square", mark: "虎嗅", sub: "HUXIU" },
          { name: "钛媒体", domain: "tmtpost.com", tone: "blue", mark: "钛媒体" },
          { name: "亿邦动力", domain: "ebrun.com", tone: "blue", mark: "亿邦动力" },
          { name: "创业邦", domain: "cyzone.cn", tone: "orange", mark: "创业邦" },
          { name: "DoNews", domain: "donews.com", tone: "dark", mark: "DoNews" },
          { name: "雷锋网", domain: "leiphone.com", tone: "blue", mark: "雷锋网" },
          { name: "极客公园", domain: "geekpark.net", tone: "blue", mark: "极客公园" },
          { name: "品玩", domain: "pingwest.com", tone: "red", mark: "PingWest" },
          { name: "动点科技", domain: "technode.com", tone: "red", mark: "动点科技" },
          { name: "镁客网", domain: "im2maker.com", tone: "purple", mark: "镁客网" },
          { name: "广告门", domain: "adquan.com", tone: "dark", mark: "广告门" },
        ],
      },
      {
        title: "行业垂直媒体",
        note: "教育、商业与空间场景",
        items: [
          { name: "芥末堆", domain: "jiemodui.com", tone: "green", mark: "芥末堆" },
          { name: "多知网", domain: "duozhi.com", tone: "blue", mark: "多知网" },
          { name: "决胜网", domain: "juesheng.com", tone: "red", mark: "决胜网" },
          { name: "赢商网", domain: "winshang.com", tone: "red", mark: "赢商网" },
          { name: "联商网", domain: "linkshop.com", tone: "blue", mark: "联商网" },
          { name: "零售商业评论", domain: "lingshou.com", tone: "dark", mark: "零售商业" },
          { name: "亿欧", domain: "iyiou.com", tone: "blue", mark: "亿欧" },
          { name: "甲子光年", domain: "jazzyear.com", tone: "purple", mark: "甲子光年" },
          { name: "新榜", domain: "newrank.cn", tone: "orange", mark: "新榜" },
          { name: "卡思数据", domain: "caasdata.com", tone: "blue", mark: "卡思数据" },
          { name: "克劳锐", domain: "topklout.com", tone: "red", mark: "克劳锐" },
          { name: "清博指数", domain: "gsdata.cn", tone: "blue", mark: "清博" },
        ],
      },
    ],
  },
  {
    id: "self",
    label: "自媒体 / 新媒体",
    title: "自媒体 / 新媒体",
    description: "内容平台、社交平台与账号型资源，适合持续内容运营、搜索占位与用户互动。",
    sections: [
      {
        title: "内容与社交平台",
        note: "平台型流量入口",
        items: [
          { name: "微信公众号", domain: "mp.weixin.qq.com", tone: "green", logoStyle: "circle", mark: "公众号" },
          { name: "视频号", domain: "channels.weixin.qq.com", tone: "green", logoStyle: "play", mark: "视频号" },
          { name: "知乎", domain: "zhihu.com", tone: "blue", mark: "知乎" },
          { name: "小红书", domain: "xiaohongshu.com", tone: "red", mark: "小红书" },
          { name: "抖音", domain: "douyin.com", tone: "dark", logoStyle: "play", mark: "抖音" },
          { name: "快手", domain: "kuaishou.com", tone: "orange", logoStyle: "play", mark: "快手" },
          { name: "哔哩哔哩", domain: "bilibili.com", tone: "pink", logoStyle: "bili", mark: "哔哩哔哩" },
          { name: "微博", domain: "weibo.com", tone: "orange", mark: "微博" },
          { name: "今日头条", domain: "toutiao.com", tone: "red", mark: "今日头条" },
          { name: "百家号", domain: "baijiahao.baidu.com", tone: "blue", mark: "百家号" },
          { name: "大鱼号", domain: "dayu.aliyun.com", tone: "orange", mark: "大鱼号" },
          { name: "豆瓣", domain: "douban.com", tone: "green", mark: "豆瓣" },
        ],
      },
      {
        title: "账号与内容分发",
        note: "可运营的账号型入口",
        items: [
          { name: "搜狐号", domain: "sohu.com", tone: "yellow", logoStyle: "square", mark: "搜狐号", sub: "SOHU" },
          { name: "网易号", domain: "163.com", tone: "red", mark: "网易号" },
          { name: "企鹅号", domain: "om.qq.com", tone: "blue", mark: "企鹅号" },
          { name: "新浪看点", domain: "sina.com.cn", tone: "dark", mark: "新浪看点" },
          { name: "凤凰号", domain: "ifeng.com", tone: "red", mark: "凤凰号" },
          { name: "一点资讯", domain: "yidianzixun.com", tone: "orange", mark: "一点资讯" },
          { name: "UC 浏览器", domain: "uc.cn", tone: "orange", mark: "UC" },
          { name: "夸克", domain: "quark.cn", tone: "blue", mark: "夸克" },
          { name: "脉脉", domain: "maimai.cn", tone: "blue", mark: "脉脉" },
          { name: "雪球", domain: "xueqiu.com", tone: "blue", mark: "雪球" },
          { name: "什么值得买", domain: "smzdm.com", tone: "red", mark: "值得买" },
          { name: "大众点评", domain: "dianping.com", tone: "orange", mark: "大众点评" },
        ],
      },
    ],
  },
];

function BrandLogo({ brand }: { brand: MediaBrand }) {
  const style = {
    "--brand-color": TONE_COLOR[brand.tone],
    "--brand-text": brand.tone === "yellow" ? "#211f1c" : "#ffffff",
  } as CSSProperties;

  if (brand.logoStyle === "square") {
    return (
      <span className={`${styles.logoSquare}`} style={style}>
        <span className={styles.squareMain}>{brand.mark ?? brand.name}</span>
        {brand.sub ? <span className={styles.squareSub}>{brand.sub}</span> : null}
      </span>
    );
  }

  if (brand.logoStyle === "china") {
    return (
      <span className={styles.logoChina}>
        {brand.mark ?? brand.name}
        <b>网</b>
      </span>
    );
  }

  if (brand.logoStyle === "circle") {
    return (
      <span className={styles.logoCircle} style={style}>
        <i />
        {brand.mark ?? brand.name}
      </span>
    );
  }

  if (brand.logoStyle === "play") {
    return (
      <span className={styles.logoPlay} style={style}>
        <i />
        {brand.mark ?? brand.name}
      </span>
    );
  }

  if (brand.logoStyle === "bili") {
    return (
      <span className={styles.logoBili}>
        <span>▷</span>
        {brand.mark ?? brand.name}
      </span>
    );
  }

  return (
    <span className={styles.logoText} style={style}>
      {brand.mark ?? brand.name}
      {brand.sub ? <small className={styles.logoSub}>{brand.sub}</small> : null}
    </span>
  );
}

export function MediaMatrix() {
  const [activeId, setActiveId] = useState(CATEGORIES[0].id);
  const active = CATEGORIES.find((category) => category.id === activeId) ?? CATEGORIES[0];
  const total = active.sections.reduce((sum, section) => sum + section.items.length, 0);

  return (
    <main className={styles.page}>
      <section className={styles.hero}>
        <a href="/internal/workbench" className={styles.back}>返回工作台</a>
        <div className={styles.heroInner}>
          <span className={styles.eyebrow}>MEDIA RESOURCE MATRIX</span>
          <h1>媒体资源矩阵</h1>
          <p>新闻媒体 · 商业媒体 · 自媒体 / 新媒体</p>
          <div className={styles.heroMeta}>
            <strong>{CATEGORIES.reduce((sum, category) => sum + category.sections.reduce((sectionSum, section) => sectionSum + section.items.length, 0), 0)}</strong>
            个资源类型 · 按渠道类型归档
          </div>
        </div>
      </section>

      <div className={styles.tabsBar}>
        <div className={styles.tabs} role="tablist" aria-label="媒体资源分类">
          {CATEGORIES.map((category) => {
            const count = category.sections.reduce((sum, section) => sum + section.items.length, 0);
            const selected = category.id === activeId;
            return (
              <button
                key={category.id}
                type="button"
                role="tab"
                aria-selected={selected}
                aria-controls={`media-panel-${category.id}`}
                className={`${styles.tab} ${selected ? styles.tabActive : ""}`}
                onClick={() => setActiveId(category.id)}
              >
                {category.label}
                <span className={styles.tabCount}>{count}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className={styles.content} id={`media-panel-${active.id}`} role="tabpanel">
        <div className={styles.categoryIntro}>
          <div>
            <h2>{active.title}</h2>
            <p>{active.description}</p>
          </div>
          <span className={styles.categoryCount}>{total} 个资源</span>
        </div>

        <div className={styles.sections}>
          {active.sections.map((section) => (
            <section key={section.title}>
              <div className={styles.sectionHead}>
                <span className={styles.sectionDot} />
                <h3>{section.title}</h3>
                <span>{section.note} · {section.items.length} 个</span>
              </div>
              <div className={styles.grid}>
                {section.items.map((brand) => (
                  <article key={`${section.title}-${brand.name}`} className={styles.card} title={`${brand.name} · ${brand.domain}`}>
                    <div className={styles.logo} aria-label={brand.name}>
                      <BrandLogo brand={brand} />
                    </div>
                    <span className={styles.domain}>{brand.domain}</span>
                  </article>
                ))}
              </div>
            </section>
          ))}
        </div>

        <p className={styles.footerNote}>
          <strong>说明：</strong>本页是媒体类型目录，用于按资源形态查看可拓展方向，不代表已签约、已开通或已发布。
          实际投放前仍需在渠道台账中完成主体核验、报价审批与发布回执登记。
        </p>
      </div>
    </main>
  );
}
