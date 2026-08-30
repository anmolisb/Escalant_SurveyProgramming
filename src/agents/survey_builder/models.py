"""Intermediate representation for a LimeSurvey survey.

Stage 4 JSON is loaded into these models, then an emitter turns them into LSS
XML. Everything here is already LimeSurvey-shaped: `type` holds LimeSurvey's
question-type letter, `relevance` holds an ExpressionScript string.

Ids (sid, gid, qid, aid) are assigned by the loader, not carried from the QRE.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# LimeSurvey question types used by the current fixtures.
#   L = list (radio), M = multiple choice, T = long free text, S = short free text
#   F = array, K = multiple numerical input (used for constant sum)
QuestionType = str


class Option(BaseModel):
    """An answer option on a single-choice question (the `answers` table)."""

    code: str          # A001, A002, ... or a code carried from the QRE
    label: str
    sortorder: int
    aid: int = 0       # assigned by the loader; answer_l10ns joins on this


class Subquestion(BaseModel):
    """An option on a multiple-choice question.

    LimeSurvey stores these as rows in the `questions` table with parent_qid
    set, not as answers. They must be emitted immediately after their parent.
    """

    code: str          # SQ001, SQ002, ...
    label: str
    question_order: int
    qid: int = 0       # assigned by the loader


class Question(BaseModel):
    title: str                     # question code shown in LimeSurvey, e.g. "Q6"
    text: str
    type: QuestionType
    question_order: int
    mandatory: str = "Y"           # "Y" or "N"
    relevance: str = "1"           # "1" means always show
    qid: int = 0                   # assigned by the loader

    # Answer options. On an array these are the columns of the scale.
    options: list[Option] = Field(default_factory=list)

    # Rows of an array, options of a multiple choice, items of a constant sum.
    subquestions: list[Subquestion] = Field(default_factory=list)

    # question_attributes rows, e.g. {"min_answers": "1", "maximum_chars": "500"}
    attributes: dict[str, str] = Field(default_factory=dict)

    # Attributes that carry display text and so need a language tag, or
    # LimeSurvey drops them silently on import.
    localized_attributes: dict[str, str] = Field(default_factory=dict)


class Group(BaseModel):
    name: str
    group_order: int
    relevance: str = "1"
    gid: int = 0                   # assigned by the loader
    questions: list[Question] = Field(default_factory=list)


class Survey(BaseModel):
    title: str
    description: str = ""
    welcome_text: str = ""
    end_text: str = ""             # may contain an {if(...)} expression
    sid: int = 900001
    groups: list[Group] = Field(default_factory=list)