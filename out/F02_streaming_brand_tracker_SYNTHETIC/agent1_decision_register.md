# Decision register — F02_streaming_brand_tracker_SYNTHETIC

Source: `F02_streaming_brand_tracker_SYNTHETIC.docx` (sha256 `c49bd90b63f0019e…`)

A decision is resolved by editing its entry in `agent1_decisions.json` -
set `status` to `RESOLVED`, fill `decision` with the ruling and
`decision_provenance` with who made it - then re-run the pipeline. It is
reused from then on unless the source document or this module's
vocabulary changes, in which case it returns here as pending, with the
old ruling kept under `previous_decision` for a quick re-confirmation.

No decisions raised for this survey.