"use client";

/** 公开微站留资：只在有手机号或微信时提交；内部样本/问题 ID 仅作隐藏字段，不在页面上展示。 */

import { useState } from "react";

export function SiteLeadForm({
  slug,
  sampleId,
  questionId,
}: {
  slug: string;
  sampleId?: string;
  questionId?: string;
}) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [wechat, setWechat] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [done, setDone] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy || done) return;
    if (!phone.trim() && !wechat.trim()) {
      setMessage({ kind: "error", text: "请至少填写手机号或微信号" });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch(`/s/${encodeURIComponent(slug)}/leads`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contact_name: name.trim() || null,
          contact_phone: phone.trim() || null,
          contact_wechat: wechat.trim() || null,
          note: note.trim() || null,
          source_sample_id: sampleId || null,
          source_question_id: questionId || null,
        }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        const error = payload?.error as { message?: unknown } | undefined;
        setMessage({
          kind: "error",
          text: typeof error?.message === "string" ? error.message : "提交失败，请稍后再试",
        });
        return;
      }
      setDone(true);
      setMessage({ kind: "ok", text: "已提交，我们会尽快联系你。" });
    } catch {
      setMessage({ kind: "error", text: "网络异常，请稍后再试" });
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return <section className="site-lead site-lead-done"><h2>留资成功</h2><p>{message?.text}</p></section>;
  }

  return (
    <section className="site-lead">
      <h2>留个联系方式</h2>
      <p className="site-lead-hint">仅用于本次咨询联系，不会公开展示。</p>
      <form onSubmit={submit}>
        <label>称呼<input value={name} onChange={(event) => setName(event.target.value)} maxLength={64} placeholder="怎么称呼你" /></label>
        <label>手机号<input value={phone} onChange={(event) => setPhone(event.target.value)} maxLength={64} inputMode="tel" placeholder="用于联系" /></label>
        <label>微信号<input value={wechat} onChange={(event) => setWechat(event.target.value)} maxLength={64} placeholder="选填" /></label>
        <label className="site-lead-note">想了解什么<textarea value={note} onChange={(event) => setNote(event.target.value)} maxLength={1000} rows={3} placeholder="选填" /></label>
        {message && <p className={`site-lead-message ${message.kind}`} role="status">{message.text}</p>}
        <button type="submit" disabled={busy}>{busy ? "提交中…" : "提交"}</button>
      </form>
    </section>
  );
}
