"use client";

import { LogOut, Monitor, Moon, Settings, Sun } from "lucide-react";
import Link from "next/link";
import { useTheme } from "next-themes";
import { useState } from "react";

import { useTranslations } from "@/components/providers/i18n-provider";
import { useRequiredSession } from "@/components/providers/session-provider";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

/** Initials for the avatar. Two letters max — three starts to look like a word. */
function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

export function UserMenu() {
  const user = useRequiredSession();
  const { t } = useTranslations();
  const { theme, setTheme } = useTheme();
  const [signingOut, setSigningOut] = useState(false);

  async function signOut(everywhere: boolean) {
    setSigningOut(true);
    await fetch(`/api/auth/logout${everywhere ? "?all=true" : ""}`, { method: "POST" });
    // A full navigation, not `router.push`. Sign-out must leave no cached RSC
    // payload holding the previous user's data — which matters on the shared
    // machines common in a staff room.
    window.location.href = "/login";
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="grid size-9 place-items-center rounded-full bg-accent text-sm font-medium text-accent-foreground transition-colors hover:bg-accent/80"
          aria-label="Account menu"
        >
          {initials(user.full_name)}
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="font-normal">
          <p className="text-sm font-medium">{user.full_name}</p>
          <p className="truncate text-xs text-muted-foreground">{user.email}</p>
          {user.role_code ? (
            <p className="mt-1 text-xs text-muted-foreground">
              {user.role_code} · {user.school_name ?? user.organization_name}
            </p>
          ) : null}
        </DropdownMenuLabel>

        <DropdownMenuSeparator />

        <DropdownMenuItem asChild>
          <Link href="/settings" className="gap-2">
            <Settings className="size-4" aria-hidden />
            {t.nav.settings}
          </Link>
        </DropdownMenuItem>

        <DropdownMenuSeparator />

        <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
          Theme
        </DropdownMenuLabel>
        {(
          [
            ["light", Sun, "Light"],
            ["dark", Moon, "Dark"],
            ["system", Monitor, "System"],
          ] as const
        ).map(([value, Icon, labelText]) => (
          <DropdownMenuItem
            key={value}
            onSelect={() => setTheme(value)}
            className="gap-2"
            data-active={theme === value}
          >
            <Icon className="size-4" aria-hidden />
            {labelText}
          </DropdownMenuItem>
        ))}

        <DropdownMenuSeparator />

        <DropdownMenuItem
          onSelect={() => signOut(false)}
          disabled={signingOut}
          className="gap-2"
        >
          <LogOut className="size-4" aria-hidden />
          {t.common.signOut}
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={() => signOut(true)}
          disabled={signingOut}
          className="gap-2 text-muted-foreground"
        >
          {/* Offered alongside the ordinary sign-out because "I think someone else
              has my password" needs a one-click answer, and burying it in settings
              means nobody finds it at the moment they need it. */}
          <LogOut className="size-4" aria-hidden />
          Sign out on all devices
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
