# Agent 1 fix tracker

One row per issue, ticked off as the fix lands, with a short note on what
changed and why it was needed.

Phases 1 to 3 came out of the C02 output review. Phase 4 came out of a later
question asked on C01 and S01 — not "is the specification complete?" but "could
the graph builder and Agent 3 actually work from it?" — so the tracker is no
longer C02-only.

**How to read this.** `[ ]` not started, `[~]` in progress, `[x]` done,
`[-]` deliberately deferred (with a reason). Nothing is ticked until the change
is actually in the code.

---

## Decisions this work is built on

| # | Decision | Taken by |
|---|---|---|
| 1 | Fix the `SP_Anmol_1708` branch, not `main`. It is the code that produced the five JSONs. | Sanskar, 23 Aug 2026 |
| 2 | Keep `condition_expression`, but mark it as unverified interpretation. Real structured conditions get built in Part 2, not Part 1. | Sanskar, 23 Aug 2026 |
| 3 | New `stage4_*.json` files are allowed, following the existing one-file-per-target pattern. No new folders. | Sanskar, 23 Aug 2026 |
| 4 | The NetworkX graph is a second output of Part 2, generated from the Canonical Survey Specification. The specification stays the source of truth. | Proposed, no objection raised |
| 5 | No existing block of code is removed without asking first. | Standing constraint |

---

## Rules from CLAUDE.md that shape these fixes

These came out of reading `CLAUDE.md` on `main` before starting. Three of them
changed a recommendation made in the earlier planning document.

| Rule | Where | Effect on the fixes |
|---|---|---|
| Part 1 must not decide semantic operators. Interpretation belongs to Part 2. | §7.1, §19 | Conditions are **not** rebuilt in Stage 4. `condition_expression` stays, marked unverified. The real work moves to Part 2. |
| Do not invent missing response codes. Use `null`, not a fabricated code. | §13 | **Changed recommendation.** No derived response codes. Options get a stable `option_id` for identity instead; LimeSurvey codes become Agent 2's job. |
| Never present an inference as if the QRE stated it. Mark every field `extracted` / `derived` / `inferred` / `unknown` / `ambiguous`. | §14 | Every value we work out rather than read carries its origin. |
| Do not hard-code fixed section names. | §9, §10 | **Changed recommendation.** The quota fix does not add a name to a fixed list. The target list becomes configurable and every target becomes optional. |
| Never silently discard content that cannot be classified. | §16 | Anything the pipeline does not understand is kept and surfaced, not dropped. |
| Provenance is required. | §15 | Source references are carried through the stages. |

---

## Phase 1 — Part 1 fixes (Stages 1 to 4)

Things the extractor can put right without interpreting survey meaning.

