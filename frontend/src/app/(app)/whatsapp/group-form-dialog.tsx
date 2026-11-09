"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { useClassSummary } from "@/hooks/use-classes";
import { useSaveWhatsAppGroup, useWhatsAppConnection } from "@/hooks/use-whatsapp";
import type { WhatsAppGroupRead } from "@/lib/api/types";
import { whatsappMessages } from "@/lib/i18n/modules/whatsapp";
import { useCatalog } from "@/lib/i18n/use-catalog";

/** Link a new group, or edit one. The invite link is how the group is addressed. */
export function GroupFormDialog({
  open,
  onOpenChange,
  group,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  group: WhatsAppGroupRead | null;
}) {
  const m = useCatalog(whatsappMessages).groupForm;
  const classes = useClassSummary();
  const save = useSaveWhatsAppGroup();
  const gateway = useWhatsAppConnection().data?.configured ?? false;

  const [classId, setClassId] = React.useState("");
  const [sectionId, setSectionId] = React.useState("");
  const [name, setName] = React.useState("");
  const [link, setLink] = React.useState("");
  const [active, setActive] = React.useState(true);
  const [feeNotice, setFeeNotice] = React.useState(true);

  React.useEffect(() => {
    if (!open) return;
    setClassId(group?.class_id ?? "");
    setSectionId(group?.section_id ?? "");
    setName(group?.name ?? "");
    setLink(group ? `https://chat.whatsapp.com/${group.invite_code}` : "");
    setActive(group?.is_active ?? true);
    setFeeNotice(group?.send_fee_notice ?? true);
  }, [open, group]);

  const sections = classes.data?.find((c) => c.id === classId)?.sections ?? [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{group ? m.editTitle : m.newTitle}</DialogTitle>
          <DialogDescription>{m.description}</DialogDescription>
        </DialogHeader>
        <form
          id="wa-group-form"
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate(
              {
                id: group?.id,
                body: {
                  class_id: classId,
                  section_id: sectionId || null,
                  name,
                  invite_link: link,
                  is_active: active,
                  send_fee_notice: feeNotice,
                },
              },
              { onSuccess: () => onOpenChange(false) },
            );
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor="wa-class">{m.class}</Label>
              <NativeSelect
                id="wa-class"
                required
                value={classId}
                onChange={(event) => {
                  setClassId(event.target.value);
                  setSectionId("");
                }}
              >
                <option value="" disabled>
                  {m.chooseClass}
                </option>
                {classes.data?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="wa-section">{m.section}</Label>
              <NativeSelect
                id="wa-section"
                value={sectionId}
                disabled={!classId}
                onChange={(event) => setSectionId(event.target.value)}
              >
                <option value="">{m.wholeClass}</option>
                {sections.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </NativeSelect>
            </div>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="wa-name">{m.name}</Label>
            <Input
              id="wa-name"
              required
              maxLength={120}
              value={name}
              placeholder={m.namePlaceholder}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="wa-link">{m.link}</Label>
            <Input
              id="wa-link"
              required
              value={link}
              placeholder="https://chat.whatsapp.com/…"
              onChange={(event) => setLink(event.target.value)}
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={feeNotice}
              onChange={(event) => setFeeNotice(event.target.checked)}
            />
            {m.feeNotice}
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={active}
              onChange={(event) => setActive(event.target.checked)}
            />
            {m.active}
          </label>
          {gateway && group && !group.chat_id && (
            <p className="rounded-md border border-warning/40 bg-warning/10 p-2 text-xs">
              {m.unreachable}
            </p>
          )}
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {m.cancel}
          </Button>
          <Button type="submit" form="wa-group-form" disabled={save.isPending}>
            {group ? m.save : m.create}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
