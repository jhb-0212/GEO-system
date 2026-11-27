"use client";

import { useEffect, useState } from "react";

import { GeoBoardWorkspace } from "@/components/workbench/geo-board";
import { workbenchClient } from "@/lib/workbench/client";
import { PERMISSION } from "@/lib/workbench/permissions";

type ProjectOption = { id: string; name: string };

/** 独立大屏页：不挂工作台侧栏，自带项目切换与返回入口，可直接投屏或转发链接。 */
export function GeoBoardPage() {
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [projectId, setProjectId] = useState("");
  const [canRead, setCanRead] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    const requested = new URLSearchParams(window.location.search).get("project_id") ?? "";
    workbenchClient.snapshot()
      .then((snapshot) => {
        if (!active) return;
        const list = (snapshot.projects ?? []).map((project) => ({ id: project.id, name: project.name }));
        const available = list.some((project) => project.id === requested)
          ? requested
          : list.some((project) => project.id === (snapshot.activeProjectId ?? ""))
            ? snapshot.activeProjectId ?? ""
            : list[0]?.id ?? "";
        setProjects(list);
        setProjectId(available);
        setCanRead(Boolean(snapshot.permissions?.includes(PERMISSION.STATS_READ)));
        if (available) syncUrl(available);
      })
      .catch((cause) => {
        if (!active) return;
        setError(cause instanceof Error ? cause.message : "大屏数据加载失败");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  function syncUrl(value: string) {
    const url = new URL(window.location.href);
    if (value) url.searchParams.set("project_id", value);
    else url.searchParams.delete("project_id");
    window.history.replaceState({}, "", url);
  }

  function chooseProject(value: string) {
    setProjectId(value);
    syncUrl(value);
  }

  const backHref = `/workbench?section=overview${projectId ? `&project_id=${projectId}` : ""}`;

  return <div className="geo-standalone">
    <header className="geo-standalone-head">
      <div>
        <p className="geo-kicker">GEO · DATA BOARD</p>
        <h1>GEO 数据大屏</h1>
        <p>独立页面：可直接投屏，也可以把这个链接发给同事。</p>
      </div>
      <div className="geo-standalone-actions">
        {projects.length > 1 && <select className="geo-standalone-select" value={projectId} onChange={(event) => chooseProject(event.target.value)} aria-label="切换项目">
          {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
        </select>}
        <a className="btn btn-secondary" href={backHref}>返回工作台</a>
      </div>
    </header>
    {error && <p className="geo-error" role="alert">{error}</p>}
    {!error && loading && <p className="geo-empty-page">正在读取项目与会话…</p>}
    {!error && !loading && !projectId && <p className="geo-empty-page">当前账号下没有可查看的项目；请先在「项目管理」里建一个项目。</p>}
    {!error && !loading && projectId && !canRead && <p className="geo-empty-page">当前账号没有数据大屏权限（stats.read）；请联系项目管理员开通。</p>}
    {!error && !loading && projectId && canRead && <GeoBoardWorkspace mode="live" projectId={projectId} canRead/>}
  </div>;
}
