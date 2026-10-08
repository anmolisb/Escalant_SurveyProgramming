"""A modular QRE repeats a heading per module and mixes table kinds under one.

Stage 2 must keep every match and split a mixed section by table; Stage 4 must
merge what Stage 3 transcribed rather than keep the last block.
"""

from src.agents.qre_interpretation import stage2_headings, stage4_deep_parse
from src.agents.qre_interpretation.models import (
    LLMHeadingCandidate,
    Paragraph,
    SourceReference,
    Stage1Document,
    Stage3Block,
    Table,
    TargetHeading,
)

QUESTIONS = ["Var", "Question text", "Type"]
ROUTING = ["Rule", "Condition", "Action", "Destination"]


def _document(*items) -> Stage1Document:
    blocks = []
    for order, item in enumerate(items):
        if isinstance(item, str):
            heading = item.startswith("# ")
            blocks.append(
                Paragraph(
                    order=order,
                    text=item.removeprefix("# "),
                    style="Heading 1" if heading else "Normal",
                    is_bold=False,
                    heading_level=1 if heading else None,
                )
            )
        else:
            blocks.append(Table(order=order, rows=[item, ["x"] * len(item)]))
    return Stage1Document(source="t.docx", blocks=blocks)


def _no_llm_match(monkeypatch):
    monkeypatch.setattr(
        stage2_headings,
        "complete",
        lambda *a, **k: LLMHeadingCandidate(is_match=False, confidence=0, reasoning=""),
    )


def test_classify_table_is_whole_word_and_refuses_to_guess():
    classify = stage2_headings._classify_table
    assert classify(QUESTIONS) is TargetHeading.QUESTIONNAIRE
    assert classify(ROUTING) is TargetHeading.ROUTING_AND_TERMINATION
    assert classify(["ID", "User/system message"]) is TargetHeading.COMPLETION_MESSAGES
    # "notes" must not read as "no", and an unknown header is nobody's.
    assert classify(["Scripter notes", "Wording", "Type"]) is None
    assert classify(["Field", "Format spec"]) is None
    # Fits two signatures: reported, not guessed.
    assert classify(["ID", "Question", "Type", "Condition", "Action"]) is None


def test_repeated_and_mixed_sections_are_all_kept(monkeypatch):
    _no_llm_match(monkeypatch)
    stage2 = stage2_headings.run(
        _document(
            "# Module A", "intro", QUESTIONS,
            "# Module A", QUESTIONS,
            "# Controls", ROUTING, ["Field", "Format spec"],
        )
    )
    by_target = [(b.target, b.matched_by, len(b.blocks)) for b in stage2.blocks]
    assert by_target == [
        (TargetHeading.QUESTIONNAIRE, "table_signature", 1),
        (TargetHeading.QUESTIONNAIRE, "table_signature", 1),
        (TargetHeading.ROUTING_AND_TERMINATION, "table_signature", 1),
    ]
    # Nothing Stage 1 read goes missing: prose and the unknown table are kept.
    kept = {b.order for s in stage2.blocks for b in s.blocks}
    kept |= {b.order for s in stage2.unclassified for b in s.blocks}
    kept |= {s.heading_order for s in stage2.blocks}
    assert kept == set(range(8))


def test_named_headings_still_match_directly_and_may_repeat(monkeypatch):
    _no_llm_match(monkeypatch)
    stage2 = stage2_headings.run(
        _document("# Questionnaire", QUESTIONS, "# Questionnaire", QUESTIONS)
    )
    assert [b.matched_by for b in stage2.blocks] == ["direct", "direct"]
    assert stage2.unclassified == []


def test_merge_keeps_every_row_and_its_provenance_aligned():
    def ref(n):
        return SourceReference(document="t.docx", row_index=n)

    target = TargetHeading.QUESTIONNAIRE
    merged = stage4_deep_parse._merge_by_target(
        [
            Stage3Block(target=target, source_kind="table", rows=[{"a": "1"}, {"a": "2"}],
                        row_sources=[ref(0)]),
            Stage3Block(target=target, source_kind="table", rows=[{"a": "3"}],
                        row_sources=[ref(7)]),
        ]
    )[target]
    assert [r["a"] for r in merged.rows] == ["1", "2", "3"]
    assert [s and s.row_index for s in merged.row_sources] == [0, None, 7]


