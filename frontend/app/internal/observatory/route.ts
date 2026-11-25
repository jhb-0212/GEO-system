import { NextResponse } from "next/server";
import { loadObservatoryData } from "@/app/observatory/observatory-server";
import { BackendError, backendRequest } from "@/lib/workbench/backend";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

interface QuestionRow {
  id: string;
  title: string;
  status: string;
}

interface CreatedQuestion {
  id: string;
  version_no: number;
}

interface CreatedContent {
  item_id: string;
}

interface CreatedVersion {
  version_id: string;
  version_no: number;
}

function fail(status: number, code: string, message: string) {
  return NextResponse.json({ error: { code, message } }, { status });
}

function failure(error: unknown) {
  if (error instanceof BackendError) {
    return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
  }
  return fail(503, "backend_unavailable", "无法连接后端");
}

function cleanQuestion(value: unknown): string {
  return typeof value === "string" ? value.trim().replace(/\s+/g, " ") : "";
}

function questionCode(): string {
  return `OBS-${Date.now().toString(36).toUpperCase()}-${Math.random().toString(36).slice(2, 6).toUpperCase()}`;
}

async function existingQuestion(token: string, base: `/api/v1/projects/${string}`, title: string): Promise<QuestionRow | undefined> {
  const result = await backendRequest<QuestionRow[]>(`${base}/questions?page=1&page_size=100` as `/api/v1/${string}`, token);
  const normalized = title.toLowerCase();
  return result.data.find((row) => row.title.trim().toLowerCase() === normalized);
}

/** 旧工作台「监测总览」的读接口：复用观察台同一份加载器，避免两套指标口径。 */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const projectId = url.searchParams.get("project_id") ?? "";
  try {
    const data = await loadObservatoryData(uuid.test(projectId) ? projectId : undefined);
    return NextResponse.json({ data });
  } catch (error) {
    return failure(error);
  }
}

/** 观察台写操作：新建监测问题、从回答缺口创建补写草稿。
 *
 * 前端只提交“问题”和项目，题目 code 由服务端生成；内容草稿会同时挂到对应题目上，
 * 保证从观察台创建的内容能在内容审核与监测链路里反查。
 */
export async function POST(request: Request) {
  const token = await getSessionToken();
  if (!token) return fail(401, "unauthorized", "请先登录");
  if (isMockMode()) return fail(400, "mock_only", "演示数据不能写入，请登录真实项目");

  const url = new URL(request.url);
  const projectId = url.searchParams.get("project_id") ?? "";
  const action = url.searchParams.get("action") ?? "";
  if (!uuid.test(projectId)) return fail(400, "validation_error", "请选择有效项目");

  const body = await request.json().catch(() => null) as { question?: unknown; source?: unknown } | null;
  if (!body || typeof body !== "object") return fail(400, "validation_error", "请求数据无效");
  const question = cleanQuestion(body.question);
  if (question.length < 2 || question.length > 255) return fail(400, "validation_error", "监测问题需要 2–255 个字");

  const base = `/api/v1/projects/${projectId}` as const;

  try {
    // 新建题目必须能读题目库，才能避免重复；创建内容草稿时读不到题目不影响落草稿。
    const exists = await existingQuestion(token, base, question).catch((error) => {
      if (action === "question") throw error;
      return undefined;
    });

    if (action === "question") {
      if (exists) {
        return NextResponse.json({ data: { duplicate: true, question_id: exists.id, message: "这个问题已经在监测题目库里，不用重复添加" } });
      }
      const created = (await backendRequest<CreatedQuestion>(`${base}/questions` as `/api/v1/${string}`, token, {
        method: "POST",
        body: JSON.stringify({
          code: questionCode(),
          title: question,
          question_type: "general",
          status: "active",
          priority: 100,
          text: question,
        }),
      })).data;
      return NextResponse.json({
        data: {
          duplicate: false,
          question_id: created.id,
          message: "已加入监测题目库；下一轮生成任务时，会按项目已启用的 AI 平台自动分配",
        },
      });
    }

    if (action === "content") {
      const title = `补写：${question}`.slice(0, 255);
      const item = (await backendRequest<CreatedContent>(`${base}/contents` as `/api/v1/${string}`, token, {
        method: "POST",
        body: JSON.stringify({ title, kind: "master", content_type: "faq" }),
      })).data;
      const draft = [
        `# ${question}`,
        "",
        "## 用户会怎么问",
        question,
        "",
        "## 这篇要回答什么",
        "用可核实的事实回答这个问题，并给出能点开的官网或内容页链接。",
        "",
        "## 需要先核实",
        "- 课程、班型、周期和收费口径",
        "- 可展示的实训项目与成果",
        "- 就业方向与作品集要求",
        "",
        "## 结尾要带什么",
        "品牌正式名、官网链接和可联系的咨询入口。",
      ].join("\n");
      const version = (await backendRequest<CreatedVersion>(`${base}/contents/${item.item_id}/versions` as `/api/v1/${string}`, token, {
        method: "POST",
        body: JSON.stringify({ body: draft, change_note: "观察台：根据监测缺口创建补写草稿" }),
      })).data;

      if (exists) {
        await backendRequest(`${base}/content-versions/${version.version_id}/links` as `/api/v1/${string}`, token, {
          method: "PUT",
          body: JSON.stringify({ question_ids: [exists.id], citation_ids: [], fact_ids: [], confirm_fact_revisions: false }),
        }).catch(() => null);
      }

      return NextResponse.json({
        data: {
          item_id: item.item_id,
          version_id: version.version_id,
          linked_question: Boolean(exists),
          message: exists
            ? "已创建补写草稿并关联到这道监测题，可到「内容审核」继续写"
            : "已创建补写草稿；题目还没入库，草稿暂未关联监测题",
        },
      });
    }

    return fail(400, "validation_error", "不支持的操作");
  } catch (error) {
    return failure(error);
  }
}