| ✓ | ID | Issue in plain language | What changed | Why it was needed |
|---|---|---|---|---|
| [x] | P1-01 | Stage 2 threw away every heading that was not one of the four targets, content and all. | Added `UnclassifiedSection` to `models.py` and a new `unclassified` list on `Stage2Blocks`. Stage 2 now keeps every unmatched heading with its content, order and level. Rides along inside the existing `stage2_blocks.json` — no new file. Nothing removed. | This, not the enum, was the real cause of the silent quota loss: unmatched sections were never carried forward at all. Keeping everything satisfies CLAUDE.md §16 and works for any QRE, rather than only for section names we happened to list. Verified on four fixtures: C02 now keeps Study specification, Quota controls and Programming and QA requirements; Z02 keeps five sections including two that match no target at all. |
| [x] | P1-02 | Quota rules are missing entirely (A1). | `Quota controls` is now a target. Its prose is transcribed line by line and emitted to a new `stage4_quotas.json` as `ExtractedStatement` records, each with a code where the line has one and a source reference. Statements are kept whole: `hard quota on D1: North=20%, ...` is captured as written, not split into cells. | Quota-full screenout is real survey behaviour that was invisible to everything downstream. Splitting the percentages into structured cells is interpretation and belongs to Part 2 (CLAUDE.md §19), so Part 1 stops at making the statement exist and addressable. |
| [x] | P1-03 | The sixth ending `TERM_QUOTA_FULL` is missing (A2). | Now captured, inside the third quota statement: "Quota-full respondents terminate at TERM_QUOTA_FULL before the next substantive question." | The ending is named in the QRE but has no message text anywhere, so it cannot be invented. Capturing the sentence that mentions it is the honest half of the fix; the missing message stays an open question. |
| [x] | P1-04 | Study details are missing: objective, audience, mode, length (A3). | `Study specification` is now a target, emitted to `stage4_study.json`. Five statements captured for C02, each with its label split from its value: Business objective, Target population, Mode, Estimated length, General instruction. | LimeSurvey needs survey-level settings and reports need to name the study. The label/value split is punctuation, not interpretation, so it is safe to do in Part 1. |
| [x] | P1-05 | The six programming and QA instructions are missing (A4). | `Programming and QA requirements` is now a target, emitted to `stage4_programming.json`. All six statements captured for C02. | They are direct requirements on the respondent bot, including capturing the displayed random order and recording expected versus observed destinations. They were being discarded. |
| [x] | P1-06 | The two general instructions are missing (A5). | Captured as the fifth study statement, labelled General instruction. | One explains why questions are mandatory; the other, "Do not infer unstated routing", limits how much any later stage may assume, so it needs to be visible rather than living only in the Word file. |
| [x] | P1-07 | Nothing recorded where each fact came from (A6). | Added a `SourceReference` model. Stage 3 now emits `row_sources`, a list index-aligned with `rows`, and Stage 4 copies the matching entry onto every `Question`, `RoutingRule`, `AcceptanceScenario` and `CompletionMessage`. Table rows carry the block position and row number; prose rows are matched to the exact paragraph containing them. | Required by CLAUDE.md §15, and every later fix depends on it: `extracted` versus `derived` markers are meaningless without being able to point at the source. A parallel list was used rather than changing the shape of `rows`, because Stage 5's audit needs Stage 3 to stay row-aligned with Stage 4, and every Stage 4 call site reads rows as plain dicts. |
| [x] | P1-08 | Options had no stable identity (C1, revised). | Added `option_id` to `Option`, filled in by Stage 4 from the question id and the option's position: `Q1-O3` for an answer, `Q9-R2` for a matrix row. `code` is untouched and still null wherever the QRE gave none. Left null when the question itself has no id, since a handle like `-O1` would collide across every unidentified question. | Matching options on their label text breaks the moment a word or a space changes, and four of C02's questions repeat the same brand labels. A position-derived handle is stated by the document rather than invented, so it does not breach CLAUDE.md §13 the way a made-up response code would. LimeSurvey response codes remain Agent 2's job. Verified unique across all 15 real fixtures: 126 ids on C02, none missing anywhere. |
| [x] | P1-09 | Numeric scales were stored only as text (C3). | Added `numeric_value` to `Option`, read from the code where that is a number and otherwise from the label. The question's own `min_value` and `max_value` are deliberately left alone, because those come from an explicit `Validate:` instruction and must stay distinguishable from a derived reading (CLAUDE.md §14). | Q8's 0-to-10 scale was eleven pieces of text with no order, so its endpoints could not be found without parsing labels downstream. Now C02 reads: Q7 gives 1 to 5 from its codes, Q8 gives 0 to 10 from its labels, and Q13 recovers a full 1-to-5 ordering despite only its endpoints carrying codes. Age bands `21-29` and `60+` and every brand name correctly stay null. Across the corpus 415 of 1177 options take a value, and every one is backed by a number the QRE actually wrote. |
| [x] | P1-10 | Settings were squashed into text, and a whole number stored as a decimal (C5, C6). | `other_attributes` now holds real JSON types instead of every value being run through `json.dumps`. `sum_to`, `min_value` and `max_value` keep the number as the QRE wrote it rather than being forced to float. | Q9's scale arrived as a string that merely looked like a list, and its `require_each_row` as the word "true" — both had to be parsed a second time downstream, and one day would have been parsed wrongly. Q18's constant sum came back as 100.0, implying a precision the QRE never claimed and which LimeSurvey would round back. Now Q9 gives a real list and a real boolean, and Q18 serialises as `100`. Corpus-wide the only values landing in `other_attributes` are `scale` as a list and `require_each_row` as a boolean, and no whole number is stored as a float anywhere. |
| [x] | P1-11 | Files had no header: no version, survey name, or source document (D1). | Every artifact is now written inside an `ArtifactEnvelope` carrying the schema version, artifact name, stage number, survey id, the source document with its SHA-256 and size, a UTC timestamp and a record count. The three loaders unwrap it, and fall back to reading the payload directly when a file has no `schema_version` — so the artifacts already committed under `out/` still load unchanged. | A bare array cannot say which QRE it came from, which code version wrote it, or when. The digest is the part that earns its place: a filename cannot tell you the client sent a revised document, and a stale artifact sitting beside a changed QRE is exactly the error nobody spots by eye. Verified on all 19 artifacts for C02; the recorded digest matches `sha256sum` on the file. Where the document is not on disk, as when re-running a later stage elsewhere, the digest is recorded as null rather than invented. |
| [x] | P1-12 | Question order was only implied by list position (D2). | Added `seq` to `Question`, counting from 1 in document order, filled in by Stage 4 from the row's position. | Order is real information — it decides the default next question — and it should not depend on nobody ever re-sorting a list. C02 runs S1-S4, Q1-Q21, D1-D4, Q22-Q23; sorted by id that becomes D1 first, S4 last and Q10 before Q2, which is a different survey. It is deliberately not the same as `source_reference.row_index`, which restarts at zero for each table and so cannot order a questionnaire split across two of them. Verified contiguous across all 15 real fixtures, and on every one of them id order differs from document order — this was never specific to C02. |
| [x] | P1-13 | Nothing recorded what a scenario actually refers to (E2, E3). | Added `input_question_ids`, the questions a scenario supplies answers for, and `referenced_ids`, every identifier appearing in its expected outcome. Both read from the scenario's own cells. | **Scope corrected while doing this.** The row originally said Part 1 would mark scenarios complete or partial. Deciding T6 is partial means knowing which questions precede Q18 and whether they are mandatory, which is reasoning about survey structure and belongs to Part 2. It would also have forced `parse_scenarios` to wait on the questionnaire task, against the README's "scenarios and messages never wait", serialising it behind roughly 31 model calls. So Part 1 records what each scenario names and Stage 5 resolves it, since Stage 5 already holds every artifact. The signal is still visible: T6 answers only Q18 and T7 only Q5 and Q6, while T1 to T5 all start at S1. T3 is now mechanically checkable too — it names Q2, Q3, Q7, Q8, Q9 as hidden but not Q15, which is the defect itself. |
| [x] | P1-14 | Review flags could not point at a rule, carried no severity and no confidence (F1, F2, F3). | Added `severity` (BLOCKING, WARNING, INFO) and `target`, a typed `{kind, id}` reference, to `ReviewFlag`. All thirteen places that raise a flag now set both. The run summary leads with the blocking count and sorts blocking flags first. | **No type change was needed after all.** `TargetHeading` is declared `(str, Enum)`, and `target_heading` is genuinely useful — it says which section a flag concerns. The real gap was narrower: nothing could name the specific item, so "R18" ended up in `candidate_heading`, a field meant for heading-match candidates. Adding a typed target fixes that without touching an existing field, so no consumer breaks and old flags still load, reading as WARNING with no target. |
| [x] | P1-15 | `condition_expression` looked authoritative but is not (B group). | Added an `Origin` vocabulary — extracted, derived, inferred, unknown, ambiguous — and a `condition_expression_origin` field set to `inferred` whenever a model produced an expression. The field's own docstring now states plainly that it must not be parsed, and names the C02 failures: R5 changed meaning, R19 became a condition that can never be true, R18 came back empty, and the same operator appears in three syntaxes. | Decision 2 keeps the field. Keeping it unlabelled was the danger: it reads as authoritative and invites exactly the trust it has not earned. Marking it inferred satisfies CLAUDE.md §14, which forbids presenting an inference as something the QRE stated. `condition_raw` stays the trustworthy field, and Part 2 builds the real condition from that. |

