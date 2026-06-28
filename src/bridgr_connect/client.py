"""Sync HTTP/SSE client for the Jobelix orchestrator (Vercel-style API)."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator

import httpx

from .events import DoneEvent, Event, ImageEvent, parse_event


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Attachment:
    """A document attached to a mission (PDF, CSV, image, etc.)."""

    name: str
    data: bytes
    mime: str = "application/octet-stream"

    @classmethod
    def from_path(cls, path: str | Path, mime: str | None = None) -> "Attachment":
        p = Path(path)
        return cls(
            name=p.name,
            data=p.read_bytes(),
            mime=mime or _guess_mime(p.suffix),
        )


@dataclass
class Mission:
    """A unit of work submitted to the orchestrator.

    Fields
    ------
    title : str
        Short human-readable label (used by the router and for the output
        directory name).
    description : str
        Precise execution instructions. Sent to ``/api/route`` as ``jobs``
        and embedded in the agent prompt.
    deliverables : list[str], optional
        What the user expects back (concatenated into the prompt — the agent
        decides what to actually attach in ``done.result.files``).
    attachments : list[Attachment], optional
        Input files (PDF, CSV, …) inlined as base64 into the agent prompt.
    budget : float | None, optional
        Compute budget in €. Sent to the router so it can pick a cheaper
        agent if needed.
    model : str | None, optional
        Preferred model hint (e.g. ``"hermes-agent"``). The backend may or
        may not honour it — primary routing key is ``agentId``.
    """

    title: str
    description: str
    deliverables: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    budget: float | None = None
    model: str | None = None

    def task_id(self) -> str:
        """Stable id for one submission. Human-readable, sortable, FS-safe."""
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = _slugify(self.title)[:32] or "mission"
        return f"{ts}-{slug}"

    def to_jobs(self) -> str:
        """Render description + deliverables for the ``/api/route`` call.

        Attachments are NOT included — the router runs a small LLM and base64
        bloat would waste tokens for no benefit. Attachments go to ``/api/chat``
        instead (see :py:meth:`to_prompt`).
        """
        lines: list[str] = [self.description.strip()]
        if self.deliverables:
            lines += ["", "DELIVERABLES:"]
            lines += [f"- {d}" for d in self.deliverables]
        return "\n".join(lines)

    def to_prompt(self) -> str:
        """Render the mission as the single user message sent to the agent."""
        lines: list[str] = [
            f"TITLE: {self.title}",
            "",
            "DESCRIPTION:",
            self.description,
        ]
        if self.deliverables:
            lines += ["", "DELIVERABLES:"]
            lines += [f"- {d}" for d in self.deliverables]
        if self.attachments:
            lines += ["", "ATTACHMENTS:"]
            for a in self.attachments:
                b64 = base64.b64encode(a.data).decode("ascii")
                lines += [f"--- file: {a.name} ({a.mime}) ---", b64]
        return "\n".join(lines)


@dataclass
class Agent:
    """A registered agent as returned by ``GET /api/agents``.

    All metadata fields are optional — the backend may omit some.
    """

    id: str
    name: str = ""
    category: str = ""
    description: str = ""
    url: str = ""
    model: str = ""
    rating: float = 0.0
    tasks: int = 0
    latency: float = 0.0
    price: float = 0.0


@dataclass
class RouteDecision:
    """One row of ``POST /api/route`` response.

    The router may split a multi-job mission across several agents — you'll
    get one decision per (sub-)job.
    """

    job: str
    agent_id: str
    reason: str = ""


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class BridgrError(Exception):
    """Base class for bridgr-connect errors."""


class NoAgentError(BridgrError):
    """Raised when no agent can be selected for the mission."""


class BackendError(BridgrError):
    """Raised when the backend returns a non-2xx response.

    Unlike a bare :class:`httpx.HTTPStatusError`, this carries the parsed
    body so you can see *why* the server failed (e.g. ``OPENAI_API_KEY not
    configured``) without re-fetching the response.
    """

    def __init__(self, status_code: int, body: str, url: str):
        self.status_code = status_code
        self.body = body
        self.url = url
        super().__init__(f"HTTP {status_code} from {url} — {body[:300]}")


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class BridgrClient:
    """Sync client for the Jobelix orchestrator (``/api/agents``, ``/api/route``, ``/api/chat``).

    Example
    -------
    >>> mission = Mission(title="hi", description="say hello", budget=0.5)
    >>> with BridgrClient("https://jobelix.vercel.app") as c:
    ...     for ev in c.submit(mission):
    ...         print(ev)
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float | None = None,
        output_dir: str | Path = "./output",
    ):
        self.base_url = base_url.rstrip("/")
        self.output_root = Path(output_dir)
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    # context manager
    def __enter__(self) -> "BridgrClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # -- agent discovery -----------------------------------------------------

    def list_agents(self) -> list[Agent]:
        """Return the agents currently exposed by the backend (``GET /api/agents``)."""
        r = self._client.get("/api/agents")
        _raise_for_status(r)
        return [_agent_from_dict(a) for a in r.json()]

    # -- routing -------------------------------------------------------------

    def route(self, mission: Mission) -> list[RouteDecision]:
        """Ask the backend's router which agent should handle this mission.

        Calls ``POST /api/route`` with ``{title, jobs, budget, model}``.
        Returns one :class:`RouteDecision` per job — the router may split
        the mission across several agents.
        """
        body: dict = {
            "title": mission.title,
            "jobs": mission.to_jobs(),
        }
        if mission.budget is not None:
            body["budget"] = mission.budget
        if mission.model:
            body["model"] = mission.model

        r = self._client.post("/api/route", json=body)
        _raise_for_status(r)
        data = r.json()
        raw = data.get("routing") or []
        if not isinstance(raw, list):
            raw = [raw]
        return [
            RouteDecision(
                job=d.get("job", ""),
                agent_id=d.get("agentId", "") or d.get("agent_id", ""),
                reason=d.get("reason", ""),
            )
            for d in raw
        ]

    # -- mission lifecycle ---------------------------------------------------

    def submit(
        self,
        mission: Mission,
        *,
        agent_id: str | None = None,
        auto_route: bool = True,
        save: bool = True,
    ) -> Iterator[Event]:
        """Send a mission and yield events as they arrive.

        Parameters
        ----------
        mission : Mission
        agent_id : optional. If set, route to this agent directly (bypasses
            ``/api/route``).
        auto_route : if True (default) and ``agent_id`` is None, call
            ``/api/route`` first to pick an agent. Set False to fall back
            to the backend's default agent picker.
        save : if True (default), persist intermediate ``image`` events to
            ``<output_dir>/<task_id>/intermediate/`` and the final
            ``done.result.files`` into ``<output_dir>/<task_id>/final/``.

        Yields
        ------
        Event
            Typed dataclasses. After a ``DoneEvent`` the iterator is exhausted.

        Raises
        ------
        httpx.HTTPError
            On transport failure or non-2xx response from the backend.
        NoAgentError
            If ``auto_route=True`` but the router returns no decisions.
        """
        task_id = mission.task_id()
        task_dir = self.output_root / task_id

        if agent_id is None and auto_route:
            decisions = self.route(mission)
            if not decisions:
                raise NoAgentError("router returned no decisions")
            agent_id = decisions[0].agent_id

        body: dict = {
            "messages": [{"role": "user", "content": mission.to_prompt()}],
            "stream": True,
        }
        if agent_id:
            body["agentId"] = agent_id

        with self._client.stream(
            "POST",
            "/api/chat",
            json=body,
            headers={"Accept": "text/event-stream"},
            timeout=None,
        ) as r:
            if r.status_code >= 400:
                # we have to consume the body before the context closes
                r.read()
                _raise_for_status(r)
            for raw in _iter_sse(r):
                ev = parse_event(raw)
                if save:
                    self._maybe_save(ev, task_dir)
                yield ev

    def run(
        self,
        mission: Mission,
        *,
        agent_id: str | None = None,
        auto_route: bool = True,
        save: bool = True,
    ) -> DoneEvent | None:
        """Consume the whole stream silently and return the final ``DoneEvent``.

        Convenience for callers that only care about the result.
        """
        last: DoneEvent | None = None
        for ev in self.submit(
            mission, agent_id=agent_id, auto_route=auto_route, save=save,
        ):
            if isinstance(ev, DoneEvent):
                last = ev
        return last

    # -- private -------------------------------------------------------------

    def _maybe_save(self, ev: Event, task_dir: Path) -> None:
        if isinstance(ev, ImageEvent):
            inter = task_dir / "intermediate"
            payload = _image_bytes(ev)
            if payload is None:
                return
            data, suffix = payload
            inter.mkdir(parents=True, exist_ok=True)
            n = 1 + sum(1 for _ in inter.glob("*"))
            (inter / f"{n:03d}{suffix}").write_bytes(data)
        elif isinstance(ev, DoneEvent):
            final = task_dir / "final"
            final.mkdir(parents=True, exist_ok=True)
            (final / "answer.txt").write_text(ev.result.text or "", encoding="utf-8")
            for f in ev.result.files:
                if f.data:
                    (final / f.name).write_bytes(base64.b64decode(f.data))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _raise_for_status(r: httpx.Response) -> None:
    """Like :py:meth:`httpx.Response.raise_for_status` but includes the body.

    Tries to surface ``{"error": "..."}`` JSON errors cleanly; falls back to
    the raw text for non-JSON responses.
    """
    if r.status_code < 400:
        return
    text = (r.text or "").strip()
    try:
        j = r.json()
        if isinstance(j, dict):
            # Combine "error" + "detail" so we surface both the high-level cause
            # (e.g. "OpenAI error") AND the low-level reason (e.g. "model_not_found").
            err = j.get("error") or j.get("message")
            detail = j.get("detail")
            parts: list[str] = []
            if err:
                parts.append(err if isinstance(err, str) else json.dumps(err))
            if detail:
                if isinstance(detail, dict):
                    detail = json.dumps(detail)
                # If detail is itself a JSON-encoded string, try to extract the
                # inner ``error.message`` for readability.
                if isinstance(detail, str):
                    try:
                        inner = json.loads(detail)
                        if isinstance(inner, dict) and "error" in inner:
                            msg = inner["error"].get("message") if isinstance(inner["error"], dict) else inner["error"]
                            if msg:
                                detail = str(msg)
                    except (ValueError, json.JSONDecodeError):
                        pass
                parts.append(str(detail))
            if parts:
                text = " — ".join(parts)
    except (ValueError, json.JSONDecodeError):
        pass
    raise BackendError(r.status_code, text or f"<{len(r.content)} bytes>", str(r.url))


