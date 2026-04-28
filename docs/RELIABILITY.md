# Reliability and Observability

## Long-running work
- Long operations must expose status, progress, and a user-visible log/status area.
- A tab switch or rerun must not silently abandon critical work; persist job state in `st.session_state` or an explicit local job artifact.
- Background work should report structured progress such as `{phase, done, total, message}`.

## Logging
- Use structured log lines for user-facing debug output: timestamp, phase, source, and concise message.
- Keep crash logs out of git. The `logs/` directory is ignored.
- Never log secrets or full credential-bearing URLs.

## Failure mode
Prefer actionable errors:
- What failed.
- Which file/key/path was involved.
- What the user can do next.
