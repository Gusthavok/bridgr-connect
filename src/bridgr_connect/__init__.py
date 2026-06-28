"""bridgr-connect — Python SDK for the Jobelix agent orchestrator."""

from .client import (
    Agent,
    Attachment,
    BackendError,
    BridgrClient,
    BridgrError,
    Mission,
    NoAgentError,
    RouteDecision,
)
from .events import (
    ChoiceEvent,
    DoneEvent,
    DoneResult,
    ErrorEvent,
    Event,
    FileAttachment,
    ImageEvent,
    StatusEvent,
    TextEvent,
    ToolEndEvent,
    ToolStartEvent,
    parse_event,
)

__all__ = [
    # client
    "BridgrClient", "Mission", "Attachment", "Agent", "RouteDecision",
    "BridgrError", "BackendError", "NoAgentError",
    # events
    "Event", "parse_event",
    "TextEvent", "StatusEvent", "ToolStartEvent", "ToolEndEvent",
    "ImageEvent", "ChoiceEvent", "ErrorEvent", "DoneEvent",
    "FileAttachment", "DoneResult",
]

__version__ = "0.1.0"
