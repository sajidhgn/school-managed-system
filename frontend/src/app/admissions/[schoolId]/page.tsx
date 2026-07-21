import type { Metadata } from "next";

import { AdmissionForm } from "./admission-form";

export const metadata: Metadata = {
  title: "Admissions application",
  description: "Apply for admission online.",
  // A half-finished application shouldn't be indexed or shared as a search result.
  robots: { index: false, follow: false },
};

/**
 * Public admissions form.
 *
 * No `requireUser()` here by design: a prospective parent has no account. The
 * route is whitelisted in `middleware.ts`, and the backend admissions endpoint
 * is public. The school is identified only by the id in the URL.
 */
export default async function AdmissionsPage({
  params,
}: {
  params: Promise<{ schoolId: string }>;
}) {
  const { schoolId } = await params;
  return <AdmissionForm schoolId={schoolId} />;
}
