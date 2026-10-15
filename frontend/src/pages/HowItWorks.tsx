import { link } from "../router";

const STEPS = [
  {
    title: "Read the questionnaire",
    body: "The QRE is read in two parts. First, everything it says is recorded word for word: questions, options, instructions, routing, quotas, endings. Then it is interpreted into a specification, where every value says whether the document stated it, code worked it out, or a model read it. Anything the document leaves open becomes a decision for a person, never a guess.",
  },
  {
    title: "Build the survey",
    body: "The specification becomes a LimeSurvey file with the questions, options, display conditions, validation, screen-outs and randomisation the questionnaire asks for. Anything it cannot build is named before the build, not discovered after.",
  },
  {
    title: "Design the tests",
    body: "Every distinct route a respondent can take through the survey is worked out, so each branch is taken both ways. Each behaviour the questionnaire claims gets a test, and the expected outcome is predicted independently of the answers chosen.",
  },
  {
    title: "Run the tests",
    body: "A bot opens the live survey in a real browser and answers it as a respondent would, one fresh session per test, recording what it saw on each page.",
  },
  {
    title: "Explain the results",
    body: "A failing test is not always a broken survey. Each one is given a single cause (survey defect, misread questionnaire, not built yet, open question, or a gap in the tests) and an owner, and each journey is reported as working, broken or not yet proven.",
  },
];

export function HowItWorks() {
  return (
    <div className="page narrow">
      <section className="hero small">
        <h1>How it works</h1>
        <p className="lede">
          Five stages, in order. Each reads what the one before it wrote, so every result can be traced back to the
          sentence in the questionnaire that asked for it.
        </p>
      </section>
      <ol className="overview">
        {STEPS.map((s, i) => (
          <li key={s.title} className="done">
            <span className="num">{i + 1}</span>
            <div>
              <h3>{s.title}</h3>
              <p>{s.body}</p>
            </div>
          </li>
        ))}
      </ol>
      <p><a className="button" href={link.home}>Open a survey</a></p>
    </div>
  );
}
