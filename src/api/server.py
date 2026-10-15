"""The web app's backend: an API over the run folders, and the built frontend.

    python -m src.api.server            then open http://localhost:8000

During frontend development, run this and `npm run dev` in frontend/ side by
side; the dev server forwards /api here.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from src.api import jobs, views
from src.common.paths import REPO_ROOT

app = FastAPI(title="Survey Programming")


def _found(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except views.NotFound as error:
        raise HTTPException(404, f"not found: {error}") from error
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error


@app.get("/api/runs")
def runs() -> list[dict]:
    return views.list_runs()


@app.get("/api/runs/{name}")
def run(name: str) -> dict:
    return _found(views.run_detail, name)


@app.get("/api/runs/{name}/graph")
def graph(name: str, vertical: bool = False) -> dict:
    return _found(views.flow_graph, name, vertical)


@app.get("/api/runs/{name}/journeys/{path_id}.svg")
def journey(name: str, path_id: str) -> Response:
    return Response(_found(views.journey_graph, name, path_id),
                     media_type="image/svg+xml")


@app.get("/api/runs/{name}/files")
def files(name: str) -> list[dict]:
    return _found(views.files, name)


@app.get("/api/runs/{name}/file")
def file(name: str, path: str) -> FileResponse:
    target = _found(views.file_path, name, path)
    return FileResponse(target, filename=target.name)


@app.get("/api/runs/{name}/zip")
def zip_all(name: str) -> StreamingResponse:
    directory = _found(views.run_dir, name)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix != ".log":
                archive.write(path, path.relative_to(directory))
    buffer.seek(0)
    return StreamingResponse(
        buffer, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'})


# --- running agents --------------------------------------------------------


def _started(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except jobs.JobError as error:
        raise HTTPException(400, str(error)) from error


@app.post("/api/upload")
async def upload(request: Request, filename: str) -> dict:
    """Keep an uploaded questionnaire and run Agents 1 to 3 on it.

    The file is the raw request body, so no form-parsing package is needed.
    """
    name = _started(jobs.save_upload, filename, await request.body())
    _started(jobs.start, name, [1, 2, 3])
    return {"name": name}


@app.post("/api/runs/{name}/run")
def run_agents(name: str, body: dict = Body(...)) -> dict:
    """Run a chain of agents: {"agents": [4, 5], "sid": "123", "base": "...", "headed": false}."""
    job = _started(jobs.start, name, [int(a) for a in body.get("agents") or []],
                   body.get("sid"), body.get("base"), bool(body.get("headed")))
    return job.view()


@app.get("/api/runs/{name}/job")
def job_status(name: str) -> dict | None:
    return jobs.status(name)


@app.post("/api/runs/{name}/stop")
def stop(name: str) -> dict:
    jobs.stop(name)
    return {"stopping": True}


@app.get("/api/running")
def running() -> list[str]:
    return jobs.running()


# The built frontend, when there is one. Mounted last so /api wins.
DIST = REPO_ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")


def main() -> None:
    import uvicorn
    uvicorn.run("src.api.server:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
