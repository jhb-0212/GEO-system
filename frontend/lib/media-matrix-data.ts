/**
 * 媒体资源矩阵的默认目录。
 *
 * 这是平台级展示目录，不是某个客户 / 项目的数据；默认目录只用于
 * 「后台还没保存过配置」和「后端不可用」两种情况兜底，线上修改以
 * 后台保存的配置为准。
 */

export type Tone = "red" | "blue" | "dark" | "yellow" | "green" | "orange" | "pink" | "purple";

export type LogoStyle = "text" | "square" | "china" | "circle" | "play" | "bili";

export type MediaBrand = {
  name: string;
  domain: string;
  tone: Tone;
  logo?: string;
  logoStyle?: LogoStyle;
  mark?: string;
  sub?: string;
  more?: boolean;
};

export type MediaSection = {
  title: string;
  note: string;
  items: MediaBrand[];
};

export type MediaCategory = {
  id: string;
  label: string;
  title: string;
  description: string;
  sections: MediaSection[];
};

export type MediaMatrixCatalog = MediaCategory[];

export const TONE_COLOR: Record<Tone, string> = {
  red: "#d71920",
  blue: "#1a73e8",
  dark: "#222838",
  yellow: "#ffd400",
  green: "#07a35a",
  orange: "#ff6900",
  pink: "#fb7299",
  purple: "#6b35f5",
};

export const CATEGORIES: MediaMatrixCatalog = [
  {
    id: "news",
    label: "新闻媒体",
    title: "新闻媒体",
    description: "主流新闻门户、权威新闻网站与行业垂直媒体，适合品牌背书、事件发布与区域声量。",
    sections: [
      {
        title: "第三方新闻媒体",
        note: "商业门户与综合资讯平台",
        items: [
          { name: "网易", domain: "163.com", tone: "red", logo: "/media-logos/netease.png" },
          { name: "腾讯网", domain: "qq.com", tone: "blue", logo: "/media-logos/tencent.png" },
          { name: "新浪", domain: "sina.com.cn", tone: "dark", logo: "/media-logos/sina.png" },
          { name: "搜狐", domain: "sohu.com", tone: "yellow", logo: "/media-logos/sohu.png" },
          { name: "凤凰网", domain: "ifeng.com", tone: "red", logo: "/media-logos/ifeng.png" },
          { name: "China.com", domain: "china.com", tone: "red", logo: "/media-logos/china.png" },
          { name: "大鲁网", domain: "dzwww.com", tone: "red", logo: "/media-logos/dalunet.png" },
          { name: "陕西法制网", domain: "shxlaw.cn", tone: "red", logo: "/media-logos/shxlaw.png" },
          { name: "江西商报", domain: "jxcbw.cn", tone: "blue", logo: "/media-logos/jxcbw.png" },
          { name: "山西科技报", domain: "sxkjb.com", tone: "red", logo: "/media-logos/sxkjb.png" },
          { name: "中国网", domain: "china.org.cn", tone: "red", logo: "/media-logos/chinaorg.png" },
          { name: "鲁网", domain: "sdnews.com.cn", tone: "red", logo: "/media-logos/lunet.png" },
          { name: "中国商人", domain: "ccm.com.cn", tone: "dark", logo: "/media-logos/chinabusiness.png" },
          { name: "企业家日报网", domain: "qyjrb.com", tone: "red", logo: "/media-logos/qyjrb.png" },
          { name: "东北网", domain: "dbw.cn", tone: "blue", logo: "/media-logos/dbw.png" },
          { name: "山东商报", domain: "sdsb.com.cn", tone: "red", logo: "/media-logos/sdsb.png" },
          { name: "更多媒体", domain: "", tone: "dark", more: true },
        ],
      },
      {
        title: "建材行业",
        note: "建材、家居与房产垂直媒体",
        items: [
          { name: "China.com 房产", domain: "house.china.com", tone: "red", logo: "/media-logos/chinafang.png" },
          { name: "房天下", domain: "fang.com", tone: "red", logo: "/media-logos/fang.png" },
          { name: "土巴兔", domain: "to8to.com", tone: "green", logo: "/media-logos/tubatu.png" },
          { name: "和讯房产", domain: "house.hexun.com", tone: "dark", logo: "/media-logos/hexun.png" },
          { name: "齐家", domain: "jia.com", tone: "red", logo: "/media-logos/qijia.png" },
          { name: "中金在线", domain: "cnfol.com", tone: "red", logo: "/media-logos/cnfol.png" },
          { name: "中国建材网", domain: "jc001.cn", tone: "blue", mark: "中国建材网" },
          { name: "九正建材网", domain: "jc001.cn", tone: "blue", mark: "九正建材" },
          { name: "建材网", domain: "jiancai.com", tone: "red", mark: "建材网" },
          { name: "慧聪建材网", domain: "b2b.hc360.com", tone: "red", mark: "慧聪建材" },
          { name: "中国建筑装饰网", domain: "ccd.com.cn", tone: "blue", mark: "建筑装饰网" },
          { name: "陶瓷网", domain: "taoci.com", tone: "orange", mark: "陶瓷网" },
          { name: "门窗网", domain: "menchuang.cn", tone: "blue", mark: "门窗网" },
          { name: "中华建材网", domain: "chinabm.cn", tone: "red", mark: "中华建材" },
          { name: "华夏家居网", domain: "hxhome.com", tone: "orange", mark: "华夏家居" },
          { name: "中国木业网", domain: "wood365.cn", tone: "green", mark: "中国木业网" },
          { name: "更多媒体", domain: "", tone: "dark", more: true },
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
