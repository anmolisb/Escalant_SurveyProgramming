# Agent 1 fix tracker

One row per issue found in the C02 output review. Each row is ticked off as the
fix lands, with a short note on what changed and why it was needed.

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
extraction contract, so none of it is started yet.

| ✓ | ID | Issue in plain language | Why it waits for Part 2 |
|---|---|---|---|
| [-] | P3-01 | Rule R5 changed meaning; R19 can never fire; three different syntaxes; R20 compares the wrong types (B1, B2, B3, B5). | Deciding what an operator means is Part 2's job by definition (§7.1, §19). |
| [-] | P3-02 | Q13's answer codes are only half filled in (C2). | Filling the gaps would be inventing codes, which §13 forbids. It gets flagged as ambiguous instead and resolved in Part 2. |
| [-] | P3-03 | The destination column mixes questions, endings and a special word (C4). | Typing a destination requires knowing what exists, which is interpretation. |
| [-] | P3-04 | Show-conditions live in two places in two formats and must be combined (D3, D4). | Combining two representations is normalisation, not extraction. |
| [-] | P3-05 | Nothing says when a rule is checked or which rule wins (D5). | Both are inferences. They must be produced and labelled as such in Part 2. |
| [-] | P3-06 | Piping is a sentence, and the Q19 to Q20 link is missed entirely (D6, D7). | Reading meaning out of question wording is semantic work. |
| [-] | P3-07 | Randomize is only true or false, with no scope or anchoring (D8). | Part 1 keeps the raw instruction. Part 2 decides what it means. |
| [-] | P3-08 | Nothing says what happens when a question was never asked (E4). | A language-level decision belonging to the canonical specification. |

---

## Change log

Filled in as work lands. Newest first.

| Date | ID | Change | Files touched |
|---|---|---|---|
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

### Verification status

Stages 1 to 4 all run offline. Stage 3's prose path and Stage 4's two LLM
calls need a `GROQ_API_KEY`, which this environment does not have; those paths
degrade to a review flag rather than failing, so the rest still executes.

Checked so far, on the real C02 document:

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

Not yet done: **the pipeline has not been run end to end with a real API key**,
and `out/` has deliberately not been regenerated. Regenerating it without a key
would overwrite the committed worked example with an empty completion-messages
section.

---

## Found along the way, not yet fixed

| # | Problem | Status |
|---|---|---|
| X-01 | `src/llm.py` kept one asyncio semaphore in a module variable. Asyncio semaphores attach to the event loop they are first used on, so calling Stage 4 a second time in the same process failed with "bound to a different event loop". Pre-existing, from commit `8b4d2c0`; it never showed up because the orchestrator runs Stage 4 once. | **Fixed** 23 Aug 2026, on request. Semaphores are now held in a weak-keyed map per event loop, which is what the function's own docstring already claimed it did. Verified by running Stage 4 three times in one process. |

---

## Open questions still needing an answer

| # | Question | Blocks |
|---|---|---|
| 1 | Is scenario T3 wrong, or is Q15 genuinely meant to show when Q3 was never asked? | P2-03, P3-08 |
| 2 | When shuffling Q1 and Q5, should "None of these" stay at the bottom? | P3-07 |
| 3 | What message should `TERM_QUOTA_FULL` display? | P1-03 |
| 4 | If S3 and S4 are both "Yes", which ending applies? | P3-05 |
| 5 | Does Q20 really refer to the answer given at Q19? | P3-06 |
