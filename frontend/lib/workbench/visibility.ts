export type NavScope = "public" | "project" | "global" | "system";

export interface NavVisibilityItem {
  id: string;
  scope: NavScope;
  permissions?: readonly string[];
  match?: "any" | "all";
}

export interface VisibilitySnapshot {
  source: "mock" | "live";
  isSystemAdmin?: boolean;
  permissions?: readonly string[];
  globalPermissions?: readonly string[];
  leadAccess?: "allowed" | "forbidden" | "unavailable";
}

/**
 * 页面是否展示：mock 全量；public 全量；project 看当前项目；global 看全局能力；system 只给系统管理员。
 * 后端接口仍是唯一权限事实源，这里只负责减少误点和 403。
 */
export function canSeeNavItem(
  item: NavVisibilityItem,
  snapshot: VisibilitySnapshot | null | undefined,
): boolean {
  if (!snapshot) return item.scope === "public";
  if (snapshot.source !== "live") return true;
  if (item.scope === "public") return true;
  if (item.scope === "system") return snapshot.isSystemAdmin === true;
  if (item.id === "leads" && snapshot.leadAccess === "forbidden") return false;

  const codes = item.permissions ?? [];
  if (!codes.length) return true;
  if (item.scope === "global" && snapshot.isSystemAdmin === true) return true;
  const owned = item.scope === "global" ? (snapshot.globalPermissions ?? []) : (snapshot.permissions ?? []);
  return item.match === "all"
    ? codes.every((code) => owned.includes(code))
    : codes.some((code) => owned.includes(code));
}
