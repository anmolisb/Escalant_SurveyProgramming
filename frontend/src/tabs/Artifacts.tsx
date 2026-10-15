import { useEffect, useState } from "react";
import { api, type FileGroup } from "../api";
import { kb, Section } from "../ui";

export function Artifacts({ run }: { run: string }) {
  const [groups, setGroups] = useState<FileGroup[] | null>(null);
  useEffect(() => { api.files(run).then(setGroups).catch(() => setGroups([])); }, [run]);
  if (!groups) return <p className="muted">Listing files…</p>;
  const count = groups.reduce((n, g) => n + g.files.length, 0);
  return (
    <>
      <Section title="Everything this run produced">
        {count} files. When a test fails, these let you tell whether the survey is wrong, the answers chosen were
        wrong, or the prediction was wrong.
      </Section>
      <p><a className="btn primary" href={api.zipUrl(run)}>Download everything as a zip</a></p>
      {groups.map((g) => (
        <details className="card" key={g.label}>
          <summary><span className="rname">{g.label}</span><span className="rmeta">{g.files.length}</span></summary>
          <div className="body">
            {g.files.map((f) => (
              <div className="filerow" key={f.path}>
                <span className="code">{f.name}</span>
                <span className="btn-row">
                  <span className="muted" style={{ fontSize: "0.82rem" }}>{kb(f.size)}</span>
                  <a className="btn" href={api.fileUrl(run, f.path)}>Download</a>
                </span>
              </div>
            ))}
          </div>
        </details>
      ))}
    </>
  );
}
