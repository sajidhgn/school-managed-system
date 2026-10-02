# Diary module

The daily homework page each section takes home: one row per subject in the
class curriculum, with that day's assignment beside it.

## Who writes what

| Who | Writes |
| --- | --- |
| Class teacher of the section (`sections.class_teacher_id`) | every subject on that section's page |
| Subject teacher (`class_subjects.teacher_id`) | only their subject's row, in every section of that class |
| Holder of `diary:manage` | any row on any page |
| Anyone else with `diary:read` | nothing, but can view every page |

`diary:write` sets *what kind* of thing a person may do. The class and subject
assignments set *where*, and the service enforces them. A save that names a row
the caller can't write is refused as a whole (403 `DIARY_NOT_ASSIGNED`).

Default grants: teacher → `diary:read`, `diary:write`; principal → all three.

## API

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/diary/sections?date=` | every section, the caller's own first, with `access` and filled/subject counts |
| GET | `/diary/sections/{id}?date=` | the page: every curriculum subject, homework or not, with `can_edit` per row |
| PUT | `/diary/sections/{id}?date=` | `{entries: [{subject_id, content}]}`; partial; blank content clears a row |
| GET | `/portal/children/{student_id}/diary?date=` | guardian view of the child's section page, read-only |

Without `diary:manage`, writes are limited to within 30 days of today in either
direction. That catches mistyped dates; it isn't meant as a permission rule.

## Storage

`diary_entries` (section, date, subject, content) is unique per
(section, date, subject). An empty page costs no rows. Every save writes one
`diary.updated` audit row listing each changed subject with its text before and
after.

## Frontend

`/diary`: pick a class and date, then fill each subject. Text direction is
automatic, so Urdu lines type right to left. **Diary image** draws the sheet
(crest, school name, date, day, Subject | Assignments) as a PNG, which can be
downloaded, shared from a phone, or printed. See `frontend/src/lib/diary-image.ts`.
