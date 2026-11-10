export type QuestionKind = 'brand' | 'generic'
export type SampleStatus = 'pending' | 'hit' | 'miss' | 'failed' | 'review'
export type SearchMode = 'web' | 'standard'

export interface Question {
  id: string
  version: number
  text: string
  kind: QuestionKind
  audience: string
  intent: string
  updatedAt: string
}

export interface Engine {
  id: string
  name: string
}

export interface Sample {
  id: string
  projectId: string
  roundId: string
  questionId: string
  questionVersion: number
  questionText: string
  engineId: string
  sequence: number
  mode: SearchMode
  status: SampleStatus
  sampledAt?: string
  answer?: string
  rawUrl?: string
  evidenceNote?: string
  failureReason?: string
}

export interface WorkspaceData {
  schemaVersion: 1
  project: { id: string; name: string }
  questions: Question[]
  engines: Engine[]
  samples: Sample[]
}

export const STATUS_LABEL: Record<SampleStatus, string> = {
  pending: '待执行',
  hit: '有效命中',
  miss: '有效未命中',
  failed: '执行失败',
  review: '待人工复核',
}

export const DEMO_QUESTIONS: Question[] = [
  { id: 'q1', version: 1, text: '广州有哪些适合学习 AI 应用开发的实训项目？', kind: 'generic', audience: '转行人群', intent: '项目发现', updatedAt: '2026-11-10' },
  { id: 'q2', version: 1, text: '广州有哪些提供真实项目实践的数字技能培训基地？', kind: 'generic', audience: '求职人群', intent: '机构比较', updatedAt: '2026-11-10' },
  { id: 'q3', version: 1, text: '学习 AI 工具与内容创作，广州有哪些线下实训选择？', kind: 'generic', audience: '职场人群', intent: '课程发现', updatedAt: '2026-11-10' },
  { id: 'q4', version: 1, text: '【基地全称】的实训路线和课程内容是什么？', kind: 'brand', audience: '意向学员', intent: '课程了解', updatedAt: '2026-11-10' },
  { id: 'q5', version: 1, text: '【基地全称】有哪些可核验的项目案例？', kind: 'brand', audience: '意向学员', intent: '案例核验', updatedAt: '2026-11-10' },
  { id: 'q6', version: 1, text: '【基地全称】的报名方式和咨询入口在哪里？', kind: 'brand', audience: '意向学员', intent: '咨询转化', updatedAt: '2026-11-10' },
]

export const INITIAL_DATA: WorkspaceData = {
  schemaVersion: 1,
  project: { id: 'guangzhou-demo', name: '广州基地试点' },
  questions: DEMO_QUESTIONS,
  engines: [
    { id: 'doubao', name: '豆包' },
    { id: 'yuanbao', name: '腾讯元宝' },
    { id: 'deepseek', name: 'DeepSeek' },
    { id: 'wenxin', name: '百度文心' },
  ],
  samples: [],
}

export function createBaseline(data: WorkspaceData): WorkspaceData {
  if (data.samples.some((sample) => sample.roundId === 'baseline-1')) return data
  const samples = data.questions.flatMap((question) => data.engines.map((engine) => ({
    id: crypto.randomUUID(),
    projectId: data.project.id,
    roundId: 'baseline-1',
    questionId: question.id,
    questionVersion: question.version,
    questionText: question.text,
    engineId: engine.id,
    sequence: 1,
    mode: 'web' as const,
    status: 'pending' as const,
  })))
  return { ...data, samples }
}

export function getMetrics(samples: Sample[]) {
  const valid = samples.filter((sample) => sample.status === 'hit' || sample.status === 'miss')
  const hits = valid.filter((sample) => sample.status === 'hit')
  const cited = valid.filter((sample) => sample.status === 'hit' && sample.rawUrl?.trim())
  const completed = samples.filter((sample) => sample.status !== 'pending')
  return {
    total: samples.length,
    completed: completed.length,
    valid: valid.length,
    hits: hits.length,
    mentionRate: valid.length ? hits.length / valid.length : null,
    // 本地演示只统计已登记的引用 URL；正式引用率需服务端确认来源归属和复核状态。
    provisionalCitationRate: valid.length ? cited.length / valid.length : null,
  }
}
