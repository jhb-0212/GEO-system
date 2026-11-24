"use client";

import type { Dispatch, ReactNode, SetStateAction } from "react";

import { FaqWorkspace, MaterialsWorkspace } from "../knowledge-workbench";
import { MonitoringRounds } from "../monitoring-rounds";
import { ChannelsWorkspace } from "../channels-workspace";
import { EnginesWorkspace } from "../engines-workspace";
import { FactsWorkspace } from "../facts-workspace";
import { StatisticsWorkspace } from "../statistics-workspace";
import { MonthlyReportWorkspace } from "../monthly-report-workspace";
import { LeadFunnelWorkspace } from "../lead-funnel-workspace";
import { QuestionsWorkspace } from "../questions-workspace";
import { SamplesWorkspace } from "../samples-workspace";
import { PublishingWorkspace } from "../publishing-workspace";
import { DiagnosticsWorkspace } from "../diagnostics-workspace";
import { OnboardingWorkspace } from "../onboarding-wizard";
import { OrganizationSettingsWorkspace } from "../organization-settings-workspace";
import { ContentWorkspace } from "../content-workspace";
import { CompetitorsWorkspace } from "../competitors-workspace";
import { BrandWorkspace } from "../brand-workspace";
import { MetricsWorkspace } from "../metrics-workspace";
import { MembersWorkspace } from "../members-workspace";
import { PlansWorkspace } from "../plans-workspace";
import { OpportunitiesWorkspace } from "../opportunities-workspace";
import { SiteDiagnosticsWorkspace } from "../site-diagnostics-workspace";
import { QuotesWorkspace } from "../quotes-workspace";
import { BudgetWorkspace } from "../budget-workspace";
import { ActivityView, Leads, Monitoring, Overview, ProfileView, Projects } from "./legacy-views";
import { CompanyProfileWorkspace } from "./company-profile";
import { BasicInfoWorkspace } from "./basic-info";
import { FeedAccessWorkspace } from "./feed-access";
import { OnboardingGuide } from "./onboarding-guide";
import { DiagnosisReportWorkspace } from "./diagnosis-report";
import { SentimentWorkspace } from "./sentiment";
import { PublishBoardWorkspace } from "./publish-board";
import { PublishClosureWorkspace } from "./publish-closure";
import { DistributionWorkspace } from "./distribution";
import { ContentFactoryWorkspace } from "./content-factory";
import { ContentAdaptationWorkspace } from "./content-adaptation";
import { MicrositeWorkspace } from "./microsite";
import { DashboardTracksWorkspace } from "./dashboard-tracks";
import { ConsumptionWorkspace } from "./consumption";
import { HealthCheckWorkspace } from "./health-check";
import { TrafficWorkspace } from "./traffic";
import { GenerationWorkspace } from "./generation";
import { EncyclopediaWorkspace } from "./encyclopedia";
import { projectName, toDemoVersion } from "./shared";
import { Icon } from "../ui";
import { PERMISSION } from "@/lib/workbench/permissions";
import type { useWorkbenchActions } from "@/lib/workbench/use-workbench-actions";
import type { Lead, MonitoringRound, MonitoringTask, Section, WorkbenchSnapshot } from "@/lib/workbench/types";

/**
 * 页面注册表：一个 section 一行，渲染函数按 context 取数据。
 * 加一个新模块 = 这里加一行 + `lib/workbench/navigation.ts` 加一条，
 * 不再往 workbench-app.tsx 的 if 链里塞分支。
 *
 * `can` 已把「演示模式一律放行」的逻辑收敛到一个函数里；
 * 需要只对真实数据生效的判定（例如写权限）用 `liveCan`。
 */
