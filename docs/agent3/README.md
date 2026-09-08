\# Agent 3 output



Two surveys, run end to end. Regenerate with:



&#x20;   python -m src.agents.test\_design.run <survey-output-dir> \\

&#x20;       --lss <built-survey>.lss \\

&#x20;       --inputs <survey-output-dir>/agent3\_inputs.json



|                          | S01 | C02 |

|--------------------------|-----|-----|

| Questions                | 10  | 31  |

| Rules                    | 4   | 20  |

| Distinct paths           | 4   | 12  |

| Test cases               | 36  | 163 |

| Runnable against build   | 36  | 163 |

| Coverage floor           | 100% | 100% |



\## The three tabs



\*\*Survey Paths.\*\* The distinct respondent journeys. Exclusive means no two walk

the same question sequence. Branch-exhaustive means every point where the

survey can go more than one way is taken in both directions by at least one

path. A testing team starts here.



\*\*Test Cases.\*\* One row per test, ordered the way the questionnaire is ordered:

S1 first, then Q1 onward. Every row names the question it belongs to and the

path it runs on.



\*\*Paths Not Enumerated.\*\* What was deliberately left out, how large each family

is, and what risk remains. Crossing every branch with every other on C02 is

262,144 answer combinations; almost all walk a sequence another already walks.



\## Two things these workbooks show that are worth reading



Filter Test Cases by Status. On C02, 156 of 163 rows read PROVISIONAL. Those

tests lean on a survey-wide reading rule nobody has confirmed, such as what

"equals" means when the answer is a set of tick-boxes. They are correct tests

of the reading we were given.



The shuffling and quota tests are expected to fail on the current build,

because the QRE specifies both and the built survey has neither. A failing

test is how a gap is proven rather than asserted.



These are output artifacts, committed so a reviewer can see what the code

produces without running it. They are regenerated on every run and are not

inputs to anything.

