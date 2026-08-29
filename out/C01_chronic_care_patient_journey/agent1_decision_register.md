# Decision register — C01_chronic_care_patient_journey

Source: `C01_chronic_care_patient_journey.docx` (sha256 `319e6b78a2a1e36e…`)

A decision is resolved by editing its entry in `agent1_decisions.json` -
set `status` to `RESOLVED`, fill `decision` with the ruling and
`decision_provenance` with who made it - then re-run the pipeline. It is
reused from then on unless the source document or this module's
vocabulary changes, in which case it returns here as pending, with the
old ruling kept under `previous_decision` for a quick re-confirmation.

**18 PENDING_CONFIRMATION**

## 🔴 `ambiguous_piping` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `8c69b2c506c9955a`
- **affects:** Q9
- **evidence:** 'your current provider' (confidence 1.00)
- **current reading:** A question's wording was read as quoting an earlier answer, from the phrasing alone; no table states the link.
- **alternatives:** The wording is generic and does not actually depend on the earlier answer.
- **downstream impact:** Whether this question's wording depends on an earlier answer, which decides the order a respondent bot must answer in and what text it should expect on screen.
- **recommendation:** Confirm the dependency with the project owner.

## 🔴 `ambiguous_piping` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `ae7f9449c4271f16`
- **affects:** Q8
- **evidence:** 'the current provider' (confidence 1.00)
- **current reading:** A question's wording was read as quoting an earlier answer, from the phrasing alone; no table states the link.
- **alternatives:** The wording is generic and does not actually depend on the earlier answer.
- **downstream impact:** Whether this question's wording depends on an earlier answer, which decides the order a respondent bot must answer in and what text it should expect on screen.
- **recommendation:** Confirm the dependency with the project owner.

## 🔴 `ambiguous_piping` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `d04e54c7a70f655f`
- **affects:** Q21
- **evidence:** 'your choice' (confidence 1.00)
- **current reading:** A question's wording was read as quoting an earlier answer, from the phrasing alone; no table states the link.
- **alternatives:** The wording is generic and does not actually depend on the earlier answer.
- **downstream impact:** Whether this question's wording depends on an earlier answer, which decides the order a respondent bot must answer in and what text it should expect on screen.
- **recommendation:** Confirm the dependency with the project owner.

## 🔴 `ambiguous_piping` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `e4c971197a4cd683`
- **affects:** Q20
- **evidence:** 'the selected proposition' (confidence 1.00)
- **current reading:** A question's wording was read as quoting an earlier answer, from the phrasing alone; no table states the link.
- **alternatives:** The wording is generic and does not actually depend on the earlier answer.
- **downstream impact:** Whether this question's wording depends on an earlier answer, which decides the order a respondent bot must answer in and what text it should expect on screen.
- **recommendation:** Confirm the dependency with the project owner.

## 🔴 `ambiguous_routing_condition` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `71002f0c34af1fbc`
- **affects:** R19
- **evidence:** exclusive option selected with another response at Q1 or Q5  ->  ((Q1 contains 'None of these' and not Q1 set_eq ['None of these']) or (Q5 contains 'None of these' and not Q5 set_eq ['None of these']))
- **current reading:** A prose condition was rewritten into a formal one by a model, and the parser accepted the rewrite.
- **alternatives:** A different formal reading of the same sentence is possible.
- **downstream impact:** Whether this rule or guard fires for a given respondent, so which questions they see and which ending they reach.
- **recommendation:** A person familiar with the survey should confirm the reading recorded here matches what the sentence intends.

## 🔴 `ambiguous_routing_condition` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `8009e053dcf0c019`
- **affects:** Q2
- **evidence:** Q1 contains at least one brand  ->  Q1 contains_any ['Care Network A', 'Care Network B', 'Care Network C']
- **current reading:** A prose condition was rewritten into a formal one by a model, and the parser accepted the rewrite.
- **alternatives:** A different formal reading of the same sentence is possible.
- **downstream impact:** Whether this rule or guard fires for a given respondent, so which questions they see and which ending they reach.
- **recommendation:** A person familiar with the survey should confirm the reading recorded here matches what the sentence intends.

## 🔴 `ambiguous_routing_condition` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `b90d8580babbddab`
- **affects:** Q6
- **evidence:** Q5 contains any touchpoint  ->  Q5 contains_any ['Primary-care physician', 'Specialist', 'Hospital', 'Pharmacy', 'Patient portal', 'Support programme']
- **current reading:** A prose condition was rewritten into a formal one by a model, and the parser accepted the rewrite.
- **alternatives:** A different formal reading of the same sentence is possible.
- **downstream impact:** Whether this rule or guard fires for a given respondent, so which questions they see and which ending they reach.
- **recommendation:** A person familiar with the survey should confirm the reading recorded here matches what the sentence intends.

## 🔴 `ambiguous_routing_condition` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `c417f67cdc3ab8cb`
- **affects:** R20
- **evidence:** selected option at Q6 was not selected at Q5  ->  not Q5 contains Q6
- **current reading:** A prose condition was rewritten into a formal one by a model, and the parser accepted the rewrite.
- **alternatives:** A different formal reading of the same sentence is possible.
- **downstream impact:** Whether this rule or guard fires for a given respondent, so which questions they see and which ending they reach.
- **recommendation:** A person familiar with the survey should confirm the reading recorded here matches what the sentence intends.

