"use client";

import * as React from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState, ErrorState, TableCardSkeleton } from "@/components/data-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useConcessions,
  useCreateConcession,
  useDeleteConcession,
  useUpdateConcession,
} from "@/hooks/use-fees";
import type { ConcessionKind, FeeConcessionRead } from "@/lib/api/types";
import { fill } from "@/lib/i18n/format";
import { feesSetupMessages } from "@/lib/i18n/modules/fees-setup";
import { useCatalog } from "@/lib/i18n/use-catalog";

const money = new Intl.NumberFormat("en-PK", {
  style: "currency",
  currency: "PKR",
  maximumFractionDigits: 0,
});

/**
 * "10% off" or "Rs 1,000 off" — how a scheme reads everywhere it is picked.
 *
 * A hook returning the formatter, because the wording is the viewer's language.
 */
export function useConcessionRate(): (concession: {
  kind: ConcessionKind;
  value: string;
}) => string {
  const m = useCatalog(feesSetupMessages).concessions;
  return (concession) =>
    concession.kind === "percent"
      ? fill(m.percentOff, { value: Number(concession.value) })
      : fill(m.amountOff, { amount: money.format(Number(concession.value)) });
}

/**
 * The named remission schemes a child can be put on.
 *
 * =============================================================================
 * THE RATE IS EDITED HERE, AND THE SCREEN SAYS WHO IT REACHES
 * =============================================================================
 *   A school runs a handful of schemes — staff child, merit, sibling — and puts
 *   families on them. Changing a scheme's rate changes it for every child on it from
 *   the next challan, which is the point (one edit, not four hundred) and also the
 *   thing the person editing must know before they press save. The "Children" column
 *   is there for the same reason: it is the number that edit will move.
 *
 *   Retiring is the normal way to stop offering a scheme. Deleting only works while
 *   nobody is on it, because deleting a scheme children are on would put those
 *   families back on full fees without anyone deciding that.
 */