def test_statement_reads_prose_and_table_rows():
    statement = stage4_deep_parse._statement_from
    assert statement({"raw_text": "Q1: hard", "code": "Q1", "text": "hard"}) == (
        "Q1", None, "hard", "Q1: hard",
    )
    code, _label, text, raw = statement({"ID": "QT01", "Variable": "Region", "Notes": ""})
    assert (code, text, raw) == ("QT01", "QT01: Variable: Region", "QT01: Variable: Region")


def test_empty_specification_cannot_pass_validation():
    from src.agents.qre_interpretation import part2_validate, qre_oracle
    from src.agents.qre_interpretation.models import CanonicalSurvey

    cross = part2_validate.cross_source(
        qre_oracle.OracleDocument(source="t.docx"),
        {},
        CanonicalSurvey(survey_id="t", source="t.docx"),
    )
    assert [f["check"] for f in cross] == ["missing_questionnaire"]
    verdict = part2_validate.verdict(
        [], {}, cross, {"semantic_reproducible": True}, [], {"passed": True, "blocking": 0}
    )
    assert verdict["canonical_status"] == "FAILED"
    assert verdict["agent3_ready"] == "NO"


def test_display_rows_are_set_apart_from_questions_and_keep_their_place():
    rows = [
        {"ID": "Q1", "Question wording": "Age?", "Type": "integer", "Programming instruction": ""},
        {"ID": "DT1", "Question wording": "Nearly done.", "Type": "text display",
         "Programming instruction": "Show before Q2."},
        {"ID": "Q2", "Question wording": "Region?", "Type": "single", "Programming instruction": ""},
    ]
    block = Stage3Block(
        target=TargetHeading.QUESTIONNAIRE, source_kind="table", rows=rows,
        row_sources=[SourceReference(row_index=i) for i in range(3)],
    )
    questions, display, layout = stage4_deep_parse._split_display(block)
    assert [r["ID"] for r in questions.rows] == ["Q1", "Q2"]
    assert [s.row_index for s in questions.row_sources] == [0, 2]
    assert layout == [False, True, False]
    (message,) = display
    assert (message.id, message.wording, message.type) == ("DT1", "Nearly done.", "text display")
    assert message.other_attributes == {"other_instructions": ["Show before Q2."]}
    assert message.source_reference.row_index == 1
    # A questionnaire with no display rows comes back untouched.
    assert stage4_deep_parse._split_display(questions) == (questions, [], [False, False])


def test_written_questionnaire_holds_display_rows_in_document_order():
    import asyncio

    def block(target, rows):
        return Stage3Block(target=target, source_kind="table", rows=rows)

    parsed, _flags = asyncio.run(stage4_deep_parse.run_async(
        [block(TargetHeading.QUESTIONNAIRE, [
            {"ID": "S1", "Wording": "Adult?", "Type": "single", "Options": "Yes; No", "Display": ""},
            {"ID": "DT1", "Wording": "Welcome.", "Type": "text display", "Options": "", "Display": ""},
            {"ID": "Q1", "Wording": "Why?", "Type": "text", "Options": "", "Display": ""},
        ])],
        "t.docx", [],
    ))
    assert [q.id for q in parsed["questionnaire"]] == ["S1", "DT1", "Q1"]
    assert [(q.id, q.seq) for q in parsed["questions"]] == [("S1", 1), ("Q1", 2)]
    assert [q.id for q in parsed["display_messages"]] == ["DT1"]


def test_keyword_led_cells_are_labelled_without_a_model():
    read = stage4_deep_parse._keyword_directives
    fields = read("Show if M01Q01 != 'Not applicable'\nValidate {\"min\": 0}\nRandomize; log order")
    assert [(d.kind.value, d.text) for d in fields.directives] == [
        ("display_condition", "M01Q01 != 'Not applicable'"),
        ("validation", '{"min": 0}'),
        ("randomize", "Randomize"),
        ("other", "log order"),
    ]
    assert read("Show if: Q5 == 'Yes'").directives[0].text == "Q5 == 'Yes'"
    # One line that needs reading sends the whole cell to the model.
    assert read("Randomize\nShow only brands selected at Q1.") is None


def test_triggered_message_catalogue_is_not_read_as_endings():
    classify = stage2_headings._classify_table
    assert classify(["Code", "Message shown to respondent"]) is TargetHeading.COMPLETION_MESSAGES
    assert classify(["ID", "Trigger", "User/system message", "Class"]) is None
