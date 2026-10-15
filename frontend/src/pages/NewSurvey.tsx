import { useRef, useState } from "react";
import { api } from "../api";
import { link } from "../router";

/** Upload a questionnaire. The first three agents need nothing from a person,
 *  so they start straight away; the survey page shows them working. */
export function NewSurvey() {
  const [file, setFile] = useState<File | null>(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const choose = (chosen: File | undefined) => {
    setError(null);
    if (!chosen) return;
    if (!chosen.name.toLowerCase().endsWith(".docx")) {
      setError("That is not a Word file. Choose the questionnaire as a .docx.");
      return;
    }
    setFile(chosen);
  };

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const { name } = await api.upload(file);
      window.location.hash = link.survey(name);
    } catch (e) {
      setError(String((e as Error).message));
      setBusy(false);
    }
  };

  return (
    <div className="page narrow">
      <section className="hero small">
        <h1>Check a questionnaire</h1>
        <p className="lede">
          Upload a questionnaire requirement document. It is read, built into a LimeSurvey survey, and
          given a full set of tests. That takes a few minutes. Running the tests comes after, once the
          survey is in LimeSurvey.
        </p>
      </section>

      <div
        className={`dropzone ${over ? "over" : ""} ${file ? "chosen" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); choose(e.dataTransfer.files[0]); }}
        onClick={() => input.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") input.current?.click(); }}
      >
        <input ref={input} type="file" accept=".docx" hidden onChange={(e) => choose(e.target.files?.[0])} />
        {file ? (
          <>
            <div className="dz-title">{file.name}</div>
            <div className="muted">{Math.max(1, Math.round(file.size / 1024))} KB. Click to choose a different file.</div>
          </>
        ) : (
          <>
            <div className="dz-title">Drop the questionnaire here</div>
            <div className="muted">or click to choose it. A Word file (.docx).</div>
          </>
        )}
      </div>

      {error && <p className="notice bad">{error}</p>}

      <div className="hero-actions">
        <button className="button" disabled={!file || busy} onClick={submit}>
          {busy ? "Uploading…" : "Start"}
        </button>
        <a className="button quiet" href={link.home}>Cancel</a>
      </div>

      <div className="steps-after">
        <h2>What happens next</h2>
        <ol>
          <li><b>Read.</b> The questionnaire becomes a specification of every question, rule and ending.</li>
          <li><b>Build.</b> The specification becomes a LimeSurvey file.</li>
          <li><b>Design tests.</b> Every journey through the survey gets its tests.</li>
          <li><b>You import the survey</b> into LimeSurvey and activate it, then give its survey id.</li>
          <li><b>Run and explain.</b> A bot answers the live survey, and every result gets a cause.</li>
        </ol>
        <p className="caption">
          The file is kept on the computer running this app, in a folder git ignores, so a client's
          questionnaire is never committed. A file with the same name as an earlier one replaces it.
        </p>
      </div>
    </div>
  );
}
