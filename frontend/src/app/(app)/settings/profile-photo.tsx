"use client";

import { Trash2, Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { useTranslations } from "@/components/providers/i18n-provider";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/use-toast";
import { UserAvatar } from "@/components/user-avatar";
import { ApiError } from "@/lib/api/errors";
import { profile } from "@/lib/api/resources";
import type { MeResponse } from "@/lib/api/types";

/**
 * The signed-in member's own photo: upload, replace, remove.
 *
 * Open to every role — it is their own face, not organization data — so unlike the
 * organization block on this page it is never disabled. After a change the page
 * re-renders from the server, which re-reads `/auth/me` and so updates the header
 * avatar too; there is no client copy of the session to patch (`SessionProvider`).
 */
export function ProfilePhoto({ user }: { user: MeResponse }) {
  const router = useRouter();
  const { t } = useTranslations();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  async function change(action: () => Promise<unknown>, done: string) {
    setBusy(true);
    try {
      await action();
      toast({ title: done });
      router.refresh();
    } catch (error) {
      toast({
        variant: "destructive",
        title: t.settings.photoFailed,
        description: error instanceof ApiError ? error.message : undefined,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-5 flex items-center gap-4 border-b border-border pb-5">
      <UserAvatar
        name={user.full_name}
        avatarUrl={user.avatar_url}
        className="size-16"
        fallbackClassName="text-lg"
      />
      <div className="grid min-w-0 gap-2">
        <span className="text-sm font-medium">{t.settings.photo}</span>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => fileInputRef.current?.click()}
          >
            <Upload className="size-4" aria-hidden />
            {busy
              ? t.common.saving
              : user.avatar_url
                ? t.settings.changePhoto
                : t.settings.uploadPhoto}
          </Button>
          {user.avatar_url ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => change(profile.removePhoto, t.settings.photoRemoved)}
            >
              <Trash2 className="size-4" aria-hidden />
              {t.settings.removePhoto}
            </Button>
          ) : null}
        </div>
        <p className="text-xs text-muted-foreground">{t.settings.photoHint}</p>
      </div>
      <input
        ref={fileInputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          // Same file picked twice must fire change again (e.g. after Remove).
          event.target.value = "";
          if (file) void change(() => profile.uploadPhoto(file), t.settings.photoUpdated);
        }}
      />
    </div>
  );
}
