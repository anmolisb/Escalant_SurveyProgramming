# Decision register — M01_mobile_network_experience

Source: `M01_mobile_network_experience.docx` (sha256 `1be6ec051fbc9146…`)

A decision is resolved by editing its entry in `agent1_decisions.json` -
set `status` to `RESOLVED`, fill `decision` with the ruling and
`decision_provenance` with who made it - then re-run the pipeline. It is
reused from then on unless the source document or this module's
vocabulary changes, in which case it returns here as pending, with the
old ruling kept under `previous_decision` for a quick re-confirmation.

**11 PENDING_CONFIRMATION**

## 🔴 `ambiguous_piping` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `1c2525515fb410ef`
- **affects:** Q3, Q5
- **evidence:** 'the experience' (confidence 0.99)
- **current reading:** A question's wording was read as quoting an earlier answer, from the phrasing alone; no table states the link.
- **alternatives:** The wording is generic and does not actually depend on the earlier answer.
- **downstream impact:** Whether this question's wording depends on an earlier answer, which decides the order a respondent bot must answer in and what text it should expect on screen.
- **recommendation:** Confirm the dependency with the project owner.

## 🔴 `ambiguous_piping` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `479ba5baeee26b97`
- **affects:** Q9
- **evidence:** 'the main problem' (confidence 0.99)
- **current reading:** A question's wording was read as quoting an earlier answer, from the phrasing alone; no table states the link.
- **alternatives:** The wording is generic and does not actually depend on the earlier answer.
- **downstream impact:** Whether this question's wording depends on an earlier answer, which decides the order a respondent bot must answer in and what text it should expect on screen.
- **recommendation:** Confirm the dependency with the project owner.

## 🔴 `ambiguous_piping` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `c6a39b1ce587b8cd`
- **affects:** Q2
- **evidence:** 'the most recent experience' (confidence 0.99)
- **current reading:** A question's wording was read as quoting an earlier answer, from the phrasing alone; no table states the link.
- **alternatives:** The wording is generic and does not actually depend on the earlier answer.
- **downstream impact:** Whether this question's wording depends on an earlier answer, which decides the order a respondent bot must answer in and what text it should expect on screen.
- **recommendation:** Confirm the dependency with the project owner.

## 🔴 `ambiguous_routing_condition` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `c33199c713b4aaab`
- **affects:** Q8
- **evidence:** Q7 contains any problem  ->  Q7 contains_any ['Dropped calls', 'Slow data', 'Unexpected charge', 'Coverage gap', 'Support delay']
- **current reading:** A prose condition was rewritten into a formal one by a model, and the parser accepted the rewrite.
- **alternatives:** A different formal reading of the same sentence is possible.
- **downstream impact:** Whether this rule or guard fires for a given respondent, so which questions they see and which ending they reach.
- **recommendation:** A person familiar with the survey should confirm the reading recorded here matches what the sentence intends.

## 🔴 `ambiguous_routing_condition` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `d407415a87012399`
- **affects:** R9
- **evidence:** Q7 includes 'None of these' plus another option  ->  (Q7 contains 'None of these' and not Q7 set_eq ['None of these'])
- **current reading:** A prose condition was rewritten into a formal one by a model, and the parser accepted the rewrite.
- **alternatives:** A different formal reading of the same sentence is possible.
- **downstream impact:** Whether this rule or guard fires for a given respondent, so which questions they see and which ending they reach.
- **recommendation:** A person familiar with the survey should confirm the reading recorded here matches what the sentence intends.

## 🔴 `multi_select_equality` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `8f44c584fbb7802c`
- **affects:** semantics
- **evidence:** multi_equality='set_equality', origin=derived
- **current reading:** '==' against a multi-select question's answer means the whole answer set is exactly that value - chosen, and nothing else.
- **alternatives:** '==' means the value is among those chosen, alongside others.; '==' against a multi-select is a document error and should be read as a different operator.
- **downstream impact:** Changes the outcome of every equality condition written against a multi-select question.
- **recommendation:** Confirm the intended reading with the project owner.

## 🔴 `quota_behaviour` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `89323997a884fd7e`
- **affects:** QUOTA_REGION
- **evidence:** QUOTA_REGION: soft quota on D1: North=20%, South=20%, East=20%, West=2 -> D1, 5 groups
- **current reading:** A quota's variable, groups and targets were read out of a prose sentence by a model and passed the structural checks.
- **alternatives:** The sentence intends a different variable, grouping, or split.
- **downstream impact:** Which respondents are counted against which quota, and when they are turned away.
- **recommendation:** Confirm the quota reading with the project owner.

## 🔴 `rule_precedence` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `ee893480c79dbb80`
- **affects:** semantics
- **evidence:** rule_precedence='document_order_first_match', origin=inferred
- **current reading:** The first rule in document order whose condition is true is the one that applies.
- **alternatives:** The most specific matching condition wins.; Every matching rule applies, and a later one can override an earlier one.
- **downstream impact:** Changes which destination is used whenever more than one rule's condition can be true for the same respondent.
- **recommendation:** Confirm the intended precedence with the project owner.

## 🔴 `unasked_question_semantics` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `fd8266d76c7306e2`
- **affects:** semantics
- **evidence:** unasked_reference='condition_false', origin=inferred
- **current reading:** A condition naming a question the respondent was never asked is treated as false, so the rule or guard does not fire.
- **alternatives:** Treat it as true instead, so the rule fires.; Treat it as an error state needing its own handling.
- **downstream impact:** Changes which questions are shown and which ending is reached whenever a condition names a question that was skipped.
- **recommendation:** Confirm the intended reading with the project owner. Once recorded here it applies to every rule in this survey and does not need asking again unless the document changes.

## ⚪ `missing_disposition_message` — PENDING_CONFIRMATION (NON_BLOCKING)

- **id:** `5fb5a46ac29c8c95`
- **affects:** TERM_QUOTA_FULL
- **evidence:** TERM_QUOTA_FULL is referenced but has no message.
- **current reading:** This ending is reachable and the document never states what it shows the respondent who reaches it.
- **downstream impact:** Nothing can be asserted about what this respondent is shown. Does not change routing: the destination itself is correct.
- **recommendation:** Ask the project owner for the missing message text.

## ⚪ `randomization_anchoring` — PENDING_CONFIRMATION (NON_BLOCKING)

- **id:** `7ae3cdfe88a408c6`
- **affects:** Q7
- **evidence:** randomize=true, exclusive_option='None of these'
- **current reading:** No option is anchored; every option in the list is free to move.
- **alternatives:** An exclusive option (such as "None of these") stays anchored at the bottom, by convention.
- **downstream impact:** Where an exclusive option appears when the list is shuffled, which decides whether a displayed-order assertion is correct. Does not change which questions are asked or how they route.
- **recommendation:** Confirm anchoring convention with the project owner.
