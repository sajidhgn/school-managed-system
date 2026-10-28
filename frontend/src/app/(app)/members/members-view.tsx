"use client";

import { MoreHorizontal, Search, UserPlus, X } from "lucide-react";
import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { Can } from "@/components/auth/can";
import type { Branch } from "./add-member-form";
import { EditMemberDialog } from "./edit-member-dialog";
import { InvitationsSection } from "./invitations-section";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toast } from "@/components/ui/use-toast";
import { useTranslations } from "@/components/providers/i18n-provider";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { ApiError } from "@/lib/api/errors";
import { members as membersApi } from "@/lib/api/resources";
import {
  MEMBER_STATUS_LABELS,
  PERMISSIONS,
  label,
  type InvitationRead,
  type MemberRead,
  type Page,
  type PageMeta,
  type RoleRead,
  type SchoolRead,
  type UsageItem,
} from "@/lib/api/types";

/**
 * The staff table across every branch: add, change role, suspend, remove.
 *
 * =============================================================================
 * EVERY ACTION GOES TO THE MEMBER'S OWN BRANCH
 * =============================================================================
 *   The list spans branches, so there is no "current school" to address a change
 *   to. A row's edits, role choices and removal all use `member.school_id`, and its
 *   role menu offers only that branch's roles. Org-level rows (the principal) have
 *   no branch and no actions here — ownership moves through Settings.
 *
 * =============================================================================
 * THE SERVER REFUSES THINGS THIS TABLE ALSO REFUSES — BOTH ARE NEEDED
 * =============================================================================
 *   You cannot act on your OWN membership here, and the last principal cannot be
 *   removed. Both are enforced server-side (409 SELF_MODIFICATION, 409 LAST_OWNER),
 *   and both are also disabled in the UI.
 *
 *   The duplication is deliberate. The server check is the guarantee; the UI check
 *   is the explanation. An administrator who clicks "Remove" on themselves and gets
 *   a red toast has learned the rule the hard way — a disabled row with a reason
 *   teaches it before the mistake.
 */
/** The "no filter" value: Radix `Select` reserves the empty string. */
const ALL = "__all__";

export interface MemberFilters {
  /** One branch, or null for every branch. */
  school: string | null;
  /** Name or email contains this; empty for no search. */
  q: string;
  /** A role CODE, so "teacher" spans every branch's Teacher role. */
  role: string | null;
}

