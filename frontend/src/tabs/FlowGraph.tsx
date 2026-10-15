import { useEffect, useState } from "react";
import { api, type Graph } from "../api";
import { Empty, Strip } from "../ui";

/** The whole survey's route graph. Opens fitted to the screen; zoom widens it
 *  and the box scrolls. */
export function FlowGraph({ run }: { run: string }) {
  const [vertical, setVertical] = useState(false);
  const [zoom, setZoom] = useState(100);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setGraph(null);
    setError(null);
    api.graph(run, vertical).then(setGraph).catch((e) => setError(String(e.message)));
  }, [run, vertical]);

  if (error) return <Empty title="No flow graph">{error}</Empty>;
  if (!graph) return <p className="muted">Drawing the graph…</p>;

  const download = () => {
    const url = URL.createObjectURL(new Blob([graph.svg], { type: "image/svg+xml" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `${run}_flow.svg` });
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <Strip cells={[
        { label: "Questions and endings", value: String(graph.nodes) },
        { label: "Routes between them", value: String(graph.edges) },
        { label: "Endings", value: String(graph.endings) },
      ]} />
      <div className="graphbar">
        <div className="stats" />
        <button className="btn" onClick={() => setZoom((z) => Math.max(50, z - 25))} title="Zoom out">{"−"}</button>
        <span className="muted" style={{ minWidth: 48, textAlign: "center" }}>{zoom}%</span>
        <button className="btn" onClick={() => setZoom((z) => Math.min(400, z + 25))} title="Zoom in">+</button>
        <button className="btn" onClick={() => setZoom(100)}>Fit</button>
        <label className="btn" style={{ gap: 8 }}>
          <input type="checkbox" checked={vertical} onChange={(e) => setVertical(e.target.checked)} /> Vertical
        </label>
      </div>
      <div className="graphwrap" style={{ ["--w" as string]: `${zoom}%` }}>
        <div className="graph-inner" dangerouslySetInnerHTML={{ __html: graph.svg }} />
      </div>
      <p className="caption">
        Grey is document order. Teal is a skip, red a termination, blue a visibility guard, purple a quota.
        A dashed question box is shown only when its guard holds. Hover an edge for its condition.
      </p>
      <button className="btn" onClick={download}>Download the graph as SVG</button>
    </>
  );
}
