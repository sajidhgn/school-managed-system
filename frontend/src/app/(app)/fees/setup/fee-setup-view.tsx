"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, Check, Plus, Trash2 } from "lucide-react";

import { BillingAutomationPanel } from "@/components/fees/billing-automation-panel";
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
import {
  FEE_RECURRENCE_LABELS,
  FEE_STRUCTURE_STATUS_LABELS,
  STATIONERY_CATEGORY_LABELS,
  STATIONERY_UNIT_LABELS,
  label,
  unitLabel,
  type FeeHeadRead,
  type StationeryItemRead,
} from "@/lib/api/types";

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
  return (
    <div className="mx-auto w-full max-w-5xl">
      <Link
        href="/fees"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        Fees
      </Link>

      <PageHeader
        title="Charges &amp; structures"
        description="Define what this campus charges and sells, then price it per class and year."
      />

      <Tabs defaultValue="heads">
        <TabsList>
          <TabsTrigger value="heads">Fee heads</TabsTrigger>
          <TabsTrigger value="stationery">Stationery</TabsTrigger>
          <TabsTrigger value="structures">Structures</TabsTrigger>
          {/* LAST, because it is the only tab that depends on all three: automation
              bills the structures, which price the two catalogs. A school that opens
              it first has nothing for it to run. */}
          <TabsTrigger value="automation">Automation</TabsTrigger>
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
        <p className="text-sm text-muted-foreground">
          The charges this campus can bill. A head is only a name and a rhythm — the
          amount belongs to a structure.
        </p>
        <Button size="sm" onClick={() => setAdding(true)}>
          <Plus className="size-4" aria-hidden />
          New head
        </Button>
      </div>

      <Card className="overflow-hidden p-0">
        {heads.isPending ? (
          <TableCardSkeleton columns={4} />
        ) : heads.isError ? (
          <ErrorState error={heads.error} onRetry={() => void heads.refetch()} />
        ) : heads.data.items.length === 0 ? (
          <EmptyState
            title="No fee heads yet"
            description="Add Tuition, Transport, Examination — whatever this campus charges for."
            action={<Button onClick={() => setAdding(true)}>Add the first head</Button>}
          />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Code</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Charged</TableHead>
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
                          Refundable
                        </Badge>
                      ) : null}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {label(FEE_RECURRENCE_LABELS, head.recurrence)}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Delete ${head.name}`}
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
              <DialogTitle>New fee head</DialogTitle>
              <DialogDescription>
                The code appears on challans and cannot be reused at this campus.
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 sm:grid-cols-[1fr_2fr]">
              <label className="grid gap-1.5 text-sm">
                <span className="font-medium">Code</span>
                <Input
                  value={code}
                  onChange={(event) => setCode(event.target.value.toUpperCase())}
                  placeholder="TUITION"
                  required
                />
              </label>
              <label className="grid gap-1.5 text-sm">
                <span className="font-medium">Name</span>
                <Input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Tuition fee"
                  required
                />
              </label>
            </div>
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">Charged</span>
              <NativeSelect
                value={recurrence}
                onChange={(event) => setRecurrence(event.target.value)}
              >
                {Object.entries(FEE_RECURRENCE_LABELS).map(([value, text]) => (
                  <option key={value} value={value}>
                    {text}
                  </option>
                ))}
              </NativeSelect>
              <span className="text-xs text-muted-foreground">
                Descriptive for now — it tells whoever generates challans what rhythm this
                charge belongs to. It does not schedule anything on its own.
              </span>
            </label>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setAdding(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={create.isPending || !code.trim() || !name.trim()}>
                {create.isPending ? "Adding…" : "Add head"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(next) => !next && setDeleting(null)}
        title={`Delete ${deleting?.name ?? ""}?`}
        description="Only possible while no structure prices it and no challan has ever billed it. Once it has been billed the head is part of the record and stays."
        confirmLabel="Delete"
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
        <p className="text-sm text-muted-foreground">
          Copies, pencils, books, uniform — anything sold by the piece. The price here is
          per unit; how many a student gets is decided on the structure or the challan.
        </p>
        <Button size="sm" onClick={() => setAdding(true)}>
          <Plus className="size-4" aria-hidden />
          New item
        </Button>
      </div>

      <Card className="overflow-hidden p-0">
        {items.isPending ? (
          <TableCardSkeleton columns={5} />
        ) : items.isError ? (
          <ErrorState error={items.error} onRetry={() => void items.refetch()} />
        ) : items.data.items.length === 0 ? (
          <EmptyState
            title="Nothing in the catalog yet"
            description="Add the copies, pencils and books this campus charges for."
            action={<Button onClick={() => setAdding(true)}>Add the first item</Button>}
          />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Code</TableHead>
                  <TableHead>Item</TableHead>
                  <TableHead>Group</TableHead>
                  <TableHead className="text-end">Price per unit</TableHead>
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
                          Retired
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {label(STATIONERY_CATEGORY_LABELS, item.category)}
                    </TableCell>
                    <TableCell className="text-end tabular-nums">
                      {money.format(Number(item.unit_price))}
                      <span className="ms-1 text-xs text-muted-foreground">
                        / {label(STATIONERY_UNIT_LABELS, item.unit)}
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
                          {item.is_active ? "Retire" : "Restore"}
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={`Delete ${item.name}`}
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

      <p className="mt-3 text-xs text-muted-foreground">
        Changing a price here changes what the next challan charges. Challans already
        generated keep the price they were generated at — a bill in a parent&rsquo;s hands is
        never restated.
      </p>

      <Dialog open={adding} onOpenChange={setAdding}>
        <DialogContent>
          <form onSubmit={submit} className="grid gap-4" noValidate>
            <DialogHeader>
              <DialogTitle>New stationery item</DialogTitle>
              <DialogDescription>
                The name is what a parent reads on the challan, so make it specific —
                &ldquo;Copy (Register, 100 pages)&rdquo; rather than &ldquo;Copy&rdquo;.
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 sm:grid-cols-[1fr_2fr]">
              <label className="grid gap-1.5 text-sm">
                <span className="font-medium">Code</span>
                <Input
                  value={code}
                  onChange={(event) => setCode(event.target.value.toUpperCase())}
                  placeholder="COPY-100"
                  required
                />
              </label>
              <label className="grid gap-1.5 text-sm">
                <span className="font-medium">Name</span>
                <Input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Copy (Register, 100 pages)"
                  required
                />
              </label>
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              <label className="grid gap-1.5 text-sm">
                <span className="font-medium">Group</span>
                <NativeSelect
                  value={category}
                  onChange={(event) => setCategory(event.target.value)}
                >
                  {Object.entries(STATIONERY_CATEGORY_LABELS).map(([value, text]) => (
                    <option key={value} value={value}>
                      {text}
                    </option>
                  ))}
                </NativeSelect>
              </label>
              <label className="grid gap-1.5 text-sm">
                <span className="font-medium">Sold by the</span>
                <NativeSelect value={unit} onChange={(event) => setUnit(event.target.value)}>
                  {Object.entries(STATIONERY_UNIT_LABELS).map(([value, text]) => (
                    <option key={value} value={value}>
                      {text}
                    </option>
                  ))}
                </NativeSelect>
              </label>
              <label className="grid gap-1.5 text-sm">
                <span className="font-medium">Price per unit</span>
                <Input
                  value={price}
                  onChange={(event) => setPrice(event.target.value)}
                  inputMode="decimal"
                  placeholder="60"
                  required
                />
              </label>
            </div>
            <p className="text-xs text-muted-foreground">
              The unit matters on the printed challan: three pencils and three dozen
              pencils differ by twelve, and the parent finds out at the counter.
            </p>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setAdding(false)}>
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={create.isPending || !code.trim() || !name.trim() || !price.trim()}
              >
                {create.isPending ? "Adding…" : "Add item"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(next) => !next && setDeleting(null)}
        title={`Delete ${deleting?.name ?? ""}?`}
        description="Only possible while no structure and no challan has ever charged it. Once it has been sold the item is part of the record — retire it instead."
        confirmLabel="Delete"
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
        <p className="text-sm text-muted-foreground">
          One structure per class per academic year. It has to be activated before it can
          bill anybody.
        </p>
        <Button size="sm" onClick={() => setAdding(true)} disabled={noHeads}>
          <Plus className="size-4" aria-hidden />
          New structure
        </Button>
      </div>

      {noHeads ? (
        <p className="mb-3 rounded-md bg-warning/15 px-4 py-3 text-sm">
          Add at least one fee head first — a structure is a price list, and there is
          nothing yet to price.
        </p>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_1.4fr]">
        <Card className="overflow-hidden p-0">
          {structures.isPending ? (
            <TableCardSkeleton columns={2} />
          ) : structures.isError ? (
            <ErrorState error={structures.error} onRetry={() => void structures.refetch()} />
          ) : structures.data.items.length === 0 ? (
            <EmptyState
              title="No structures yet"
              description="Create one per class, per year."
            />
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
                      {label(FEE_STRUCTURE_STATUS_LABELS, structure.status)}
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
              <DialogTitle>New fee structure</DialogTitle>
              <DialogDescription>
                Prices one class for one academic year. You add the amounts next.
              </DialogDescription>
            </DialogHeader>
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">Class</span>
              <NativeSelect
                value={className}
                onChange={(event) => setClassName(event.target.value)}
                required
              >
                <option value="">Choose a class…</option>
                {(classes.data ?? []).map((cls) => (
                  <option key={cls.id} value={cls.id}>
                    {cls.name}
                  </option>
                ))}
              </NativeSelect>
            </label>
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">Academic year</span>
              <Input
                value={year}
                onChange={(event) => setYear(event.target.value)}
                placeholder="2026-2027"
                required
              />
            </label>
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">Name</span>
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Grade 5 — 2026-2027"
                required
              />
            </label>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setAdding(false)}>
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={create.isPending || !className || !year.trim() || !name.trim()}
              >
                {create.isPending ? "Creating…" : "Create"}
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
        Choose a structure to price it.
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
            Activate
          </Button>
        ) : (
          <Badge variant={data.status === "active" ? "success" : "neutral"}>
            {label(FEE_STRUCTURE_STATUS_LABELS, data.status)}
          </Badge>
        )}
      </div>

      {data.items.length === 0 ? (
        <p className="px-5 py-8 text-center text-sm text-muted-foreground">
          Nothing priced yet. A structure with no lines cannot be activated.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Line</TableHead>
                <TableHead className="text-end">Qty</TableHead>
                <TableHead className="text-end">Amount</TableHead>
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
                          Stationery
                        </Badge>
                      ) : null}
                    </TableCell>
                    {/* A fee line has no meaningful quantity, so it shows a dash
                        rather than a "1" the reader would try to interpret. */}
                    <TableCell className="text-end text-sm tabular-nums text-muted-foreground">
                      {isStationery
                        ? `${qty} ${unitLabel(item.unit, qty)} × ${money.format(
                            Number(item.unit_price),
                          )}`
                        : "—"}
                    </TableCell>
                    <TableCell className="text-end tabular-nums">
                      {money.format(Number(item.amount))}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Remove ${item.name}`}
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
                      Fees
                    </TableCell>
                    <TableCell className="text-end text-sm tabular-nums text-muted-foreground">
                      {money.format(Number(data.fee_total))}
                    </TableCell>
                    <TableCell />
                  </TableRow>
                  <TableRow>
                    <TableCell colSpan={2} className="text-sm text-muted-foreground">
                      Stationery
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
                  Total
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
            <span className="text-xs font-medium">Fee head</span>
            <NativeSelect value={headId} onChange={(event) => setHeadId(event.target.value)}>
              <option value="">Choose…</option>
              {availableHeads.map((head) => (
                <option key={head.id} value={head.id}>
                  {head.name}
                </option>
              ))}
            </NativeSelect>
          </label>
          <label className="grid w-32 gap-1.5 text-sm">
            <span className="text-xs font-medium">Amount</span>
            <Input
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              inputMode="decimal"
              placeholder="0"
            />
          </label>
          <Button type="submit" variant="outline" disabled={setItem.isPending || !headId}>
            Add line
          </Button>
        </form>
      ) : null}

      {availableItems.length > 0 ? (
        <form
          onSubmit={addStationeryLine}
          className="flex flex-wrap items-end gap-2 border-t border-border bg-muted/30 p-4"
        >
          <label className="grid flex-1 gap-1.5 text-sm">
            <span className="text-xs font-medium">Stationery</span>
            <NativeSelect value={itemId} onChange={(event) => setItemId(event.target.value)}>
              <option value="">Choose…</option>
              {availableItems.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} — {money.format(Number(item.unit_price))} /{" "}
                  {label(STATIONERY_UNIT_LABELS, item.unit)}
                </option>
              ))}
            </NativeSelect>
          </label>
          <label className="grid w-24 gap-1.5 text-sm">
            <span className="text-xs font-medium">Qty</span>
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
            Add item
          </Button>
          <p className="w-full text-xs text-muted-foreground">
            Every student in this class is billed this quantity. One student taking extra
            is charged on their own challan while it is still a draft.
          </p>
        </form>
      ) : null}
    </Card>
  );
}
