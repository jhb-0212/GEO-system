"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ApiEnvelope } from "./types";

/**
 * 分页列表的统一取数逻辑：一次只负责「当前页 + 总数 + 加载态 + 错误」。
 *
 * 各面板此前各写一套 useEffect + page + loading + error，行为虽然一致，但新增面板
 * 继续复制粘贴就会各自漂移（页大小、总数口径、错误文案）。这里收敛成一份。
 *
 * `fetchPage` 必须是稳定引用（useCallback），否则每次渲染都会重新请求。
 * 取数结果只在 Promise 回调里落地，避免在 effect 同步阶段改状态（React 19 的
 * set-state-in-effect 规则也因此成立）。
 */
export function usePagedData<T>({
  fetchPage,
  enabled = true,
}: {
  fetchPage: (page: number) => Promise<ApiEnvelope<T[]>>;
  enabled?: boolean;
}) {
  const [rows, setRows] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPageState] = useState(1);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState("");
  const [reloadToken, setReloadToken] = useState(0);
  const requestId = useRef(0);

  useEffect(() => {
    if (!enabled) return;
    const id = ++requestId.current;
    let cancelled = false;
    fetchPage(page)
      .then((result) => {
        if (cancelled || id !== requestId.current) return;
        setRows(result.data);
        setTotal(result.meta?.total ?? result.data.length);
        setError("");
      })
      .catch((cause: unknown) => {
        if (cancelled || id !== requestId.current) return;
        setRows([]);
        setTotal(0);
        setError(cause instanceof Error ? cause.message : "列表加载失败");
      })
      .finally(() => {
        if (cancelled || id !== requestId.current) return;
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, [enabled, fetchPage, page, reloadToken]);

  /** 翻页时先置加载态，再改页码。 */
  const goToPage = useCallback((next: number) => {
    setLoading(true);
    setPageState(next);
  }, []);

  const reload = useCallback(() => {
    // 未启用（无权限、未选项目）时不发请求，也不能进入 loading：
    // 没有 effect 收尾，界面会一直停在「加载中」。
    if (!enabled) return;
    setLoading(true);
    setReloadToken((value) => value + 1);
  }, [enabled]);

  /** 筛选条件变化：回到第 1 页并强制重取（页码没变时 reload 仍生效）。 */
  const refresh = useCallback(() => {
    if (!enabled) return;
    setLoading(true);
    setPageState(1);
    setReloadToken((value) => value + 1);
  }, [enabled]);

  // setRows 只用于本地乐观更新（改角色、停用成员这类「服务端已成功、界面先改」的场景）。
  // 不要用它替代服务端重取：它不会更新 total，绕过这个基座的总数口径。
  return { rows, total, page, setPage: goToPage, setRows, loading, error, reload, refresh };
}
