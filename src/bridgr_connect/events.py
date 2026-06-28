"""Typed event dataclasses for the SSE stream returned by ``/api/chat``.

Each event has a ``type`` discriminator matching the wire format from the backend.
See ``GUIDE_AGENT.md`` for the full contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Union


@dataclass
class TextEvent:
    content: str = ""
    type: str = "text"


@dataclass
class StatusEvent:
    text: str = ""
    type: str = "status"


@dataclass
class ToolStartEvent:
    toolId: str = ""
    tool: str = ""
    emoji: str = ""
    label: str = ""
    type: str = "tool_start"


@dataclass
class ToolEndEvent:
    toolId: str = ""
    status: str = "completed"   # "completed" | "failed"
    type: str = "tool_end"


@dataclass
class ImageEvent:
    """An image event from the agent.

    Can carry either a ``url`` (http(s):// or ``data:`` URI) OR a ``data``
    base64 payload with its ``mime`` type. Use :py:meth:`src` to get a
    single usable URL regardless of which shape the agent sent.
    """

    url: str = ""
    alt: str = ""
    data: str = ""   # base64-encoded payload (alternative to ``url``)
    mime: str = ""
    type: str = "image"

    def src(self) -> str:
        """Return a single URL ready to embed in an ``<img>`` (or to decode)."""
        if self.url:
            return self.url
        if self.data:
            return f"data:{self.mime or 'image/png'};base64,{self.data}"
        return ""


@dataclass
class ChoiceEvent:
    id: str = ""
    options: list[dict[str, Any]] = field(default_factory=list)
    type: str = "choice"


@dataclass
class ErrorEvent:
    message: str = ""
    code: str = ""
    type: str = "error"


@dataclass
class FileAttachment:
    name: str = ""
    mime: str = ""
    data: str = ""   # base64-encoded payload
    url: str = ""    # alternative to ``data``: a URL to fetch from
    size: int = 0


@dataclass
class DoneResult:
    text: str = ""
    files: list[FileAttachment] = field(default_factory=list)


@dataclass
class DoneEvent:
    result: DoneResult = field(default_factory=DoneResult)
    type: str = "done"


Event = Union[
    TextEvent, StatusEvent, ToolStartEvent, ToolEndEvent,
    ImageEvent, ChoiceEvent, ErrorEvent, DoneEvent,
    dict,   # unknown event types pass through as raw dict for forward compat
]


def parse_event(raw: dict[str, Any]) -> Event:
    """Turn a raw ``{"type": "...", ...}`` dict into the matching dataclass.

    Also handles OpenAI-style chunks (``{"choices": [{"delta": {"content": …}}]}``)
    by converting them to a :class:`TextEvent` — some agents emit this shape
    instead of the typed ``text`` event.

    Unknown types are returned as the raw dict — callers should ignore them.
    """
    t = raw.get("type")
    if t == "text":
        return TextEvent(content=raw.get("content", ""))
    if t == "status":
        return StatusEvent(text=raw.get("text", ""))
    if t == "tool_start":
        return ToolStartEvent(
            toolId=raw.get("toolId", "") or raw.get("tool", ""),
            tool=raw.get("tool", ""),
            emoji=raw.get("emoji", ""),
            label=raw.get("label", ""),
        )
    if t == "tool_end":
        return ToolEndEvent(
            toolId=raw.get("toolId", "") or raw.get("tool", ""),
            status=raw.get("status", "completed"),
        )
    if t == "image":
        return ImageEvent(
            url=raw.get("url", ""),
            alt=raw.get("alt", ""),
            data=raw.get("data", ""),
            mime=raw.get("mime", ""),
        )
    if t == "choice":
        return ChoiceEvent(id=raw.get("id", ""), options=raw.get("options", []))
    if t == "error":
        return ErrorEvent(message=raw.get("message", ""), code=raw.get("code", ""))
    if t == "done":
        r = raw.get("result") or {}
        files = [
            FileAttachment(
                name=f.get("name", ""),
                mime=f.get("mime", ""),
                data=f.get("data", ""),
                url=f.get("url", ""),
                size=f.get("size", 0),
            )
            for f in (r.get("files") or [])
        ]
        return DoneEvent(result=DoneResult(text=r.get("text", ""), files=files))
    # OpenAI-style fallback: {"choices": [{"delta": {"content": "…"}}]}
    delta = (raw.get("choices") or [{}])[0].get("delta") or {}
    if delta.get("content"):
        return TextEvent(content=delta["content"])
    return raw
