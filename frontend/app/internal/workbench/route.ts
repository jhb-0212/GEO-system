import { NextResponse } from "next/server";
import { BackendError, backendRequest } from "@/lib/workbench/backend";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";
import { getMockSnapshot } from "@/lib/workbench/mock";
import type { Project, WorkbenchSnapshot } from "@/lib/workbench/types";

interface BackendProject { id: string; code: string; name: string; status: string }
interface BackendLead {
  id: string;
  contact_name: string | null;
  contact_phone: string | null;
  interested_course: string | null;
  enrollment_status: string;
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
    const projectsPage = await backendRequest<BackendProject[]>("/api/v1/projects?page=1&page_size=100", session);
    const projects: Project[] = projectsPage.data.map((project) => ({
      id: project.id,
      code: project.code,
      name: project.name,
      owner: "—",
      status: project.status === "active" ? "运行中" : "筹备中",
      updatedAt: "—",
      channels: 0,
      tasks: 0,
    }));
    const requestedProject = new URL(request.url).searchParams.get("project_id");
    const selectedProject = projects.find((project) => project.id === requestedProject) ?? projects[0];
    let leads: WorkbenchSnapshot["leads"] = [];
    if (selectedProject) {
      const leadsPage = await backendRequest<BackendLead[]>(`/api/v1/projects/${selectedProject.id}/leads?page=1&page_size=100`, session);
      leads = leadsPage.data.map((lead) => ({
        id: lead.id,
        contactName: lead.contact_name ?? "未填写",
        phone: lead.contact_phone ?? "—",
        interest: lead.interested_course ?? "—",
        source: "—",
        projectId: selectedProject.id,
        status: "待跟进",
        createdAt: "—",
      }));
    }
    const snapshot: WorkbenchSnapshot = {
      source: "live", projects, leads, tasks: [], reviews: [], activities: [], trend: [], engines: [],
    };
    return NextResponse.json({ data: snapshot });
  } catch (error) {
    if (error instanceof BackendError) {
      return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
    }
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端，请检查服务状态" } }, { status: 503 });
  }
}
