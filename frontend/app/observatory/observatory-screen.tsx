import { connection } from "next/server";
import { ObservatoryClient } from "./observatory-client";
import { loadObservatoryData } from "./observatory-server";

/** 观察台整屏（服务端取数 + 客户端交互），供 /observatory 与 /workbench 概览共用。 */
export async function ObservatoryScreen({ projectId }: { projectId?: string }) {
  await connection();
  const data = await loadObservatoryData(projectId);
  return <ObservatoryClient data={data} />;
}