---

## Phase 2 — Stage 5, the extraction quality check

The README already designs this stage. It audits Stage 4 against Stage 3 and
Stage 2 rather than re-extracting. These checks live there.

| ✓ | ID | Issue in plain language | What changed | Why it was needed |
|---|---|---|---|---|
| [x] | P2-01 | Nothing noticed when a whole section of the document was skipped (F4). | `check_source_coverage` accounts for every block Stage 1 read. A block is accounted for if it sits under a matched heading or under an unmatched one that Stage 2 now keeps. Anything else is reported. | This is the failure that hurt C02 worst, and it produced no flag at all. It needs no model: Stage 1 already lists every block. It also found something new — three blocks of front matter above the first heading reach no stage at all, on every fixture. |
| [x] | P2-02 | `parse_errors` was empty everywhere, including on the faulty T3 (F5). | `check_row_accounting` compares Stage 3's transcribed rows against Stage 4's objects per section and scores each one against the README's thresholds. The audit lists `checks_run` by name, and scenario `parse_errors` are surfaced as blocking findings. | An empty list used to mean "nothing was looked at" while reading as "nothing is wrong". Naming the checks that ran makes an empty result mean something. A matched section that transcribes nothing now scores zero rather than passing vacuously. |
| [x] | P2-03 | Acceptance scenarios were never checked against the rules (E1). | `check_condition_consistency` groups questions by their display condition text and reports any scenario that names some of a group but not the rest. **Not a full replay** — see why in the note. | A real replay means evaluating "Q3 != 'None/currently not using'", which means parsing it, which is Part 2's job. Comparing condition text for equality needs no evaluator and catches the same defect: on the committed C02 artifacts it reports that T3 names Q7, Q8 and Q9 but not Q15, though all four carry an identical condition. That is the defect found by hand in the original review, now found mechanically. |
| [x] | P2-05 | Not on the original list: nothing checked that identifiers point at things that exist. | `check_reference_integrity` resolves every routing destination, every identifier a scenario expects, and every code named in a prose statement against the questions and endings that exist. | Added because the material was already there once P1-13 recorded what scenarios name. It surfaces two real things on C02: `CURRENT_QUESTION` is a destination that names neither a question nor an ending, and `TERM_QUOTA_FULL` is named by a quota statement but defined nowhere — which is issue A2 found automatically. |
| [x] | P2-04 | Q2's piped options had no validation rule while Q6's did (D9). | `check_piping_symmetry` compares questions carrying a piping instruction and reports any that no rule guards while a peer is guarded. | The asymmetry is in the QRE itself, so it is surfaced rather than evened out. On C02 it reports that Q2's piping would never be tested, while Q6 has R20. |