export function MembersView({
  initialMembers,
  membersMeta,
  invitations,
  pendingInvitations,
  invitationStatus,
  rolesByBranch,
  branches,
  branchNames,
  schools,
  filters,
  roleOptions,
  isOrgLevel,
  staffSeats,
  canAssignBranches,
  currentMembershipId,
  initialInviteOpen = false,
}: {
  initialMembers: MemberRead[];
  membersMeta: PageMeta;
  /** One page of invitations, filtered in the database. */
  invitations: Page<InvitationRead>;
  pendingInvitations: number;
  invitationStatus: string | null;
  rolesByBranch: Record<string, RoleRead[]>;
  /** Branches a member can be added to. */
  branches: Branch[];
  branchNames: Record<string, string>;
  schools: SchoolRead[];
  filters: MemberFilters;
  /** One choice per role code, across every branch. */
  roleOptions: { code: string; name: string }[];
  /** The principal: sees every branch, so the table names each row's branch. */
  isOrgLevel: boolean;
  staffSeats: UsageItem | null;
  canAssignBranches: boolean;
  currentMembershipId: string | null;
  initialInviteOpen?: boolean;
}) {
  const { t } = useTranslations();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const schoolFilter = filters.school;
  const [busy, setBusy] = useState<string | null>(null);
  const [removing, setRemoving] = useState<MemberRead | null>(null);
  const [assigning, setAssigning] = useState<MemberRead | null>(null);
  const [editing, setEditing] = useState<MemberRead | null>(null);
  const [selectedBranches, setSelectedBranches] = useState<string[]>([]);
  const [inviteOpen, setInviteOpen] = useState(initialInviteOpen);
  const inviteSectionRef = useRef<HTMLDivElement | null>(null);

  // The section header is always in the DOM, so scrolling does not need to wait
  // for the panel's expanded content to render.
  function openAddMember() {
    setInviteOpen(true);
    inviteSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // =========================================================================
  // THE FILTERS LIVE IN THE URL, NOT IN THIS COMPONENT
  // =========================================================================
  // Branch, search, role and page are all query parameters, so a filtered list
  // survives Back and a refresh, can be sent to a colleague, and the server fetches
  // only the matching slice. Every write is `replace`, not `push`: typing six
  // letters must leave ONE history entry, not a per-keystroke undo. Same contract
  // as the Students directory.
  const writeParams = useCallback(
    (changes: Record<string, string | null>) => {
      const next = new URLSearchParams(searchParams.toString());
      for (const [key, value] of Object.entries(changes)) {
        if (value) next.set(key, value);
        else next.delete(key);
      }
      if (inviteOpen) next.set("invite", "1");
      else next.delete("invite");
      const qs = next.toString();
      router.replace((qs ? `${pathname}?${qs}` : pathname) as Route, { scroll: false });
    },
    [inviteOpen, pathname, router, searchParams],
  );

  // The box keeps its own copy so typing stays instant; the URL catches up on the
  // debounce. `lastWritten` tells our own writes apart from Back/Forward, which
  // change the URL without touching the box — without it the two effects chase.
  const [search, setSearch] = useState(filters.q);
  const debouncedSearch = useDebouncedValue(search.trim(), 300);
  const lastWritten = useRef(filters.q);

  useEffect(() => {
    if (filters.q === lastWritten.current) return;
    lastWritten.current = filters.q;
    setSearch(filters.q);
  }, [filters.q]);

  useEffect(() => {
    // Only once the box has settled, or a Back pressed mid-word would be undone by
    // the abandoned word still in the debounce.
    if (debouncedSearch !== search.trim() || debouncedSearch === filters.q) return;
    lastWritten.current = debouncedSearch;
    // A new filter invalidates the page number: page 4 of the old result set means
    // nothing against the new one.
    writeParams({ q: debouncedSearch || null, page: null });
  }, [debouncedSearch, search, filters.q, writeParams]);

  const hasFilters = Boolean(filters.school || filters.q || filters.role);

  function clearFilters() {
    setSearch("");
    lastWritten.current = "";
    writeParams({ school: null, q: null, role: null, page: null, ipage: null });
  }

  // A role code from a shared link that this caller's role lists do not include
  // still shows by name in the picker, rather than as a blank trigger.
  const roleChoices =
    filters.role && !roleOptions.some((r) => r.code === filters.role)
      ? [...roleOptions, { code: filters.role, name: filters.role }]
      : roleOptions;

  // Only rows with a branch get an actions menu, so this is never the empty string
  // where it is used. Roles come pre-filtered to the branch's OWN roles: the
  // org-level `principal` role is transferred, never granted.
  const branchOf = (member: MemberRead) => member.school_id ?? "";
  const rolesFor = (member: MemberRead | null) =>
    member ? (rolesByBranch[branchOf(member)] ?? []) : [];

  async function act(fn: () => Promise<unknown>, successMessage: string, id: string) {
    setBusy(id);
    try {
      await fn();
      toast({ title: successMessage });
      router.refresh();
    } catch (error) {
      toast({
        variant: "destructive",
        title: t.common.somethingWrong,
        description: error instanceof ApiError ? error.message : t.common.tryAgain,
      });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mx-auto w-full max-w-5xl">
      <PageHeader
        title={t.members.title}
        description={t.members.subtitle}
        actions={
          <Can permission={PERMISSIONS.memberInvite}>
            <Button onClick={openAddMember}>
              <UserPlus className="size-4" aria-hidden />
              {t.members.addMember}
            </Button>
          </Can>
        }
      />

      <Can anyOf={[PERMISSIONS.invitationRead, PERMISSIONS.memberInvite]}>
        <div ref={inviteSectionRef} className="scroll-mt-4">
          <InvitationsSection
            invitations={invitations}
            pendingCount={pendingInvitations}
            statusFilter={invitationStatus}
            onStatusChange={(status) => writeParams({ istatus: status, ipage: null })}
            onPageChange={(next) => writeParams({ ipage: next > 1 ? String(next) : null })}
            branches={branches}
            branchNames={branchNames}
            rolesByBranch={rolesByBranch}
            defaultBranchId={schoolFilter}
            showBranch={isOrgLevel && schoolFilter === null}
            staffSeats={staffSeats}
            open={inviteOpen}
            onToggle={() => setInviteOpen((current) => !current)}
          />
        </div>
      </Can>

      <div className="rounded-xl border border-border bg-card">
        {/* Always rendered, so a search that matches nobody can be corrected in place. */}
        <div className="flex flex-col gap-3 border-b border-border p-4 lg:flex-row lg:items-center">
          <div className="relative flex-1">
            <Search
              className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t.members.searchPlaceholder}
              aria-label={t.members.searchPlaceholder}
              maxLength={200}
              className="ps-9"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {isOrgLevel && schools.length > 1 ? (
              <Select
                value={filters.school ?? ALL}
                onValueChange={(value) =>
                  // The invitation list follows the branch too, so its page resets.
                  writeParams({ school: value === ALL ? null : value, page: null, ipage: null })
                }
              >
                <SelectTrigger className="w-44" aria-label={t.members.branch}>
                  <SelectValue placeholder={t.members.allBranches} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>{t.members.allBranches}</SelectItem>
                  {schools.map((school) => (
                    <SelectItem key={school.id} value={school.id}>
                      {school.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : null}

            {roleChoices.length > 0 ? (
              <Select
                value={filters.role ?? ALL}
                onValueChange={(value) =>
                  writeParams({ role: value === ALL ? null : value, page: null })
                }
              >
                <SelectTrigger className="w-40" aria-label={t.common.role}>
                  <SelectValue placeholder={t.members.allRoles} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>{t.members.allRoles}</SelectItem>
                  {roleChoices.map((role) => (
                    <SelectItem key={role.code} value={role.code}>
                      {role.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : null}

            {hasFilters ? (
              <Button variant="ghost" size="sm" onClick={clearFilters}>
                <X className="size-4" aria-hidden />
                {t.members.clearFilters}
              </Button>
            ) : null}
          </div>
        </div>

        {membersMeta.total === 0 ? (
          hasFilters ? (
            <EmptyState
              icon={Search}
              title={t.members.noMatchTitle}
              description={t.members.noMatchBody}
              action={
                <Button variant="outline" onClick={clearFilters}>
                  {t.members.clearFilters}
                </Button>
              }
            />
          ) : (
            <EmptyState
              title={t.members.emptyTitle}
              description={t.members.emptyBody}
              action={
                <Can permission={PERMISSIONS.memberInvite}>
                  <Button onClick={openAddMember}>{t.members.addMember}</Button>
                </Can>
              }
            />
          )
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t.common.name}</TableHead>
                  {isOrgLevel ? <TableHead>{t.members.branch}</TableHead> : null}
                  <TableHead>{t.common.role}</TableHead>
                  <TableHead>Classes assigned</TableHead>
                  <TableHead>{t.common.status}</TableHead>
                  <TableHead className="w-12" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {initialMembers.map((member) => {
                  const isSelf = member.membership_id === currentMembershipId;
                  // The org-level principal. Removing the last one would leave the
                  // organization with nobody who can pay for it or appoint a successor.
                  const isOwner = member.role_code === "principal";
                  const branchId = member.school_id;

                  return (
                    <TableRow key={member.membership_id}>
                      <TableCell>
                        <div className="font-medium">{member.full_name}</div>
                        <div className="text-xs text-muted-foreground">{member.email}</div>
                      </TableCell>
                      {isOrgLevel ? (
                        <TableCell>
                          {branchId ? (
                            (branchNames[branchId] ?? "—")
                          ) : (
                            <Badge variant="neutral">{t.members.organizationWide}</Badge>
                          )}
                        </TableCell>
                      ) : null}
                      <TableCell>{member.role_name}</TableCell>
                      <TableCell>
                        {member.assigned_classes && member.assigned_classes.length > 0 ? (
                          <div className="flex max-w-xs flex-wrap gap-1">
                            {member.assigned_classes.map((a, i) => (
                              <Badge
                                key={i}
                                variant={a.section_name ? "default" : "neutral"}
                                title={a.section_name ? "Class teacher" : "Subject teacher"}
                              >
                                {a.class_name}
                                {a.section_name ? ` – ${a.section_name}` : ""}
                                {a.subject_name ? ` · ${a.subject_name}` : ""}
                              </Badge>
                            ))}
                          </div>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge variant={member.status === "active" ? "success" : "destructive"}>
                          {label(MEMBER_STATUS_LABELS, member.status)}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {isSelf ? (
                          <span className="text-xs text-muted-foreground">{t.common.you}</span>
                        ) : branchId === null ? null : (
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button variant="ghost" size="icon" disabled={busy !== null}>
                                <MoreHorizontal className="size-4" aria-hidden />
                                <span className="sr-only">Actions for {member.full_name}</span>
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className="w-56">
                              <Can permission={PERMISSIONS.memberUpdate}>
                                <DropdownMenuItem onSelect={() => setEditing(member)}>
                                  Edit member
                                </DropdownMenuItem>
                                <DropdownMenuSeparator />
                                {canAssignBranches ? (
                                  <DropdownMenuItem
                                    onSelect={() => {
                                      setSelectedBranches([]);
                                      setAssigning(member);
                                    }}
                                  >
                                    Assign school branches
                                  </DropdownMenuItem>
                                ) : null}
                                {rolesFor(member)
                                  .filter((role) => role.id !== member.role_id)
                                  .map((role) => (
                                    <DropdownMenuItem
                                      key={role.id}
                                      onSelect={() =>
                                        act(
                                          () =>
                                            membersApi.update(branchId, member.membership_id, {
                                              role_id: role.id,
                                            }),
                                          `${member.full_name} is now ${role.name}.`,
                                          member.membership_id,
                                        )
                                      }
                                    >
                                      {t.members.changeRoleTo} {role.name}
                                    </DropdownMenuItem>
                                  ))}
                                <DropdownMenuSeparator />
                              </Can>

                              <Can permission={PERMISSIONS.memberSuspend}>
                                <DropdownMenuItem
                                  onSelect={() =>
                                    act(
                                      () =>
                                        membersApi.update(branchId, member.membership_id, {
                                          suspended: member.status === "active",
                                        }),
                                      member.status === "active"
                                        ? `${member.full_name} is suspended.`
                                        : `${member.full_name} is active again.`,
                                      member.membership_id,
                                    )
                                  }
                                >
                                  {member.status === "active"
                                    ? t.members.suspendAccess
                                    : t.members.reactivate}
                                </DropdownMenuItem>
                              </Can>

                              <Can permission={PERMISSIONS.memberRemove}>
                                <DropdownMenuItem
                                  className="text-destructive focus:text-destructive"
                                  // The server refuses to remove the last principal (409).
                                  // Disabling it here explains the rule instead of
                                  // teaching it through a failed action.
                                  disabled={isOwner}
                                  onSelect={() => setRemoving(member)}
                                >
                                  {t.members.removeFromSchool}
                                </DropdownMenuItem>
                              </Can>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
            <Pagination
              meta={membersMeta}
              onPageChange={(page) => writeParams({ page: page > 1 ? String(page) : null })}
              disabled={busy !== null}
            />
          </>
        )}
      </div>

      <EditMemberDialog
        schoolId={editing ? branchOf(editing) : ""}
        member={editing}
        roles={rolesFor(editing)}
        onClose={() => setEditing(null)}
      />

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={`Remove ${removing?.full_name}?`}
        description={t.members.removeBody}
        confirmLabel="Remove"
        variant="destructive"
        onConfirm={async () => {
          if (!removing) return;
          await act(
            () => membersApi.remove(branchOf(removing), removing.membership_id),
            `${removing.full_name} was removed.`,
            removing.membership_id,
          );
          setRemoving(null);
        }}
      />

      <Dialog open={assigning !== null} onOpenChange={(open) => !open && setAssigning(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Assign school branches</DialogTitle>
            <DialogDescription>
              Add {assigning?.full_name} to one or more branches. Existing branch access is preserved.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            {schools.filter((school) => school.id !== assigning?.school_id && school.status === "active").map((school) => (
              <label key={school.id} className="flex items-center gap-3 rounded-md border p-3 text-sm">
                <input
                  type="checkbox"
                  checked={selectedBranches.includes(school.id)}
                  onChange={(event) => setSelectedBranches((current) => event.target.checked ? [...current, school.id] : current.filter((id) => id !== school.id))}
                />
                <span><span className="font-medium">{school.name}</span> <span className="text-muted-foreground">({school.code})</span></span>
              </label>
            ))}
            {schools.filter((school) => school.id !== assigning?.school_id && school.status === "active").length === 0 ? (
              <p className="text-sm text-muted-foreground">There are no other active school branches.</p>
            ) : null}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAssigning(null)}>Cancel</Button>
            <Button
              disabled={!assigning || selectedBranches.length === 0 || busy !== null}
              onClick={async () => {
                if (!assigning) return;
                await act(
                  () =>
                    membersApi.assignBranches(
                      branchOf(assigning),
                      assigning.membership_id,
                      selectedBranches,
                    ),
                  `${assigning.full_name} was assigned to ${selectedBranches.length} additional branch${selectedBranches.length === 1 ? "" : "es"}.`,
                  assigning.membership_id,
                );
                setAssigning(null);
              }}
            >
              Assign branches
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