def _agent_from_dict(d: dict) -> Agent:
    """Build an Agent from the wire dict (tolerant to missing fields)."""
    return Agent(
        id=d.get("id", "") or d.get("agent_id", ""),
        name=d.get("name", ""),
        category=d.get("category", ""),
        description=d.get("description", ""),
        url=d.get("url", ""),
        model=d.get("model", ""),
        rating=float(d.get("rating") or 0.0),
        tasks=int(d.get("tasks") or 0),
        latency=float(d.get("latency") or 0.0),
        price=float(d.get("price") or 0.0),
    )


# SSE block separator is "\n\n", but some servers (or proxies) emit "\r\n\r\n".
_BLOCK_SEP = re.compile(r"\r?\n\r?\n")
_LINE_SEP = re.compile(r"\r?\n")


def _iter_sse(response: httpx.Response) -> Iterator[dict]:
    """Yield JSON payloads from each SSE block in the response.

    Skips the OpenAI ``[DONE]`` sentinel. Malformed JSON is silently dropped.
    """
    buffer = ""
    for chunk in response.iter_text():
        buffer += chunk
        while True:
            m = _BLOCK_SEP.search(buffer)
            if not m:
                break
            block, buffer = buffer[: m.start()], buffer[m.end():]
            for line in _LINE_SEP.split(block):
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].lstrip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    yield json.loads(payload)
                except json.JSONDecodeError:
                    continue


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