---

## Phase 3 — Part 2, the semantic interpreter

Interpretation work. CLAUDE.md puts all of this after Part 1 has a stable
extraction contract, which it now has. All eight items have landed; Phase 4
below covers what came after them.

| ✓ | ID | Issue in plain language | Why it waits for Part 2 |
|---|---|---|---|
| [x] | P3-01 | Rule R5 changed meaning; R19 can never fire; three different syntaxes; R20 compares the wrong types (B1, B2, B3, B5). | Done. The typed condition tree is built from condition_raw, never from the model's expression, and operators come from a closed set so the three-syntax problem cannot recur. 22 of the 28 forms parse with no model at all. The six that are genuine prose now go to a model which rewrites them into the same grammar, and the parser is what decides whether to accept - so the model can only propose what the QRE could have written formally itself. All 20 of C02's rules now read. R5 keeps set equality, R18 is read where the model had returned nothing, and R19 comes out satisfiable and correct at last: None of these was chosen but not on its own, rather than the impossible condition Stage 4 produced. |
| [x] | P3-02 | Q13's answer codes are only half filled in (C2). | Done. _check_partial_codes reports any question whose options are only partly coded. On C02 it reports Q13, coded on 2 of 5. The missing codes are not filled in, because inventing a response code is forbidden (CLAUDE.md 13) - the point is that a bot told to answer by code cannot resolve the rest, and somebody has to decide. |
| [x] | P3-03 | The destination column mixes questions, endings and a special word (C4). | Done. Destination now carries a kind: question, disposition, position or unknown. C02 resolves to 15 questions, 4 endings and one position - CURRENT_QUESTION, correctly reported as naming a place in the flow rather than as a broken reference. |
| [x] | P3-04 | Show-conditions live in two places in two formats and must be combined (D3, D4). | Done. _build_guards combines the questionnaire display conditions with the routing table show rules rather than choosing between them, and records whether the two agree. On C02: 9 agree, 3 are prose that could not be read, and Q15 is single_source - stated only in the questionnaire, exactly as the QRE has it. Anyone reading only the routing table would lose it. |
| [x] | P3-05 | Nothing says when a rule is checked or which rule wins (D5). | Done. Each rule gets an evaluation_point, the last question its condition depends on, and a precedence from its position in the table. Both are marked inferred because the QRE states neither - and it says plainly not to infer unstated routing, so they are surfaced for review rather than buried. C02 derives R1 after S1, R5 after Q1, and so on. |
| [x] | P3-06 | Piping is a sentence, and the Q19 to Q20 link is missed entirely (D6, D7). | Partly done. Piping instructions become typed links: Q1 to Q2 and Q5 to Q6 on C02, read from the source question named in the sentence. Now done: one call over the whole questionnaire finds every wording that refers back to an earlier answer. Q20 asks about "the selected proposition", meaning the answer to Q19; Q8 and Q9 both refer to the current provider, meaning whatever was answered at Q3. The original review by hand had spotted only the first of the three. Each is reported with the exact phrase and marked inferred, and the model must name two questions that exist in the right order, which is checked. **"Repeatably" was wrong** — see X-03. Three runs of C01 gave three different sets, and it is the decision record from P4-08, not the call itself, that makes the answer stable. |
| [x] | P3-07 | Randomize is only true or false, with no scope or anchoring (D8). | Done. Randomization records what is shuffled and what is anchored. C02 gives Q9 rows (it is a matrix) and the rest options, both marked inferred. Q1 and Q5 shuffle while carrying an exclusive option, so their anchoring is marked ambiguous and raised for the client rather than silently defaulted to convention. |
| [x] | P3-08 | Nothing says what happens when a question was never asked (E4). | Done, pending confirmation. A semantics block states the three decisions the QRE never makes: an unasked question makes a condition false, the first matching rule wins, and == against a multi-select compares the whole answer set. It is the single blocking review item on every fixture, because each of the three changes which questions appear on many routes. |

