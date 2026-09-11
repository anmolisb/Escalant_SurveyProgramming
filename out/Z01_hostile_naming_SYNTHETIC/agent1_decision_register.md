# Decision register — Z01_hostile_naming_SYNTHETIC

Source: `Z01_hostile_naming_SYNTHETIC.docx` (sha256 `8bdbf584606f4512…`)

A decision is resolved by editing its entry in `agent1_decisions.json` -
set `status` to `RESOLVED`, fill `decision` with the ruling and
`decision_provenance` with who made it - then re-run the pipeline. It is
reused from then on unless the source document or this module's
vocabulary changes, in which case it returns here as pending, with the
old ruling kept under `previous_decision` for a quick re-confirmation.

**1 PENDING_CONFIRMATION**

## 🔴 `mandatory_unknown` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `19a45b17f09c4cc3`
- **affects:** Z01_hostile_naming_SYNTHETIC.docx
- **evidence:** A_01, A_02, A_03
- **current reading:** Whether an answer is required is left unknown: the question carries no explicit marking and the document states no default.
- **alternatives:** Assume required.; Assume optional.
- **downstream impact:** Whether a skip-without-answering test should expect a validation error.
- **recommendation:** Confirm the default with the project owner.
