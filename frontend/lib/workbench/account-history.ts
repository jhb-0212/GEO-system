// 仅在浏览器本地记录登录过的用户名，用于账号菜单的历史账号回填。
// 不存储密码、不存储 access_token；切换账号仍需在登录页重新认证。

const STORAGE_KEY = "geo_account_history";
const MAX_ENTRIES = 5;

export interface AccountEntry {
  username: string;
  lastUsedAt: number;
}

function safeParse(raw: string | null): AccountEntry[] {
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is AccountEntry =>
      !!item && typeof item === "object" &&
      typeof (item as AccountEntry).username === "string" &&
      (item as AccountEntry).username.trim() !== "");
  } catch {
    return [];
  }
}

export function readAccountHistory(): AccountEntry[] {
  if (typeof window === "undefined") return [];
  return safeParse(window.localStorage.getItem(STORAGE_KEY));
}

export function recordAccount(username: string): void {
  const name = username.trim();
  if (!name || typeof window === "undefined") return;
  const history = readAccountHistory().filter((item) => item.username !== name);
  history.unshift({ username: name, lastUsedAt: Date.now() });
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(history.slice(0, MAX_ENTRIES)));
}
