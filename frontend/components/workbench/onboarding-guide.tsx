"use client";

import { useEffect, useState } from "react";

import { Badge, Button, Icon, Panel } from "../ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { CertificationRecord, CompanyProfileRecord, ProjectContactRecord, Section, StartupMaterialsRecord } from "@/lib/workbench/types";

/**
 * 首次引导：把「还差什么」聚合成一条可执行的下一步。
 *
 * 判定口径全部来自各页面的真实数据源（企业档案完整度、投喂盘点、资质、对外渠道），
 * 首页只做汇总与跳转：不重算完整度、不把「有记录」读成「已就绪」。
 * 一处都没缺时整块不渲染，避免首页常驻一条无意义的「都好了」。
 */

interface Gap {
  key: string;
  title: string;
  detail: string;
  count: number;
  target: Section;
  action: string;
  tone: "amber" | "red" | "slate";
}

export function OnboardingGuide({
  mode,
  projectId,
  canRead,
  canReadCert,
  onNavigate,
}: {
  mode: "mock" | "live";
  projectId: string;
  canRead: boolean;
  canReadCert: boolean;
  onNavigate: (section: Section) => void;
}) {
  const [company, setCompany] = useState<CompanyProfileRecord | null>(null);
  const [materials, setMaterials] = useState<StartupMaterialsRecord | null>(null);
  const [certs, setCerts] = useState<CertificationRecord[] | null>(null);
  const [contacts, setContacts] = useState<ProjectContactRecord[] | null>(null);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);

  const projectReady = Boolean(projectId) && projectId !== "all";
  const active = mode === "live" && canRead && projectReady;
  const loading = active && loadedFor !== projectId;

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    const settle = (promise: Promise<unknown>) => promise.catch(() => null);
    Promise.all([
      settle(workbenchClient.companyProfile(projectId)).then((row) => { if (!cancelled) setCompany(row as CompanyProfileRecord | null); }),
      settle(workbenchClient.startupMaterials(projectId)).then((row) => { if (!cancelled) setMaterials(row as StartupMaterialsRecord | null); }),
      canReadCert
        ? settle(workbenchClient.certifications(projectId)).then((row) => { if (!cancelled) setCerts(row as CertificationRecord[] | null); })
        : Promise.resolve(),
      canReadCert
        ? settle(workbenchClient.projectContacts(projectId)).then((row) => { if (!cancelled) setContacts(row as ProjectContactRecord[] | null); })
        : Promise.resolve(),
    ]).finally(() => { if (!cancelled) setLoadedFor(projectId); });
    return () => { cancelled = true; };
  }, [projectId, active, canReadCert]);

  if (loading) {
    return (
      <Panel className="onboarding-panel" title="下一步">
        <p className="onboarding-loading">正在汇总缺口…</p>
      </Panel>
    );
  }
  if (!active) return null;

  const gaps: Gap[] = [];

  if (company) {
    const missing = company.missing ?? [];
    if (!company.configured) {
      gaps.push({
        key: "company-new", title: "先建企业档案", target: "company", action: "去填写",
        detail: "企业档案是对外口径的唯一结构化来源，档案空着，后面的生成与投喂都没有依据。", count: 16, tone: "red",
      });
    } else if (missing.length) {
      gaps.push({
        key: "company-gap", title: `企业档案还缺 ${missing.length} 项`, target: "company", action: "补齐",
        detail: missing.slice(0, 4).join("、") + (missing.length > 4 ? ` 等 ${missing.length} 项` : ""),
        count: missing.length, tone: missing.length >= 5 ? "red" : "amber",
      });
    }
  }

  if (materials) {
    const items = materials.items ?? [];
    const notReady = items.filter((item) => item.status !== "ready");
    if (materials.missing.length) {
      gaps.push({
        key: "feed-gap", title: `投喂材料还缺 ${materials.missing.length} 项`, target: "feed-access", action: "查看缺口",
        detail: materials.missing.slice(0, 2).join("；"),
        count: notReady.length || materials.missing.length, tone: "amber",
      });
    }
  }

  if (certs) {
    const expired = certs.filter((row) => row.status === "expired" && row.is_active);
    const expiring = certs.filter((row) => row.status === "expiring" && row.is_active);
    if (certs.length === 0) {
      gaps.push({
        key: "cert-empty", title: "还没有登记资质证书", target: "basic-info", action: "去登记",
        detail: "营业执照与办学许可是对外可信度的基础，登记后到期前 60 天自动标黄。", count: 0, tone: "amber",
      });
    } else if (expired.length || expiring.length) {
      gaps.push({
        key: "cert-expiry", title: expired.length ? `${expired.length} 项资质已过期` : `${expiring.length} 项资质即将到期`,
        target: "basic-info", action: "处理",
        detail: expired.length ? "过期资质不能再作为对外凭据，尽快补证或停用。" : "60 天内到期，先准备续证材料。",
        count: expired.length || expiring.length, tone: expired.length ? "red" : "amber",
      });
    }
  }

  if (contacts && contacts.length === 0) {
    gaps.push({
      key: "contact-empty", title: "还没有登记对外渠道", target: "basic-info", action: "去登记",
      detail: "公众号、小红书、抖音这些入口登记后，投放与生成才引用得到正确账号。", count: 0, tone: "slate",
    });
  }

  if (!gaps.length) return null;
  const shown = gaps.slice(0, 3);

  return (
    <Panel className="onboarding-panel" title="下一步">
      <div className="panel-heading">
        <div>
          <h3>下一步</h3>
          <p>按「先有口径、再有材料、最后补凭据」的顺序排的，做完一条就少一条</p>
        </div>
        <Badge tone="amber">{gaps.length} 项待办</Badge>
      </div>
      <div className="onboarding-grid">
        {shown.map((gap) => (
          <div className="onboarding-card" key={gap.key}>
            <div className="onboarding-card-head">
              <strong>{gap.title}</strong>
              <Badge tone={gap.tone}>{gap.count ? `${gap.count} 项` : "未开始"}</Badge>
            </div>
            <p>{gap.detail}</p>
            <Button variant="secondary" icon="arrowRight" onClick={() => onNavigate(gap.target)}>{gap.action}</Button>
          </div>
        ))}
      </div>
      {gaps.length > shown.length && (
        <p className="onboarding-more"><Icon name="info" size={13} /> 另有 {gaps.length - shown.length} 项待办，先处理上面这三条。</p>
      )}
    </Panel>
  );
}