_MIME_BY_SUFFIX = {
    ".pdf":  "application/pdf",
    ".csv":  "text/csv",
    ".json": "application/json",
    ".md":   "text/markdown",
    ".txt":  "text/plain",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif":  "image/gif",
    ".webp": "image/webp",
    ".svg":  "image/svg+xml",
}


def _guess_mime(suffix: str) -> str:
    return _MIME_BY_SUFFIX.get(suffix.lower(), "application/octet-stream")


_DATA_URI_RE = re.compile(r"^data:([^;,]+)(;base64)?,(.*)$", re.DOTALL)

_SUFFIX_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}


def _image_bytes(ev: ImageEvent) -> tuple[bytes, str] | None:
    """Return (bytes, suffix) for an ImageEvent, or None for http(s) URLs."""
    # base64 payload + mime → decode directly
    if ev.data:
        suffix = _SUFFIX_BY_MIME.get(ev.mime.lower(), ".bin")
        try:
            return base64.b64decode(ev.data), suffix
        except (ValueError, TypeError):
            return None
    # data: URI → decode
    if ev.url:
        m = _DATA_URI_RE.match(ev.url)
        if m:
            mime, is_b64, payload = m.group(1), m.group(2), m.group(3)
            suffix = _SUFFIX_BY_MIME.get(mime.lower(), ".bin")
            data = base64.b64decode(payload) if is_b64 else payload.encode("utf-8")
            return data, suffix
    # http(s) URL — leave to the caller
    return None
