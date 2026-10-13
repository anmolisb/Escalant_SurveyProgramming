# Design principles

The rules the code is built on. Each explains a choice you will see in the
code, and comments refer to them by number ("principle 2"). Change one only
deliberately, and record why in `docs/decisions/`.

## Reading the QRE

**1. Record first, interpret second.** Agent 1 Part 1 (stages 1 to 5) keeps
what the document says, word for word: `Show if: Q5 contains any touchpoint`
stays as text. Only Part 2 (stage 6 on) decides what it means. Because Part 1
is a faithful copy, any later mistake can be traced to the stage that made it.

**2. Every value says where it came from.** Each value carries an origin:
`extracted` (stated in the QRE), `derived` (worked out by code), `inferred`
(read by a model), `unknown` or `ambiguous`. An inference is never presented as
something the QRE stated.

**3. Every fact points back to its source.** Questions, rules, options and
endings keep a source reference: section, table row and the text itself. A
failing test can then be traced to the sentence in the QRE that asked for it.

**4. Never invent.** No question, option, answer code, rule, quota, message or
default appears unless the QRE states it. Where the document is silent the
value is null and a review item says so. Option handles like `Q1-O3` record
position only and are not answer codes.

**5. Keep what cannot be read.** Content that matches nothing known is kept
with its location and flagged, never dropped. Unknown content is better than
silent loss.

**6. Code first, the model only for meaning.** Anything code can read reliably
(tables, labelled lines, formal conditions such as `S1 == 'No'`) is read by
code. The model is used only for prose, and it proposes in a fixed grammar that
code then accepts or rejects. Every model answer is cached so a document reads
the same way on every run.

**7. A visible failure beats a silent wrong answer.** Uncertain readings
become review items, and readings the QRE does not settle become decisions for
a person. A specification is not passed to testing until those are confirmed.
Stage 7's check shares no code with the stages it checks, so the two cannot
agree by construction.

## Building and testing

**8. The canonical specification is the contract.** Agents 2 to 5 read
`agent1_canonical_survey_spec.json` and nothing else from Agent 1. It is
platform-neutral: everything specific to LimeSurvey (types, attribute names,
expression syntax) lives in Agent 2, so another survey platform needs a new
builder, not a new reader.

**9. Learn the pattern, never the sample.** No section name, column name,
question id, wording or option label from a sample QRE is hard-coded. Known
forms (section names, labelled instruction lines) sit in one configurable table
each, so a new QRE format means extending a table rather than rewriting code.

**10. Do not develop against the holdout.** QREs in `fixtures/holdout/` exist
to measure whether the pipeline works on documents it was not built against.
Reading them while developing destroys that measurement (decision 0002). A QRE
used to debug a failure is retired and replaced, and that is recorded in
`docs/decisions/`.

**11. Say what is not supported before running.** Each agent declares what it
supports, and the readiness check (`python -m src.common.readiness`) compares
the specification against those declarations before Agents 2 to 4 start, so a
gap is named up front instead of surfacing as blocked journeys.

## Security

**12. Client material and secrets stay out of git.**
- Never commit confidential QREs, client ground truth, real respondent data,
  private exports or screenshots, or logs containing secrets. Client material
  goes in `data/ground_truth/Client/`, which git ignores, or outside the
  repository.
- Keys live only in `.env`, which git ignores. `config/.env.example` holds
  placeholders.
- Every model call goes through `src/common/llm/`, so the provider can be
  audited or swapped in one place. Confidential QREs must only be sent to a
  provider the client has approved.

## Earlier references

Older records (`docs/decisions/`, `docs/fix-tracker.md`, the weekly progress
notes and some code history) cite sections of a previous instruction file,
`CLAUDE.md`. They map to these principles as follows:

| Old section | Principle |
|---|---|
| §6, §7, §19 | 1 |
| §14 | 2 |
| §15 | 3 |
| §13, §30 | 4 |
| §16, §31 | 5 and 7 |
| §20, §29 | 6 |
| §32, §40 | 7 |
| §21 to §26 | 8 |
| §9, §10, §61, §62 | 9 |
| §41 (holdout) | 10 |
| §51 to §53 | 12 |
