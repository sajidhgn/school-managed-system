# WhatsApp module

Posts to each class's parents' WhatsApp group. It does two things:

- **Monthly fee notice.** On the campus's send day (default the 1st), every
  linked group gets one message built from that class's issued challans: month,
  standard fee and due date. The office's standing "custom message" is appended
  underneath.
- **Custom messages.** The office types a message and picks the groups to send
  it to.

## How sending works

The API never posts. Everything is written to the `whatsapp_messages` outbox,
and `python -m app.cli send-whatsapp` (`make send-whatsapp`) drains it through
`WHATSAPP_BACKEND`:

| Backend | What it does |
| --- | --- |
| `console` (default) | logs each message and marks it sent |
| `null` | marks it sent, logs nothing |
| `pywhatkit` | really posts, by driving WhatsApp Web in a browser |
| `waha` | really posts **and receives**, through a self-hosted WAHA gateway (headless, one linked session per campus). Required by the [diary agent](diary-agent.md). |

**pywhatkit runs on a desktop only.** It opens `web.whatsapp.com`, opens the
group from its invite code and types the message with simulated keystrokes.
To run it:

1. Use a desktop PC where WhatsApp Web is logged in as the school's number.
   That number must be an admin of every group.
2. Install it: `uv sync --extra whatsapp`.
3. Set `WHATSAPP_BACKEND=pywhatkit` in that machine's `.env`, pointed at the
   production database.
4. Schedule `make send-whatsapp` (cron or Windows Task Scheduler) to run a few
   minutes after the server's nightly `run-maintenance`.
5. Leave the screen alone while it runs. A click elsewhere sends the text to the
   wrong window.

Each run sends at most `WHATSAPP_DISPATCH_BATCH` messages (default 50), taking
about 30 seconds each. A pywhatkit "sent" status means the message was typed
into WhatsApp Web without an error. It is not a delivery receipt.

Known limits of pywhatkit:

- Automating WhatsApp Web is against WhatsApp's terms, and a number that posts
  in bursts can be banned.
- Non-Latin text (Urdu) may not type correctly.

The sender sits behind a Protocol (`app/common/whatsapp/sender.py`), so a
hosted gateway can replace pywhatkit as one new class.

**WAHA** (`WHATSAPP_BACKEND=waha`) is that gateway. Each campus links its number
from the WhatsApp page (**Connect WhatsApp**, then scan the QR code). Groups are
then addressed by their WhatsApp id, resolved from the invite link. Run
`send-whatsapp --watch` (the `whatsapp-worker` service in `compose.yml`) to drain
the outbox continuously. It carries the same terms-of-service risk as pywhatkit.
See [diary-agent.md](diary-agent.md#whatsapp-the-waha-gateway).

## Parent-portal sign-in codes

With `WHATSAPP_BACKEND=waha`, the six-digit code a parent asks for at `/parent/login`
is sent to them directly (not through the outbox), from the WAHA session of a
campus where they have a child they may view. The number is checked first
(`GET /api/contacts/check-exists`): a number with no WhatsApp gets no WhatsApp
message, and a campus whose session is not working is skipped for the next one.
When WhatsApp cannot deliver, the code falls back to `SMS_BACKEND` (the console in
development; `null` in production until an SMS provider exists). The send runs
after the HTTP response, so response timing does not reveal whether a number is
registered. Code: `backend/app/modules/guardians/delivery.py`.

A parent can sign in only once staff turn access on from the student's page
(**Parent portal** card): `POST /guardians/students/{id}/portal-access`, which
registers the phone if needed and links it to the child. The free-text guardian
phone on the student form never becomes a login by itself.

## The fee notice

- The notice is queued only when the class has **issued** challans for the
  month. Drafts are not announced.
- If the challans are still drafts on the send day, each later nightly pass
  checks again and queues the notice the night after they are issued. It stops
  once the challans are past due.
- Each group gets at most **one notice per month**. A partial unique index on
  `(group_id, period_label) WHERE kind = 'fee_notice'` enforces this, so retries
  and overlapping passes can't post twice.
- The amount is the most common challan subtotal in the class (the standard
  fee), never a single family's dues.
- A group linked to a section counts only that section's challans.
- Template placeholders: `{class} {month} {amount} {due_date} {school} {challans}`.
  Unknown placeholders are left as typed.

## Permissions

| Code | Grants |
| --- | --- |
| `whatsapp:read` | groups, settings, preview, outbox |
| `whatsapp:send` | queue custom messages or the fee notice now; retry or cancel |
| `whatsapp:manage` | link groups; configure the monthly notice |

Default grants: principal → all three; accountant → read and send.

## API

| Method | Path | Notes |
| --- | --- | --- |
| GET/POST | `/whatsapp/groups` | `invite_link` accepts the full `chat.whatsapp.com/...` link or the bare code |
| PUT/DELETE | `/whatsapp/groups/{id}` | deleting drops the group's still-queued messages |
| GET/PUT | `/whatsapp/settings` | `fee_notice_enabled`, `send_day` (1-28), `fee_template`, `monthly_note` |
| GET | `/whatsapp/fee-notices/preview?period_label=` | what each group would receive |
| POST | `/whatsapp/fee-notices` | queue the month's notice now (still once per group per month) |
| POST/GET | `/whatsapp/messages` | queue a custom message; list the outbox |
| POST | `/whatsapp/messages/{id}/retry` | failed → queued |
| DELETE | `/whatsapp/messages/{id}` | cancel an unsent message |

## Frontend

`/whatsapp` has four tabs: Groups, Monthly fee notice (settings, live preview
and Send now), Send message, and Outbox.
