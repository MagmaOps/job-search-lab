"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { api, Job, Status } from "@/lib/api";

function scoreClass(s: number | null): string {
  if (s === null || s === undefined) return "na";
  if (s >= 70) return "high";
  if (s >= 40) return "mid";
  return "low";
}

const STATUSES = ["new", "saved", "dismissed", "applied", "interview"];

const ANALYSIS_STATE: Record<string, { cls: string; label: string }> = {
  current: { cls: "current", label: "Analyzed against the current CV" },
  outdated: { cls: "outdated", label: "Analyzed against an older CV — re-analyze for an up-to-date score" },
  error: { cls: "error", label: "Last analysis failed — try re-analyze" },
  none: { cls: "none", label: "Not analyzed against the current CV" },
};

export default function Dashboard() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [minScore, setMinScore] = useState("");
  const [location, setLocation] = useState("");
  const [company, setCompany] = useState("");
  const [language, setLanguage] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const load = useCallback(async () => {
    setErr(null);
    try {
      const params: Record<string, string> = {};
      if (minScore) params.min_score = minScore;
      if (location) params.location = location;
      if (company) params.company = company;
      if (language) params.language = language;
      if (statusFilter) params.status = statusFilter;
      const [j, s] = await Promise.all([api.jobs(params), api.status()]);
      setJobs(j);
      setStatus(s);
    } catch (e) {
      setErr(String(e));
    }
  }, [minScore, location, company, language, statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  async function runNow() {
    setBusy(true);
    setErr(null);
    try {
      const queries = await api.queries();
      const first = queries.find((q) => q.enabled) || queries[0];
      if (first) await api.runQuery(first.id);
      await load();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function analyzeExisting() {
    setBusy(true);
    setErr(null);
    try {
      const res = await api.analyze(200);
      await load();
      alert(`Analyzed ${res.analyzed} job(s) against the current CV.`);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function setJobStatus(id: number, s: string) {
    await api.setJobStatus(id, s);
    load();
  }

  async function reanalyze(id: number) {
    await api.reanalyze(id);
    load();
  }

  return (
    <>
      <h1>Dashboard</h1>

      <div className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="muted">
            {status?.last_run_at
              ? `Last search: ${new Date(status.last_run_at).toLocaleString()} (${status.last_run_trigger})`
              : "No searches run yet"}
            {status && (
              <> · {status.jobs_total} jobs · {status.jobs_analyzed} analyzed
              {!status.ai_enabled && <span className="badge" style={{ marginLeft: 8 }}>AI: stub</span>}</>
            )}
          </div>
          <div className="row">
            <button className="secondary" onClick={analyzeExisting} disabled={busy}
                    title="Score already-collected jobs against the current CV (run this after uploading a new CV)">
              {busy ? "Working…" : "Analyze jobs vs CV"}
            </button>
            <button onClick={runNow} disabled={busy}>
              {busy ? "Running…" : "Run search now"}
            </button>
          </div>
        </div>
        {status && status.errors.length > 0 && (
          <div className="error detail">
            {status.errors.length} source error(s) in last run.
          </div>
        )}
      </div>

      <div className="panel filters">
        <div className="row">
          <input placeholder="Min score" value={minScore}
                 onChange={(e) => setMinScore(e.target.value)} type="number" min={0} max={100} />
          <input placeholder="Location" value={location}
                 onChange={(e) => setLocation(e.target.value)} />
          <input placeholder="Company" value={company}
                 onChange={(e) => setCompany(e.target.value)} />
          <input placeholder="Language (e.g. en)" value={language}
                 onChange={(e) => setLanguage(e.target.value)} />
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All statuses</option>
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <button className="secondary" onClick={load}>Apply</button>
        </div>
      </div>

      {err && <div className="panel error">{err}</div>}

      <div className="panel">
        <div className="legend" style={{ marginBottom: 12 }}>
          <span>Analysis:</span>
          <span><span className="astate current" />current CV</span>
          <span><span className="astate outdated" />older CV</span>
          <span><span className="astate error" />failed</span>
          <span><span className="astate none" />not analyzed</span>
        </div>
        <table>
          <thead>
            <tr>
              <th>Score</th><th>Title</th><th>Company</th><th>Location</th>
              <th>Lang</th><th>Status</th><th>Found</th><th></th>
            </tr>
          </thead>
          <tbody>
            {jobs.length === 0 && (
              <tr><td colSpan={8} className="muted">No jobs yet. Run a search.</td></tr>
            )}
            {jobs.map((j) => (
              <Fragment key={j.id}>
                <tr>
                  <td>
                    <span
                      className={`astate ${ANALYSIS_STATE[j.analysis_state]?.cls || "none"}`}
                      title={ANALYSIS_STATE[j.analysis_state]?.label || ""}
                    />
                    <span className={`score ${scoreClass(j.match_score)}`}>
                      {j.match_score ?? "—"}
                    </span>
                  </td>
                  <td>
                    {j.url ? <a href={j.url} target="_blank" rel="noreferrer">{j.title}</a> : j.title}
                    <div className="muted" style={{ fontSize: 12 }}>{j.source}</div>
                  </td>
                  <td>{j.company || "—"}</td>
                  <td>{j.location || "—"}</td>
                  <td>{j.language || "—"}</td>
                  <td>
                    <select value={j.status} onChange={(e) => setJobStatus(j.id, e.target.value)}>
                      {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                  </td>
                  <td className="muted">{new Date(j.discovered_at).toLocaleDateString()}</td>
                  <td>
                    <button className="secondary"
                            onClick={() => setExpanded(expanded === j.id ? null : j.id)}>
                      {expanded === j.id ? "Hide" : "Details"}
                    </button>
                  </td>
                </tr>
                {expanded === j.id && (
                  <tr>
                    <td colSpan={8}>
                      {j.translated_summary && (
                        <p><strong>Summary:</strong> {j.translated_summary}</p>
                      )}
                      {j.explanation && <p><strong>Why:</strong> {j.explanation}</p>}
                      {j.matching_skills && j.matching_skills.length > 0 && (
                        <p><strong>Matching:</strong>{" "}
                          {j.matching_skills.map((s) => <span key={s} className="chip">{s}</span>)}</p>
                      )}
                      {j.missing_requirements && j.missing_requirements.length > 0 && (
                        <p><strong>Missing:</strong>{" "}
                          {j.missing_requirements.map((s) => <span key={s} className="chip">{s}</span>)}</p>
                      )}
                      <button className="secondary" onClick={() => reanalyze(j.id)}>
                        Re-analyze
                      </button>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
