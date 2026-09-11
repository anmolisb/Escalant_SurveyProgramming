# Decision register — S02_e_commerce_checkout_experience

Source: `S02_e_commerce_checkout_experience.docx` (sha256 `f02204a21d2522bc…`)

A decision is resolved by editing its entry in `agent1_decisions.json` -
set `status` to `RESOLVED`, fill `decision` with the ruling and
`decision_provenance` with who made it - then re-run the pipeline. It is
reused from then on unless the source document or this module's
vocabulary changes, in which case it returns here as pending, with the
old ruling kept under `previous_decision` for a quick re-confirmation.

**2 PENDING_CONFIRMATION**

## 🔴 `rule_precedence` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `ef0c285fb8451312`
- **affects:** semantics
- **evidence:** rule_precedence='document_order_first_match', origin=inferred
- **current reading:** The first rule in document order whose condition is true is the one that applies.
- **alternatives:** The most specific matching condition wins.; Every matching rule applies, and a later one can override an earlier one.
- **downstream impact:** Changes which destination is used whenever more than one rule's condition can be true for the same respondent.
- **recommendation:** Confirm the intended precedence with the project owner.

## 🔴 `unasked_question_semantics` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `4d7ebc8b83731dea`
- **affects:** semantics
- **evidence:** unasked_reference='condition_false', origin=inferred
- **current reading:** A condition naming a question the respondent was never asked is treated as false, so the rule or guard does not fire.
- **alternatives:** Treat it as true instead, so the rule fires.; Treat it as an error state needing its own handling.
- **downstream impact:** Changes which questions are shown and which ending is reached whenever a condition names a question that was skipped.
- **recommendation:** Confirm the intended reading with the project owner. Once recorded here it applies to every rule in this survey and does not need asking again unless the document changes.
