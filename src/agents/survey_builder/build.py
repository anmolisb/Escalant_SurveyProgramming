from src.agents.survey_builder.loader import load
from src.agents.survey_builder.emitter import write

survey = load("fixtures/stage4-outputs/S01")
write(survey, "S01_generated.lss")
print(f"Wrote S01_generated.lss ({len(survey.groups)} groups)")