/**
 * Next.js middleware — route protection.
 *
 * When AUTH_ENABLED=true, unauthenticated requests to any page are redirected
 * to /login.  Auth.js API routes (/api/auth/*) and the login page itself are
 * always public so the OAuth callback can complete.
 *
 * When AUTH_ENABLED is not "true", this middleware is a no-op and every route
 * is accessible without authentication (existing behaviour).
 */

import { auth, AUTH_ENABLED } from "@/auth";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export async function middleware(req: NextRequest) {
  // Auth disabled — pass all requests through unchanged
  if (!AUTH_ENABLED) {
    return NextResponse.next();
  }

  const session = await auth();

  const { pathname } = req.nextUrl;
  const isAuthRoute =
    pathname.startsWith("/api/auth") ||
    pathname.startsWith("/login") ||
    pathname.startsWith("/_next") ||
    pathname === "/favicon.ico";

  if (!session && !isAuthRoute) {
    const loginUrl = new URL("/login", req.url);
    loginUrl.searchParams.set("callbackUrl", req.url);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  // Run on every route; the function itself decides whether to enforce auth
  matcher: ["/((?!_next/static|_next/image|favicon.ico|public/).*)"],
};
