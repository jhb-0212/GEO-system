/**
 * 北京标准时间（Asia/Shanghai）辅助函数。
 *
 * 原则：日期口径一律显式锚定东八区，不依赖浏览器/服务器本地时区，
 * 避免部署在境外机器或用户设备时区不同时"今天/当前月"发生漂移。
 * 后端已按 UTC 存储、按项目时区（默认 Asia/Shanghai）解析日期边界，
 * 前端这里只负责把"现在"换算成北京时间。
 */

export interface BeijingDateParts {
  y: number;
  m: number;
  d: number;
}

export function beijingNowParts(instant: Date = new Date()): BeijingDateParts {
  // en-CA 的日期段顺序是 YYYY-MM-DD，再用 formatToParts 按 type 取值，无歧义
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(instant);
  const get = (type: Intl.DateTimeFormatPartTypes) => Number(parts.find((part) => part.type === type)?.value ?? 0);
  return { y: get("year"), m: get("month"), d: get("day") };
}

/** 北京时间的今天，格式 YYYY-MM-DD */
export function beijingTodayKey(instant: Date = new Date()): string {
  const { y, m, d } = beijingNowParts(instant);
  return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

/** 北京时间的当前月，格式 YYYY-MM */
export function beijingCurrentMonth(instant: Date = new Date()): string {
  const { y, m } = beijingNowParts(instant);
  return `${y}-${String(m).padStart(2, "0")}`;
}
