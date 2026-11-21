import { NextResponse } from "next/server";
import { BackendError, backendRequest } from "@/lib/workbench/backend";
import { formatAuditTarget, formatDateTime, formatSerialNo } from "@/lib/workbench/format";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";
import { getMockSnapshot } from "@/lib/workbench/mock";
import { PERMISSION } from "@/lib/workbench/permissions";
import type { Project, WorkbenchSnapshot } from "@/lib/workbench/types";

interface BackendMembership { id: string; code: string; name: string; role_code: string; permissions: string[] }
interface BackendMe { id: string; username: string; display_name: string; is_system_admin: boolean; projects: BackendMembership[] }
interface BackendProject {
  id: string;
  code: string;
  name: string;
  status: string;
  owner_name: string | null;
  priority: number;
  business_confirmed_at: string | null;
  business_confirmed_by: string | null;
  updated_at: string | null;
  channel_count: number;
  task_count: number;
}
interface BackendLead {
  id: string;
  serial_no: number;
  contact_name: string | null;
  contact_phone: string | null;
  interested_course: string | null;
  reported_ai_product?: string | null;
  is_valid?: boolean;
  enrollment_status: string | null;
  lead_source: string | null;
  note?: string | null;
  owner_name?: string | null;
  created_at?: string | null;
}
interface BackendTask {
  id: string; serial_no: number; round_id: string; status: string; sampling_no: number;
  question_code: string; question_title: string; engine_name: string; updated_at: string;
  engine_code?: string; entry_name?: string | null; entry_type?: string | null; entry_url?: string | null;
}
interface BackendReview { version_id: string; title: string; author_name: string | null; submitted_at: string | null }
interface BackendAudit { id: string; serial_no: number; actor_name: string | null; action: string; target_type: string | null; target_id: string | null; created_at: string }
interface BackendTrend { date?: string | null; week_start?: string; brand_mention_rate: number | null }
interface BackendDistribution { engine_name: string; share: number }
interface BackendStats { brand_mention_rate: number | null }

interface PagedRows<T> { rows: T[]; total: number; truncated: boolean }

/**
 * 分页拉全量，但**超限不再抛错**。
 *
 * 之前超过 maxPages 就抛 502 pagination_limit，而工作台快照是一次性聚合的：
 * 一个项目任务数超过 500 条，整个工作台（含与任务无关的项目/线索/品牌页）一起打不开。
 * 现在返回已加载部分 + 后端真实总数 + 截断标记，由界面显式提示「已加载 X / 共 Y」，
 * 计数用 total 而不是 rows.length，避免把截断后的条数当成业务总数。
 */
