import { NextResponse } from "next/server";
import { BackendError, backendRequest } from "@/lib/workbench/backend";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";
import { getMockSnapshot } from "@/lib/workbench/mock";
import type { Project, WorkbenchSnapshot } from "@/lib/workbench/types";

interface BackendMembership { id: string; code: string; name: string; role_code: string; permissions: string[] }
interface BackendMe { username: string; display_name: string; is_system_admin: boolean; projects: BackendMembership[] }
interface BackendProject {
  id: string;
  code: string;
  name: string;
  status: string;
  owner_name: string | null;
  updated_at: string | null;
  channel_count: number;
  task_count: number;
}
interface BackendLead {
  id: string;
  contact_name: string | null;
  contact_phone: string | null;
  interested_course: string | null;
  enrollment_status: string | null;
  lead_source: string | null;
  note?: string | null;
  owner_name?: string | null;
  created_at?: string | null;
}
interface BackendTask {
  id: string; round_id: string; status: string; sampling_no: number;
  question_code: string; question_title: string; engine_name: string; updated_at: string;
}
interface BackendReview { version_id: string; title: string; author_name: string | null; submitted_at: string | null }
interface BackendAudit { id: string; actor_name: string | null; action: string; target_type: string | null; target_id: string | null; created_at: string }
interface BackendTrend { brand_mention_rate: number | null }
interface BackendDistribution { engine_name: string; share: number }
interface BackendStats { brand_mention_rate: number | null }

async function allPages<T>(path: `/api/v1/${string}`, token: string): Promise<T[]> {
  const rows: T[] = [];
  for (let page = 1; page <= 100; page++) {
    const separator = path.includes("?") ? "&" : "?";
    const result = await backendRequest<T[]>(`${path}${separator}page=${page}&page_size=100`, token);
    rows.push(...result.data);
    if (!result.meta || rows.length >= result.meta.total || result.data.length === 0) return rows;
  }
  throw new BackendError(502, "pagination_limit", "数据量超出当前工作台分页上限");
}

