import Link from "next/link";

export default function NotFound() {
  return (
    <main className="access-denied">
      <h1>页面不存在</h1>
      <p>链接可能已经调整。返回工作台继续操作。</p>
      <Link href="/workbench">进入工作台</Link>
    </main>
  );
}
