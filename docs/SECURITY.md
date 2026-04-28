# Security

## Secrets
- Store local secrets in `.streamlit/secrets.toml` only; it must never be committed.
- Use `.streamlit/secrets_dummy.toml` for examples.
- Do not print R2 access keys, secret keys, app passwords, or signed URLs.

## User data
Videos, audio, generated MAT/JSON files, frame packs, and logs are user data. They are not source files and must stay out of git.

## Network calls
Network-capable helpers must be isolated behind storage/client classes so tests can use fakes.
