"use client";

import { useCallback } from "react";
import type { Dispatch, SetStateAction } from "react";
import { workbenchClient } from "./client";
import type { Lead, WorkbenchSnapshot } from "./types";

export interface WorkbenchActionDeps {
  snapshot: WorkbenchSnapshot | null;
  projectId: string;
  setSnapshot: Dispatch<SetStateAction<WorkbenchSnapshot | null>>;
  notify: (message: string) => void;
  reload: (projectId?: string) => Promise<void> | void;
}

export interface LeadDraft {
  contactName: string;
  phone: string;
  interest: string;
  source: string;
  reportedAiProduct: string;
  isValid: boolean;
}

function message(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback;
}

/**
 * 工作台的写操作集中在这里：壳只负责布局与导航，不再直接拼请求、不再自己造 export 数据。
 * 演示（mock）与真实（live）的差异只体现在「能不能真的落库」的提示语上，不另开一套导出实现。
 */
export function useWorkbenchActions({ snapshot, projectId, setSnapshot, notify, reload }: WorkbenchActionDeps) {
  const submitLead = useCallback(async (draft: LeadDraft): Promise<boolean> => {
    if (!snapshot) return false;
    const targetProject = projectId === "all" ? snapshot.projects[0]?.id : projectId;
    if (!targetProject) { notify("请先选择项目"); return false; }
    try {
      const lead = await workbenchClient.createLead({ ...draft, projectId: targetProject });
      setSnapshot((current) => current ? { ...current, leads: [lead, ...current.leads] } : current);
      notify(snapshot.source === "mock" ? "已添加到演示列表，未写入正式数据" : "线索已保存");
      return true;
    } catch (cause) {
      notify(message(cause, "保存失败"));
      return false;
    }
  }, [snapshot, projectId, setSnapshot, notify]);

  const exportLeads = useCallback(async () => {
    if (snapshot?.source !== "live") { notify("演示模式不提供导出，请切换到真实接口后使用"); return; }
    if (projectId === "all") { notify("请先选择具体项目再导出线索"); return; }
    try {
      await workbenchClient.downloadLeads(projectId);
      notify("线索 CSV 已下载");
    } catch (cause) {
      notify(message(cause, "导出失败"));
    }
  }, [snapshot?.source, projectId, notify]);

  const updateLeadStatus = useCallback(async (lead: Lead, status: Lead["status"]) => {
    if (!snapshot || snapshot.source !== "live" || projectId === "all") return;
    const statusCode = status === "跟进中" ? "contacted" : status === "已转化" ? "enrolled" : status === "已流失" ? "lost" : "unknown";
    try {
      await workbenchClient.updateLead(projectId, lead.id, { enrollment_status: statusCode });
      setSnapshot((current) => current ? { ...current, leads: current.leads.map((item) => item.id === lead.id ? { ...item, status } : item) } : current);
      notify("线索状态已更新");
    } catch (cause) {
      notify(message(cause, "线索更新失败"));
    }
  }, [snapshot, projectId, setSnapshot, notify]);

  const confirmProject = useCallback(async (project: WorkbenchSnapshot["projects"][number], priority: number) => {
    if (snapshot?.source !== "live") {
      setSnapshot((current) => current ? { ...current, projects: current.projects.map((item) => item.id === project.id ? { ...item, priority, businessConfirmedAt: "刚刚", businessConfirmedBy: "当前账号" } : item) } : current);
      notify("演示模式：已标记资料确认与优先级");
      return;
    }
    try {
      await workbenchClient.confirmProject(project.id, priority);
      await reload(projectId === "all" ? undefined : projectId);
      notify("项目资料已确认，优先级已更新");
    } catch (cause) {
      notify(message(cause, "确认失败"));
    }
  }, [snapshot?.source, projectId, setSnapshot, notify, reload]);

  return { submitLead, exportLeads, updateLeadStatus, confirmProject };
}
