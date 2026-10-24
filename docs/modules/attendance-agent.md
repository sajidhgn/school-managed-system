# Attendance agent (WhatsApp → register)

A teacher takes the day's attendance by **messaging the school's WhatsApp
number** with the class and the roll numbers of the students who are not simply
present. The agent matches the numbers to names, shows them back, and submits
the register once the teacher replies **OK**.

It rides the same number, gateway and webhook as the
[diary agent](diary-agent.md). Photos go to the diary; registers go here.

## The teacher's side

```
teacher  Nursery-A absent 12, 13, 15
agent    📋 Attendance - Nursery-A
         🗓️ Friday, 17 Oct 2026

         ❌ Absent (3)
         12 - Ali Khan
         13 - Sara Ahmed
         15 - Bilal Raza

         ✅ Everyone else present (27 of 30)

         Reply OK to submit.
         To change something, just tell me (e.g. "13 was present", "also 17 absent").
         Reply CANCEL to discard.
teacher  13 was present
agent    📋 ... ❌ Absent (2) ...
teacher  ok
agent    ✅ Attendance submitted for Nursery-A (Friday, 17 Oct 2026): 28 present, 2 absent.
```

What a teacher can send:

| Message | Meaning |
| --- | --- |
| `Nursery-A absent 12, 13, 15` | 12, 13, 15 absent; everyone else present |
| `5B absent 3 late 7 leave 9 half day 8` | several statuses at once |
| `Grade 5-B all present` / `sab hazir` | the whole class present |
| `absent 4, 9` | no class: their only class, or the one on screen, or they are asked |
| `ghair hazir`, `chutti`, `rukhsat`, `hazir` | Roman Urdu: absent, leave, leave, present |
| `۱۲، ۱۳` | Urdu digits work |
| `also 17`, `13 was present`, `remove 4` | a change to the list on screen |

**Leave** (`leave`, `chutti`, `rukhsat`, `excused`) is recorded as `excused`,
which leaves the attendance percentage's denominator. See
[attendance.md](attendance.md) §4.2.

Only the **whole-day** register (period 0) of **today** is marked this way.
Period registers and back-dated registers stay on the web.

## How a message is read

1. **The parser** (`parser.py`) reads the usual shape in code:
   `[class] <status> <rolls> [<status> <rolls>]…`. It accounts for every word
   or gives up. Anything it might misread goes to the model: a range (`12-15`),
   the status after the numbers (`12, 13 absent`), `also`, `except`, the same
   child twice.
2. **The model** (`agent.py`, LangChain `ChatOpenAI` with structured output,
   `DIARY_AGENT_MODEL`) reads the rest, plus changes to the list on screen. It is
   given the message, the teacher's class labels, and the current list **as roll
   numbers**. **It never sees a student's name.**
3. **Code** matches roll numbers to students, against the class roster. The
   teacher confirms the **names** before anything is written.

## The rules, and where they live

| Rule | Where |
| --- | --- |
| Only identified staff of this campus are answered; unknown numbers get no reply. | `diary_agent/conversation.py::_identify` |
| Sending a register needs `attendance:mark`, the same code as the web register. | `conversation.py::handle` |
| The class must be one the teacher may mark (class teacher, or subject teacher in the class); with `class:view_all`, any. The model's choice is checked against that list again. | `repository.py::markable_sections`, `conversation.py::_target_for` |
| A class the teacher **named** but does not teach is never swapped for their own: they are asked. | `conversation.py::_target_for` |
| Nothing touches the register until OK. The OK then opens, marks and submits it in one transaction, through `AttendanceService`. | `conversation.py::_submit` |
| A submitted register is never changed from WhatsApp. If one was submitted on the web between preview and OK, the OK is refused. Amending still needs `attendance:amend` on the web. | `conversation.py::_resolve`, `_write_register` |
| If none of the roll numbers are in the class, it is refused, not submitted as "everyone present". | `conversation.py::_resolve` |
| The message is the whole register: anyone not named is present, including on a web draft opened earlier. | `conversation.py::_write_register` |
| With a diary and a register both waiting, **OK goes to the one shown last**. | `conversation.py::handle` (`diary_open_at`) |
| A redelivered webhook is read once (unique `(school_id, inbound_message_id)`). A double OK submits once (row lock). | `models.py`, `repository.py::open_for` |

## Data

| Table | What |
| --- | --- |
| `attendance_chat_drafts` | One row per register sent: the teacher's words (`request_text`), what they were read as (`marks`, by roll number), what was matched and shown (`resolved`), the class, the register it became (`attendance_session_id`) and why it failed (`error`). |

Migration: `d4f6a8c0e2b4`. No new permission, no new setting. Drafts lapse
after `DIARY_DRAFT_TTL_MINUTES` (default 3 hours).

## Setup

Nothing beyond the [diary agent's setup](diary-agent.md#setup): WAHA connected,
and each teacher's **phone** saved on their staff account. The parser works
without `OPENAI_API_KEY`; free-form messages and changes need it.

## Not in this slice

- Period-wise (per lesson) registers and back-dated registers.
- Amending a submitted register over WhatsApp.
- An office screen listing the WhatsApp registers. The register itself records
  who submitted it, and `attendance_chat_drafts` keeps the messages.
- Absence alerts to parents. A submitted register is the trigger; that is a
  separate feature.
