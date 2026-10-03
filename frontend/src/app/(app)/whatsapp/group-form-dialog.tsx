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
import { useSaveWhatsAppGroup } from "@/hooks/use-whatsapp";
import type { WhatsAppGroupRead } from "@/lib/api/types";

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
  const classes = useClassSummary();
  const save = useSaveWhatsAppGroup();

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
          <DialogTitle>{group ? "Edit group" : "Link a WhatsApp group"}</DialogTitle>
          <DialogDescription>
            In WhatsApp open the group → Group info → Invite via link → Copy link, and paste it
            below. The school&apos;s WhatsApp number must be an admin of the group.
          </DialogDescription>
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
              <Label htmlFor="wa-class">Class</Label>
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
                  Choose a class
                </option>
                {classes.data?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="wa-section">Section</Label>
              <NativeSelect
                id="wa-section"
                value={sectionId}
                disabled={!classId}
                onChange={(event) => setSectionId(event.target.value)}
              >
                <option value="">Whole class</option>
                {sections.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </NativeSelect>
            </div>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="wa-name">Group name</Label>
            <Input
              id="wa-name"
              required
              maxLength={120}
              value={name}
              placeholder="Grade 5-A Parents"
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="wa-link">Invite link</Label>
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
            Send the monthly fee notice to this group
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={active}
              onChange={(event) => setActive(event.target.checked)}
            />
            Active (uncheck to pause all messages)
          </label>
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" form="wa-group-form" disabled={save.isPending}>
            {group ? "Save" : "Link group"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
