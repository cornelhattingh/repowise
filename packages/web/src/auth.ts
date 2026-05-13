/**
 * Auth.js v5 configuration for RepoWise.
 *
 * Authentication is optional and controlled by the AUTH_ENABLED environment
 * variable. When AUTH_ENABLED is not "true", the auth helpers are still
 * importable but the session will always be null — the middleware skips all
 * route protection and the app behaves as before.
 *
 * Required env vars when AUTH_ENABLED=true:
 *   AUTH_SECRET                          — random 32-byte secret (openssl rand -base64 32)
 *   AUTH_MICROSOFT_ENTRA_ID_ID           — Entra app client ID
 *   AUTH_MICROSOFT_ENTRA_ID_SECRET       — Entra app client secret
 *   AUTH_MICROSOFT_ENTRA_ID_ISSUER       — https://login.microsoftonline.com/<TENANT_ID>/v2.0/
 *
 * Optional:
 *   AUTH_ALLOWED_DOMAINS  — comma-separated list of allowed email domains
 *                           e.g. "mycompany.com,partner.com"
 *                           When omitted, any authenticated Entra user is allowed.
 */

import NextAuth from "next-auth";
import MicrosoftEntraID from "next-auth/providers/microsoft-entra-id";

export const AUTH_ENABLED = process.env.AUTH_ENABLED === "true";

const allowedDomains = process.env.AUTH_ALLOWED_DOMAINS
  ? process.env.AUTH_ALLOWED_DOMAINS.split(",").map((d) => d.trim().toLowerCase())
  : null;

export const { handlers, signIn, signOut, auth } = NextAuth({
  providers: [
    MicrosoftEntraID({
      clientId: process.env.AUTH_MICROSOFT_ENTRA_ID_ID ?? "",
      clientSecret: process.env.AUTH_MICROSOFT_ENTRA_ID_SECRET ?? "",
      // issuer is the full OIDC issuer URL; set AUTH_MICROSOFT_ENTRA_ID_ISSUER
      // to https://login.microsoftonline.com/<TENANT_ID>/v2.0/
      // If unset, the provider defaults to the "common" (multi-tenant) endpoint.
    }),
  ],

  callbacks: {
    async signIn({ profile }) {
      if (!allowedDomains) return true;
      const email = (profile?.email ?? profile?.preferred_username ?? "").toLowerCase();
      return allowedDomains.some((domain) => email.endsWith(`@${domain}`));
    },

    async session({ session, token }) {
      // Expose the Entra Object ID so server components can identify the user
      if (token.sub) session.user.id = token.sub;
      return session;
    },
  },

  pages: {
    signIn: "/login",
    error: "/login",
  },
});
