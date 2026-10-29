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
const WORK_TYPES = ["remote", "hybrid", "onsite"];

const WORK_TYPE_LABEL: Record<string, string> = {
  remote: "Remote",
  hybrid: "Hybrid",
  onsite: "On-site",
};

const ELIGIBILITY = ["worldwide", "restricted", "unclear"];

const ELIGIBILITY_META: Record<string, { cls: string; label: string }> = {
  worldwide: { cls: "elig-worldwide", label: "Worldwide" },
  restricted: { cls: "elig-restricted", label: "Restricted" },
  unclear: { cls: "elig-unclear", label: "Unclear" },
};

const ANALYSIS_STATE: Record<string, { cls: string; label: string }> = {
  current: { cls: "current", label: "Analyzed against the current CV" },
  outdated: { cls: "outdated", label: "Analyzed against an older CV — re-analyze for an up-to-date score" },
  error: { cls: "error", label: "Last analysis failed — try re-analyze" },
  none: { cls: "none", label: "Not analyzed against the current CV" },
  pending: { cls: "pending", label: "Queued — the worker is analyzing this job" },
};

function SalaryEditor({
  job,
  onSave,
}: {
  job: Job;
  onSave: (id: number, salary: string) => Promise<void>;
}) {
  const [value, setValue] = useState(job.salary ?? "");
  const [saving, setSaving] = useState(false);
  const dirty = (job.salary ?? "") !== value;

  async function save() {
    setSaving(true);
    await onSave(job.id, value);
    setSaving(false);
  }

  return (
    <span className="salary-editor">
      <label style={{ display: "inline" }}>Salary:</label>{" "}
      <input
        value={value}
        placeholder="e.g. EUR 70,000 – 90,000/year"
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && dirty) save();
        }}
        style={{ width: 240 }}
      />
      <button className="secondary" onClick={save} disabled={!dirty || saving}
              style={{ marginLeft: 6 }}>
        {saving ? "Saving…" : "Save"}
      </button>
      {job.salary && (
        <button className="secondary" onClick={() => onSave(job.id, "")}
                title="Clear the salary" style={{ marginLeft: 6 }}>
          Clear
        </button>
      )}
    </span>
  );
}

