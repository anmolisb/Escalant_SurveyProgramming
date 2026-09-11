"""Build a LimeSurvey .lss file from a stage 4 output directory.

    python -m src.agents.survey_builder.build tests/survey_builder/stage4-outputs/C02

The input is checked before anything is built, because the loader raises on the
first problem it meets and a new QRE usually has several. A build that cannot
go ahead says why.

Some inputs build correctly but carry fields LimeSurvey has no equivalent for,
which are dropped. Those are not errors and are not printed here: pass --notes
to see them, or run preflight, which reports everything it finds.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.agents.survey_builder.emitter import write
from src.agents.survey_builder.loader import load
from src.agents.survey_builder.preflight import check

OUTPUT_DIR = Path("out")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="a stage 4 output folder")
    parser.add_argument("--notes", action="store_true",
                        help="also list input the builder is ignoring")
    args = parser.parse_args()

    directory = Path(args.directory)
    gaps = check(directory)

    blocking = [gap for gap in gaps if gap.blocking]
    if blocking:
        print(f"{directory}: cannot build, {len(blocking)} unsupported thing(s)\n")
        for gap in blocking:
            print(gap)
        return 1

    survey = load(directory)
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / f"{directory.name}_generated.lss"
    write(survey, path)

    questions = sum(len(group.questions) for group in survey.groups)
    print(f"{path}  ({len(survey.groups)} groups, {questions} questions)")

    if args.notes:
        notes = [gap for gap in gaps if not gap.blocking]
        if notes:
            print()
            for gap in notes:
                print(gap)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())