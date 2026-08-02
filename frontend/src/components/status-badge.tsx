import { Badge } from "@/components/ui/badge";
import {
  INVITATION_STATUS_LABELS,
  MEMBER_STATUS_LABELS,
  ORG_STATUS_LABELS,
  SCHOOL_STATUS_LABELS,
  STUDENT_STATUS_LABELS,
  SUBSCRIPTION_STATUS_LABELS,
  label,
} from "@/lib/api/types";

/**
 * Status pills.
 *
 * =============================================================================
 * KEYED ON `string`, NOT ON AN ENUM UNION — and that is a deliberate change
 * =============================================================================
 *   These used to take `Record<SchoolStatus, ...>` maps, which required every
 *   possible value to be enumerated at compile time. Several of these statuses are
 *   now open-ended on the backend: an organization can gain a lifecycle state, and
 *   `over_limit` was added exactly that way.
 *
 *   An exhaustive map would mean the frontend fails to build every time the backend
 *   adds a state — or, worse, that someone "fixes" the build by mapping the new
 *   value to whatever tone was nearest. Falling back to `neutral` and the raw string
 *   renders an unknown status honestly and legibly.
 *
 * TONE IS SEMANTIC, NOT DECORATIVE. Green means fine, amber means attention needed,
 * red means blocked. Colour is never the only signal — the label always says the
 * same thing in words, which is what a colourblind user and a screen reader read.
 */

type Tone = "success" | "warning" | "destructive" | "neutral" | "default";

const TONES: Record<string, Tone> = {
  // Healthy
  active: "success",
  accepted: "success",
  paid: "success",
  trialing: "success",

  // Needs attention, still working
  pending: "warning",
  pending_approval: "warning",
  past_due: "warning",
  over_limit: "warning",
  open: "warning",

  // Blocked or ended
  suspended: "destructive",
  cancelled: "destructive",
  expired: "destructive",
  revoked: "destructive",
  uncollectible: "destructive",

  // Neutral outcomes
  inactive: "neutral",
  archived: "neutral",
  graduated: "neutral",
  transferred: "neutral",
  draft: "neutral",
  void: "neutral",
};

function toneFor(status: string | null | undefined): Tone {
  if (!status) return "neutral";
  return TONES[status] ?? "neutral";
}

function StatusBadge({
  status,
  labels,
}: {
  status: string | null | undefined;
  labels: Record<string, string>;
}) {
  return <Badge variant={toneFor(status)}>{label(labels, status)}</Badge>;
}

export function StudentStatusBadge({ status }: { status: string | null | undefined }) {
  return <StatusBadge status={status} labels={STUDENT_STATUS_LABELS} />;
}

export function SchoolStatusBadge({ status }: { status: string | null | undefined }) {
  return <StatusBadge status={status} labels={SCHOOL_STATUS_LABELS} />;
}

export function OrganizationStatusBadge({ status }: { status: string | null | undefined }) {
  return <StatusBadge status={status} labels={ORG_STATUS_LABELS} />;
}

export function SubscriptionStatusBadge({ status }: { status: string | null | undefined }) {
  return <StatusBadge status={status} labels={SUBSCRIPTION_STATUS_LABELS} />;
}

export function MemberStatusBadge({ status }: { status: string | null | undefined }) {
  return <StatusBadge status={status} labels={MEMBER_STATUS_LABELS} />;
}

export function InvitationStatusBadge({ status }: { status: string | null | undefined }) {
  return <StatusBadge status={status} labels={INVITATION_STATUS_LABELS} />;
}
