"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, Check, Plus, Trash2 } from "lucide-react";

import { BillingAutomationPanel } from "@/components/fees/billing-automation-panel";
import { ConcessionsPanel } from "@/components/fees/concessions-panel";
import { LateFeePanel } from "@/components/fees/late-fee-panel";
import { SiblingDiscountsPanel } from "@/components/fees/sibling-discounts-panel";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState, ErrorState, TableCardSkeleton } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/misc";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useClassSummary } from "@/hooks/use-classes";
import {
  useActivateStructure,
  useCreateFeeHead,
  useCreateStationeryItem,
  useCreateStructure,
  useDeleteFeeHead,
  useDeleteStationeryItem,
  useFeeHeads,
  useFeeStructure,
  useFeeStructures,
  useRemoveStructureItem,
  useRemoveStructureStationery,
  useSetStructureItem,
  useSetStructureStationery,
  useStationeryItems,
  useUpdateStationeryItem,
} from "@/hooks/use-fees";
import { currentAcademicYear } from "@/lib/academic-year";
import { label, type FeeHeadRead, type StationeryItemRead } from "@/lib/api/types";
import { fill } from "@/lib/i18n/format";
import { feesSetupMessages } from "@/lib/i18n/modules/fees-setup";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { useLabels } from "@/lib/i18n/use-labels";

/** The units an article can be sold by, in picker order. Labels come from `useLabels`. */
const STATIONERY_UNITS = ["piece", "dozen", "pack", "set", "pair", "ream"] as const;

/**
 * What the campus charges.
 *
 * =============================================================================
 * THREE THINGS IN ORDER, NOT THREE UNRELATED TABS
 * =============================================================================
 *   A fee head is a name for a flat charge — "Tuition", "Transport". A stationery
 *   item is a thing the school SELLS, with a price per copy, per dozen, per set. A
 *   structure prices both for one class and one academic year. You cannot build the
 *   third without at least one of the first two, so they come first and the
 *   Structures tab says so when it finds neither.
 *
 *   The two catalogs are separate tabs rather than one list because they are priced
 *   differently and the difference is the whole point: a head has an amount that
 *   belongs to the structure, while an item has a unit price that belongs to the
 *   item and gets multiplied by a quantity. Merging them into one table would need a
 *   column that is blank on half the rows.
 *
 *   Pricing is edited in place on the structure rather than in a dialog: setting six
 *   amounts through six modals is the kind of flow people abandon halfway, and a
 *   half-priced structure that then gets activated bills the wrong money.
 */
