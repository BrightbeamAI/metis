# Security

TacitFlow is a local-first reference toolkit. It does not require, and by default does
not contact, any cloud service or external model API.

## Reporting a vulnerability

Please open a private security advisory or email the maintainers rather than filing a
public issue for anything that could expose worker data or break the audit chain.

## Security-relevant design notes

- **Append-only evidence.** TacitFlow records every governance action as a
  CHAP-compatible evidence entry in a hash-linked, optionally Ed25519-signed chain.
  History is never rewritten; corrections and revocations are appended.
- **Signing.** The CHAP adapter signs envelopes with Ed25519 over the RFC 8785 (JCS)
  canonicalisation of the envelope with `evidence.sig` removed, exactly as the CHAP
  specification requires. Test/demo runs use deterministic keys; production deployments
  should manage real participant keys.
- **No secret material in fragments.** Do not place credentials, tokens, or personal
  identifiers in fragment content. Provenance references participants by URI, not by
  personal data.
- **Local models.** The Ollama client talks only to a local model runtime
  (default `http://localhost:11434`). It fails gracefully (and deterministically in
  tests) when no server is present.

## Threat model boundaries

TacitFlow governs how tacit fragments are captured, validated, and retrieved. It does
not provide authentication, authorisation, or transport security for a multi-tenant
deployment; those are the responsibility of the surrounding CHAP Coordinator and host
environment.
