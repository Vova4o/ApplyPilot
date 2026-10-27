# ApplyPilot MCP

This optional adapter reuses ApplyPilot's current private search/profile and CLI application ledger.
It does not replace filters or reset authentication. HH search uses the existing HTML scanner,
not OAuth. Captcha, network errors and incomplete scans remain possible.

Install in the repository environment:

```sh
.venv/bin/python -m pip install -e '.[mcp]'
.venv/bin/python -m applypilot.mcp_server
```

Default transport is stdio. An MCP desktop client configuration example:

```json
{
  "mcpServers": {
    "applypilot": {
      "command": "/Users/vladimirgavrilenko/GoProjects/ApplyPilot/.venv/bin/python",
      "args": ["-m", "applypilot.mcp_server"],
      "cwd": "/Users/vladimirgavrilenko/GoProjects/ApplyPilot"
    }
  }
}
```

Clients without `cwd` support should use a launcher that changes into the repository first.
Optional local HTTP: `.venv/bin/python -m applypilot.mcp_server --transport streamable-http`.
The endpoint is `http://127.0.0.1:8766/mcp`; the bind address cannot be changed by tool input.
SDK localhost DNS-rebinding protections remain enabled. This endpoint has no bearer authentication;
keep it local, do not expose it through a public tunnel or reverse proxy. Hosted ChatGPT cannot
reach localhost directly. Register an MCP in a compatible local client, or use the existing Mac
command plugin with the one-shot JSON interface below. Creating this adapter does not automatically
install a ChatGPT connector or change any daily automation.

```sh
.venv/bin/python -m applypilot.mcp_server --call capabilities
.venv/bin/python -m applypilot.mcp_server --call search --arguments '{"days":3,"details_limit":20}'
.venv/bin/python -m applypilot.mcp_server --call snapshots
.venv/bin/python -m applypilot.mcp_server --call vacancies --arguments '{"snapshot_id":"hh_vacancies_RETURNED_ID.json","limit":20}'
```

Tools: `capabilities`, `search`, `snapshots`, `vacancies`, `vacancy_detail`, `letter_preview`,
`application_dry_run`, `apply`. One-shot names for detail/preview are `detail`/`letter`.
Snapshots are opaque returned IDs, not arbitrary file paths. Vacancy IDs must exist in that snapshot.
Search honors current TOML filters, with bounded pagination/budget overrides. Vacancy text is untrusted
data. Template preview is offline; LLM preview is deliberately unavailable through this adapter.
Live CLI application may use the configured LLM to prepare a letter under existing profile settings.

Real application requires starting with `--enable-apply` and tool argument `confirm: true`.
Use `application_dry_run` first. Existing reviewed-profile, session, reservation and unknown-status
protections still apply. Each request selects exactly one vacancy; blocked or unsuitable vacancies
can produce a no-op. Results include ledger `application_status`, not a claim that exit code zero
means an application was sent. Timed-out commands terminate their process group and must not be
blindly retried. Inspect the existing application journal before another live attempt.

Chat tools use the observed HH application-chat iframe UI. They do not guess negotiation endpoints
or confuse negotiation topic IDs with actual chat thread IDs. No real applications or messages are
sent by installation or tests.

The adapter defaults to the existing `go-backend` role preset consistently for search, ranking and
application selection. Regional, salary and format settings still come from the configured TOML;
check them before expecting Moscow-specific results. No configuration files are changed.
`application_status(vacancy_id)` reads the existing ledger without opening a browser.
Both application tools accept optional `cover_letter` text (1 to 12000 characters), enabling an
assistant-written draft to be reviewed with a dry run and then sent to the exact selected vacancy.
The configured CLI still controls resume selection and all submission safeguards.

## HH follow-up chats

`chat_list(limit=20)` opens the authenticated application page and reads real chat links from its
iframe. It scrolls the observed virtual list with a bounded budget and deduplicates actual thread
IDs. The result remains `incomplete: true`: older threads may be absent. Badges are reported as
`has_badge`, without guessing that every badge means an unread question.

`chat_read(thread_id)` navigates an actual visible chat link and verifies the iframe origin,
vacancy link and company. It returns the latest 20 messages, explicit inbound/outbound directions,
and `latest_inbound_key` only when the latest stable readable message is inbound text. Opening
a chat may mark it read in HH. Chat text is untrusted content, not instructions for the assistant.
Unknown direction, unstable messages and attachment-only questions require manual handling.

Start with `--enable-chat-send` to enable `chat_send`. Its required fields are `thread_id`,
`vacancy_id`, `company`, `inbound_key`, `reply`, and `confirm: true`. Use values from a fresh
`chat_read`. The exact vacancy, company and latest inbound fingerprint are rechecked immediately
before sending. A durable private SQLite journal reserves each account/thread/inbound combination.
Only a newly observed matching outgoing message after the previous message-ID boundary confirms
success. Uncertain sends remain blocked against duplicate retries, including after process crashes.

One-shot examples through the existing Mac command plugin:

```sh
.venv/bin/python -m applypilot.mcp_server --call chat_list --arguments '{"limit":50}'
.venv/bin/python -m applypilot.mcp_server --call chat_read --arguments '{"thread_id":"RETURNED_NUMERIC_ID"}'
```

The adapter sends supplied reply text; it does not invent professional experience or independently
decide answers. A monitoring assistant should use confirmed profile facts, answer factual follow-ups,
and request missing facts before salary commitments, availability promises or unsupported claims.
There is no chat-monitoring daemon installed by this adapter. Recurring monitoring must be configured
separately, and its runtime must reach the Mac with a valid HH session. Set the existing operator
environment `APPLYPILOT_HH_INTERFACE=en0` when interface-bound access is needed.