export function FeeSetupView({ canIssue }: { canIssue: boolean }) {
  const m = useCatalog(feesSetupMessages).page;
  // Controlled so the Siblings tab can send someone to Concessions when no scheme
  // exists yet to pick.
  const [tab, setTab] = React.useState("heads");
  return (
    <div className="mx-auto w-full max-w-5xl">
      <Link
        href="/fees"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4 rtl:rotate-180" aria-hidden />
        {m.back}
      </Link>

      <PageHeader title={m.title} description={m.description} />

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="heads">{m.tabHeads}</TabsTrigger>
          <TabsTrigger value="stationery">{m.tabStationery}</TabsTrigger>
          <TabsTrigger value="structures">{m.tabStructures}</TabsTrigger>
          {/* What comes off a structure's price: the schemes, then the rule that
              proposes the sibling ones per family. */}
          <TabsTrigger value="concessions">{m.tabConcessions}</TabsTrigger>
          <TabsTrigger value="siblings">{m.tabSiblings}</TabsTrigger>
          {/* What is ADDED when a family pays late — billed under a head, so it
              comes after the heads it depends on. */}
          <TabsTrigger value="late-fees">{m.tabLateFees}</TabsTrigger>
          {/* LAST, because it is the only tab that depends on all three: automation
              bills the structures, which price the two catalogs. A school that opens
              it first has nothing for it to run. */}
          <TabsTrigger value="automation">{m.tabAutomation}</TabsTrigger>
        </TabsList>

        <TabsContent value="heads" className="mt-5">
          <FeeHeadsPanel />
        </TabsContent>
        <TabsContent value="stationery" className="mt-5">
          <StationeryPanel />
        </TabsContent>
        <TabsContent value="structures" className="mt-5">
          <StructuresPanel />
        </TabsContent>
        <TabsContent value="concessions" className="mt-5">
          <ConcessionsPanel />
        </TabsContent>
        <TabsContent value="siblings" className="mt-5">
          <SiblingDiscountsPanel
            academicYear={currentAcademicYear()}
            onOpenConcessions={() => setTab("concessions")}
          />
        </TabsContent>
        <TabsContent value="late-fees" className="mt-5">
          <LateFeePanel academicYear={currentAcademicYear()} canIssue={canIssue} />
        </TabsContent>
        <TabsContent value="automation" className="mt-5">
          <BillingAutomationPanel academicYear={currentAcademicYear()} canIssue={canIssue} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Fee heads
// ---------------------------------------------------------------------------

function FeeHeadsPanel() {
  const { heads: m, common: c } = useCatalog(feesSetupMessages);
  const L = useLabels();
  const heads = useFeeHeads({ size: 100 });
  const create = useCreateFeeHead();
  const remove = useDeleteFeeHead();

  const [adding, setAdding] = React.useState(false);
  const [deleting, setDeleting] = React.useState<FeeHeadRead | null>(null);
  const [code, setCode] = React.useState("");
  const [name, setName] = React.useState("");
  const [recurrence, setRecurrence] = React.useState("monthly");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!code.trim() || !name.trim()) return;
    await create.mutateAsync({
      code: code.trim().toUpperCase(),
      name: name.trim(),
      recurrence: recurrence as FeeHeadRead["recurrence"],
    });
    setAdding(false);
    setCode("");
    setName("");
  }

  return (
    <>
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">{m.intro}</p>
        <Button size="sm" onClick={() => setAdding(true)}>
          <Plus className="size-4" aria-hidden />
          {m.newHead}
        </Button>
      </div>

      <Card className="overflow-hidden p-0">
        {heads.isPending ? (
          <TableCardSkeleton columns={4} />
        ) : heads.isError ? (
          <ErrorState error={heads.error} onRetry={() => void heads.refetch()} />
        ) : heads.data.items.length === 0 ? (
          <EmptyState
            title={m.emptyTitle}
            description={m.emptyDescription}
            action={<Button onClick={() => setAdding(true)}>{m.addFirst}</Button>}
          />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{c.code}</TableHead>
                  <TableHead>{c.name}</TableHead>
                  <TableHead>{m.colCharged}</TableHead>
                  <TableHead className="w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {heads.data.items.map((head) => (
                  <TableRow key={head.id}>
                    <TableCell className="font-mono text-xs">{head.code}</TableCell>
                    <TableCell>
                      {head.name}
                      {head.is_refundable ? (
                        <Badge variant="neutral" className="ms-2">
                          {m.refundable}
                        </Badge>
                      ) : null}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {label(L.feeRecurrence, head.recurrence)}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={fill(c.deleteNamed, { name: head.name })}
                        onClick={() => setDeleting(head)}
                      >
                        <Trash2 className="size-4" aria-hidden />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Card>

      <Dialog open={adding} onOpenChange={setAdding}>
        <DialogContent>
          <form onSubmit={submit} className="grid gap-4" noValidate>
            <DialogHeader>
              <DialogTitle>{m.dialogTitle}</DialogTitle>
              <DialogDescription>{m.dialogDescription}</DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 sm:grid-cols-[1fr_2fr]">
              <label className="grid gap-1.5 text-sm">
                <span className="font-medium">{c.code}</span>
                <Input
                  value={code}
                  onChange={(event) => setCode(event.target.value.toUpperCase())}
                  placeholder="TUITION"
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
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">{m.charged}</span>
              <NativeSelect
                value={recurrence}
                onChange={(event) => setRecurrence(event.target.value)}
              >
                {Object.entries(L.feeRecurrence).map(([value, text]) => (
                  <option key={value} value={value}>
                    {text}
                  </option>
                ))}
              </NativeSelect>
              <span className="text-xs text-muted-foreground">{m.chargedHelp}</span>
            </label>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setAdding(false)}>
                {c.cancel}
              </Button>
              <Button type="submit" disabled={create.isPending || !code.trim() || !name.trim()}>
                {create.isPending ? c.adding : m.addHead}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

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

// ---------------------------------------------------------------------------
// Stationery catalog
// ---------------------------------------------------------------------------

/**
 * What the campus sells, and what one unit of it costs.
 *
 * =============================================================================
 * THE PRICE IS EDITED IN PLACE, AND THE TABLE SAYS WHY THAT IS SAFE
 * =============================================================================
 *   Repricing is the operation this screen exists for — a copy goes from 60 to 70
 *   between terms and someone has to change it. The reason it needs no confirmation
 *   dialog is that it is not retroactive: every structure line and every challan
 *   line snapshotted the price it was added at. That is stated on the screen rather
 *   than left in the API docs, because the person changing the number is the person
 *   who needs to know it.
 */
function StationeryPanel() {
  const { stationery: m, common: c } = useCatalog(feesSetupMessages);
  const L = useLabels();
  const items = useStationeryItems({ size: 100 });
  const create = useCreateStationeryItem();
  const update = useUpdateStationeryItem();
  const remove = useDeleteStationeryItem();

  const [adding, setAdding] = React.useState(false);
  const [deleting, setDeleting] = React.useState<StationeryItemRead | null>(null);
  const [code, setCode] = React.useState("");
  const [name, setName] = React.useState("");
  const [category, setCategory] = React.useState("notebook");
  const [unit, setUnit] = React.useState("piece");
  const [price, setPrice] = React.useState("");

  const money = new Intl.NumberFormat("en-PK", { style: "currency", currency: "PKR" });

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!code.trim() || !name.trim() || !price.trim()) return;
    await create.mutateAsync({
      code: code.trim().toUpperCase(),
      name: name.trim(),
      category: category as StationeryItemRead["category"],
      unit: unit as StationeryItemRead["unit"],
      unit_price: price.trim(),
    });
    setAdding(false);
    setCode("");
    setName("");
    setPrice("");
  }

  return (
    <>
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">{m.intro}</p>
        <Button size="sm" onClick={() => setAdding(true)}>
          <Plus className="size-4" aria-hidden />
          {m.newItem}
        </Button>
      </div>

      <Card className="overflow-hidden p-0">
        {items.isPending ? (
          <TableCardSkeleton columns={5} />
        ) : items.isError ? (
          <ErrorState error={items.error} onRetry={() => void items.refetch()} />
        ) : items.data.items.length === 0 ? (
          <EmptyState
            title={m.emptyTitle}
            description={m.emptyDescription}
            action={<Button onClick={() => setAdding(true)}>{m.addFirst}</Button>}
          />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{c.code}</TableHead>
                  <TableHead>{m.colItem}</TableHead>
                  <TableHead>{m.colGroup}</TableHead>
                  <TableHead className="text-end">{m.colPrice}</TableHead>
                  <TableHead className="w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.data.items.map((item) => (
                  <TableRow key={item.id} className={item.is_active ? undefined : "opacity-60"}>
                    <TableCell className="font-mono text-xs">{item.code}</TableCell>
                    <TableCell>
                      {item.name}
                      {item.is_active ? null : (
                        <Badge variant="neutral" className="ms-2">
                          {c.retired}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {label(L.stationeryCategory, item.category)}
                    </TableCell>
                    <TableCell className="text-end tabular-nums">
                      {money.format(Number(item.unit_price))}
                      <span className="ms-1 text-xs text-muted-foreground">
                        {fill(m.perUnit, { unit: L.unit(item.unit, 1) })}
                      </span>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-1">
                        {/* Retiring an article is the normal path and always works;
                            deleting only works while nothing has ever charged it. */}
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() =>
                            update.mutate({
                              id: item.id,
                              body: { is_active: !item.is_active },
                            })
                          }
                        >
                          {item.is_active ? c.retire : c.restore}
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={fill(c.deleteNamed, { name: item.name })}
                          onClick={() => setDeleting(item)}
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

      <p className="mt-3 text-xs text-muted-foreground">{m.repriceNote}</p>

      <Dialog open={adding} onOpenChange={setAdding}>
        <DialogContent>
          <form onSubmit={submit} className="grid gap-4" noValidate>
            <DialogHeader>
              <DialogTitle>{m.dialogTitle}</DialogTitle>
              <DialogDescription>{m.dialogDescription}</DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 sm:grid-cols-[1fr_2fr]">
              <label className="grid gap-1.5 text-sm">
                <span className="font-medium">{c.code}</span>
                <Input
                  value={code}
                  onChange={(event) => setCode(event.target.value.toUpperCase())}
                  placeholder="COPY-100"
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
            <div className="grid gap-4 sm:grid-cols-3">
              <label className="grid gap-1.5 text-sm">
                <span className="font-medium">{m.group}</span>
                <NativeSelect
                  value={category}
                  onChange={(event) => setCategory(event.target.value)}
                >
                  {Object.entries(L.stationeryCategory).map(([value, text]) => (
                    <option key={value} value={value}>
                      {text}
                    </option>
                  ))}
                </NativeSelect>
              </label>
              <label className="grid gap-1.5 text-sm">
                <span className="font-medium">{m.soldBy}</span>
                <NativeSelect value={unit} onChange={(event) => setUnit(event.target.value)}>
                  {STATIONERY_UNITS.map((value) => (
                    <option key={value} value={value}>
                      {L.unit(value, 1)}
                    </option>
                  ))}
                </NativeSelect>
              </label>
              <label className="grid gap-1.5 text-sm">
                <span className="font-medium">{m.pricePerUnit}</span>
                <Input
                  value={price}
                  onChange={(event) => setPrice(event.target.value)}
                  inputMode="decimal"
                  placeholder="60"
                  required
                />
              </label>
            </div>
            <p className="text-xs text-muted-foreground">{m.unitHelp}</p>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setAdding(false)}>
                {c.cancel}
              </Button>
              <Button
                type="submit"
                disabled={create.isPending || !code.trim() || !name.trim() || !price.trim()}
              >
                {create.isPending ? c.adding : m.addItem}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

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

// ---------------------------------------------------------------------------
// Structures
// ---------------------------------------------------------------------------

function StructuresPanel() {
  const { structures: m, common: c } = useCatalog(feesSetupMessages);
  const L = useLabels();
  const structures = useFeeStructures({ size: 100 });
  const classes = useClassSummary();
  const heads = useFeeHeads({ size: 100 });
  const create = useCreateStructure();

  const [selected, setSelected] = React.useState<string | null>(null);
  const [adding, setAdding] = React.useState(false);
  const [className, setClassName] = React.useState("");
  const [year, setYear] = React.useState("");
  const [name, setName] = React.useState("");

  const noHeads = heads.isSuccess && heads.data.items.length === 0;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!className || !year.trim() || !name.trim()) return;
    const created = await create.mutateAsync({
      class_id: className,
      academic_year: year.trim(),
      name: name.trim(),
    });
    setAdding(false);
    setSelected(created.id);
    setName("");
  }

  return (
    <>
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">{m.intro}</p>
        <Button size="sm" onClick={() => setAdding(true)} disabled={noHeads}>
          <Plus className="size-4" aria-hidden />
          {m.newStructure}
        </Button>
      </div>

      {noHeads ? (
        <p className="mb-3 rounded-md bg-warning/15 px-4 py-3 text-sm">{m.noHeads}</p>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_1.4fr]">
        <Card className="overflow-hidden p-0">
          {structures.isPending ? (
            <TableCardSkeleton columns={2} />
          ) : structures.isError ? (
            <ErrorState error={structures.error} onRetry={() => void structures.refetch()} />
          ) : structures.data.items.length === 0 ? (
            <EmptyState title={m.emptyTitle} description={m.emptyDescription} />
          ) : (
            <ul className="divide-y divide-border">
              {structures.data.items.map((structure) => (
                <li key={structure.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(structure.id)}
                    aria-current={structure.id === selected ? "true" : undefined}
                    className="flex w-full items-center justify-between gap-3 px-4 py-3 text-start transition-colors hover:bg-accent/50 aria-[current]:bg-accent"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium">
                        {structure.name}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {structure.academic_year}
                      </span>
                    </span>
                    <Badge variant={structure.status === "active" ? "success" : "neutral"}>
                      {label(L.structureStatus, structure.status)}
                    </Badge>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <StructureDetail structureId={selected} />
      </div>

      <Dialog open={adding} onOpenChange={setAdding}>
        <DialogContent>
          <form onSubmit={submit} className="grid gap-4" noValidate>
            <DialogHeader>
              <DialogTitle>{m.dialogTitle}</DialogTitle>
              <DialogDescription>{m.dialogDescription}</DialogDescription>
            </DialogHeader>
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">{m.class}</span>
              <NativeSelect
                value={className}
                onChange={(event) => setClassName(event.target.value)}
                required
              >
                <option value="">{m.chooseClass}</option>
                {(classes.data ?? []).map((cls) => (
                  <option key={cls.id} value={cls.id}>
                    {cls.name}
                  </option>
                ))}
              </NativeSelect>
            </label>
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">{m.academicYear}</span>
              <Input
                value={year}
                onChange={(event) => setYear(event.target.value)}
                placeholder="2026-2027"
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
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setAdding(false)}>
                {c.cancel}
              </Button>
              <Button
                type="submit"
                disabled={create.isPending || !className || !year.trim() || !name.trim()}
              >
                {create.isPending ? m.creating : m.create}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
/**
 * The price list for one structure, edited in place.
 *
 * =============================================================================
 * ONE TABLE, TWO KINDS OF LINE
 * =============================================================================
 *   Fees and stationery are shown in one list because that is how they reach the
 *   parent — one challan, one total. Splitting them into two tables here would make
 *   the screen disagree with the document it produces, and would hide the number
 *   that actually matters, which is what the class pays altogether.
 *
 *   The two subtotals below the lines exist because "what does this class pay us
 *   every month" and "what did we sell them" are different questions: an annual book
 *   set folded into one structure would otherwise read as the monthly charge having
 *   tripled.
 */
function StructureDetail({ structureId }: { structureId: string | null }) {
  const { structures: m, common: c } = useCatalog(feesSetupMessages);
  const L = useLabels();
  const structure = useFeeStructure(structureId);
  const heads = useFeeHeads({ size: 100 });
  const stationery = useStationeryItems({ size: 100, active_only: true });
  const setItem = useSetStructureItem();
  const removeItem = useRemoveStructureItem();
  const setStationery = useSetStructureStationery();
  const removeStationery = useRemoveStructureStationery();
  const activate = useActivateStructure();

  const [headId, setHeadId] = React.useState("");
  const [amount, setAmount] = React.useState("");
  const [itemId, setItemId] = React.useState("");
  const [quantity, setQuantity] = React.useState("1");

  if (!structureId) {
    return (
      <Card className="grid place-items-center p-10 text-center text-sm text-muted-foreground">
        {m.choosePrompt}
      </Card>
    );
  }

  if (structure.isPending) return <Card className="h-64 animate-pulse" />;
  if (structure.isError) {
    return (
      <Card className="p-0">
        <ErrorState error={structure.error} onRetry={() => void structure.refetch()} />
      </Card>
    );
  }

  const data = structure.data;
  const pricedHeads = new Set(data.items.map((item) => item.head_id).filter(Boolean));
  const pricedItems = new Set(data.items.map((item) => item.stationery_item_id).filter(Boolean));
  const availableHeads = (heads.data?.items ?? []).filter((head) => !pricedHeads.has(head.id));
  const availableItems = (stationery.data?.items ?? []).filter((item) => !pricedItems.has(item.id));

  const money = new Intl.NumberFormat("en-PK", {
    style: "currency",
    currency: "PKR",
    maximumFractionDigits: 0,
  });

  async function addLine(event: React.FormEvent) {
    event.preventDefault();
    if (!headId || !amount.trim()) return;
    await setItem.mutateAsync({
      id: data.id,
      body: { head_id: headId, amount: Number(amount) },
    });
    setHeadId("");
    setAmount("");
  }

  async function addStationeryLine(event: React.FormEvent) {
    event.preventDefault();
    if (!itemId || !quantity.trim()) return;
    // The price is deliberately not sent — the server copies it from the catalog, so
    // a structure can never charge a price the catalog has no record of.
    await setStationery.mutateAsync({
      id: data.id,
      body: { stationery_item_id: itemId, quantity: quantity.trim() },
    });
    setItemId("");
    setQuantity("1");
  }

  return (
    <Card className="overflow-hidden p-0">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-5 py-3">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-medium">{data.name}</h2>
          <p className="text-xs text-muted-foreground">{data.academic_year}</p>
        </div>
        {data.status === "draft" ? (
          <Button
            size="sm"
            disabled={activate.isPending || data.items.length === 0}
            onClick={() => activate.mutate(data.id)}
          >
            <Check className="size-4" aria-hidden />
            {m.activate}
          </Button>
        ) : (
          <Badge variant={data.status === "active" ? "success" : "neutral"}>
            {label(L.structureStatus, data.status)}
          </Badge>
        )}
      </div>

      {data.items.length === 0 ? (
        <p className="px-5 py-8 text-center text-sm text-muted-foreground">
          {m.nothingPriced}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{m.colLine}</TableHead>
                <TableHead className="text-end">{c.qty}</TableHead>
                <TableHead className="text-end">{c.amount}</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((item) => {
                const isStationery = item.line_type === "stationery";
                const qty = Number(item.quantity);
                return (
                  <TableRow key={item.id}>
                    <TableCell>
                      {item.name}
                      {isStationery ? (
                        <Badge variant="neutral" className="ms-2">
                          {m.stationeryBadge}
                        </Badge>
                      ) : null}
                    </TableCell>
                    {/* A fee line has no meaningful quantity, so it shows a dash
                        rather than a "1" the reader would try to interpret. */}
                    <TableCell className="text-end text-sm tabular-nums text-muted-foreground">
                      {isStationery
                        ? fill(c.working, {
                            qty,
                            unit: L.unit(item.unit, qty),
                            price: money.format(Number(item.unit_price)),
                          })
                        : "—"}
                    </TableCell>
                    <TableCell className="text-end tabular-nums">
                      {money.format(Number(item.amount))}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={fill(c.removeNamed, { name: item.name })}
                        onClick={() =>
                          isStationery
                            ? removeStationery.mutate({
                                id: data.id,
                                stationeryItemId: item.stationery_item_id!,
                              })
                            : removeItem.mutate({ id: data.id, headId: item.head_id! })
                        }
                      >
                        <Trash2 className="size-4" aria-hidden />
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}

              {/* Shown only when the structure actually mixes both kinds — on a
                  fees-only structure the split would be the total repeated twice. */}
              {Number(data.stationery_total) > 0 && Number(data.fee_total) > 0 ? (
                <>
                  <TableRow>
                    <TableCell colSpan={2} className="text-sm text-muted-foreground">
                      {m.fees}
                    </TableCell>
                    <TableCell className="text-end text-sm tabular-nums text-muted-foreground">
                      {money.format(Number(data.fee_total))}
                    </TableCell>
                    <TableCell />
                  </TableRow>
                  <TableRow>
                    <TableCell colSpan={2} className="text-sm text-muted-foreground">
                      {m.stationery}
                    </TableCell>
                    <TableCell className="text-end text-sm tabular-nums text-muted-foreground">
                      {money.format(Number(data.stationery_total))}
                    </TableCell>
                    <TableCell />
                  </TableRow>
                </>
              ) : null}

              <TableRow>
                <TableCell colSpan={2} className="font-medium">
                  {c.total}
                </TableCell>
                <TableCell className="text-end font-semibold tabular-nums">
                  {money.format(Number(data.total))}
                </TableCell>
                <TableCell />
              </TableRow>
            </TableBody>
          </Table>
        </div>
      )}

      {availableHeads.length > 0 ? (
        <form
          onSubmit={addLine}
          className="flex flex-wrap items-end gap-2 border-t border-border p-4"
        >
          <label className="grid flex-1 gap-1.5 text-sm">
            <span className="text-xs font-medium">{m.feeHead}</span>
            <NativeSelect value={headId} onChange={(event) => setHeadId(event.target.value)}>
              <option value="">{c.choose}</option>
              {availableHeads.map((head) => (
                <option key={head.id} value={head.id}>
                  {head.name}
                </option>
              ))}
            </NativeSelect>
          </label>
          <label className="grid w-32 gap-1.5 text-sm">
            <span className="text-xs font-medium">{c.amount}</span>
            <Input
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              inputMode="decimal"
              placeholder="0"
            />
          </label>
          <Button type="submit" variant="outline" disabled={setItem.isPending || !headId}>
            {m.addLine}
          </Button>
        </form>
      ) : null}

      {availableItems.length > 0 ? (
        <form
          onSubmit={addStationeryLine}
          className="flex flex-wrap items-end gap-2 border-t border-border bg-muted/30 p-4"
        >
          <label className="grid flex-1 gap-1.5 text-sm">
            <span className="text-xs font-medium">{m.stationery}</span>
            <NativeSelect value={itemId} onChange={(event) => setItemId(event.target.value)}>
              <option value="">{c.choose}</option>
              {availableItems.map((item) => (
                <option key={item.id} value={item.id}>
                  {fill(c.option, {
                    name: item.name,
                    price: money.format(Number(item.unit_price)),
                    unit: L.unit(item.unit, 1),
                  })}
                </option>
              ))}
            </NativeSelect>
          </label>
          <label className="grid w-24 gap-1.5 text-sm">
            <span className="text-xs font-medium">{c.qty}</span>
            <Input
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
              inputMode="decimal"
              placeholder="1"
            />
          </label>
          <Button
            type="submit"
            variant="outline"
            disabled={setStationery.isPending || !itemId || !quantity.trim()}
          >
            {m.addItem}
          </Button>
          <p className="w-full text-xs text-muted-foreground">{m.stationeryHelp}</p>
        </form>
      ) : null}
    </Card>
  );
}
