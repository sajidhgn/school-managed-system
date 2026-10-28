import { LocaleSwitcher } from "@/components/locale-switcher";
import { LogoMark } from "@/components/marketing/logo";

import { ParentSignOutButton } from "./sign-out-button";

/** The bar across every signed-in portal page: the school group, language, sign out. */
export function ParentHeader({ organizationName }: { organizationName: string }) {
  return (
    <header className="border-b border-border bg-card">
      <div className="mx-auto flex h-14 w-full max-w-2xl items-center justify-between gap-3 px-4">
        <div className="flex min-w-0 items-center gap-2">
          <LogoMark className="size-7 shrink-0" />
          <span className="truncate font-semibold">{organizationName}</span>
        </div>
        <div className="flex items-center gap-1">
          <LocaleSwitcher />
          <ParentSignOutButton />
        </div>
      </div>
    </header>
  );
}