export default function Dashboard() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const [minScore, setMinScore] = useState("");
  const [location, setLocation] = useState("");
  const [company, setCompany] = useState("");
  const [language, setLanguage] = useState("");
  const [workType, setWorkType] = useState("");
  const [eligibility, setEligibility] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const load = useCallback(async () => {
    setErr(null);
    try {
      const params: Record<string, string> = {};
      if (minScore) params.min_score = minScore;
      if (location) params.location = location;
      if (company) params.company = company;
      if (language) params.language = language;
      if (workType) params.work_type = workType;
      if (eligibility) params.eligibility = eligibility;
      if (statusFilter) params.status = statusFilter;
      const [j, s] = await Promise.all([api.jobs(params), api.status()]);
      setJobs(j);
      setStatus(s);
    } catch (e) {
      setErr(String(e));
    }
  }, [minScore, location, company, language, workType, eligibility, statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  // While any job is queued/analyzing, poll so spinners resolve on their own — the worker
  // does the analysis, so this reflects its progress even if the page was just reopened.
  const hasPending = jobs.some((j) => j.analysis_state === "pending");
  useEffect(() => {
    if (!hasPending) return;
    const t = setInterval(() => load(), 3000);
    return () => clearInterval(t);
  }, [hasPending, load]);

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
      const res = await api.analyze();
      await load(); // jobs flip to "pending"; polling clears them as the worker finishes
      setMsg(`Queued ${res.queued} job(s) for analysis. They'll update as the worker processes them — you can leave this page.`);
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

  async function saveSalary(id: number, salary: string) {
    try {
      await api.setJobSalary(id, salary);
      await load();
    } catch (e) {
      setErr(String(e));
    }
  }

  async function reanalyze(id: number) {
    // Optimistically show the spinner immediately; the worker does the actual analysis, so
    // it completes even if this tab is closed. Polling will flip it to a score when done.
    setJobs((prev) => prev.map((j) => (j.id === id ? { ...j, analysis_state: "pending" } : j)));
    try {
      await api.reanalyze(id);
    } catch (e) {
      setErr(String(e));
    }
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
          <select value={workType} onChange={(e) => setWorkType(e.target.value)}>
            <option value="">All work types</option>
            {WORK_TYPES.map((w) => <option key={w} value={w}>{WORK_TYPE_LABEL[w]}</option>)}
          </select>
          <select value={eligibility} onChange={(e) => setEligibility(e.target.value)}>
            <option value="">All eligibility</option>
            {ELIGIBILITY.map((el) => <option key={el} value={el}>{ELIGIBILITY_META[el].label}</option>)}
          </select>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All statuses</option>
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <button className="secondary" onClick={load}>Apply</button>
        </div>
      </div>

      {msg && <div className="panel">{msg}</div>}
      {err && <div className="panel error">{err}</div>}

      <div className="panel">
        <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Score</th><th>Title</th><th>Company</th><th>Location</th>
              <th>Type</th><th>Eligibility</th><th>Salary</th><th>Lang</th>
              <th>Status</th><th>Found</th><th></th>
            </tr>
          </thead>
          <tbody>
            {jobs.length === 0 && (
              <tr><td colSpan={11} className="muted">No jobs yet. Run a search.</td></tr>
            )}
            {jobs.map((j) => (
              <Fragment key={j.id}>
                <tr>
                  <td>
                    {j.analysis_state === "pending" ? (
                      <span className="analyzing" title={ANALYSIS_STATE.pending.label}>
                        <span className="spinner" />
                        <span className="muted" style={{ fontSize: 12 }}>analyzing…</span>
                      </span>
                    ) : (
                      <>
                        <span
                          className={`astate ${ANALYSIS_STATE[j.analysis_state]?.cls || "none"}`}
                          title={ANALYSIS_STATE[j.analysis_state]?.label || ""}
                        />
                        <span className={`score ${scoreClass(j.match_score)}`}>
                          {j.match_score ?? "—"}
                        </span>
                      </>
                    )}
                  </td>
                  <td>
                    {j.url ? <a href={j.url} target="_blank" rel="noreferrer">{j.title}</a> : j.title}
                    <div className="muted" style={{ fontSize: 12 }}>{j.source}</div>
                  </td>
                  <td>{j.company || "—"}</td>
                  <td>{j.location || "—"}</td>
                  <td>
                    {j.work_type
                      ? <span className={`chip wt-${j.work_type}`}>{WORK_TYPE_LABEL[j.work_type] || j.work_type}</span>
                      : <span className="muted">—</span>}
                  </td>
                  <td>
                    {j.eligibility ? (
                      <span className={`chip ${ELIGIBILITY_META[j.eligibility]?.cls}`}
                            title={j.eligibility_note || ""}>
                        {ELIGIBILITY_META[j.eligibility]?.label}
                        {j.posting_country ? ` · ${j.posting_country}` : ""}
                      </span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td className="muted" style={{ fontSize: 13 }}>{j.salary || "—"}</td>
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
                    <td colSpan={11}>
                      {j.translated_summary && (
                        <p><strong>Summary:</strong> {j.translated_summary}</p>
                      )}
                      {j.explanation && <p><strong>Why:</strong> {j.explanation}</p>}
                      {(j.eligibility || j.posting_country) && (
                        <p>
                          <strong>Where / eligibility:</strong>{" "}
                          {j.posting_country ? `${j.posting_country} · ` : ""}
                          {j.eligibility ? ELIGIBILITY_META[j.eligibility]?.label : "—"}
                          {j.eligibility_note ? ` — ${j.eligibility_note}` : ""}
                        </p>
                      )}
                      {j.dimension_scores && j.dimension_scores.length > 0 && (
                        <div className="breakdown">
                          <strong>Score breakdown:</strong>
                          <table className="dims">
                            <tbody>
                              {j.dimension_scores.map((d) => (
                                <tr key={d.dimension}>
                                  <td className="dim-name">{d.dimension}</td>
                                  <td className="dim-bar">
                                    <span className={`bar ${scoreClass(d.score)}`}
                                          style={{ width: `${d.score}%` }} />
                                  </td>
                                  <td className="dim-score">{d.score}</td>
                                  <td className="dim-weight muted">{Math.round(d.weight * 100)}%</td>
                                  <td className="dim-reason muted">{d.reason}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                      {j.matching_skills && j.matching_skills.length > 0 && (
                        <p><strong>Matching:</strong>{" "}
                          {j.matching_skills.map((s) => <span key={s} className="chip">{s}</span>)}</p>
                      )}
                      {j.missing_requirements && j.missing_requirements.length > 0 && (
                        <p><strong>Missing:</strong>{" "}
                          {j.missing_requirements.map((s) => <span key={s} className="chip">{s}</span>)}</p>
                      )}
                      <div className="row" style={{ marginBottom: 10 }}>
                        <SalaryEditor job={j} onSave={saveSalary} />
                      </div>
                      <button className="secondary" onClick={() => reanalyze(j.id)}
                              disabled={j.analysis_state === "pending"}>
                        {j.analysis_state === "pending" ? "Analyzing…" : "Re-analyze"}
                      </button>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
        </div>
      </div>
    </>
  );
}
