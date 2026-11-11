"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Icon } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      const response = await fetch("/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error?.message ?? "登录失败");
      router.replace("/workbench");
      router.refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "登录失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-screen">
      <section className="login-story" aria-label="GEO 工作台介绍">
        <div className="login-brand"><span className="brand-mark">G</span><span>GEO<span className="brand-dot">.</span>WORKSPACE</span></div>
        <div className="login-story-content">
          <span className="eyebrow light">BRAND INTELLIGENCE PLATFORM</span>
          <h1>让每一次品牌呈现<br />都有迹可循。</h1>
          <p>从监测、内容到线索，汇集在同一个清晰的工作空间。</p>
          <div className="login-story-stats"><div><strong>01</strong><span>统一项目视图</span></div><div><strong>02</strong><span>可追踪的协作</span></div><div><strong>03</strong><span>有依据的决策</span></div></div>
        </div>
        <div className="login-story-footer">GEO SYSTEM <span>·</span> INTERNAL WORKSPACE</div>
      </section>
      <section className="login-form-wrap">
        <div className="login-form-box">
          <div className="login-form-icon"><Icon name="grid" size={23} /></div>
          <p className="eyebrow">WELCOME BACK</p>
          <h2>登录工作台</h2>
          <p className="login-subtitle">仅限团队成员访问，请使用工作账号登录。</p>
          <form onSubmit={submit}>
            <label className="field-label" htmlFor="username">账号</label>
            <div className="input-with-icon"><Icon name="user" size={18} /><input id="username" autoComplete="username" placeholder="请输入工作账号" value={username} onChange={(event) => setUsername(event.target.value)} required /></div>
            <label className="field-label" htmlFor="password">密码</label>
            <div className="input-with-icon"><Icon name="lock" size={18} /><input id="password" type="password" autoComplete="current-password" placeholder="请输入密码" value={password} onChange={(event) => setPassword(event.target.value)} required /></div>
            {error && <p className="form-error" role="alert">{error}</p>}
            <button className="login-submit" disabled={loading} type="submit">{loading ? "正在登录…" : "进入工作台"}<Icon name="arrowRight" size={18} /></button>
          </form>
          <div className="demo-note"><Icon name="info" size={18} /><span>当前为前端演示环境。演示账号和密码均为 <strong>demo</strong>；真实登录需后端接口交付后启用。</span></div>
        </div>
        <p className="login-copyright">© 2026 GEO SYSTEM · 团队内部使用</p>
      </section>
    </main>
  );
}
