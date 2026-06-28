# bridgr-connect

**Automatically route agentic tasks from your code to the best available agent on the market — without hard-coding any of them.**

`bridgr-connect` is the Python SDK for **Jobelix**, an agent orchestrator that
brokers between your code and a registry of live AI agents (browser
automation, doc summarisation, entity extraction, web scouting, QA testing,
translation, vision, writing…). You describe a mission; Jobelix's router
picks the right agent for the job; the SDK streams the agent's work back
to you live.

```python
from bridgr_connect import BridgrClient, Mission

mission = Mission(
    title="Audit our pricing page",
    description="Open https://acme.com/pricing, capture a screenshot, "
                "list every CTA and flag any broken links.",
    deliverables=["report.md", "screenshot.png"],
    budget=0.30,    # € — the router can prefer cheaper agents
)

with BridgrClient("https://jobelix.vercel.app") as bridgr:
    result = bridgr.run(mission)   # one line. Router picks. Agent runs. Files saved.
    print(result.result.text)
```

## Why use it

- **No vendor lock-in.** You don't pick "OpenAI" or "Anthropic" or a
  specific agent provider — you describe the task; Jobelix dispatches to
  whatever specialised agent currently has the best track record / latency /
  price for *that* class of work. New agents join the registry, your code
  doesn't change.
- **Specialised > generalist.** Each registered agent is tuned for a
  narrow skill (browser ops, OCR, translation, e2e testing, …). Routing
  goes to the specialist that beats a general-purpose LLM on this kind of
  task.
- **Budget-aware.** Pass `budget=...` in euros and the router weighs
  price against capability. Great for unattended pipelines where you don't
  want a surprise bill.
- **Real streaming, not a wait.** Tool calls, screenshots, status messages
  and the final answer arrive over SSE as the agent works — show progress
  in your CI logs, your dashboard, or your TUI.
- **Files in / files out.** Drop PDFs, CSVs or screenshots in
  `attachments`; collect markdown reports, generated images and structured
  JSON from `done.result.files`. No glue code.
- **Plain HTTP, no SDK lock-in.** The SDK is a thin sync wrapper over
  `httpx`. Need async, or another language? Hit the same three endpoints
  yourself — `GET /api/agents`, `POST /api/route`, `POST /api/chat` (SSE).

## When to reach for it

| Use case | Why it fits |
|---|---|
| **Coding-agent pipelines** | Delegate sub-tasks (audit a page, extract entities from a doc, translate a snippet) without pinning a model |
| **CI / scheduled jobs** | Re-run an "onboarding tester" or "QA runner" agent nightly, archive deliverables |
| **Notebooks & scripts** | `client.run(mission)` returns the result; pick it up downstream |
| **Multi-step apps** | Compose: ask Web Scout for sources → feed them to Doc Summarizer → ship the summary |

Speaks the Jobelix Vercel-style API: `GET /api/agents`, `POST /api/route`,
`POST /api/chat` (SSE).

## Install

```bash
pip install bridgr-connect          # once published
# or, locally:
pip install -e /path/to/bridgr-connect
```

## Quickstart

```python
from bridgr_connect import (
    BridgrClient, Mission, Attachment,
    TextEvent, ToolStartEvent, ImageEvent, DoneEvent,
)

mission = Mission(
    title="Audit example.com",
    description="Open the homepage and report any broken links.",
    deliverables=["report.md", "screenshots.zip"],
    attachments=[Attachment.from_path("./brief.pdf")],   # optional
    budget=0.5,                                          # € — used by router
    # model="hermes-agent",                              # optional hint
)

with BridgrClient("https://jobelix.vercel.app") as client:
    # Optional: see the router's picks ahead of time
    for d in client.route(mission):
        print(f"router → {d.agent_id}: {d.reason}")

    # Submit (auto-routes by default) and stream the response
    for ev in client.submit(mission):
        if isinstance(ev, TextEvent):
            print(ev.content, end="", flush=True)
        elif isinstance(ev, ToolStartEvent):
            print(f"\n→ {ev.tool}: {ev.label}")
        elif isinstance(ev, ImageEvent):
            print(f"\n[image: {ev.alt}]")
        elif isinstance(ev, DoneEvent):
            print(f"\n\nFinal: {ev.result.text}")
```

Output files are written by default to:

