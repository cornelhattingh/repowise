"use client";

import { LogOut } from "lucide-react";
import { signOut } from "next-auth/react";

interface SignOutButtonProps {
  iconOnly?: boolean;
}

export function SignOutButton({ iconOnly = false }: SignOutButtonProps) {
  return (
    <button
      onClick={() => signOut({ callbackUrl: "/login" })}
      className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs text-[var(--color-text-tertiary)] transition-colors hover:bg-[var(--color-bg-elevated)] hover:text-[var(--color-text-secondary)]"
      aria-label="Sign out"
      title="Sign out"
    >
      <LogOut className="h-3.5 w-3.5 shrink-0" />
      {!iconOnly && <span>Sign out</span>}
    </button>
  );
}