---

## Phase 4 — the graph, and the specification as an input to it

Phases 1 to 3 came out of the C02 review. This phase came out of a different
question, asked on C01 and S01: not "is the specification complete?" but "could
a graph builder and a test designer actually work from it?" Several things
looked complete and were not.

| ✓ | ID | Issue in plain language | What changed | Why it was needed |
|---|---|---|---|---|
| [x] | P4-01 | The specification had no structural view, so nothing could ask where a route goes. | `part2_graph.py` builds a `RouteGraph` and a `DependencyGraph` from the specification, plus a `rule_edge_map` recording which rule produced which edge or guard, and a report checking the graph against the specification it came from. | The specification stays the source of truth; these are a view of it. Two graphs rather than one because "how does a respondent move" and "which answers does this question need" are different questions, and one graph answers neither well. Show rules, reject rules and randomisation are deliberately not edges — see the README for why each. |
| [x] | P4-02 | A question was `{id, seq, guard}` — enough to draw a route graph, not enough to walk one. | Questions now carry type, wording, options, matrix rows and validation. Condition values resolve to option ids alongside their original text, checked rather than assumed. | A reader could see a rule fire on `S1 == 'No'` and had no way to learn that S1 is single-choice answered Yes or No, because that lived only in Part 1's questionnaire file. A bot handed the specification could not execute the simplest route, because nothing told it what to click. Without the bounds there is also no way to generate a value that *should* be refused, so this is what makes a negative test possible at all. |
| [x] | P4-03 | Quota statements were prose, and the ending they name reached nothing. | Quotas become structured cells with targets, resolved to option ids, with an evaluation point and an `on_full` ending. `TERM_QUOTA_FULL` becomes a real disposition node marked `defined_in_source=false`. | Quota-full screenout is real survey behaviour. An ending a rule sends people to but the QRE never defines still needs a node, or a hole in the survey looks like a tidy graph. |
| [x] | P4-04 | Three sections Part 1 extracted never reached Part 2 at all. | Acceptance scenarios, study metadata and programming requirements are now carried. Scenarios have their answers resolved to option ids and their expectations resolved to questions or endings. | The scenarios are the document's own statement of correct behaviour — seven on C01, three on S01, inputs and expected outcome already machine-readable. They are the closest thing to ground truth in the pipeline and were being dropped on the floor. The programming section holds six requirements addressed squarely at Agents 3 and 4. |
| [x] | P4-05 | `mandatory` was asserted from nothing. | Tri-state with an origin. The survey-wide default is read from the document's own sentence by a fixed rule and recorded in the semantics block with that sentence as evidence; null where no document states one. Every question now carries a validation object, so an all-null validation means "the QRE stated no constraint". | It was `not question.optional`, which quietly claimed every question carrying any validation required an answer — true of both documents and asserted from nothing in them, which is exactly what CLAUDE.md §14 forbids. Returning `None` for validation was the same problem one level up: "nothing was stated" looked identical to "this was never populated". |
| [x] | P4-06 | A piped question advertised a list nobody would see. | `OptionSource` on the question names the earlier answer that narrows the list. The printed list is kept as the QRE wrote it. | C01's Q2 lists four brands and shows only those chosen at Q1, and nothing on the question said so. A bot reading the specification would pick an option that is not on screen — which is precisely what the QRE's own scenario T7 exists to catch. Editing the list down to a guess would hide the difference; saying nothing lets the failure happen. |
| [x] | P4-07 | Provenance stopped at rules. | `source_reference` added to questions, dispositions, dependencies, randomization and scenarios; `confidence` carried on inferred dependencies. | CLAUDE.md §15 requires it, and without it a failing test on a question cannot point back at the line of the QRE that asked for the behaviour. |
| [x] | P4-08 | The same document read differently on every run. | Every model answer is recorded to `out/<stem>/llm_decisions.json` and reused, keyed by model, system prompt, user prompt, schema and token cap. `QRE_LLM_CACHE=off` re-asks everything. Dependencies are sorted into question order so agreeing runs produce identical files. | See X-03. This is the difference between a specification and an opinion: a test built on one reading could not be told apart from a test built on another. The file is also a deliverable — it says what was inferred, from what text, by which model and when, which makes the inferred half reviewable in a way a fresh call is not. |
| [x] | P4-09 | A model reading a prose condition silently chose which answers count. | A set-valued condition proposed by a model that names only some of a question's selectable answers now has the omitted ones named in the review queue. | On C01, "Q1 contains at least one brand" was read as three of Q1's four selectable answers, leaving out "Independent provider" — while the skip rule directly above it implies the opposite reading. The QRE does not settle it. The reading is kept, because the parser accepted it and refusing would lose a condition that is probably right; what is added is the fact that it was a choice. |

