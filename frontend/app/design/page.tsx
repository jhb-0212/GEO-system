import { Badge, Button, Icon, Panel } from "@/components/ui";
import { GaugeArc, StatTile, TrendArea } from "@/components/viz-kit";
import { StatePlaceholder, TableEmptyRow } from "@/components/states";

export const metadata = { title: "设计地基预览" };

const BRAND = [
  ["--g-brand-50", "#eef3ff"],
  ["--g-brand-100", "#dde7ff"],
  ["--g-brand-300", "#9db9ff"],
  ["--g-brand-500", "#326af4"],
  ["--g-brand-700", "#1d43a3"],
  ["--g-brand-900", "#122a63"],
];

const SEMANTIC = [
  ["--g-info", "#326af4"],
  ["--g-positive", "#2a9d8f"],
  ["--g-warning", "#e5a84b"],
  ["--g-danger", "#e67265"],
  ["--g-neutral", "#8da1bd"],
  ["--g-accent", "#6b5cf0"],
];

const TREND = [
  { label: "08-01", value: 18 },
  { label: "08-08", value: 22 },
  { label: "08-15", value: 31 },
  { label: "08-22", value: null },
  { label: "08-29", value: 44 },
  { label: "09-05", value: 41 },
  { label: "09-12", value: 58 },
];

export default function DesignSystemPage() {
  return (
    <main style={{ padding: 32, background: "var(--g-bg)", minHeight: "100vh", fontFamily: "var(--g-font-sans)" }}>
      <div style={{ maxWidth: "var(--g-content-max)", margin: "0 auto", display: "grid", gap: "var(--g-space-4)" }}>
        <header style={{ display: "grid", gap: 8 }}>
          <p style={{ fontSize: 12, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--g-text-muted)" }}>
            Design tokens · v1
          </p>
          <h1 style={{ fontSize: "var(--g-fs-28)", color: "var(--g-text)", fontWeight: 600 }}>设计地基</h1>
          <p style={{ fontSize: "var(--g-fs-13)", color: "var(--g-text-soft)", maxWidth: 720, lineHeight: "var(--g-lh-base)" }}>
            这一页是 token 与组件的唯一验收口径：色值只从这里取，组件只从这里复用。新页面进来先对照此页，不再各写一套。
          </p>
        </header>

        <div className="g-ds-grid">
          <section className="g-ds-section">
            <div className="g-ds-section-head">
              <h2>色彩</h2>
              <p>主色沿用现有 #326af4；紫色只做「AI 生成」标记的点缀，不当主色。</p>
            </div>
            <div className="g-swatches">
              {BRAND.map(([name, hex]) => (
                <div className="g-swatch" key={name}>
                  <i style={{ background: hex }} />
                  <span>{name}</span>
                </div>
              ))}
            </div>
            <div className="g-swatches">
              {SEMANTIC.map(([name, hex]) => (
                <div className="g-swatch" key={name}>
                  <i style={{ background: hex }} />
                  <span>{name}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="g-ds-section">
            <div className="g-ds-section-head">
              <h2>指标卡</h2>
              <p>value=null 一律显示「尚未采集」，绝不显示 0——这是与加快科技最大的差别。</p>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
              <StatTile label="训练词总量" value={4} unit="个" icon="pulse" />
              <StatTile label="推荐词覆盖" value={833} unit="词" icon="search" tone="positive" delta={12} deltaSuffix="%" hint="较上周" />
              <StatTile label="累计收录" value={15861} unit="条" icon="layers" tone="info" delta={-3} deltaSuffix="%" lowerIsBetter hint="较上周" />
              <StatTile label="线索事件" value={null} icon="users" tone="neutral" hint="等待埋点上报" />
            </div>
          </section>

          <section className="g-ds-section">
            <div className="g-ds-section-head">
              <h2>趋势</h2>
              <p>缺失期断线，不插值、不当 0；轴只留首/中/末三个标签，避免拥挤。</p>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16 }}>
              <TrendArea points={TREND} label="提及量 / 周" ariaLabel="提及量周趋势" unit=" 次" />
              <TrendArea points={TREND.map((point) => ({ ...point, value: null }))} ariaLabel="无数据趋势" />
            </div>
          </section>

          <section className="g-ds-section">
            <div className="g-ds-section-head">
              <h2>分项仪表</h2>
              <p>只评单项达成率，不合成总分。要好看不靠总分，靠满屏单项都接近 100%。</p>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 8 }}>
              <GaugeArc value={0.93} label="基础信息" caption="16/16 项完整" tone="positive" />
              <GaugeArc value={0.62} label="场景词" caption="覆盖不足，建议补 5 个" tone="warning" />
              <GaugeArc value={0.35} label="媒体训练" caption="已发 3/9 篇" tone="danger" />
              <GaugeArc value={null} label="用户画像" />
            </div>
          </section>

          <section className="g-ds-section">
            <div className="g-ds-section-head">
              <h2>五态占位</h2>
              <p>空 / 未采集 / 加载 / 失败 / 无权，各有各的话术与动作，不许都用一句「暂无数据」。</p>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 12 }}>
              <StatePlaceholder kind="empty" description="还没有创建企业档案，先补基础信息才能开始采集。" action={<Button variant="secondary" icon="plus">新建档案</Button>} />
              <StatePlaceholder kind="not-collected" description="该指标的上游采集任务尚未运行，本次不计入。不显示 0 以免误读为真的没有。" />
              <StatePlaceholder kind="loading" title="正在加载第 3 轮快照" />
              <StatePlaceholder kind="error" description="后端返回 503，可能是迁移未完成。请重试或联系管理员。" action={<Button variant="secondary" icon="refresh">重试</Button>} />
            </div>
          </section>

          <section className="g-ds-section">
            <div className="g-ds-section-head">
              <h2>基础控件</h2>
              <p>复用既有 ui.tsx，只补 token 化的排版；不新增第二套按钮。</p>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
              <Button icon="plus">新建</Button>
              <Button variant="secondary" icon="download">导出</Button>
              <Button variant="quiet" icon="filter">筛选</Button>
              <Button variant="danger" icon="close">删除</Button>
              <Badge tone="green" dot>已完成</Badge>
              <Badge tone="amber">待审核</Badge>
              <Badge tone="slate">未采集</Badge>
              <Icon name="spark" size={18} />
              <Icon name="eye" size={18} />
            </div>
            <Panel className="" title="面板示例">
              <div className="panel-heading">
                <h3>可折叠面板</h3>
                <Badge tone="blue">示例</Badge>
              </div>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <tbody>
                  <TableEmptyRow colSpan={3} text="这个模块还没有记录" hint="创建第一条后，这里会按时间倒序显示。" />
                </tbody>
              </table>
            </Panel>
          </section>
        </div>
      </div>
    </main>
  );
}
