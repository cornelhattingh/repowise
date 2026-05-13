import Image from "next/image";
import { signIn, AUTH_ENABLED } from "@/auth";
import { redirect } from "next/navigation";

export const metadata = { title: "Sign in — repowise" };

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ callbackUrl?: string; error?: string }>;
}) {
  // If auth is disabled, redirect away — this page should never be reachable
  if (!AUTH_ENABLED) {
    redirect("/");
  }

  const { callbackUrl = "/", error } = await searchParams;

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--color-bg-root)]">
      <div className="w-full max-w-sm space-y-8 rounded-xl border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-8 shadow-lg">
        {/* Logo */}
        <div className="flex flex-col items-center gap-3">
          <Image
            src="/repowise-logo.png"
            alt="repowise"
            width={40}
            height={40}
            priority
          />
          <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">
            Sign in to repowise
          </h1>
          <p className="text-center text-sm text-[var(--color-text-secondary)]">
            Authenticate with your organisation account to continue.
          </p>
        </div>

        {/* Error banner */}
        {error && (
          <div className="rounded-md border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
            {error === "AccessDenied"
              ? "Access denied. Your account is not authorised to access this application."
              : "Authentication failed. Please try again."}
          </div>
        )}

        {/* Sign-in form */}
        <form
          action={async () => {
            "use server";
            await signIn("microsoft-entra-id", { redirectTo: callbackUrl });
          }}
        >
          <button
            type="submit"
            className="flex w-full items-center justify-center gap-3 rounded-md bg-[var(--color-accent-primary)] px-4 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-accent-primary)]"
          >
            {/* Microsoft logo SVG */}
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 23 23"
              width="18"
              height="18"
              aria-hidden="true"
            >
              <rect x="1" y="1" width="10" height="10" fill="#f25022" />
              <rect x="12" y="1" width="10" height="10" fill="#7fba00" />
              <rect x="1" y="12" width="10" height="10" fill="#00a4ef" />
              <rect x="12" y="12" width="10" height="10" fill="#ffb900" />
            </svg>
            Continue with Microsoft
          </button>
        </form>
      </div>
    </div>
  );
}