---

## Change log

Filled in as work lands. Newest first.

| Date | ID | Change | Files touched |
|---|---|---|---|
| 29 Aug 2026 | P4-04..09, X-02 | Acceptance scenarios, study metadata and programming requirements carried into the specification. Mandatory made tri-state and read from the document. Piped option lists marked. Provenance completed. Model answers recorded so a document reads the same way twice. | `src/llm.py`, `src/models.py`, `src/part2_canonical.py`, `src/orchestrator.py` |
| 29 Aug 2026 | — | Regenerated C01's specification and graph against the current pipeline, from the Stage 4 artifacts already on disk. | `out/C01_chronic_care_patient_journey/*` |
| 29 Aug 2026 | P4-02 | Questions carry their type, wording, options, matrix rows and validation; condition values resolve to option ids, checked rather than assumed. | `src/models.py`, `src/part2_canonical.py` |
| 29 Aug 2026 | P4-01 | Route and dependency graphs built from the specification, with a rule-to-edge map and a fidelity report. | `src/part2_graph.py` (new), `src/models.py`, `src/orchestrator.py`, `requirements.txt` |
| 28 Aug 2026 | — | Regenerated S01 with the current pipeline. | `out/S01_campus_cafeteria_experience/*` |
| 28 Aug 2026 | P4-03 | Quotas structured into cells with targets and an evaluation point; the full-quota ending becomes a reachable disposition. | `src/part2_canonical.py`, `src/models.py` |
| 24 Aug 2026 | X-04 | Column matching and matrix splitting fixed for tables not shaped like C02's. | `src/stage4_deep_parse.py` |
| 23 Aug 2026 | X-05 | A daily token limit is told apart from a per-minute one, and fails fast instead of sleeping through retries that cannot succeed. | `src/llm.py` |
| 23 Aug 2026 | P3-01, P3-06 | Prose conditions go to a model that rewrites them into the parser's grammar; question wording is read for references to earlier answers. | `src/part2_conditions.py`, `src/part2_canonical.py`, `src/models.py` |
| 23 Aug 2026 | P3-02..08 | Canonical survey specification: typed destinations, combined guards, derived evaluation points and precedence, structured piping, scoped randomisation, and a stated semantics block. Written to part2_canonical.json. | src/part2_canonical.py (new), src/models.py, src/orchestrator.py |
| 23 Aug 2026 | P3-01 | Typed condition tree and a deterministic parser for it. 75% of routing rules parse with no model; R5 and R18 fixed. | `src/part2_conditions.py` (new), `src/models.py` |
| 23 Aug 2026 | P2-01..05 | Stage 5 built: five deterministic checks, written to `stage5_audit.json`. Catches the T3 defect mechanically. | `src/stage5_audit.py` (new), `src/models.py`, `src/orchestrator.py`, `README.md` |
| 23 Aug 2026 | P1-14, P1-15 | Flags carry a severity and a typed target; `condition_expression` is labelled as an unverified inference. | `src/models.py`, `src/stage2_headings.py`, `src/stage3_raw_json.py`, `src/stage4_deep_parse.py`, `src/orchestrator.py` |
| 23 Aug 2026 | P1-13 | Scenarios record which questions they answer and which identifiers they expect. Resolving those against the questionnaire moves to Stage 5. | `src/models.py`, `src/stage4_deep_parse.py` |
| 23 Aug 2026 | P1-12 | Questions carry an explicit position in the survey, so document order survives storage and re-sorting. | `src/models.py`, `src/stage4_deep_parse.py` |
| 23 Aug 2026 | P1-11 | Every artifact is written inside a header naming the run, the document and its digest. Loaders read both the new and the old shape. | `src/models.py`, `src/orchestrator.py` |
| 23 Aug 2026 | P1-10 | Leftover settings keep their JSON type, and whole numbers stay whole. | `src/models.py`, `src/stage4_deep_parse.py` |
| 23 Aug 2026 | P1-09 | Scale options carry the number the QRE wrote for them, so a scale can be ordered and its endpoints found without reading label text. | `src/models.py`, `src/stage4_deep_parse.py` |
| 23 Aug 2026 | P1-08 | Every answer option and matrix row now carries a stable `option_id`. Unique across all 15 real fixtures. | `src/models.py`, `src/stage4_deep_parse.py` |
| 23 Aug 2026 | X-01 | Semaphore held per event loop instead of once per process, so Stage 4 can run more than once in a session. | `src/llm.py` |
| 23 Aug 2026 | P1-02..06 | Three sections the pipeline never read — quota controls, study specification, programming and QA requirements — are now targets, transcribed deterministically and written to three new `stage4_*.json` files. | `src/models.py`, `src/stage2_headings.py`, `src/stage3_raw_json.py`, `src/stage4_deep_parse.py`, `src/orchestrator.py` |
| 23 Aug 2026 | P1-07 | Provenance carried end to end. Added `SourceReference`; added `row_sources` to `Stage3Block` and `source_reference` to the four Stage 4 output models, all defaulted so existing artifacts still load. | `src/models.py`, `src/stage3_raw_json.py`, `src/stage4_deep_parse.py` |
| 23 Aug 2026 | P1-01 | Stage 2 keeps unmatched sections instead of discarding them. Added `UnclassifiedSection`; added `unclassified` field to `Stage2Blocks`, defaulted to empty so existing artifacts still load. | `src/models.py`, `src/stage2_headings.py` |

