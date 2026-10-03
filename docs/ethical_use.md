# Ethical use (documentation)

This complements the top-level [ETHICAL_USE.md](../ETHICAL_USE.md), which is the authoritative
statement.

Metis exists to make tacit-knowledge capture **governed and inspectable**, because quietly mining
what workers know is harmful. The design choices follow from that:

- capture is consented and visible to the worker, who answers in their own words and states consent
  with the answer;
- whispers are short, respectful, and rationed per worker, and they never ask a worker to justify
  their performance;
- fragments are partial, situated claims that workers and reviewers can contest;
- Evidence-layer fragments stay with reviewers, out of agents' reach;
- by default a quorum of two named reviewers grants authority, and only the contributing worker
  can withdraw a fragment's consent;
- rejected fragments stay on the record, and the audit chain is append-only.

The reference implementation has **no** capability to record audio, video, biometrics, screenshots,
or keystrokes, and no covert monitoring path. Local models draft wording; people make every
governance decision.

Production use of anything resembling this toolkit requires worker consultation (and where relevant
collective/union engagement), legal review, domain validation of every fragment, and organisational
governance for promotion, revocation, and review cadence. The paper treats knowledge ownership,
worker compensation, and labour relations as foundational, unresolved issues; deployments should do
the same.
