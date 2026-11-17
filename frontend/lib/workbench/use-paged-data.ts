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
  reloadKey,
}: {
  fetchPage: (page: number) => Promise<ApiEnvelope<T[]>>;
  enabled?: boolean;
  /** 外部触发重取（例如新增成员后 version+1）；值变化即回到当前页重取。 */
  reloadKey?: unknown;
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
  }, [enabled, fetchPage, page, reloadKey, reloadToken]);

  /** 翻页时先置加载态，再改页码。 */
  const goToPage = useCallback((next: number) => {
    setLoading(true);
    setPageState(next);
  }, []);

  const reload = useCallback(() => {
    setLoading(true);
    setReloadToken((value) => value + 1);
  }, []);

  /** 筛选条件变化：回到第 1 页并强制重取（页码没变时 reload 仍生效）。 */
  const refresh = useCallback(() => {
    setLoading(true);
    setPageState(1);
    setReloadToken((value) => value + 1);
  }, []);

  return { rows, total, page, setPage: goToPage, setRows, loading, error, reload, refresh };
}
