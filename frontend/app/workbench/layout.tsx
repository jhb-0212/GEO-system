import { cookies } from "next/headers";
import { redirect } from "next/navigation";

// Session validation is request-bound; this route cannot be prerendered.
export const instant = false;

export default async function WorkbenchLayout({ children }: LayoutProps<"/workbench">) {
  const session = (await cookies()).get("geo_workbench_session")?.value;
  if (!session || (process.env.GEO_API_MODE === "mock" && session !== "demo")) {
    redirect("/login");
  }
  return children;
}
