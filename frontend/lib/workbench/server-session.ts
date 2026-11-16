import { cookies } from "next/headers";
import { BackendError, backendRequest } from "./backend";

export const sessionCookieName = "geo_workbench_session";

// The demo account must never be accepted by a production build.
export function isMockMode(): boolean {
  return process.env.NODE_ENV !== "production" && process.env.GEO_API_MODE === "mock";
}

export async function getSessionToken(): Promise<string | undefined> {
  return (await cookies()).get(sessionCookieName)?.value;
}

export async function isSessionValid(token: string): Promise<boolean> {
  if (isMockMode()) return token === "demo";

  try {
    // The backend validates token_version as well as expiry and account status.
    await backendRequest<unknown>("/api/v1/auth/me", token);
    return true;
  } catch (error) {
    if (error instanceof BackendError && (error.status === 401 || ["token_expired", "token_invalid", "token_stale", "user_inactive"].includes(error.code))) return false;
    throw error;
  }
}