export interface SectionContext {
  projectId: string;
  snapshot: WorkbenchSnapshot;
  can: (permission: string) => boolean;
  liveCan: (permission: string) => boolean;
  isSystemAdmin: boolean;
  navigate: (section: Section) => void;
  notify: (message: string) => void;
  openTask: (task: MonitoringTask) => void;
  openManualTask: (task: MonitoringTask) => void;
  search: string;
  setSearch: (value: string) => void;
  status: string;
  setStatus: (value: string) => void;
  filteredProjects: WorkbenchSnapshot["projects"];
  filteredTasks: MonitoringTask[];
  filteredLeads: Lead[];
  actions: ReturnType<typeof useWorkbenchActions>;
  demoRounds: MonitoringRound[];
  setDemoRounds: Dispatch<SetStateAction<MonitoringRound[]>>;
  generatedRoundKeys: string[];
  setGeneratedRoundKeys: Dispatch<SetStateAction<string[]>>;
  reload: (projectId: string) => void;
}

export const SECTION_VIEWS: Record<Section, (ctx: SectionContext) => ReactNode> = {
  overview: ({ snapshot, projectId, can, navigate, openTask }) => (
    <>
      <OnboardingGuide
        key={`onboarding-${projectId}`}
        mode={snapshot.source}
        projectId={projectId}
        canRead={can(PERMISSION.MONITORING_READ)}
        canReadCert={can(PERMISSION.CONTENT_READ)}
        onNavigate={navigate}
      />
      <Overview snapshot={snapshot} projectName={(id) => projectName(snapshot, id)} onNavigate={navigate} onTask={openTask} />
    </>
  ),

  company: ({ snapshot, projectId, can, notify, navigate }) => (
    <CompanyProfileWorkspace key={`company-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.MONITORING_READ)} canWrite={can(PERMISSION.BRAND_MANAGE)} onNotice={notify} onNavigate={navigate} />
  ),

  "feed-access": ({ snapshot, projectId, can, navigate }) => (    <FeedAccessWorkspace key={`feed-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.CONTENT_READ)} canReadPublish={can(PERMISSION.PUBLISH_READ)} onNavigate={navigate} />
  ),

  report: ({ snapshot, projectId, can }) => (
    <DiagnosisReportWorkspace key={`report-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.STATS_READ)} canExport={can(PERMISSION.EXPORT_DATA)} />
  ),

  sentiment: ({ snapshot, projectId, can, notify }) => (
    <SentimentWorkspace key={`sentiment-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.CONTENT_READ)} canWrite={can(PERMISSION.CONTENT_WRITE)} onNotice={notify} />
  ),

  board: ({ snapshot, projectId, can }) => (
    <PublishBoardWorkspace key={`board-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.PUBLISH_READ)} canExport={can(PERMISSION.EXPORT_DATA)} />
  ),

  closure: ({ snapshot, projectId, can }) => (
    <PublishClosureWorkspace key={`closure-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.PUBLISH_READ)} />
  ),

  distribution: ({ snapshot, projectId, can, notify }) => (
    <DistributionWorkspace key={`dist-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.CONTENT_READ)} canWrite={can(PERMISSION.CONTENT_WRITE)} onNotice={notify} />
  ),

  factory: ({ snapshot, projectId, can, notify }) => (
    <ContentFactoryWorkspace key={`factory-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.CONTENT_READ)} canWrite={can(PERMISSION.CONTENT_WRITE)} onNotice={notify} />
  ),

  adaptation: ({ snapshot, projectId, can, notify }) => (
    <ContentAdaptationWorkspace key={`adapt-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.CONTENT_READ)} canWrite={can(PERMISSION.CONTENT_WRITE)} onNotice={notify} />
  ),

  site: ({ snapshot, projectId, can, notify }) => (
    <MicrositeWorkspace key={`site-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.CONTENT_READ)} canWrite={can(PERMISSION.CONTENT_WRITE)} onNotice={notify} />
  ),

  dash: ({ snapshot, projectId, can }) => (
    <DashboardTracksWorkspace key={`dash-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.STATS_READ)} />
  ),

  health: ({ snapshot, projectId, can }) => (
    <HealthCheckWorkspace key={`health-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.STATS_READ)} />
  ),

  traffic: ({ snapshot, projectId, can }) => (
    <TrafficWorkspace key={`traffic-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.STATS_READ)} />
  ),

  consumption: ({ snapshot, projectId, can }) => (
    <ConsumptionWorkspace key={`consumption-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.STATS_READ)} />
  ),

  generation: ({ snapshot, projectId, can, notify }) => (
    <GenerationWorkspace key={`generation-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.CONTENT_READ)} canWrite={can(PERMISSION.CONTENT_WRITE)} onNotice={notify} />
  ),

  encyclopedia: ({ snapshot, projectId, can, notify }) => (
    <EncyclopediaWorkspace key={`encyclopedia-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.CONTENT_READ)} canWrite={can(PERMISSION.CONTENT_WRITE)} canReview={can(PERMISSION.CONTENT_REVIEW)} onNotice={notify} />
  ),

  "basic-info": ({ snapshot, projectId, can, notify }) => (
    <BasicInfoWorkspace key={`basic-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.CONTENT_READ)} canWrite={can(PERMISSION.CONTENT_WRITE)} onNotice={notify} />
  ),

  projects: ({ filteredProjects, search, setSearch, can, actions }) => (
    <Projects projects={filteredProjects} search={search} onSearch={setSearch} canConfirm={can(PERMISSION.PROJECT_CONFIRM)} onConfirm={actions.confirmProject} />
  ),

  monitoring: ({ snapshot, projectId, demoRounds, setDemoRounds, generatedRoundKeys, setGeneratedRoundKeys, can, filteredTasks, search, setSearch, status, setStatus, openTask, openManualTask, notify, reload }) => (
    <>
      <details className="rounds-fold">
        <summary><span><Icon name="layers" size={17}/>监测轮次与批量生成</span><small>展开后可新建轮次、批量生成监测任务</small><Icon name="chevronDown" size={15}/></summary>
        <MonitoringRounds key={projectId} mode={snapshot.source} projectId={projectId} projects={snapshot.projects} rounds={demoRounds} setRounds={setDemoRounds} generatedKeys={generatedRoundKeys} setGeneratedKeys={setGeneratedRoundKeys} canExecute={can(PERMISSION.MONITORING_EXECUTE)} onNotice={notify} onGenerated={() => reload(projectId)} />
      </details>
      <Monitoring snapshot={snapshot} tasks={filteredTasks} search={search} status={status} onSearch={setSearch} onStatus={setStatus} onTask={openTask} onManualTask={openManualTask} onNotice={notify} />
    </>
  ),

  diagnostics: ({ snapshot, projectId, can, isSystemAdmin }) => (
    <DiagnosticsWorkspace key={projectId} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.MONITORING_EXECUTE) || can(PERMISSION.PROJECT_MEMBER_MANAGE)} isSystemAdmin={isSystemAdmin} />
  ),

  questions: ({ snapshot, projectId, can, notify }) => (
    <QuestionsWorkspace key={projectId} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.QUESTION_READ)} canWrite={can(PERMISSION.QUESTION_WRITE)} onNotice={notify} />
  ),

  samples: ({ snapshot, projectId, can, liveCan, notify }) => (
    <SamplesWorkspace
      key={projectId}
      mode={snapshot.source}
      projectId={projectId}
      canRead={can(PERMISSION.MONITORING_READ)}
      canReview={can(PERMISSION.EVIDENCE_REVIEW)}
      canReadChannels={can(PERMISSION.CHANNEL_READ)}
      canDownloadEvidence={can(PERMISSION.EVIDENCE_READ)}
      canCreate={liveCan(PERMISSION.MONITORING_EXECUTE)}
      canUploadEvidence={liveCan(PERMISSION.MONITORING_EXECUTE) || liveCan(PERMISSION.EVIDENCE_REVIEW)}
      onNotice={notify}
    />
  ),

  publishing: ({ snapshot, projectId, can, notify }) => (
    <PublishingWorkspace
      key={projectId}
      mode={snapshot.source}
      projectId={projectId}
      canRead={can(PERMISSION.PUBLISH_READ)}
      canExecute={can(PERMISSION.PUBLISH_EXECUTE)}
      canCancel={can(PERMISSION.PUBLISH_CANCEL) || can(PERMISSION.PUBLISH_EXECUTE)}
      canApprove={can(PERMISSION.CHANNEL_APPROVE)}
      canDeleteAccounts={can(PERMISSION.PUBLISH_ACCOUNT_DELETE) || can(PERMISSION.PUBLISH_EXECUTE)}
      onNotice={notify}
    />
  ),

  channels: ({ snapshot, projectId, can, notify }) => (
    <ChannelsWorkspace key={projectId} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.CHANNEL_READ)} canWrite={can(PERMISSION.CHANNEL_WRITE)} canApprove={can(PERMISSION.CHANNEL_APPROVE)} canExport={can(PERMISSION.EXPORT_DATA)} onNotice={notify} />
  ),

  statistics: ({ snapshot, projectId, can, notify, navigate }) => (
    <StatisticsWorkspace key={projectId} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.STATS_READ)} canExport={can(PERMISSION.EXPORT_DATA)} canFreeze={can(PERMISSION.MONITORING_EXECUTE)} canCheckVisibility={can(PERMISSION.MONITORING_EXECUTE)} onNotice={notify} onNavigate={navigate} />
  ),

  facts: ({ snapshot, projectId, can, liveCan, notify }) => (
    <FactsWorkspace key={`facts-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.CONTENT_READ)} canWrite={liveCan(PERMISSION.CONTENT_WRITE)} canReview={liveCan(PERMISSION.CONTENT_REVIEW)} canReviewClaims={liveCan(PERMISSION.EVIDENCE_REVIEW)} onNotice={notify} />
  ),

  monthly: ({ snapshot, projectId, can, liveCan, notify }) => (
    <MonthlyReportWorkspace key={`monthly-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.STATS_READ)} canFreeze={liveCan(PERMISSION.CONTENT_REVIEW) || liveCan(PERMISSION.MONITORING_EXECUTE)} onNotice={notify} />
  ),

  funnel: ({ snapshot, projectId }) => (
    <LeadFunnelWorkspace key={`funnel-${projectId}`} mode={snapshot.source} projectId={projectId} leadAccess={snapshot.leadAccess ?? "unavailable"} />
  ),

  reviews: ({ snapshot, projectId, can, liveCan, notify }) => (
    <ContentWorkspace key={projectId} mode={snapshot.source} projectId={projectId} demoItems={snapshot.source === "mock" ? snapshot.reviews.map(toDemoVersion) : undefined} canRead={can(PERMISSION.CONTENT_READ)} canWrite={liveCan(PERMISSION.CONTENT_WRITE)} canReview={liveCan(PERMISSION.CONTENT_REVIEW)} onNotice={notify} />
  ),

  leads: ({ snapshot, filteredLeads, search, setSearch, status, setStatus, actions, can, liveCan }) => (
    <Leads snapshot={snapshot} leads={filteredLeads} search={search} onSearch={setSearch} status={status} onStatus={setStatus} onExport={actions.exportLeads} onUpdate={actions.updateLeadStatus} canExport={liveCan(PERMISSION.EXPORT_DATA)} canWrite={can(PERMISSION.LEAD_WRITE)} />
  ),

  faq: ({ snapshot, projectId, can, notify }) => (
    <FaqWorkspace key={`faq-${projectId}`} mode={snapshot.source} projectId={projectId} projects={snapshot.projects} canRead={can(PERMISSION.CONTENT_READ)} canWrite={can(PERMISSION.CONTENT_WRITE)} canReview={can(PERMISSION.CONTENT_REVIEW)} onNotice={notify} />
  ),

  materials: ({ snapshot, projectId, can, notify }) => (
    <MaterialsWorkspace key={`materials-${projectId}`} mode={snapshot.source} projectId={projectId} projects={snapshot.projects} canRead={can(PERMISSION.CONTENT_READ)} canWrite={can(PERMISSION.CONTENT_WRITE)} onNotice={notify} />
  ),

  competitors: ({ snapshot, projectId, can, notify }) => (
    <CompetitorsWorkspace key={`competitors-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.MONITORING_READ)} canWrite={can(PERMISSION.COMPETITOR_WRITE)} onNotice={notify} />
  ),

  organization: ({ snapshot, projectId, isSystemAdmin, notify }) => (
    <OrganizationSettingsWorkspace key={`org-settings-${projectId}`} mode={snapshot.source} projectId={projectId} isSystemAdmin={isSystemAdmin} projects={snapshot.projects} onNotice={notify} />
  ),

  onboarding: ({ snapshot, projectId, can, liveCan, notify }) => (
    <OnboardingWorkspace key={`onboarding-wizard-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.STATS_READ)} canConfirm={liveCan(PERMISSION.PROJECT_CONFIRM)} onNotice={notify} />
  ),

  brand: ({ snapshot, projectId, can, notify }) => (
    <BrandWorkspace key={`brand-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.MONITORING_READ)} canWrite={can(PERMISSION.BRAND_MANAGE)} onNotice={notify} />
  ),

  metrics: ({ snapshot, projectId, can, notify }) => (
    <MetricsWorkspace key={`metrics-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.STATS_READ)} canWrite={can(PERMISSION.METRIC_MANAGE)} onNotice={notify} />
  ),

  members: ({ snapshot, projectId, can, isSystemAdmin, notify }) => (
    <MembersWorkspace key={`members-${projectId}`} mode={snapshot.source} projectId={projectId} canManage={can(PERMISSION.PROJECT_MEMBER_MANAGE)} isSystemAdmin={isSystemAdmin} onNotice={notify} />
  ),

  plans: ({ snapshot, projectId, can, notify }) => (
    <PlansWorkspace key={`plans-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.CONTENT_READ)} canWrite={can(PERMISSION.CONTENT_WRITE)} onNotice={notify} />
  ),

  opportunities: ({ snapshot, projectId, can, notify }) => (
    <OpportunitiesWorkspace key={`opportunities-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.CONTENT_READ)} canWrite={can(PERMISSION.CONTENT_WRITE)} onNotice={notify} />
  ),

  "site-diagnostics": ({ snapshot, projectId, can, notify }) => (
    <SiteDiagnosticsWorkspace key={`site-diagnostics-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.CONTENT_READ)} canWrite={can(PERMISSION.CONTENT_WRITE)} canImport={can(PERMISSION.MONITORING_EXECUTE)} onNotice={notify} />
  ),

  quotes: ({ snapshot, projectId, can, notify }) => (
    <QuotesWorkspace key={`quotes-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={can(PERMISSION.CONTENT_READ)} canWrite={can(PERMISSION.CONTENT_WRITE)} canReview={can(PERMISSION.CONTENT_REVIEW)} onNotice={notify} />
  ),

  budget: ({ snapshot, projectId, can, notify }) => (
    <BudgetWorkspace key={`budget-${projectId}`} mode={snapshot.source} projectId={projectId} currentUserId={snapshot.currentUserId} canRead={can(PERMISSION.BUDGET_READ)} canWrite={can(PERMISSION.BUDGET_WRITE)} canApprove={can(PERMISSION.BUDGET_APPROVE)} onNotice={notify} />
  ),

  activity: ({ snapshot }) => <ActivityView key={snapshot.activeProjectId ?? "all"} snapshot={snapshot} />,

  engines: ({ snapshot, notify }) => (
    <EnginesWorkspace mode={snapshot.source} canManage={snapshot.isSystemAdmin === true} canVerify={snapshot.isSystemAdmin === true || snapshot.globalPermissions?.includes(PERMISSION.ENGINE_VERIFY) === true} onNotice={notify} />
  ),

  profile: ({ snapshot }) => <ProfileView snapshot={snapshot} />,
};

/** 与 workbench-app 里的 toDemoVersion 同一逻辑，供 reviews 入口用 */
