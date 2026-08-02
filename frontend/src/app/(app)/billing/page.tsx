import type { Metadata } from "next";

import { BillingView } from "./billing-view";
import { API_BASE_URL, API_V1_PREFIX } from "@/lib/api/config";
import { serverGet } from "@/lib/api/server";
import type {
  InvoiceRead,
  PlanPublic,
  SubscriptionRead,
  UsageResponse,
} from "@/lib/api/types";
import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireUser } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Billing" };

export default async function BillingPage() {
  const user = await requireUser();
  const canRead = hasPermission(user, PERMISSIONS.billingRead);

  const [subscription, usage, invoices, plansResponse] = await Promise.all([
    canRead
      ? serverGet<SubscriptionRead | null>("/billing/subscription", null)
      : Promise.resolve(null),
    // Usage is readable by any member, so it renders even for someone without
    // billing rights — they can still see why a create was refused.
    serverGet<UsageResponse | null>("/org/usage", null),
    hasPermission(user, PERMISSIONS.invoiceRead)
      ? serverGet<InvoiceRead[]>("/billing/invoices", [])
      : Promise.resolve<InvoiceRead[]>([]),
    fetch(`${API_BASE_URL}${API_V1_PREFIX}/public/plans`, { next: { revalidate: 300 } }),
  ]);

  const plans: PlanPublic[] = plansResponse.ok ? await plansResponse.json() : [];

  return (
    <BillingView
      subscription={subscription}
      usage={usage}
      invoices={invoices}
      plans={plans}
      canManage={hasPermission(user, PERMISSIONS.billingManage)}
    />
  );
}
