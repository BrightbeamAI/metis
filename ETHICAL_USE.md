# Ethical Use

Metis is a research and practitioner reference toolkit. It captures fragments of
human practice. That makes its misuse a real risk. Read this before you deploy it.

## Hard constraints (enforced by the reference implementation)

- **No covert surveillance.** Metis does not record audio, video, biometrics,
  screenshots, keystrokes, or any hidden behavioural data, and the reference
  implementation provides no path to do so. Capture is consented, narrow, and
  visible to the worker.
- **Fragments are not ground truth.** A captured fragment is a partial, situated,
  contestable representation of practice. It is never treated as fact.
- **Evidence-layer fragments are not operational advice.** They cannot be retrieved
  for decision support and cannot become agent-visible tacit memory.
- **Agents and models cannot promote their own fragments.** Endogenous fragments
  start in the Evidence layer and require Mission Group review.
- **Local model outputs are suggestions only.** A Gemma/Ollama model may draft a
  whisper, structure a candidate, or summarise a confirmation. It can never promote,
  validate, retrieve, authorise, or revoke a fragment.
- **Rejected fragments are retained, never deleted.** The audit chain is append-only.
  Rejection is a governance signal, not an erasure.

## Worker protections

- Workers must be able to see records associated with their contribution
  (`consent.worker_visible_record`).
- Workers and reviewers can challenge, correct, withdraw, supersede, or request
  re-elicitation of a fragment. These are first-class auditable events.
- Withdrawing consent blocks future retrieval unless retention is explicitly
  audit-only.
- Whisper prompts are bounded and non-accusatory. They never ask a worker to justify
  their personal performance.

## Before any production use

Production use of anything resembling this toolkit requires, at minimum:

- worker consultation and (where relevant) collective/union engagement,
- legal review (employment, privacy/data-protection, sector regulation),
- domain validation of every fragment by qualified reviewers,
- organisational governance for promotion, revocation, and review cadence.

Metis is **not** a production quality-management system, a worker-monitoring
platform, or a tool for covertly extracting expertise. If you cannot meet the
constraints above, do not deploy it.
