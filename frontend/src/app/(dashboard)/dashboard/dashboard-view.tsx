"use client";

import Link from "next/link";
import { ArrowRight, GraduationCap, Layers, Users, UsersRound } from "lucide-react";

import { EmptyState, ErrorState } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { StudentStatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useClassSummary } from "@/hooks/use-classes";
import { useStudents } from "@/hooks/use-students";
import type { UserRead } from "@/lib/api/types";
import { formatDate } from "@/lib/utils";

/**
 * A single headline number.
 *
 * `value` is `undefined` while loading and stays `undefined` on failure — a
 * dash is honest, whereas rendering 0 would assert something the API never
 * confirmed.
 */
function StatCard({
  icon: Icon,
  label,
  value,
  hint,
  loading,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: number | undefined;
  hint?: string;
  loading?: boolean;
}) {
  return (
    <Card>
      <CardContent className="flex items-start gap-4 p-5">
        <div className="rounded-lg bg-accent p-2.5">
          <Icon className="size-4 text-accent-foreground" />
        </div>
        <div className="min-w-0 space-y-1">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {label}
          </p>
          {loading ? (
            <Skeleton className="h-7 w-14" />
          ) : (
            <p className="text-2xl font-semibold tabular-nums leading-none">
              {value === undefined ? "—" : value.toLocaleString()}
            </p>
          )}
          {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
        </div>
      </CardContent>
    </Card>
  );
}

export function DashboardView({ user }: { user: UserRead }) {
  // Size 1 — these queries exist only for `meta.total`, so there is no reason
  // to transfer a full page of rows.
  const totalStudents = useStudents({ page: 1, size: 1 });
  const pendingStudents = useStudents({ status: "pending", page: 1, size: 1 });
  const recentStudents = useStudents({
    page: 1,
    size: 5,
    sort_by: "created_at",
    sort_dir: "desc",
  });
  const classSummary = useClassSummary();

  const classes = classSummary.data ?? [];
  const sectionCount = classes.reduce((sum, cls) => sum + cls.section_count, 0);
  const pendingCount = pendingStudents.data?.meta.total;
  const recent = recentStudents.data?.items ?? [];

  // Only school admins can act on the queue; for everyone else the count is
  // information, not a call to action.
  const canReviewAdmissions = user.role === "school_admin";
  const largestClass = classes.reduce((max, cls) => Math.max(max, cls.student_count), 0);

  const firstName = user.full_name.split(" ")[0] || user.full_name;

  return (
    <>
      <PageHeader
        title={`Welcome back, ${firstName}`}
        description="A snapshot of your school today."
      />

      {canReviewAdmissions && pendingCount !== undefined && pendingCount > 0 ? (
        <Card className="mb-5 border-warning/40 bg-warning/8">
          <CardContent className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <div className="rounded-lg bg-warning/20 p-2.5">
                <GraduationCap className="size-4 text-warning-foreground dark:text-warning" />
              </div>
              <div className="space-y-0.5">
                <p className="text-sm font-semibold">
                  {pendingCount} {pendingCount === 1 ? "application is" : "applications are"}{" "}
                  waiting for review
                </p>
                <p className="text-sm text-muted-foreground">
                  Families have applied and can&apos;t enrol until someone decides.
                </p>
              </div>
            </div>
            <Button asChild className="shrink-0">
              <Link href="/admissions-queue">
                Review admissions
                <ArrowRight />
              </Link>
            </Button>
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          icon={Users}
          label="Students"
          value={totalStudents.data?.meta.total}
          hint="All statuses"
          loading={totalStudents.isLoading}
        />
        <StatCard
          icon={GraduationCap}
          label="Pending admissions"
          value={pendingCount}
          hint="Awaiting a decision"
          loading={pendingStudents.isLoading}
        />
        <StatCard
          icon={Layers}
          label="Classes"
          value={classSummary.data ? classes.length : undefined}
          hint={classSummary.data ? `${sectionCount} sections` : undefined}
          loading={classSummary.isLoading}
        />
        <StatCard
          icon={UsersRound}
          label="Placed in sections"
          value={
            classSummary.data
              ? classes.reduce((sum, cls) => sum + cls.student_count, 0)
              : undefined
          }
          hint="Assigned to a class"
          loading={classSummary.isLoading}
        />
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-5">
        <Card className="overflow-hidden lg:col-span-3">
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>Recently added students</CardTitle>
            <Link
              href="/students"
              className="text-sm font-medium text-primary hover:underline"
            >
              View all
            </Link>
          </CardHeader>

          {recentStudents.isError ? (
            <ErrorState
              error={recentStudents.error}
              onRetry={() => void recentStudents.refetch()}
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Admission no.</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Added</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recentStudents.isLoading ? (
                  Array.from({ length: 5 }).map((_, index) => (
                    <TableRow key={index}>
                      {Array.from({ length: 4 }).map((__, cell) => (
                        <TableCell key={cell}>
                          <Skeleton className="h-4 w-full max-w-28" />
                        </TableCell>
                      ))}
                    </TableRow>
                  ))
                ) : recent.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={4} className="p-0">
                      <EmptyState
                        icon={Users}
                        title="No students yet"
                        description="Once students are enrolled they'll show up here."
                      />
                    </TableCell>
                  </TableRow>
                ) : (
                  recent.map((student) => (
                    <TableRow key={student.id}>
                      <TableCell>
                        <Link
                          href={`/students/${student.id}`}
                          className="font-medium text-foreground hover:text-primary hover:underline"
                        >
                          {student.full_name}
                        </Link>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {student.admission_number}
                      </TableCell>
                      <TableCell>
                        <StudentStatusBadge status={student.status} />
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDate(student.created_at)}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          )}
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Headcount by class</CardTitle>
          </CardHeader>

          {classSummary.isError ? (
            <ErrorState
              error={classSummary.error}
              onRetry={() => void classSummary.refetch()}
            />
          ) : classSummary.isLoading ? (
            <CardContent className="space-y-4">
              {Array.from({ length: 5 }).map((_, index) => (
                <div key={index} className="space-y-2">
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-1.5 w-full" />
                </div>
              ))}
            </CardContent>
          ) : classes.length === 0 ? (
            <EmptyState
              icon={Layers}
              title="No classes yet"
              description="Create a class to start organising students into sections."
              action={
                <Button variant="outline" size="sm" asChild>
                  <Link href="/classes">Go to classes</Link>
                </Button>
              }
            />
          ) : (
            <CardContent className="space-y-4">
              {classes.map((cls) => (
                <div key={cls.id} className="space-y-1.5">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="truncate text-sm font-medium">{cls.name}</span>
                    <span className="shrink-0 text-sm tabular-nums text-muted-foreground">
                      {cls.student_count}
                      <span className="ml-1.5 text-xs">
                        · {cls.section_count} {cls.section_count === 1 ? "section" : "sections"}
                      </span>
                    </span>
                  </div>
                  {/* Bars are scaled to the largest class, not to a total — the
                      question is "which class is fullest", not "what share". */}
                  <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary"
                      style={{
                        width: largestClass > 0 ? `${(cls.student_count / largestClass) * 100}%` : "0%",
                      }}
                    />
                  </div>
                </div>
              ))}
            </CardContent>
          )}
        </Card>
      </div>
    </>
  );
}
