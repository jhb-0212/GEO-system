import { useEffect, useMemo, useState } from 'react'
import { createBaseline, getMetrics, STATUS_LABEL, type Question, type QuestionKind, type Sample, type SampleStatus, type SearchMode, type WorkspaceData } from './model'
import { loadWorkspace, resetWorkspace, saveWorkspace } from './storage'

type Page = 'overview' | 'questions' | 'samples'
type QuestionDraft = Pick<Question, 'text' | 'kind' | 'audience' | 'intent'>

const emptyQuestion: QuestionDraft = { text: '', kind: 'generic', audience: '', intent: '' }
const formatPercent = (value: number | null) => value === null ? '暂无数据' : `${Math.round(value * 100)}%`
const today = () => new Date().toISOString().slice(0, 10)

function App() {
  const [data, setData] = useState<WorkspaceData>(loadWorkspace)
  const [page, setPage] = useState<Page>('overview')
  const [editingQuestion, setEditingQuestion] = useState<Question | 'new' | null>(null)
  const [questionDraft, setQuestionDraft] = useState<QuestionDraft>(emptyQuestion)
  const [selectedSampleId, setSelectedSampleId] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<SampleStatus | 'all'>('all')
  const [engineFilter, setEngineFilter] = useState('all')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    try { saveWorkspace(data) } catch { setNotice('浏览器存储不可用，本次修改可能不会保留。') }
  }, [data])

  const metrics = useMemo(() => getMetrics(data.samples), [data.samples])
  const selectedSample = data.samples.find((sample) => sample.id === selectedSampleId) ?? null
  const filteredSamples = data.samples.filter((sample) =>
    (statusFilter === 'all' || sample.status === statusFilter) &&
    (engineFilter === 'all' || sample.engineId === engineFilter),
  )

  function openQuestion(question?: Question) {
    setEditingQuestion(question ?? 'new')
    setQuestionDraft(question ? { text: question.text, kind: question.kind, audience: question.audience, intent: question.intent } : emptyQuestion)
  }

  function saveQuestion() {
    const text = questionDraft.text.trim()
    if (!text) { setNotice('请填写问题内容。'); return }
    if (editingQuestion === 'new') {
      const question: Question = { id: crypto.randomUUID(), version: 1, text, kind: questionDraft.kind, audience: questionDraft.audience.trim(), intent: questionDraft.intent.trim(), updatedAt: today() }
      setData((current) => ({ ...current, questions: [...current.questions, question] }))
      setNotice('问题已加入题库。已有基线不会自动增加组合。')
    } else if (editingQuestion) {
      const currentQuestion = editingQuestion
      setData((current) => ({ ...current, questions: current.questions.map((question) => question.id === currentQuestion.id ? { ...question, ...questionDraft, text, audience: questionDraft.audience.trim(), intent: questionDraft.intent.trim(), version: question.version + 1, updatedAt: today() } : question) }))
      setNotice('已生成新问题版本。已有采样保留创建时的问题快照。')
    }
    setEditingQuestion(null)
  }

  function updateSample(next: Sample) {
    setData((current) => ({ ...current, samples: current.samples.map((sample) => sample.id === next.id ? next : sample) }))
    setSelectedSampleId(null)
    setNotice('采样记录已保存在本地演示数据中。')
  }

  function generateBaseline() {
    setData((current) => createBaseline(current))
    setPage('samples')
    setNotice('首轮基线组合已生成，请逐条登记人工采样结果。')
  }

  function resetDemo() {
    if (!window.confirm('清空本浏览器中的演示修改与采样记录？')) return
    setData(resetWorkspace())
    setSelectedSampleId(null)
    setNotice('演示数据已重置。')
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">G</span><div><strong>GEO 工作台</strong><small>广州基地 · 试点项目</small></div></div>
      <div className="workspace-switch"><span className="workspace-avatar">广</span><div><strong>{data.project.name}</strong><small>当前项目</small></div><span className="chevron">⌄</span></div>
      <div className="nav-label">工作空间</div>
      <nav aria-label="主导航">
        <button className={page === 'overview' ? 'nav-item active' : 'nav-item'} onClick={() => setPage('overview')}><span>▦</span>工作台概览</button>
        <button className={page === 'questions' ? 'nav-item active' : 'nav-item'} onClick={() => setPage('questions')}><span>▤</span>标准题库 <em>{data.questions.length}</em></button>
        <button className={page === 'samples' ? 'nav-item active' : 'nav-item'} onClick={() => setPage('samples')}><span>◎</span>监测采样 <em>{data.samples.length || '—'}</em></button>
      </nav>
      <div className="sidebar-bottom"><span className="demo-dot" />本地演示模式<br /><small>数据仅保存在此浏览器</small></div>
    </aside>

    <div className="main-area">
      <header className="topbar"><div className="breadcrumb">广州基地试点 <span>/</span> {page === 'overview' ? '工作台概览' : page === 'questions' ? '标准题库' : '监测采样'}</div><div className="topbar-right"><span className="mode-chip">● 本地演示</span><span className="user-avatar">前</span></div></header>
      <main className="content">
        {notice && <div className="notice" role="status"><span>{notice}</span><button aria-label="关闭提示" onClick={() => setNotice('')}>×</button></div>}
        {page === 'overview' && <>
          <div className="page-heading"><div><div className="eyebrow">WORKSPACE OVERVIEW</div><h1>工作台概览</h1><p>从标准问题建立监测基线，逐条记录真实回答与证据。</p></div><button className="secondary-button" onClick={resetDemo}>重置演示数据</button></div>
          <div className="hero"><div><div className="hero-kicker">项目启动 · 第 1 阶段</div><h2>先把监测基线跑起来</h2><p>技术方案要求首轮固定 6 道标准问题 × 4 个引擎。确认题目和品牌全称后，生成组合并登记人工采样结果。</p><div className="hero-actions"><button className="primary-button light" onClick={() => setPage('questions')}>检查标准题库 <span>→</span></button><button className="text-button light-text" onClick={() => setPage('samples')}>查看监测记录 →</button></div></div><div className="hero-graphic" aria-hidden="true"><div className="graphic-ring ring-one"/><div className="graphic-ring ring-two"/><div className="graphic-core">GEO</div><span className="graphic-pip pip-one"/><span className="graphic-pip pip-two"/><span className="graphic-pip pip-three"/></div></div>
          <div className="stats-grid">
            <Stat label="标准问题" value={String(data.questions.length)} suffix="道" hint="品牌题与通用题" icon="▤" />
            <Stat label="计划组合" value={String(metrics.total || data.questions.length * data.engines.length)} suffix="组" hint={metrics.total ? '首轮基线已生成' : '待生成首轮基线'} icon="⊞" />
            <Stat label="采样完成" value={`${metrics.completed}/${metrics.total || data.questions.length * data.engines.length}`} hint="含失败与待复核" icon="◎" />
            <Stat label="品牌提及率" value={formatPercent(metrics.mentionRate)} hint={metrics.valid ? `${metrics.hits} 条命中 / ${metrics.valid} 条有效回答` : '仅按有效回答计算'} icon="↗" />
          </div>
          <div className="overview-grid"><section className="card process-card"><div className="card-heading"><div><h3>首轮基线流程</h3><p>按技术方案固定测试口径，避免样本混算。</p></div><span className="subtle-pill">6 题 × 4 引擎</span></div><div className="steps"><Step number="01" title="确认问题" description="品牌题替换基地全称，核对问题分类和版本。" done={data.questions.length >= 6} /><Step number="02" title="生成组合" description="以问题版本、引擎、轮次和序号建立 24 个采样位。" done={metrics.total > 0} /><Step number="03" title="登记证据" description="填入原始回答、引用链接或明确的失败原因。" done={metrics.completed > 0} /></div><button className="outline-button" onClick={metrics.total ? () => setPage('samples') : generateBaseline}>{metrics.total ? '进入监测采样' : '生成首轮基线'} <span>→</span></button></section>
          <section className="card engine-card"><div className="card-heading"><div><h3>首轮监测引擎</h3><p>每个入口分别采样，记录联网模式。</p></div></div><div className="engine-list">{data.engines.map((engine, index) => <div className="engine-row" key={engine.id}><span className={`engine-icon engine-${index}`}>{engine.name.slice(0, 1)}</span><span>{engine.name}</span><small>{data.samples.filter((sample) => sample.engineId === engine.id && sample.status !== 'pending').length}/{data.samples.filter((sample) => sample.engineId === engine.id).length || data.questions.length} 已登记</small></div>)}</div></section></div>
          <div className="info-line"><span>ⓘ</span> 页面中的题目是演示草稿；品牌全称、题目口径和采样结果需由团队确认。当前没有真实 API 或生产数据。</div>
        </>}

        {page === 'questions' && <>
          <div className="page-heading"><div><div className="eyebrow">QUESTION BANK</div><h1>标准题库</h1><p>编辑问题会生成新版本，已创建的采样记录保留原问题快照。</p></div><button className="primary-button" onClick={() => openQuestion()}>＋ 新建问题</button></div>
          <div className="summary-strip"><div><strong>{data.questions.length}</strong><span>当前问题</span></div><div><strong>{data.questions.filter((q) => q.kind === 'brand').length}</strong><span>品牌题</span></div><div><strong>{data.questions.filter((q) => q.kind === 'generic').length}</strong><span>通用题</span></div><p>演示题目需运营与后端共同确认。品牌题中的【基地全称】必须替换为正式名称。</p></div>
          <section className="card table-card"><div className="card-heading"><div><h3>问题列表</h3><p>首轮基线建议固定 6 道问题。</p></div><span className="subtle-pill">版本可追溯</span></div><div className="table-wrap"><table><thead><tr><th>问题内容</th><th>类型</th><th>目标人群</th><th>意图</th><th>版本</th><th>操作</th></tr></thead><tbody>{data.questions.map((question, index) => <tr key={question.id}><td><div className="question-cell"><span className="row-index">{String(index + 1).padStart(2, '0')}</span><span>{question.text}</span></div></td><td><span className={question.kind === 'brand' ? 'tag tag-blue' : 'tag tag-gray'}>{question.kind === 'brand' ? '品牌题' : '通用题'}</span></td><td>{question.audience || '—'}</td><td>{question.intent || '—'}</td><td>v{question.version}</td><td><button className="link-button" onClick={() => openQuestion(question)}>编辑</button></td></tr>)}</tbody></table></div></section>
          <div className="action-banner"><div><strong>题目确认后，开始首轮基线</strong><p>已生成的组合固定问题文本和版本；后续改题不会改写历史记录。</p></div><button className="primary-button" onClick={generateBaseline}>{metrics.total ? '查看已生成的组合' : '生成 6 × 4 组合'} →</button></div>
        </>}

        {page === 'samples' && <>
          <div className="page-heading"><div><div className="eyebrow">MONITORING</div><h1>监测采样</h1><p>人工采样录入原始回答、引用证据与失败原因。</p></div>{!metrics.total && <button className="primary-button" onClick={generateBaseline}>生成首轮基线</button>}</div>
          {!metrics.total ? <div className="empty-state"><span>◎</span><h2>还没有监测组合</h2><p>确认题库后生成首轮基线，系统会建立每题 × 每引擎的待执行记录。</p><button className="primary-button" onClick={() => setPage('questions')}>先检查题库 →</button></div> : <>
            <div className="sample-stats"><div><small>计划组合</small><strong>{metrics.total}</strong></div><div><small>已登记</small><strong>{metrics.completed}</strong></div><div><small>有效回答</small><strong>{metrics.valid}</strong></div><div><small>执行失败</small><strong>{data.samples.filter((s) => s.status === 'failed').length}</strong></div><div><small>待人工复核</small><strong>{data.samples.filter((s) => s.status === 'review').length}</strong></div></div>
            <div className="toolbar"><div><label htmlFor="status-filter">状态</label><select id="status-filter" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as SampleStatus | 'all')}><option value="all">全部状态</option>{Object.entries(STATUS_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div><div><label htmlFor="engine-filter">引擎</label><select id="engine-filter" value={engineFilter} onChange={(event) => setEngineFilter(event.target.value)}><option value="all">全部引擎</option>{data.engines.map((engine) => <option key={engine.id} value={engine.id}>{engine.name}</option>)}</select></div><span>共 {filteredSamples.length} 条记录</span></div>
            <section className="card table-card sample-table"><div className="table-wrap"><table><thead><tr><th>标准问题</th><th>引擎</th><th>模式</th><th>状态</th><th>采样时间</th><th>操作</th></tr></thead><tbody>{filteredSamples.map((sample) => <tr key={sample.id}><td><div className="question-cell"><span className="row-index">{String(data.questions.findIndex((question) => question.id === sample.questionId) + 1).padStart(2, '0')}</span><span>{sample.questionText}<small>问题 v{sample.questionVersion} · 第 1 轮</small></span></div></td><td>{data.engines.find((engine) => engine.id === sample.engineId)?.name ?? sample.engineId}</td><td>{sample.mode === 'web' ? '联网 / 搜索' : '普通对话'}</td><td><span className={`status status-${sample.status}`}><i />{STATUS_LABEL[sample.status]}</span></td><td>{sample.sampledAt ? new Date(sample.sampledAt).toLocaleString('zh-CN') : '—'}</td><td><button className="link-button" onClick={() => setSelectedSampleId(sample.id)}>{sample.status === 'pending' ? '录入结果' : '查看 / 修改'}</button></td></tr>)}</tbody></table></div>{!filteredSamples.length && <div className="no-results">没有符合筛选条件的记录。</div>}</section>
            <div className="info-line"><span>ⓘ</span> 失败记录不进入有效样本分母。此处仅显示本地演示结果，正式指标应由服务端按审核口径计算。</div>
          </>}
        </>}
      </main>
    </div>

    {editingQuestion && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setEditingQuestion(null) }}><div className="dialog" role="dialog" aria-modal="true" aria-labelledby="question-dialog-title"><div className="dialog-heading"><div><small>QUESTION BANK</small><h2 id="question-dialog-title">{editingQuestion === 'new' ? '新建标准问题' : `编辑问题 · v${editingQuestion.version + 1}`}</h2></div><button className="icon-button" aria-label="关闭" onClick={() => setEditingQuestion(null)}>×</button></div><div className="form-body"><label>问题内容 <span>*</span><textarea rows={3} value={questionDraft.text} onChange={(event) => setQuestionDraft({ ...questionDraft, text: event.target.value })} placeholder="请输入完整的采样问题" /></label><div className="form-grid"><label>问题类型<select value={questionDraft.kind} onChange={(event) => setQuestionDraft({ ...questionDraft, kind: event.target.value as QuestionKind })}><option value="generic">通用题</option><option value="brand">品牌题</option></select></label><label>目标人群<input value={questionDraft.audience} onChange={(event) => setQuestionDraft({ ...questionDraft, audience: event.target.value })} placeholder="例如：意向学员" /></label></div><label>搜索意图<input value={questionDraft.intent} onChange={(event) => setQuestionDraft({ ...questionDraft, intent: event.target.value })} placeholder="例如：课程了解" /></label><p className="form-help">修改会生成新版本；已经创建的采样组合不会被覆盖。</p></div><div className="dialog-footer"><button className="secondary-button" onClick={() => setEditingQuestion(null)}>取消</button><button className="primary-button" onClick={saveQuestion}>保存问题</button></div></div></div>}
    {selectedSample && <SampleDialog sample={selectedSample} engineName={data.engines.find((engine) => engine.id === selectedSample.engineId)?.name ?? selectedSample.engineId} onClose={() => setSelectedSampleId(null)} onSave={updateSample} />}
  </div>
}

