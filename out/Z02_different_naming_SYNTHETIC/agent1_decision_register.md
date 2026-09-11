# Decision register — Z02_different_naming_SYNTHETIC

Source: `Z02_different_naming_SYNTHETIC.docx` (sha256 `67c042bd3b112118…`)

A decision is resolved by editing its entry in `agent1_decisions.json` -
set `status` to `RESOLVED`, fill `decision` with the ruling and
`decision_provenance` with who made it - then re-run the pipeline. It is
reused from then on unless the source document or this module's
vocabulary changes, in which case it returns here as pending, with the
old ruling kept under `previous_decision` for a quick re-confirmation.

No decisions raised for this survey.