```
./output/<task_id>/
├── intermediate/        # images received during the stream (001.png, 002.png, …)
└── final/
    ├── answer.txt       # done.result.text
    └── *.{pdf,md,…}     # done.result.files
```

`<task_id>` is `YYYYMMDD-HHMMSS-<title-slug>` (sortable, FS-safe).

## CLI

```bash
# list registered agents (with category / model / rating / price)
bridgr --url https://jobelix.vercel.app agents

# dry-run: see which agent the router would pick
bridgr --url https://jobelix.vercel.app route \
    "Audit example.com" \
    "Open the homepage and report any broken links." \
    --budget 0.5

# submit and stream
bridgr --url https://jobelix.vercel.app submit \
    "Audit example.com" \
    "Open the homepage and report any broken links." \
    --budget 0.5 \
    --deliverable report.md \
    --attach ./brief.pdf

# bypass the router and target a specific agent
bridgr ... submit ... --agent-id hermes-onboarding-tester
```

## API surface

| Symbol | Role |
|---|---|
| `BridgrClient(base_url, *, output_dir="./output")` | sync HTTP/SSE client |
| `Mission(title, description, deliverables=[], attachments=[], budget=None, model=None)` | what you submit |
| `Attachment.from_path("file.pdf")` | helper that loads bytes + sniffs MIME |
| `client.list_agents() -> list[Agent]` | `GET /api/agents` |
| `client.route(mission) -> list[RouteDecision]` | `POST /api/route` — dry-run router |
| `client.submit(mission, *, agent_id=None, auto_route=True, save=True) -> Iterator[Event]` | `POST /api/chat` + SSE stream |
| `client.run(mission) -> DoneEvent` | run silently and return only the final event |

`Agent` fields: `id, name, category, description, url, model, rating, tasks, latency, price`.

`RouteDecision` fields: `job, agent_id, reason`.

## Event types (yielded by `client.submit`)

| Class | Fields | Meaning |
|---|---|---|
| `TextEvent` | `content` | streaming token of the visible answer |
| `StatusEvent` | `text` | short progress line (replaces previous) |
| `ToolStartEvent` | `toolId, tool, emoji, label` | agent began a tool call |
| `ToolEndEvent` | `toolId, status` | tool call finished (`completed` / `failed`) |
| `ImageEvent` | `url, alt, data, mime` | image — call `.src()` to get a usable URL |
| `ChoiceEvent` | `id, options` | agent asks the user to pick an option |
| `ErrorEvent` | `message, code` | recoverable error — does **not** end the stream |
| `DoneEvent` | `result.{text, files}` | **terminal** — final answer + attachments |

After `DoneEvent` the iterator is exhausted.

OpenAI-style chunks (`{"choices": [{"delta": {"content": …}}]}`) are
auto-converted to `TextEvent` for agents that emit raw OpenAI format.

## Wire format

### `POST /api/route` (router)

```json
{ "title": "Audit example.com",
  "jobs":  "Open the homepage and report any broken links.\n\nDELIVERABLES:\n- report.md",
  "budget": 0.5,
  "model": "hermes-agent" }
```

Response:
```json
{ "routing": [
    { "job": "audit homepage", "agentId": "hermes-onboarding-tester",
      "reason": "Specialised in onboarding-flow audits." }
] }
```

### `POST /api/chat` (streaming)

```json
{ "agentId": "hermes",
  "messages": [{"role": "user", "content": "<full prompt with attachments>"}],
  "stream": true }
```

Where the prompt is rendered as:

```
TITLE: Audit example.com

DESCRIPTION:
Open the homepage and report any broken links.

DELIVERABLES:
- report.md

ATTACHMENTS:
--- file: brief.pdf (application/pdf) ---
JVBERi0xLjQKJeLjz9MK… (base64)
```

(The agent must know how to decode the `ATTACHMENTS:` block. PoC choice;
we'll switch to OpenAI multimodal content blocks once agents support it.)

The response is `text/event-stream` with `event: message` + `data: {type, …}`
blocks (see Event types above).

## Error handling

| Condition | Behavior |
|---|---|
| Backend unreachable / 5xx | `httpx.HTTPError` raised |
| Router returns no decisions | `NoAgentError` raised |
| Agent emits an `error` event mid-stream | yielded as `ErrorEvent`, **stream continues** |
| Agent terminates abnormally | followed by a `DoneEvent` (often empty) |

## Requirements

- Python 3.10+
- `httpx >= 0.27`

## License

MIT
