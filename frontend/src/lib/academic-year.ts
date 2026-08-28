/**
 * The academic year a date falls in, on an April start — the Pakistani school
 * calendar.
 *
 * Lives here rather than in a view because two screens need the same answer: the
 * fees register defaults its year filter to it, and a student's page uses it to
 * pre-frame a challan run. Two copies of this would drift by a month boundary and
 * quietly file a challan under the wrong year.
 */
export function currentAcademicYear(now: Date = new Date()): string {
  const startYear = now.getMonth() + 1 >= 4 ? now.getFullYear() : now.getFullYear() - 1;
  return `${startYear}-${startYear + 1}`;
}
