# Decision register — F01_snack_bar_concept_test_SYNTHETIC

Source: `F01_snack_bar_concept_test_SYNTHETIC.docx` (sha256 `12b02e04b203b53d…`)

A decision is resolved by editing its entry in `agent1_decisions.json` -
set `status` to `RESOLVED`, fill `decision` with the ruling and
`decision_provenance` with who made it - then re-run the pipeline. It is
reused from then on unless the source document or this module's
vocabulary changes, in which case it returns here as pending, with the
old ruling kept under `previous_decision` for a quick re-confirmation.

**2 PENDING_CONFIRMATION**

## 🔴 `mandatory_unknown` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `89356eb6c770f97d`
- **affects:** F01_snack_bar_concept_test_SYNTHETIC.docx
- **evidence:** , , , , , , 
- **current reading:** Whether an answer is required is left unknown: the question carries no explicit marking and the document states no default.
- **alternatives:** Assume required.; Assume optional.
- **downstream impact:** Whether a skip-without-answering test should expect a validation error.
- **recommendation:** Confirm the default with the project owner.

## 🔴 `rule_precedence` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `5d5d04a61c182f21`
- **affects:** semantics
- **evidence:** rule_precedence='document_order_first_match', origin=inferred
- **current reading:** The first rule in document order whose condition is true is the one that applies.
- **alternatives:** The most specific matching condition wins.; Every matching rule applies, and a later one can override an earlier one.
- **downstream impact:** Changes which destination is used whenever more than one rule's condition can be true for the same respondent.
- **recommendation:** Confirm the intended precedence with the project owner.