### Verification status — Part 1, on C02

Written while this environment had no `GROQ_API_KEY`. Stages 1 to 4 all run
offline; Stage 3's prose path and Stage 4's two LLM calls degrade to a review
flag rather than failing, so the rest still executes. The end-to-end run with a
real key follows below.

Checked on the real C02 document:

- Stage 2 keeps unmatched sections. Verified on C02, S01, Z01 and Z02.
- Stage 3 emits one source reference per row, and `rows` and `row_sources` stay
  the same length for every section.
- Stage 4 attaches provenance to all 31 questions, 20 rules and 7 scenarios,
  with none missing. Row numbers were checked against the document: Q9 is the
  13th question and reports row 12; R19 is the 19th rule and reports row 18.
- Prose rows locate the right paragraph even though four of the five completion
  messages share identical text, because the disposition code separates them.
- Artifacts written before these changes still load, and Stage 4 parses them to
  the same 31 / 20 / 7 / 5 counts with `source_reference` left as null.
- Stages 1 to 4 run clean over the whole 17-fixture corpus, not just the two the
  README records as verified. Option ids come out unique on all 15 real QREs.
  Z01 and Z02 yield nothing without an API key, which is expected: their
  headings match no target by name, so they need shape-matching. Their content
  is preserved as unclassified either way.

### Verification status — Part 2, on C01 and S01

Both documents were regenerated and validated field by field against their raw
QREs on 29 August 2026: question order and types, option sets, every display
condition, every rule's condition, action and destination, completion messages,
quota statements and acceptance scenarios.

- **29 invariants hold on each.** They cover the specification (contiguous
  order, provenance on every element kind, every condition literal resolved to
  option ids, every scenario reference resolving) and the graph's fidelity to it
  (every rule edge matching the rule it came from, node guards matching the
  specification, no ending with a way out, every question reaching an ending).
- **Both graphs pass** with no blocking findings. C01 maps 20 of 20 rules and
  2 of 2 quotas across 38 nodes; S01 maps 4 of 4 across 13.
- **Reproducible.** C01 rebuilt byte-identically three times, S01 twice. Before
  the decision record, three C01 runs gave three different specifications.
- One blocking review item remains on each, and it is the same one:
  `semantics_unconfirmed`. It is deliberate — see P3-08.

