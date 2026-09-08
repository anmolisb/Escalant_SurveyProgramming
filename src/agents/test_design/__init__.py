"""Agent 3 - Test Designer.

Reads Agent 1's specification and, where one is supplied, the survey Agent 2
actually built. Produces the distinct respondent paths through the survey, a
test case for every behaviour the questionnaire defines, and a coverage
reading across nine kinds of behaviour that are reported separately and never
summed.

Anything it cannot test is named, with the reason, from a closed list. No model
is called anywhere in this package: the same specification always produces the
same tests, which is what makes a failing test attributable to the survey
rather than to the tool.

Entry point:
    python -m src.agents.test_design.run <survey-output-dir> [--lss FILE] [--inputs FILE]
"""