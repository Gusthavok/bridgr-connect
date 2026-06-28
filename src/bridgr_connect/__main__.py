"""CLI entry point: ``bridgr agents`` / ``bridgr route`` / ``bridgr submit``.

Examples
--------
    $ bridgr --url https://jobelix.vercel.app agents

    $ bridgr --url https://jobelix.vercel.app route \\
          "Audit example.com" "Open the homepage and report any 404s" --budget 0.5

    $ bridgr --url https://jobelix.vercel.app submit \\
          "Audit example.com" "Open the homepage and report any 404s" \\
          --budget 0.5 \\
          --deliverable report.md \\
          --attach ./brief.pdf
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .client import Attachment, BackendError, BridgrClient, Mission, NoAgentError
from .events import (
    ChoiceEvent,
    DoneEvent,
    ErrorEvent,
    ImageEvent,
    StatusEvent,
    TextEvent,
    ToolEndEvent,
    ToolStartEvent,
)


def _cmd_agents(args: argparse.Namespace) -> int:
    with BridgrClient(args.url, output_dir=args.out) as c:
        agents = c.list_agents()
    if not agents:
        print("(no agents exposed by this backend)")
        return 0
    for a in agents:
        price = f"€{a.price:.2f}" if a.price else "—"
        rating = f"{a.rating}★" if a.rating else "—"
        print(
            f"{a.id:30s}  {a.category:12s}  {a.model:14s}  "
            f"{rating:>6s}  {price:>6s}  {a.name}"
        )
    return 0


def _build_mission(args: argparse.Namespace) -> Mission:
    attachments = [Attachment.from_path(p) for p in (args.attach or [])]
    return Mission(
        title=args.title,
        description=args.description,
        deliverables=args.deliverable or [],
        attachments=attachments,
        budget=args.budget,
        model=args.model,
    )


def _cmd_route(args: argparse.Namespace) -> int:
    mission = _build_mission(args)
    with BridgrClient(args.url, output_dir=args.out) as c:
        decisions = c.route(mission)
    if not decisions:
        print("(router returned no decisions)")
        return 1
    for i, d in enumerate(decisions, 1):
        print(f"#{i}  {d.agent_id}")
        print(f"    job:    {d.job}")
        print(f"    reason: {d.reason}")
    return 0


def _cmd_submit(args: argparse.Namespace) -> int:
    mission = _build_mission(args)
    task_id = mission.task_id()

    with BridgrClient(args.url, output_dir=args.out) as c:
        try:
            agent_id = args.agent_id
            if agent_id is None and not args.no_route:
                decisions = c.route(mission)
                if not decisions:
                    print("❌ router returned no decisions", file=sys.stderr)
                    return 1
                agent_id = decisions[0].agent_id
                print(f"→ router picked: {agent_id}  ({decisions[0].reason})",
                      file=sys.stderr)
        except Exception as e:  # transport / HTTP errors
            print(f"❌ routing failed: {e}", file=sys.stderr)
            return 1

        print(f"→ task: {task_id}", file=sys.stderr)
        print(f"→ agent: {agent_id or '(backend default)'}", file=sys.stderr)
        print(f"→ output: {Path(args.out)/task_id}", file=sys.stderr)
        print("─" * 60, file=sys.stderr)

        for ev in c.submit(
            mission,
            agent_id=agent_id,
            auto_route=False,   # we already routed above
        ):
            if isinstance(ev, TextEvent):
                print(ev.content, end="", flush=True)
            elif isinstance(ev, StatusEvent):
                print(f"\n[STATUS] {ev.text}", file=sys.stderr)
            elif isinstance(ev, ToolStartEvent):
                emoji = (ev.emoji + " ") if ev.emoji else ""
                print(f"\n[▶ {emoji}{ev.tool}] {ev.label}", file=sys.stderr)
            elif isinstance(ev, ToolEndEvent):
                print(f"[✓ {ev.toolId}] {ev.status}", file=sys.stderr)
            elif isinstance(ev, ImageEvent):
                short = (ev.src() or "(no src)")[:60]
                print(f"\n[IMG] {ev.alt or '(no alt)'}  {short}…",
                      file=sys.stderr)
            elif isinstance(ev, ChoiceEvent):
                opts = " | ".join(o.get("label", "?") for o in ev.options)
                print(f"\n[CHOICE {ev.id}] {opts}", file=sys.stderr)
            elif isinstance(ev, ErrorEvent):
                print(f"\n[ERROR {ev.code}] {ev.message}", file=sys.stderr)
            elif isinstance(ev, DoneEvent):
                print("\n" + "─" * 60, file=sys.stderr)
                print("FINAL:", file=sys.stderr)
                print(ev.result.text)
                if ev.result.files:
                    print(f"\nFiles ({len(ev.result.files)}):", file=sys.stderr)
                    for f in ev.result.files:
                        print(f"  📎 {f.name} ({f.mime})", file=sys.stderr)
    return 0


def main() -> None:
    p = argparse.ArgumentParser(
        prog="bridgr",
        description="Client CLI for the Jobelix agent orchestrator.",
    )
    p.add_argument("--url", default="http://localhost:3000",
                   help="backend URL (default: %(default)s)")
    p.add_argument("--out", default="./output",
                   help="output root dir (default: %(default)s)")

    sub = p.add_subparsers(dest="cmd", required=True)

    # agents
    pa = sub.add_parser("agents", help="list registered agents")
    pa.set_defaults(func=_cmd_agents)

    # shared mission args (route + submit)
    def add_mission_args(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("title", help="short mission title")
        sp.add_argument("description", help="precise execution instructions")
        sp.add_argument("--deliverable", "-d", action="append",
                        help="(repeatable) expected deliverable name")
        sp.add_argument("--attach", "-a", action="append",
                        help="(repeatable) path to a file to attach")
        sp.add_argument("--budget", type=float, default=None,
                        help="compute budget in €")
        sp.add_argument("--model", default=None,
                        help="preferred model hint (forwarded to the router)")

    # route
    pr = sub.add_parser("route",
                        help="dry-run: ask the router which agent would handle this")
    add_mission_args(pr)
    pr.set_defaults(func=_cmd_route)

    # submit
    ps = sub.add_parser("submit",
                        help="submit a mission and stream the result")
    add_mission_args(ps)
    ps.add_argument("--agent-id", default=None,
                    help="bypass the router and target this agent")
    ps.add_argument("--no-route", action="store_true",
                    help="skip the /api/route call; let the backend pick")
    ps.set_defaults(func=_cmd_submit)

    args = p.parse_args()
    try:
        rc = args.func(args)
    except NoAgentError as e:
        print(f"❌ {e}", file=sys.stderr)
        rc = 1
    except BackendError as e:
        print(f"❌ backend HTTP {e.status_code}: {e.body}", file=sys.stderr)
        if e.status_code == 500 and "OPENAI_API_KEY" in e.body:
            print("   → the router needs OPENAI_API_KEY set in Vercel env vars;",
                  file=sys.stderr)
            print("   → workaround: re-run with `--agent-id <id>` to bypass the router.",
                  file=sys.stderr)
        rc = 1
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