## 🔴 `inferred_condition_partial_options` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `756d035e6abbdf43`
- **affects:** Q2, Q3, R6, R7
- **evidence:** Q1 contains at least one brand
- **current reading:** A model reading a set-valued condition named only some of a question's selectable answers as satisfying it.
- **alternatives:** The omitted answer(s) should also satisfy the condition.
- **downstream impact:** Which answers satisfy the rule; a respondent choosing an omitted answer takes a different path than intended.
- **recommendation:** Confirm whether the omitted answer(s) should count.

## 🔴 `missing_option_codes` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `70e04d836cb40d1b`
- **affects:** Q13
- **evidence:** 1=Very low; -=2; -=3; -=4; 5=Very high
- **current reading:** Some but not all of this question's options carry an answer code; the rest are left null rather than invented.
- **downstream impact:** A respondent bot told to answer by code cannot resolve the uncoded options.
- **recommendation:** Ask the project owner for the missing codes.

## 🔴 `multi_select_equality` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `5c5b9104ff079c25`
- **affects:** semantics
- **evidence:** multi_equality='set_equality', origin=derived
- **current reading:** '==' against a multi-select question's answer means the whole answer set is exactly that value - chosen, and nothing else.
- **alternatives:** '==' means the value is among those chosen, alongside others.; '==' against a multi-select is a document error and should be read as a different operator.
- **downstream impact:** Changes the outcome of every equality condition written against a multi-select question.
- **recommendation:** Confirm the intended reading with the project owner.

## 🔴 `quota_behaviour` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `0430c3303a173c36`
- **affects:** QUOTA_REGION
- **evidence:** QUOTA_REGION: hard quota on D1: North=20%, South=20%, East=20%, West=2 -> D1, 5 groups
- **current reading:** A quota's variable, groups and targets were read out of a prose sentence by a model and passed the structural checks.
- **alternatives:** The sentence intends a different variable, grouping, or split.
- **downstream impact:** Which respondents are counted against which quota, and when they are turned away.
- **recommendation:** Confirm the quota reading with the project owner.

## 🔴 `quota_behaviour` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `d1c767adabb142b1`
- **affects:** QUOTA_AGE
- **evidence:** QUOTA_AGE: soft quota on D2: 21-29=20%, 30-39=25%, 40-49=25%, 50-59=20 -> D2, 5 groups
- **current reading:** A quota's variable, groups and targets were read out of a prose sentence by a model and passed the structural checks.
- **alternatives:** The sentence intends a different variable, grouping, or split.
- **downstream impact:** Which respondents are counted against which quota, and when they are turned away.
- **recommendation:** Confirm the quota reading with the project owner.

## 🔴 `rule_precedence` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `00db7d74442cb17d`
- **affects:** semantics
- **evidence:** rule_precedence='document_order_first_match', origin=inferred
- **current reading:** The first rule in document order whose condition is true is the one that applies.
- **alternatives:** The most specific matching condition wins.; Every matching rule applies, and a later one can override an earlier one.
- **downstream impact:** Changes which destination is used whenever more than one rule's condition can be true for the same respondent.
- **recommendation:** Confirm the intended precedence with the project owner.

## 🔴 `unasked_question_semantics` — PENDING_CONFIRMATION (BLOCKING)

- **id:** `f6de93712798f5f5`
- **affects:** semantics
- **evidence:** unasked_reference='condition_false', origin=inferred
- **current reading:** A condition naming a question the respondent was never asked is treated as false, so the rule or guard does not fire.
- **alternatives:** Treat it as true instead, so the rule fires.; Treat it as an error state needing its own handling.
- **downstream impact:** Changes which questions are shown and which ending is reached whenever a condition names a question that was skipped.
- **recommendation:** Confirm the intended reading with the project owner. Once recorded here it applies to every rule in this survey and does not need asking again unless the document changes.

## ⚪ `guard_single_source` — PENDING_CONFIRMATION (NON_BLOCKING)

- **id:** `74f6f819e190cab4`
- **affects:** Q15
- **evidence:** Q3 != 'None/currently not using'
- **current reading:** The display condition is stated only in the questionnaire table, not in the routing table, and is carried from the one place that states it.
- **downstream impact:** None to this specification, which already combines both sources. Worth flagging back to whoever maintains the QRE, since a reader of only the routing table would miss it.
- **recommendation:** No action needed here; consider noting the asymmetry to the QRE author.

## ⚪ `missing_disposition_message` — PENDING_CONFIRMATION (NON_BLOCKING)

- **id:** `7a5bd08ade146ea4`
- **affects:** TERM_QUOTA_FULL
- **evidence:** TERM_QUOTA_FULL is referenced but has no message.
- **current reading:** This ending is reachable and the document never states what it shows the respondent who reaches it.
- **downstream impact:** Nothing can be asserted about what this respondent is shown. Does not change routing: the destination itself is correct.
- **recommendation:** Ask the project owner for the missing message text.

## ⚪ `randomization_anchoring` — PENDING_CONFIRMATION (NON_BLOCKING)

- **id:** `95eaab2b4ebfe62e`
- **affects:** Q1, Q5
- **evidence:** randomize=true, exclusive_option='None of these'
- **current reading:** No option is anchored; every option in the list is free to move.
- **alternatives:** An exclusive option (such as "None of these") stays anchored at the bottom, by convention.
- **downstream impact:** Where an exclusive option appears when the list is shuffled, which decides whether a displayed-order assertion is correct. Does not change which questions are asked or how they route.
- **recommendation:** Confirm anchoring convention with the project owner.
