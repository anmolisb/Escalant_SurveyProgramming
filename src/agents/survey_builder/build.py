"""Build a LimeSurvey .lss file from a QRE run folder.

    python -m src.agents.survey_builder.build out/S01_campus_cafeteria_experience

The stage 4 files are read from the run's agent1/ folder and the survey is
written to its agent2/ folder. A folder that holds the stage 4 files directly,
such as tests/survey_builder/stage4-outputs/C02, also works and writes to out/.

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
from src.common.paths import AGENT1, OUT_ROOT, agent1_dir, agent2_lss

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="a QRE run folder, or a stage 4 output folder")
    parser.add_argument("--notes", action="store_true",
                        help="also list input the builder is ignoring")
    args = parser.parse_args()

    directory = Path(args.directory)
    if directory.name == AGENT1:
        directory = directory.parent
    source = agent1_dir(directory)
    gaps = check(source)

    blocking = [gap for gap in gaps if gap.blocking]
    if blocking:
        print(f"{directory}: cannot build, {len(blocking)} unsupported thing(s)\n")
        for gap in blocking:
            print(gap)
        return 1

    survey = load(source)
    # A run folder keeps its survey in agent2/. Anything else, such as a test
    # fixture, still writes to out/ so the fixture folder is left untouched.
    if directory.resolve().parent == OUT_ROOT.resolve():
        path = agent2_lss(directory)
    else:
        path = OUT_ROOT / f"{directory.name}_generated.lss"
    path.parent.mkdir(parents=True, exist_ok=True)
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