export function ConcessionsPanel() {
  const { concessions: m, common: c } = useCatalog(feesSetupMessages);
  const concessionRate = useConcessionRate();
  const concessions = useConcessions({ size: 100 });
  const create = useCreateConcession();
  const update = useUpdateConcession();
  const remove = useDeleteConcession();

  const [editing, setEditing] = React.useState<FeeConcessionRead | "new" | null>(null);
  const [deleting, setDeleting] = React.useState<FeeConcessionRead | null>(null);

  return (
    <>
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">{m.intro}</p>
        <Button size="sm" onClick={() => setEditing("new")}>
          <Plus className="size-4" aria-hidden />
          {m.newScheme}
        </Button>
      </div>

      <Card className="overflow-hidden p-0">
        {concessions.isPending ? (
          <TableCardSkeleton columns={5} />
        ) : concessions.isError ? (
          <ErrorState error={concessions.error} onRetry={() => void concessions.refetch()} />
        ) : concessions.data.items.length === 0 ? (
          <EmptyState
            title={m.emptyTitle}
            description={m.emptyDescription}
            action={<Button onClick={() => setEditing("new")}>{m.addFirst}</Button>}
          />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{c.code}</TableHead>
                  <TableHead>{m.colScheme}</TableHead>
                  <TableHead>{m.colRate}</TableHead>
                  <TableHead className="text-end">{m.colChildren}</TableHead>
                  <TableHead className="w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {concessions.data.items.map((concession) => (
                  <TableRow
                    key={concession.id}
                    className={concession.is_active ? undefined : "opacity-60"}
                  >
                    <TableCell className="font-mono text-xs">{concession.code}</TableCell>
                    <TableCell>
                      {concession.name}
                      {concession.is_active ? null : (
                        <Badge variant="neutral" className="ms-2">
                          {c.retired}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-sm">{concessionRate(concession)}</TableCell>
                    <TableCell className="text-end tabular-nums">
                      {concession.student_count}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() =>
                            update.mutate({
                              id: concession.id,
                              body: { is_active: !concession.is_active },
                            })
                          }
                        >
                          {concession.is_active ? c.retire : c.restore}
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={fill(c.editNamed, { name: concession.name })}
                          onClick={() => setEditing(concession)}
                        >
                          <Pencil className="size-4" aria-hidden />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={fill(c.deleteNamed, { name: concession.name })}
                          onClick={() => setDeleting(concession)}
                        >
                          <Trash2 className="size-4" aria-hidden />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Card>

      <ConcessionDialog
        key={editing === null ? "closed" : editing === "new" ? "new" : editing.id}
        editing={editing}
        pending={create.isPending || update.isPending}
        onClose={() => setEditing(null)}
        onSubmit={async (values) => {
          if (editing === "new") {
            await create.mutateAsync(values);
          } else if (editing) {
            // `code` is fixed once created; the API has no field for it.
            const { name, kind, value } = values;
            await update.mutateAsync({ id: editing.id, body: { name, kind, value } });
          }
          setEditing(null);
        }}
      />

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(next) => !next && setDeleting(null)}
        title={fill(c.deleteTitle, { name: deleting?.name ?? "" })}
        description={m.deleteDescription}
        confirmLabel={c.delete}
        onConfirm={async () => {
          if (!deleting) return;
          await remove.mutateAsync(deleting.id);
          setDeleting(null);
        }}
      />
    </>
  );
}

interface ConcessionValues {
  code: string;
  name: string;
  kind: ConcessionKind;
  value: string;
}

function ConcessionDialog({
  editing,
  pending,
  onClose,
  onSubmit,
}: {
  editing: FeeConcessionRead | "new" | null;
  pending: boolean;
  onClose: () => void;
  onSubmit: (values: ConcessionValues) => Promise<void>;
}) {
  const { concessions: m, common: c } = useCatalog(feesSetupMessages);
  const existing = editing && editing !== "new" ? editing : null;
  const [code, setCode] = React.useState(existing?.code ?? "");
  const [name, setName] = React.useState(existing?.name ?? "");
  const [kind, setKind] = React.useState<ConcessionKind>(existing?.kind ?? "percent");
  const [value, setValue] = React.useState(existing ? String(Number(existing.value)) : "");

  const amount = Number(value);
  const valid =
    code.trim() !== "" &&
    name.trim() !== "" &&
    value.trim() !== "" &&
    amount > 0 &&
    (kind === "amount" || amount <= 100);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!valid) return;
    await onSubmit({
      code: code.trim().toUpperCase(),
      name: name.trim(),
      kind,
      value: amount.toFixed(2),
    });
  }

  return (
    <Dialog open={editing !== null} onOpenChange={(next) => !next && onClose()}>
      <DialogContent>
        <form onSubmit={submit} className="grid gap-4" noValidate>
          <DialogHeader>
            <DialogTitle>
              {existing ? fill(c.editNamed, { name: existing.name }) : m.newTitle}
            </DialogTitle>
            <DialogDescription>
              {existing
                ? fill(
                    existing.student_count === 1 ? m.editDescriptionOne : m.editDescriptionMany,
                    { count: existing.student_count ?? 0 },
                  )
                : m.newDescription}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 sm:grid-cols-[1fr_2fr]">
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">{c.code}</span>
              <Input
                value={code}
                onChange={(event) => setCode(event.target.value.toUpperCase())}
                placeholder="SIB2"
                disabled={existing !== null}
                required
              />
            </label>
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">{c.name}</span>
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={m.namePlaceholder}
                required
              />
            </label>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">{m.takesOff}</span>
              <NativeSelect
                value={kind}
                onChange={(event) => setKind(event.target.value as ConcessionKind)}
              >
                <option value="percent">{m.kindPercent}</option>
                <option value="amount">{m.kindAmount}</option>
              </NativeSelect>
            </label>
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">{kind === "percent" ? m.percent : m.amountPkr}</span>
              <Input
                value={value}
                onChange={(event) => setValue(event.target.value)}
                inputMode="decimal"
                placeholder={kind === "percent" ? "10" : "1000"}
                required
              />
              {kind === "percent" && amount > 100 ? (
                <span className="text-xs text-destructive">{m.percentTooHigh}</span>
              ) : (
                <span className="text-xs text-muted-foreground">{m.fixedHelp}</span>
              )}
            </label>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {c.cancel}
            </Button>
            <Button type="submit" disabled={pending || !valid}>
              {pending ? c.saving : existing ? m.save : m.addScheme}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