function Stat({ label, value, suffix, hint, icon }: { label: string; value: string; suffix?: string; hint: string; icon: string }) {
  return <div className="stat-card"><div className="stat-top"><span>{label}</span><span className="stat-icon">{icon}</span></div><div className="stat-value">{value}<small>{suffix}</small></div><div className="stat-hint">{hint}</div></div>
}

function Step({ number, title, description, done }: { number: string; title: string; description: string; done: boolean }) {
  return <div className="step"><span className={done ? 'step-number done' : 'step-number'}>{done ? '✓' : number}</span><div><strong>{title}</strong><p>{description}</p></div></div>
}

function SampleDialog({ sample, engineName, onClose, onSave }: { sample: Sample; engineName: string; onClose: () => void; onSave: (sample: Sample) => void }) {
  const [draft, setDraft] = useState(sample)
  const [error, setError] = useState('')
  function save() {
    if (draft.status === 'pending') { setError('请选择采样结果状态。'); return }
    if (draft.status === 'failed' && !draft.failureReason?.trim()) { setError('执行失败时请填写失败原因。'); return }
    if ((draft.status === 'hit' || draft.status === 'miss' || draft.status === 'review') && !draft.answer?.trim()) { setError('有效回答或待复核记录需要填写原始回答。'); return }
    onSave({ ...draft, answer: draft.answer?.trim(), rawUrl: draft.rawUrl?.trim(), failureReason: draft.failureReason?.trim(), evidenceNote: draft.evidenceNote?.trim(), sampledAt: draft.sampledAt || new Date().toISOString() })
  }
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}><div className="dialog sample-dialog" role="dialog" aria-modal="true" aria-labelledby="sample-dialog-title"><div className="dialog-heading"><div><small>MANUAL SAMPLE · 第 1 轮</small><h2 id="sample-dialog-title">录入采样结果</h2></div><button className="icon-button" aria-label="关闭" onClick={onClose}>×</button></div><div className="form-body"><div className="sample-context"><span>{engineName}</span><strong>{sample.questionText}</strong><small>问题 v{sample.questionVersion} · 采样序号 {sample.sequence}</small></div><div className="form-grid"><label>采样模式<select value={draft.mode} onChange={(event) => setDraft({ ...draft, mode: event.target.value as SearchMode })}><option value="web">联网 / 搜索</option><option value="standard">普通对话</option></select></label><label>结果状态 <span>*</span><select value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value as SampleStatus })}>{Object.entries(STATUS_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label></div>{draft.status === 'failed' ? <label>失败原因 <span>*</span><select value={draft.failureReason ?? ''} onChange={(event) => setDraft({ ...draft, failureReason: event.target.value })}><option value="">请选择原因</option><option value="登录阻断">登录阻断</option><option value="超时">超时</option><option value="访问阻断">访问阻断</option><option value="验证码">验证码</option><option value="其他">其他</option></select></label> : <><label>原始回答 {(draft.status === 'hit' || draft.status === 'miss' || draft.status === 'review') && <span>*</span>}<textarea rows={5} value={draft.answer ?? ''} onChange={(event) => setDraft({ ...draft, answer: event.target.value })} placeholder="粘贴 AI 产品返回的完整原始回答" /></label><label>原始引用 URL<input type="url" value={draft.rawUrl ?? ''} onChange={(event) => setDraft({ ...draft, rawUrl: event.target.value })} placeholder="https://...（如有多个，先登记主要引用）" /></label></>}<label>证据备注<textarea rows={2} value={draft.evidenceNote ?? ''} onChange={(event) => setDraft({ ...draft, evidenceNote: event.target.value })} placeholder="记录入口、截图位置或复核说明" /></label>{error && <div className="form-error" role="alert">{error}</div>}<p className="form-help">原始回答和人工判断分开保存。截图上传、URL 归一化与审核记录需待接口契约确认后接入。</p></div><div className="dialog-footer"><button className="secondary-button" onClick={onClose}>取消</button><button className="primary-button" onClick={save}>保存记录</button></div></div></div>
}

export default App