export async function GET(request: Request) {
  const session = await getSessionToken();
  if (!session) {
    return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  }
  if (isMockMode()) {
    if (session !== "demo") return NextResponse.json({ error: { code: "unauthorized", message: "演示会话无效" } }, { status: 401 });
    return NextResponse.json({ data: getMockSnapshot() });
  }

  try {
    const me = (await backendRequest<BackendMe>("/api/v1/auth/me", session)).data;
    const projectRows = await allPages<BackendProject>("/api/v1/projects", session);
    const projectMap = new Map(projectRows.map((row) => [row.id, row]));
    const projects: Project[] = me.projects.map((project) => {
      const detail = projectMap.get(project.id);
      return {
        id: project.id,
        code: project.code,
        name: project.name,
        owner: detail?.owner_name ?? "—",
        status: detail?.status === "active" ? "运行中" : "筹备中",
        updatedAt: detail?.updated_at ? detail.updated_at.slice(0, 10) : "—",
        channels: detail?.channel_count ?? 0,
        tasks: detail?.task_count ?? 0,
      };
    });
    const requestedProject = new URL(request.url).searchParams.get("project_id");
    const selectedProject = projects.find((project) => project.id === requestedProject) ?? (requestedProject ? undefined : projects[0]);
    if (requestedProject && !selectedProject) return NextResponse.json({ error: { code: "project_forbidden", message: "无权访问该项目" } }, { status: 403 });
    const membership = me.projects.find((project) => project.id === selectedProject?.id);
    const permissions = membership?.permissions ?? [];
    let leads: WorkbenchSnapshot["leads"] = [];
    let leadAccess: WorkbenchSnapshot["leadAccess"] = "unavailable";
    if (selectedProject) {
      if (!permissions.includes("lead.read")) leadAccess = "forbidden";
      else try {
        const leadRows = await allPages<BackendLead>(`/api/v1/projects/${selectedProject.id}/leads`, session);
        leadAccess = "allowed";
        leads = leadRows.map((lead) => ({
          id: lead.id,
          contactName: lead.contact_name ?? "未填写",
          phone: lead.contact_phone ?? "—",
          interest: lead.interested_course ?? "—",
          source: lead.lead_source ?? "—",
          projectId: selectedProject.id,
          status: lead.enrollment_status === "contacted" ? "跟进中" : lead.enrollment_status === "enrolled" ? "已转化" : lead.enrollment_status === "lost" ? "已流失" : "待跟进",
          createdAt: lead.created_at ? lead.created_at.slice(0, 10) : "—",
          note: lead.note ?? null,
          ownerName: lead.owner_name ?? null,
        }));
      } catch (error) {
        if (!(error instanceof BackendError) || error.status !== 403) throw error;
        leadAccess = "forbidden";
      }
    }
    const tasks: WorkbenchSnapshot["tasks"] = selectedProject && permissions.includes("monitoring.read")
      ? (await allPages<BackendTask>(`/api/v1/projects/${selectedProject.id}/monitoring/tasks`, session)).map((task) => ({
          id: task.id,
          question: `${task.question_code} · ${task.question_title}`,
          engine: task.engine_name,
          projectId: selectedProject.id,
          status: task.status === "running" ? "进行中" as const : task.status === "done" ? "已完成" as const : task.status === "failed" ? "失败" as const : "待执行" as const,
          progress: ["done", "failed"].includes(task.status) ? 100 : 0,
          updatedAt: task.updated_at,
        })) : [];
    const reviewRows = selectedProject && permissions.includes("content.read")
      ? await allPages<BackendReview>(`/api/v1/projects/${selectedProject.id}/content-versions?status=pending_review`, session)
      : [];
    const reviews: WorkbenchSnapshot["reviews"] = reviewRows.map((row) => ({
      id: row.version_id, title: row.title, type: "内容版本", projectId: selectedProject!.id,
      author: row.author_name ?? "未知作者", submittedAt: row.submitted_at ?? "—", status: "待审核",
    }));
    const auditRows = selectedProject && permissions.includes("audit.read")
      ? (await backendRequest<BackendAudit[]>(`/api/v1/projects/${selectedProject.id}/audit-logs?page=1&page_size=20`, session)).data
      : [];
    const activities: WorkbenchSnapshot["activities"] = auditRows.map((row) => ({
      id: row.id, actor: row.actor_name ?? "未知操作者", action: row.action,
      target: `${row.target_type ?? "资源"}${row.target_id ? ` · ${row.target_id.slice(0, 8)}` : ""}`,
      time: row.created_at, tone: "blue",
    }));
    let trend: (number | null)[] = [];
    let engines: WorkbenchSnapshot["engines"] = [];
    let brandMentionRate: number | null = null;
    if (selectedProject && permissions.includes("stats.read")) {
      const base = `/api/v1/projects/${selectedProject.id}/stats` as const;
      const [weekly, distribution, overview] = await Promise.all([
        backendRequest<BackendTrend[]>(`${base}/trend`, session),
        backendRequest<BackendDistribution[]>(`${base}/task-distribution`, session),
        backendRequest<BackendStats>(`${base}/overview`, session),
      ]);
      if (weekly.data.some((point) => point.brand_mention_rate !== null)) {
        trend = weekly.data.map((point) => point.brand_mention_rate === null ? null : point.brand_mention_rate * 100);
      }
      engines = distribution.data.map((item, index) => ({
        name: item.engine_name, share: item.share,
        color: ["#4475ea", "#64b5f6", "#7c65d8", "#55b59b"][index % 4],
      }));
      brandMentionRate = overview.data.brand_mention_rate;
    }
    const snapshot: WorkbenchSnapshot = {
      source: "live", userName: me.display_name || me.username, isSystemAdmin: me.is_system_admin, permissions, leadAccess, projects, leads, tasks, reviews, activities, trend, engines, brandMentionRate,
    };
    return NextResponse.json({ data: snapshot });
  } catch (error) {
    if (error instanceof BackendError) {
      return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
    }
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端，请检查服务状态" } }, { status: 503 });
  }
}
