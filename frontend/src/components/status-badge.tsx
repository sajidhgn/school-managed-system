import { Badge, type BadgeProps } from "@/components/ui/badge";
import {
  SCHOOL_STATUS_LABELS,
  STUDENT_STATUS_LABELS,
  USER_STATUS_LABELS,
  PLAN_LABELS,
  type SchoolStatus,
  type StudentStatus,
  type SubscriptionPlan,
  type UserStatus,
} from "@/lib/api/types";

type Variant = NonNullable<BadgeProps["variant"]>;

/**
 * Status → colour maps.
 *
 * Exhaustive Records, so a new backend enum variant becomes a compile error
 * rather than an unstyled grey pill nobody notices in production.
 */
const STUDENT_VARIANTS: Record<StudentStatus, Variant> = {
  active: "success",
  pending: "warning",
  inactive: "neutral",
  graduated: "default",
  transferred: "neutral",
};

const SCHOOL_VARIANTS: Record<SchoolStatus, Variant> = {
  active: "success",
  pending_approval: "warning",
  suspended: "destructive",
  cancelled: "neutral",
};

const USER_VARIANTS: Record<UserStatus, Variant> = {
  active: "success",
  pending_verification: "warning",
  suspended: "destructive",
};

const PLAN_VARIANTS: Record<SubscriptionPlan, Variant> = {
  trial: "warning",
  basic: "neutral",
  standard: "default",
  premium: "success",
};

export function StudentStatusBadge({ status }: { status: StudentStatus }) {
  return <Badge variant={STUDENT_VARIANTS[status]}>{STUDENT_STATUS_LABELS[status]}</Badge>;
}

export function SchoolStatusBadge({ status }: { status: SchoolStatus }) {
  return <Badge variant={SCHOOL_VARIANTS[status]}>{SCHOOL_STATUS_LABELS[status]}</Badge>;
}

export function UserStatusBadge({ status }: { status: UserStatus }) {
  return <Badge variant={USER_VARIANTS[status]}>{USER_STATUS_LABELS[status]}</Badge>;
}

export function PlanBadge({ plan }: { plan: SubscriptionPlan }) {
  return <Badge variant={PLAN_VARIANTS[plan]}>{PLAN_LABELS[plan]}</Badge>;
}
