# Diary agent (WhatsApp → class group)

Teachers already write the day's diary on paper. Instead of retyping it, a
teacher **photographs the diary page and sends it to the school's WhatsApp
number**. An AI agent reads the photo, works out which class it is for, writes
it in **this campus's own format**, shows it back to the teacher, and posts it
to that class's parents' WhatsApp group once the teacher replies **OK**.

It replaces the old typed Diary screen (removed with migration `b8d0f2a4c6e8`,
which drops `diary_entries`).

The same number also takes attendance: a text such as `Nursery-A absent 12, 13`
goes to the [attendance agent](attendance-agent.md). Every text is offered to it
first; photos are always the diary's. With a diary and a register both waiting,
**OK** confirms the one shown last.

## The teacher's side (all on WhatsApp)

```
teacher  [photo of today's diary page]
agent    Got it - reading the diary page... 📖
agent    Here is the diary for *Grade 9-A*, ready for "9-A Parents":
         ...formatted diary...
         Reply OK to post it. To change something, just tell me.
         Wrong class? Reply CLASS 9-B. Reply CANCEL to discard.
teacher  maths is ex 4.3 not 4.2
agent    Here is the diary for *Grade 9-A* ... (corrected)
teacher  ok
agent    ✅ Posted to "9-A Parents".
```

- If the page doesn't say which class and the teacher has several, the agent
  lists them and asks for a number.
- A new photo replaces an unfinished one. A draft nobody answers lapses after
  `DIARY_DRAFT_TTL_MINUTES` (default 3 hours).
- OK words: `ok`, `yes`, `post`, `send`, `haan`, `ji`, `👍`, … Cancel words:
  `cancel`, `no`, `nahi`, … Anything else is treated as a correction.

## Who it answers, and where a diary may go

| Rule | Where |
| --- | --- |
| Only staff of **this campus** whose account **phone** matches the sender. Everyone else, parents included, gets **no reply at all**. | `conversation.py::_identify` |
| The sender needs the `whatsapp:diary` permission (seeded on the teacher role). | `conversation.py` |
| The diary can only go to an **active class group in the teacher's teaching scope**: the section they class-teach, or the classes they teach a subject in. With `class:view_all`, any group. | `repository.py::targets` |
| Nothing is posted until the teacher replies OK to the exact text shown. | `conversation.py::_post` |
| The model only *proposes* a class, chosen from that list. The proposal is checked against the list again before it's used. | `agent.py`, `conversation.py::_pick` |

Staff phones can be saved in any form (`0300-1234567`, `+92 300 1234567`, …).
They are normalised with `WHATSAPP_DEFAULT_COUNTRY_CODE` (default `92`). Senders
hidden behind WhatsApp's privacy ids (`…@lid`) are resolved to their phone
through WAHA.

## The format (per campus)

**WhatsApp → Diary agent** in the web app (`/api/v1/diary-agent/settings`):

- **Template**: the whole message. Placeholders: `{school}`, `{class}`,
  `{date}`, `{day}`, `{entries}`, `{notes}`, `{teacher}`.
- **Entry template**: one line per subject, joined into `{entries}`.
  Placeholders: `{subject}`, `{homework}`.
- **Instructions**: free-text guidance for the model on how to read the page,
  e.g. "keep Urdu homework in Urdu", "call Maths 'Mathematics'".
- **Preview** renders a sample diary in the unsaved format.

The layout is filled in code, never by the model, so the preview is exactly
what parents receive.

## The agent

`app/modules/diary_agent/agent.py` uses LangChain
`ChatOpenAI(model=DIARY_AGENT_MODEL).with_structured_output(DiaryReading)`:

- `read_page`: the photo (made upright, long edge capped at 2048 px) → subjects
  with homework, notes, the class as written, and `class_choice` from the
  offered list.
- `revise`: the current reading plus the teacher's message → the corrected
  reading.

The page is untrusted input. It reaches the model only as an image, and
answers come back through the schema.

## WhatsApp: the WAHA gateway

Meta's official Cloud API can't post into ordinary parents' groups: its Groups
API only covers groups the business created, with at most 8 participants. So
the agent uses **WAHA**, a self-hosted gateway that links the school's own
number the way WhatsApp Web does. **It is unofficial.** WhatsApp can ban a
number that posts in bursts, so the outbox is drained one message at a time.

- One WAHA container serves every campus, with one session per campus
  (`school_<school id hex>`).
- Each session's webhook carries the organization and school ids in its
  metadata and is **HMAC-SHA512 signed** with `WAHA_WEBHOOK_SECRET`. Unsigned
  or mis-signed webhooks get a 401.
- Groups are addressed by their WhatsApp id (`whatsapp_groups.chat_id`),
  resolved from the invite link once the number is connected. Resolving may
  join the group through its link, because the number must be a member to post.

### Setup

1. `.env`: `WHATSAPP_BACKEND=waha`, `WAHA_WEBHOOK_SECRET=<random>`,
   `WAHA_API_KEY`, `WAHA_BASE_URL`, `WAHA_WEBHOOK_URL` (see `.env.example`),
   and a valid `OPENAI_API_KEY`.
2. Start WAHA: `make waha-up` (dev, port 3001). In the full stack
   (`compose.yml`), the `waha` and `whatsapp-worker` services start with
   everything else.
3. Apply the migration: `make migrate`.
4. In the web app, open **WhatsApp → Connect WhatsApp**. On the school's
   phone, go to WhatsApp → Linked devices → Link a device and scan the QR code.
5. Link each class's parents' group (invite link) if not already linked. The
   school's number must be in the group.
6. Make sure each teacher's **phone** is saved on their staff account.

## Data

| Table | What |
| --- | --- |
| `diary_agent_settings` | One row per campus: enabled, template, entry template, instructions. |
| `diary_drafts` | One row per photo: status, what was read (`content` JSONB), class/group, the text shown, the outbox row once posted. The photo itself is not kept. |
| `whatsapp_messages` (`kind = 'diary'`) | What parents received, and whether it was sent. |