async function allPages<T>(path: `/api/v1/${string}`, token: string, maxPages = 10): Promise<PagedRows<T>> {
  const rows: T[] = [];
  let total = 0;
  for (let page = 1; page <= maxPages; page++) {
    const separator = path.includes("?") ? "&" : "?";
    const result = await backendRequest<T[]>(`${path}${separator}page=${page}&page_size=100`, token);
    rows.push(...result.data);
    total = result.meta?.total ?? rows.length;
    if (!result.meta || rows.length >= total || result.data.length === 0) return { rows, total, truncated: false };
  }
  return { rows, total, truncated: true };
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
    // 项目列表用于补齐看板字段；用分页拉全，避免系统管理员超过 100 个项目时被截断。
    const projectPage = await allPages<BackendProject>("/api/v1/projects", session, 10);
    const projectRows = projectPage.rows;
    const projectMap = new Map(projectRows.map((row) => [row.id, row]));
    // 系统管理员可看全部项目；普通账号只列自己已加入的项目。
    const visibleProjects = me.is_system_admin
      ? projectRows.map((row) => ({ id: row.id, code: row.code, name: row.name }))
      : me.projects;
    const membershipRole = new Map(me.projects.map((project) => [project.id, project.role_code]));
    const projects: Project[] = visibleProjects.map((project) => {
      const detail = projectMap.get(project.id);
      return {
        id: project.id,
        code: project.code,
        name: project.name,
        owner: detail?.owner_name ?? "—",
        priority: detail?.priority ?? 3,
        businessConfirmedAt: detail?.business_confirmed_at ?? null,
        businessConfirmedBy: detail?.business_confirmed_by ?? null,
        // 后端 ProjectStatus 有 active/paused/archived 三态，之前只认 active，
        // 暂停和归档项目都被显示成「筹备中」，运营会误以为项目还没启动。
        status: detail?.status === "active" ? "运行中" : detail?.status === "paused" ? "已暂停" : detail?.status === "archived" ? "已归档" : "筹备中",
        updatedAt: detail?.updated_at ? detail.updated_at.slice(0, 10) : "—",
        channels: detail?.channel_count ?? 0,
        tasks: detail?.task_count ?? 0,
        roleCode: membershipRole.get(project.id),
      };
    });
    const requestedProject = new URL(request.url).searchParams.get("project_id");
    // 系统管理员能看到全部项目，但默认上下文仍优先落在自己已加入的项目，
    // 避免库里混入测试项目时把工作台带到没有项目权限的空项目。
    const defaultProjectId = me.projects[0]?.id;
    const selectedProject = projects.find((project) => project.id === requestedProject)
      ?? (requestedProject
        ? undefined
        : projects.find((project) => project.id === defaultProjectId) ?? projects[0]);
    if (requestedProject && !selectedProject) return NextResponse.json({ error: { code: "project_forbidden", message: "无权访问该项目" } }, { status: 403 });
    const membership = me.projects.find((project) => project.id === selectedProject?.id);
    const permissions = membership?.permissions ?? [];
    // 全局资源（如 AI 平台入口）按“任一项目持有”判断，和后端 ensure_engine_verification_capability 对齐。
    const globalPermissions = Array.from(new Set(me.projects.flatMap((project) => project.permissions)));
    let leads: WorkbenchSnapshot["leads"] = [];
    let leadAccess: WorkbenchSnapshot["leadAccess"] = "unavailable";
    if (selectedProject) {
      if (!permissions.includes(PERMISSION.LEAD_READ)) leadAccess = "forbidden";
      else try {
        const leadPage = await allPages<BackendLead>(`/api/v1/projects/${selectedProject.id}/leads`, session, 10);
        leadAccess = "allowed";
        leads = leadPage.rows.map((lead) => ({
          id: lead.id,
          serialNo: formatSerialNo(lead.serial_no),
          contactName: lead.contact_name ?? "未填写",
          phone: lead.contact_phone ?? "—",
          interest: lead.interested_course ?? "—",
          source: lead.lead_source ?? "—",
          reportedAiProduct: lead.reported_ai_product ?? null,
          isValid: lead.is_valid ?? true,
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
    let tasks: WorkbenchSnapshot["tasks"] = [];
    let taskTotal = 0;
    let tasksTruncated = false;
    if (selectedProject && permissions.includes(PERMISSION.MONITORING_READ)) {
      const taskPage = await allPages<BackendTask>(`/api/v1/projects/${selectedProject.id}/monitoring/tasks`, session, 5);
      taskTotal = taskPage.total;
      tasksTruncated = taskPage.truncated;
      tasks = taskPage.rows.map((task) => ({
        id: task.id,
        serialNo: formatSerialNo(task.serial_no),
        question: `${task.question_code} · ${task.question_title}`,
        questionTitle: task.question_title,
        engine: task.engine_name,
        engineCode: task.engine_code,
        entryName: task.entry_name ?? null,
        entryType: task.entry_type ?? null,
        entryUrl: task.entry_url ?? null,
        projectId: selectedProject.id,
        // cancelled / uncertain 之前落进 else 分支被显示成「待执行」：
        // uncertain 是「请求已发出但结果未落库」，必须人工核实，不能当成还没跑。
        status: task.status === "running" ? "进行中" as const
          : task.status === "done" ? "已完成" as const
          : task.status === "failed" ? "失败" as const
          : task.status === "cancelled" ? "已取消" as const
          : task.status === "uncertain" ? "待核实" as const
          : "待执行" as const,
        progress: ["done", "failed"].includes(task.status) ? 100 : 0,
        updatedAt: task.updated_at,
      }));
    }
    let reviews: WorkbenchSnapshot["reviews"] = [];
    let reviewTotal = 0;
    let reviewsTruncated = false;
    if (selectedProject && permissions.includes(PERMISSION.CONTENT_READ)) {
      const reviewPage = await allPages<BackendReview>(`/api/v1/projects/${selectedProject.id}/content-versions?status=pending_review`, session, 3);
      reviewTotal = reviewPage.total;
      reviewsTruncated = reviewPage.truncated;
      reviews = reviewPage.rows.map((row) => ({
        id: row.version_id, title: row.title, type: "内容版本", projectId: selectedProject.id,
        author: row.author_name ?? "未知作者", submittedAt: row.submitted_at ?? "—", status: "待审核",
      }));
    }
    const auditPage = selectedProject && permissions.includes(PERMISSION.AUDIT_READ)
      ? await backendRequest<BackendAudit[]>(`/api/v1/projects/${selectedProject.id}/audit-logs?page=1&page_size=20`, session)
      : null;
    const auditRows = auditPage?.data ?? [];
    const activities: WorkbenchSnapshot["activities"] = auditRows.map((row) => ({
      id: row.id, serialNo: formatSerialNo(row.serial_no), actor: row.actor_name ?? "未知操作者", action: row.action,
      target: formatAuditTarget(row.target_type),
      time: formatDateTime(row.created_at), tone: "blue",
    }));
    let trend: (number | null)[] = [];
    let trendDates: string[] = [];
    let engines: WorkbenchSnapshot["engines"] = [];
    let brandMentionRate: number | null = null;
    if (selectedProject && permissions.includes(PERMISSION.STATS_READ)) {
      const base = `/api/v1/projects/${selectedProject.id}/stats` as const;
      const [daily, distribution, overview] = await Promise.all([
        backendRequest<BackendTrend[]>(`${base}/trend/daily?days=30`, session),
        backendRequest<BackendDistribution[]>(`${base}/task-distribution`, session),
        backendRequest<BackendStats>(`${base}/overview`, session),
      ]);
      if (daily.data.some((point) => point.brand_mention_rate !== null)) {
        trend = daily.data.map((point) => point.brand_mention_rate === null ? null : point.brand_mention_rate * 100);
      }
      trendDates = daily.data.map((point) => point.date ?? point.week_start ?? "");
      engines = distribution.data.map((item, index) => ({
        name: item.engine_name, share: item.share,
        color: ["#4475ea", "#64b5f6", "#7c65d8", "#55b59b"][index % 4],
      }));
      brandMentionRate = overview.data.brand_mention_rate;
    }
    const snapshot: WorkbenchSnapshot = {
      source: "live", userName: me.display_name || me.username, username: me.username, currentUserId: me.id, isSystemAdmin: me.is_system_admin, projectRoleCode: membership?.role_code ?? null, permissions, globalPermissions, leadAccess, projects, leads, tasks, reviews, activities, activityTotal: auditPage?.meta?.total ?? activities.length, activeProjectId: selectedProject?.id, trend, trendDates, engines, brandMentionRate,
      taskTotal, reviewTotal, truncated: tasksTruncated || reviewsTruncated || projectPage.truncated,
    };
    return NextResponse.json({ data: snapshot });
  } catch (error) {
    if (error instanceof BackendError) {
      return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
    }
    return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端，请检查服务状态" } }, { status: 503 });
  }
}
