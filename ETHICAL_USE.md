# Ethical Use

Metis is a research and practitioner reference toolkit. It captures fragments of
human practice. That makes its misuse a real risk. Read this before you deploy it.

## Hard constraints (enforced by the reference implementation)

- **No covert surveillance.** Metis records no audio, video, biometrics, screenshots,
  keystrokes, or hidden behavioural data, and the reference implementation provides no path
  to do so. Capture is consented, narrow, and visible to the worker.
- **Fragments are partial and contestable.** A captured fragment is a situated account of
  practice, held as a claim that people can check, correct, and withdraw.
- **Evidence-layer fragments serve learning and review only.** They stay out of decision
  support and out of agent-visible tacit memory.
- **Only people promote.** Agents and models cannot promote fragments, their own included.
  Endogenous fragments start in the Evidence layer and require Mission Group review.
- **Local model outputs are drafts.** A Gemma model running on Ollama may draft a whisper,
  structure a candidate, or summarise a confirmation. Promotion, validation, retrieval,
  authorisation, and revocation stay with people and the retrieval gate.
- **Rejected fragments stay on the record.** The audit chain is append-only, so a rejection is
  recorded alongside the fragment it concerns.

## Worker protections

- Workers must be able to see records associated with their contribution
  (`consent.worker_visible_record`).
- Workers and reviewers can challenge, correct, supersede, or request re-elicitation of a
  fragment, and the contributing worker can withdraw it. Each action is an auditable event that
  opens a Mission Group task or, for a withdrawal, revokes the fragment.
- Withdrawing consent blocks future retrieval at once; the fragment's record stays on the chain
  for audit.
- Whisper prompts are short and non-accusatory. They never ask a worker to justify their
  personal performance.
- Whispers are rationed. A worker receives at most five in eight hours by default
  (`WhisperBudget`); beyond that, capture is deferred and the deferral recorded.
- Workers speak for themselves. Only the worker a whisper was addressed to may answer it,
  and an agent can never answer, confirm, or contest on a worker's behalf. Consent is stated
  with the answer: when a worker declines, Metis records the answer and stores no fragment.
- Granting authority is collective. With the default policy, promotion needs two named
  Mission Group reviewers, and no agent or model can promote a fragment.

## Before any production use

Production use of anything resembling this toolkit requires, at minimum:

- worker consultation and (where relevant) collective/union engagement,
- legal review (employment, privacy/data-protection, sector regulation),
- domain validation of every fragment by qualified reviewers,
- organisational governance for promotion, revocation, and review cadence.

Metis is a reference toolkit for consented, governed capture in research and pilots. Do not use
it as a worker-monitoring platform or to extract expertise covertly, and do not deploy it where
you cannot meet the constraints above.
