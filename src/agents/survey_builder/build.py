"""Build a LimeSurvey .lss file from a stage 4 output directory.

    python -m src.agents.survey_builder.build fixtures/stage4-outputs/C02

The input is checked before anything is built. The loader raises on the first
problem it meets, which means fixing gaps one rerun at a time; preflight walks
the whole input first so a new QRE reports every gap at once.
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.agents.survey_builder.emitter import write
from src.agents.survey_builder.loader import load
from src.agents.survey_builder.preflight import check

OUTPUT_DIR = Path("out")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    directory = Path(sys.argv[1])

    gaps = check(directory)
    if gaps:
        print(f"{directory}: cannot build, {len(gaps)} unsupported thing(s)\n")
        for gap in gaps:
            print(gap)
        return 1

    survey = load(directory)
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / f"{directory.name}_generated.lss"
    write(survey, path)

    questions = sum(len(group.questions) for group in survey.groups)
    print(f"{path}  ({len(survey.groups)} groups, {questions} questions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
