# Fragment Retirement / Revocation Record (tacit.revocation_record)

- **Fragment id:** ____________________
- **New status:** withdrawn / superseded / rejected / retired / under_re_elicitation
- **Reason:** consent_withdrawn / superseded / rejected / drift / safety_concern / retired / re_elicitation
- **Actioned by:** ____________________
- **Superseded by (fragment id, if applicable):** ____________________
- **Note:** ____________________
- **Retention:** the record stays on the append-only chain for audit.

Revocation blocks future retrieval. The original fragment and all prior evidence remain in the
append-only CHAP evidence chain.
