# Decision register — S03_employee_training_feedback

Source: `S03_employee_training_feedback.docx` (sha256 `dd283ca690fd6496…`)

A decision is resolved by editing its entry in `agent1_decisions.json` -
set `status` to `RESOLVED`, fill `decision` with the ruling and
`decision_provenance` with who made it - then re-run the pipeline. It is
reused from then on unless the source document or this module's
vocabulary changes, in which case it returns here as pending, with the
old ruling kept under `previous_decision` for a quick re-confirmation.

**5 PENDING_CONFIRMATION**

## 🔴 `ambiguous_piping` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `7b1a23554cfefd51`
- **affects:** Q1
- **evidence:** 'this training session' (confidence 1.00)
- **current reading:** A question's wording was read as quoting an earlier answer, from the phrasing alone; no table states the link.
- **alternatives:** The wording is generic and does not actually depend on the earlier answer.
- **downstream impact:** Whether this question's wording depends on an earlier answer, which decides the order a respondent bot must answer in and what text it should expect on screen.
- **recommendation:** Confirm the dependency with the project owner.

## 🔴 `ambiguous_piping` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `9c178a37676a4866`
- **affects:** Q2
- **evidence:** 'the training session' (confidence 1.00)
- **current reading:** A question's wording was read as quoting an earlier answer, from the phrasing alone; no table states the link.
- **alternatives:** The wording is generic and does not actually depend on the earlier answer.
- **downstream impact:** Whether this question's wording depends on an earlier answer, which decides the order a respondent bot must answer in and what text it should expect on screen.
- **recommendation:** Confirm the dependency with the project owner.

## 🔴 `ambiguous_piping` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `cb654cd9a6e39431`
- **affects:** Q6
- **evidence:** 'the main problem' (confidence 1.00)
- **current reading:** A question's wording was read as quoting an earlier answer, from the phrasing alone; no table states the link.
- **alternatives:** The wording is generic and does not actually depend on the earlier answer.
- **downstream impact:** Whether this question's wording depends on an earlier answer, which decides the order a respondent bot must answer in and what text it should expect on screen.
- **recommendation:** Confirm the dependency with the project owner.

## 🔴 `rule_precedence` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `44383c449911f820`
- **affects:** semantics
- **evidence:** rule_precedence='document_order_first_match', origin=inferred
- **current reading:** The first rule in document order whose condition is true is the one that applies.
- **alternatives:** The most specific matching condition wins.; Every matching rule applies, and a later one can override an earlier one.
- **downstream impact:** Changes which destination is used whenever more than one rule's condition can be true for the same respondent.
- **recommendation:** Confirm the intended precedence with the project owner.

## 🔴 `unasked_question_semantics` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `3f92c357c8ca3afb`
- **affects:** semantics
- **evidence:** unasked_reference='condition_false', origin=inferred
- **current reading:** A condition naming a question the respondent was never asked is treated as false, so the rule or guard does not fire.
- **alternatives:** Treat it as true instead, so the rule fires.; Treat it as an error state needing its own handling.
- **downstream impact:** Changes which questions are shown and which ending is reached whenever a condition names a question that was skipped.
- **recommendation:** Confirm the intended reading with the project owner. Once recorded here it applies to every rule in this survey and does not need asking again unless the document changes.
