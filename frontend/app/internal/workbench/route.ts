import { NextResponse } from "next/server";
import { BackendError, backendRequest } from "@/lib/workbench/backend";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";
import { getMockSnapshot } from "@/lib/workbench/mock";
import type { Project, WorkbenchSnapshot } from "@/lib/workbench/types";

interface BackendMembership { id: string; code: string; name: string; role_code: string; permissions: string[] }
interface BackendMe { username: string; display_name: string; projects: BackendMembership[] }
interface BackendLead {
  id: string;
  contact_name: string | null;
  contact_phone: string | null;
  interested_course: string | null;
  enrollment_status: string | null;
  lead_source: string | null;
}
interface BackendTask { id: string; round_id: string; status: string; sampling_no: number }

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
    const projects: Project[] = me.projects.map((project) => ({
      id: project.id,
      code: project.code,
      name: project.name,
      owner: "—",
      status: "运行中",
      updatedAt: "—",
      channels: 0,
      tasks: 0,
    }));
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
          createdAt: "—",
        }));
      } catch (error) {
        if (!(error instanceof BackendError) || error.status !== 403) throw error;
        leadAccess = "forbidden";
      }
    }
    const tasks: WorkbenchSnapshot["tasks"] = selectedProject && permissions.includes("monitoring.read")
      ? (await allPages<BackendTask>(`/api/v1/projects/${selectedProject.id}/monitoring/tasks`, session)).map((task) => ({
          id: task.id,
          question: `任务 ${task.id.slice(0, 8)}`,
          engine: "—",
          projectId: selectedProject.id,
          status: task.status === "running" ? "进行中" as const : task.status === "done" ? "已完成" as const : task.status === "failed" ? "失败" as const : "待执行" as const,
          progress: ["done", "failed"].includes(task.status) ? 100 : 0,
          updatedAt: "—",
        })) : [];
    const snapshot: WorkbenchSnapshot = {
      source: "live", userName: me.display_name || me.username, permissions, leadAccess, projects, leads, tasks, reviews: [], activities: [], trend: [], engines: [],
    };
    return NextResponse.json({ data: snapshot });
  } catch (error) {
    if (error instanceof BackendError) {
      return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
    }
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端，请检查服务状态" } }, { status: 503 });
  }
}
