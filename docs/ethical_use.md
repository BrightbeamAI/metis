# Ethical use (documentation)

This complements the top-level [ETHICAL_USE.md](../ETHICAL_USE.md), which is the authoritative
statement.

TacitFlow exists to make tacit-knowledge capture **governed and inspectable**, precisely because the
naïve version of this idea, quietly mining what workers know, is harmful. The design choices follow
from that: capture is consented and worker-visible; whispers are bounded and non-accusatory and never
ask a worker to justify their performance; fragments are never ground truth; Evidence-layer fragments
never reach an agent; rejected fragments are retained, not erased; and the audit chain is append-only.

The reference implementation deliberately has **no** capability to record audio, video, biometrics,
screenshots, or keystrokes, and no covert monitoring path. Local models are bounded assistants that
can never make a governance decision.

Production use of anything resembling this toolkit requires worker consultation (and where relevant
collective/union engagement), legal review, domain validation of every fragment, and organisational
governance for promotion, revocation, and review cadence. The paper is explicit that knowledge
ownership, worker compensation, and labour relations are foundational, unresolved issues, treat them
as such.
