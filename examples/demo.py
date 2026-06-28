"""Submit a mission and stream the response.

Run:
    python examples/demo.py
"""

from __future__ import annotations

from bridgr_connect import (
    BridgrClient,
    DoneEvent,
    ImageEvent,
    Mission,
    StatusEvent,
    TextEvent,
    ToolStartEvent,
)


BACKEND_URL = "https://jobelix.vercel.app:3000"


def main() -> None:
    mission = Mission(
        title="Capture example.com",
        description="Navigate to example.com and capture the rendered page.",
        deliverables=["screenshot.png", "page-title.txt"],
        budget=0.5,                          # € — used by the router
        # model="hermes-agent",              # optional hint
        # attachments=[Attachment.from_path("input.pdf")],
    )

    with BridgrClient(BACKEND_URL) as c:
        agents = c.list_agents()
        print(f"available agents: {[a.id for a in agents] or '(none)'}")

        # Optional: see what the router would pick (without running anything)
        for d in c.route(mission):
            print(f"router → {d.agent_id}  ({d.reason})")

        for ev in c.submit(mission):
            if isinstance(ev, TextEvent):
                print(ev.content, end="", flush=True)
            elif isinstance(ev, StatusEvent):
                print(f"\n[status] {ev.text}")
            elif isinstance(ev, ToolStartEvent):
                print(f"\n→ {ev.tool}: {ev.label}")
            elif isinstance(ev, ImageEvent):
                print(f"\n[image: {ev.alt or 'untitled'}]")
            elif isinstance(ev, DoneEvent):
                print(f"\n\nFINAL: {ev.result.text}")
                print(f"  → {len(ev.result.files)} file(s) saved to ./output/")


if __name__ == "__main__":
    main()
