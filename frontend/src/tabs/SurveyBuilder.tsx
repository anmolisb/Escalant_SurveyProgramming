import { api, type RunDetail } from "../api";
import { Empty, kb, Section, Strip } from "../ui";
import { questionCount } from "./Questions";

export function SurveyBuilder({ run }: { run: RunDetail }) {
  const file = run.survey_file;
  return (
    <>
      <Section title="The survey file">
        The builder turns the specification into a .lss that LimeSurvey can import. It stops rather than guessing,
        so a question it cannot translate is named rather than approximated.
      </Section>
      {!file ? (
        <Empty title="Not built yet" then="Run Survey Builder, step 2 in the sidebar">
          The specification is ready. Building it produces the .lss file that everything downstream is tested against.
        </Empty>
      ) : (
        <>
          <div className="banner ok">The survey file for {run.title} is built.</div>
          <Strip cells={[
            { label: "Survey file", value: "Built", tone: "ok" },
            { label: "Size", value: kb(file.size) },
            { label: "Questions carried", value: String(run.questions.filter((q) => !q.display).length),
              sub: run.questions.some((q) => q.display) ? `+ ${run.questions.filter((q) => q.display).length} messages` : undefined },
          ]} />
          <a className="btn primary" href={api.fileUrl(run.name, `agent2/${file.name}`)}>Download the .lss file</a>
          <p style={{ marginTop: 16 }}>
            Import it in LimeSurvey under <b>Surveys {"→"} Create {"→"} Import</b>, then <b>activate</b> it.
            Use <b>Preview</b> to walk the questionnaire as a respondent would see it. An inactive survey will not
            serve respondents, so the bot cannot test it.
          </p>
        </>
      )}
    </>
  );
}