Seeding S01's decision record from a cold run froze two wording pipes an earlier
run had missed: Q4's "your rating" and Q6's "the main problem", both referring
back. Both are defensible, both marked inferred and raised for review, and both
now stable — which is the point of recording them.

---

## End-to-end verification

Run on C02 on 23 August 2026 with a real API key, the first time the whole
pipeline has executed since this work began.

| | Before, with no key | Now |
|---|---|---|
| Sections extracted | 6 of 7 | 7 of 7 |
| Completion messages | 0 | 5 |
| Stage 4 review flags | 52, 32 blocking | 1, 0 blocking |
| Conditions read | 15 of 20 | 20 of 20 |
| Audit blocking finding | the missing messages section | scenario T3, a real defect |

The three model-dependent paths - shape-matching a heading, transcribing prose
messages, and splitting a question's inline instructions - all ran successfully.

---

## Found along the way, not yet fixed

| # | Problem | Status |
|---|---|---|
| X-01 | `src/llm.py` kept one asyncio semaphore in a module variable. Asyncio semaphores attach to the event loop they are first used on, so calling Stage 4 a second time in the same process failed with "bound to a different event loop". Pre-existing, from commit `8b4d2c0`; it never showed up because the orchestrator runs Stage 4 once. | **Fixed** 23 Aug 2026, on request. Semaphores are now held in a weak-keyed map per event loop, which is what the function's own docstring already claimed it did. Verified by running Stage 4 three times in one process. |
| X-02 | Review findings appended after the `CanonicalSurvey` object was built were silently discarded. Pydantic copies a list when it validates one onto a model, so `review` and `survey.review` stop being the same object. `condition_option_unresolved` — a BLOCKING check — had never once been able to write into an artifact. It read as clean because it was reporting into a list nobody kept. | **Fixed** 29 Aug 2026. Post-construction checks append to `survey.review`. Found only because a new check that should have fired on C01's R6 and R7 produced nothing. |
| X-03 | Temperature 0 is not determinism. Three runs of C01 on identical code gave three different specifications: Q21's wording was read as quoting Q19 twice and not the third time, and R8's prose condition was declined once and accepted twice. Each changes which questions a respondent sees. | **Fixed** 29 Aug 2026 — P4-08. Model answers are recorded per document and reused. Verified: C01 byte-identical three runs, S01 twice. |
| X-04 | Column matching and matrix splitting assumed C02's table shape. | **Fixed** 24 Aug 2026. |
| X-05 | A per-day token cap was treated as a per-minute one, so the retry loop burned six attempts on calls that could not succeed and then reported a generic failure. | **Fixed** 23 Aug 2026. |
| X-06 | `build_route_graph` connects the last question to `completions[0]`. A QRE with two `complete` dispositions would wire it to only one of them. | **Open.** Latent — neither committed fixture has two. Found by reading, not by failing. |
| X-07 | Nothing checks that a survey can end at all. The disposition checks iterate the dispositions that exist, so a document with none passes them vacuously — as C01 did while its specification was stale and carried none. | **Open.** |
| X-08 | `--from-stage` skips stages 1 to 3 only; Stage 4 always re-runs. Iterating on Part 2 therefore costs a full Stage 4 — roughly fifty model calls. | **Open.** The decision record removes most of the cost; a `load_stage4` would remove the rest. |

---

## Open questions still needing an answer

These are questions for the client, not work items. Each is preserved in the
specification's `review` list rather than answered by a default.

| # | Question | Blocks | QRE |
|---|---|---|---|
| 1 | Is scenario T3 wrong, or is Q15 genuinely meant to show when Q3 was never asked? | P2-03, P3-08 | C02 |
| 2 | When shuffling a question with an exclusive option, should that option stay at the bottom? | P3-07 | C01, C02 |
| 3 | What message should `TERM_QUOTA_FULL` display? The document names the ending and never says what it shows. | P1-03, P4-03 | C01, C02 |
| 4 | If S3 and S4 are both "Yes", which ending applies? | P3-05 | C01, C02 |
| 5 | Does Q20 really refer to the answer given at Q19? | P3-06 | C01, C02 |
| 6 | Does "Independent provider" count as a brand for "Q1 contains at least one brand"? A model read it as three of Q1's four selectable answers; the skip rule directly above implies the opposite. | P4-09 | C01 |
| 7 | What sample size are the quota percentages proportions of? Without a total, when a cell fills cannot be computed. | P4-03 | C01, C02 |
| 8 | Confirm the three semantics decisions. Still the only blocking finding on either survey. | P3-08 | all |
