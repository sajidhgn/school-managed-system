"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import * as React from "react";

import { useTranslations } from "@/components/providers/i18n-provider";
import { Button } from "@/components/ui/button";

export function ParentSignOutButton() {
  const { t } = useTranslations();
  const router = useRouter();
  const [busy, setBusy] = React.useState(false);

  async function signOut() {
    setBusy(true);
    try {
      await fetch("/api/parent/logout", { method: "POST", credentials: "same-origin" });
    } finally {
      router.push("/parent/login" as Route);
      router.refresh();
    }
  }

  return (
    <Button variant="ghost" size="sm" loading={busy} onClick={signOut}>
      <LogOut />
      {t.parent.signOut}
    </Button>
  );
}
