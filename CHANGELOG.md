# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] — 2026-06-28

### Changed
- README: add PyPI / Python / License badges and a Links section.
- `pyproject.toml`: cleaner description, add `[project.urls]` so the PyPI page
  links to the GitHub repo, broader keyword set.

### Notes
- No code changes. This release exists to refresh the PyPI page metadata —
  PyPI never re-reads metadata for an already-published version, so refreshed
  README/links require a version bump.

## [0.1.0] — 2026-06-28

### Added
- Initial release.
- `BridgrClient` (sync) with `list_agents()` / `route()` / `submit()` / `run()`.
- `Mission` (title, description, deliverables, attachments, budget, model).
- `Attachment.from_path()` helper.
- Typed dataclasses for every SSE event type emitted by Jobelix agents:
  `text`, `status`, `tool_start`, `tool_end`, `image`, `choice`, `error`, `done`.
- Sync streaming via `httpx` + custom `\n\n` SSE parser
  (tolerates `\r\n\r\n`, skips `[DONE]`, auto-promotes OpenAI-style
  `choices[0].delta.content` chunks to `TextEvent`).
- `BackendError` that surfaces JSON `{error, detail}` from the server (incl.
  unwrapping nested OpenAI error JSON for readability).
- CLI: `bridgr agents` / `bridgr route` / `bridgr submit`, with
  `--budget`, `--model`, `--attach`, `--agent-id`, `--no-route`.
- Default file persistence: intermediate images to `<output_dir>/<task_id>/intermediate/`,
  final answer + attached files to `<output_dir>/<task_id>/final/`.

[0.1.1]: https://github.com/Gusthavok/bridgr-connect/releases/tag/v0.1.1
[0.1.0]: https://github.com/Gusthavok/bridgr-connect/releases/tag/v0.1.0
