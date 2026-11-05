"use client";

import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { api, Application, Job, ManualJobIn, Status } from "@/lib/api";

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
  stale: { cls: "outdated", label: "The description changed since this score — re-analyze for an up-to-date score" },
  error: { cls: "error", label: "Last analysis failed — try re-analyze" },
  none: { cls: "none", label: "Not analyzed against the current CV" },
  pending: { cls: "pending", label: "Queued — the worker is analyzing this job" },
  incomplete: { cls: "incomplete", label: "Description looks truncated — not analyzed until you paste the full posting" },
};

// Application-generation indicator vs the active CV. Mirrors the analysis-state dot.
const APPLICATION_STATE: Record<string, { cls: string; label: string; short: string }> = {
  none: { cls: "none", label: "No application generated yet", short: "—" },
  pending: { cls: "pending", label: "Queued — the worker is drafting the application", short: "drafting…" },
  done: { cls: "current", label: "Application ready — open Details to view and edit", short: "ready" },
  error: { cls: "error", label: "Application generation failed — open Details to retry", short: "failed" },
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

function ApplicationPanel({ jobId }: { jobId: number }) {
  const [app, setApp] = useState<Application | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // Local editable copies so the user can tweak the draft before sending it out.
  const [cover, setCover] = useState("");
  const [summary, setSummary] = useState("");
  const [full, setFull] = useState("");
  const [saved, setSaved] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const syncLocal = useCallback((a: Application | null) => {
    setApp(a);
    setCover(a?.cover_letter_md ?? "");
    setSummary(a?.cv_summary_md ?? "");
    setFull(a?.cv_full_md ?? "");
  }, []);

  const load = useCallback(async () => {
    try {
      const a = await api.getApplication(jobId);
      syncLocal(a);
    } catch (e) {
      setErr(String(e));
    }
  }, [jobId, syncLocal]);

  useEffect(() => {
    load();
  }, [load]);

  // Poll while the worker is generating, so the draft appears on its own.
  const pending = app?.processing_status === "pending";
  useEffect(() => {
    if (!pending) {
      if (pollRef.current) clearInterval(pollRef.current);
      return;
    }
    pollRef.current = setInterval(load, 3000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [pending, load]);

  async function generate() {
    setBusy(true);
    setErr(null);
    try {
      const a = await api.generateApplication(jobId);
      syncLocal(a); // flips to pending; polling clears it as the worker finishes
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    setBusy(true);
    setErr(null);
    try {
      const a = await api.updateApplication(jobId, {
        cover_letter_md: cover,
        cv_summary_md: summary,
        cv_full_md: full,
      });
      syncLocal(a);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (app === undefined) return <p className="muted">Loading application…</p>;

  const dirty =
    app?.processing_status === "done" &&
    (cover !== (app.cover_letter_md ?? "") ||
      summary !== (app.cv_summary_md ?? "") ||
      full !== (app.cv_full_md ?? ""));

  return (
    <div className="application">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>Application</strong>
        <button className="secondary" onClick={generate} disabled={busy || pending}>
          {pending ? "Generating…" : app ? "Regenerate" : "Generate application"}
        </button>
      </div>
      {err && <div className="error detail">{err}</div>}
      {!app && !pending && (
        <p className="muted">
          No application yet. Generate a tailored cover letter and CV summary for this job.
        </p>
      )}
      {pending && (
        <p className="analyzing">
          <span className="spinner" />
          <span className="muted">The worker is drafting and reviewing — you can leave this page.</span>
        </p>
      )}
      {app?.processing_status === "error" && (
        <div className="error detail">Generation failed: {app.error_message}</div>
      )}
      {app?.processing_status === "done" && (
        <>
          <label>Cover letter (Markdown)</label>
          <textarea
            value={cover}
            onChange={(e) => setCover(e.target.value)}
            rows={14}
            style={{ width: "100%", fontFamily: "monospace", fontSize: 13 }}
          />
          <label>CV summary (Markdown)</label>
          <textarea
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            rows={10}
            style={{ width: "100%", fontFamily: "monospace", fontSize: 13 }}
          />
          <label>Full tailored CV (Markdown — ready to render to PDF)</label>
          <textarea
            value={full}
            onChange={(e) => setFull(e.target.value)}
            rows={20}
            style={{ width: "100%", fontFamily: "monospace", fontSize: 13 }}
          />
          {app.reviewer_notes && (
            <details className="reviewer-notes">
              <summary>Reviewer notes</summary>
              <pre style={{ whiteSpace: "pre-wrap" }}>{app.reviewer_notes}</pre>
            </details>
          )}
          <div className="row" style={{ marginTop: 8 }}>
            <button onClick={save} disabled={!dirty || busy}>
              {busy ? "Saving…" : "Save edits"}
            </button>
            {saved && <span className="muted">Saved.</span>}
            {app.model && <span className="muted" style={{ marginLeft: "auto" }}>model: {app.model}</span>}
          </div>
        </>
      )}
    </div>
  );
}

function DescriptionEditor({
  jobId,
  incomplete,
  hasScore,
  onSaved,
}: {
  jobId: number;
  incomplete: boolean;
  hasScore: boolean;
  onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [value, setValue] = useState("");
  const [original, setOriginal] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  // Lazy-load the full description only when the editor is first opened — keeps the list
  // payload lean (descriptions can be large, and we edit one job at a time).
  const toggle = useCallback(async () => {
    const next = !open;
    setOpen(next);
    if (next && !loaded) {
      const d = await api.getJob(jobId);
      setValue(d.description ?? "");
      setOriginal(d.description ?? "");
      setLoaded(true);
    }
  }, [open, loaded, jobId]);

  // A truncated job's whole point is to be fixed here, so open the editor straight away.
  useEffect(() => {
    if (incomplete && !open && !loaded) toggle();
    // Only on mount / when the job becomes incomplete — not on every toggle.
  }, [incomplete]);

  async function save() {
    setBusy(true);
    setMsg(null);
    try {
      await api.setJobDescription(jobId, value);
      setOriginal(value);
      setMsg(
        hasScore
          ? "Saved. Re-analyze to score against the full text."
          : "Saved. The worker will analyze it shortly."
      );
      onSaved(); // refresh the list so the analysis indicator flips to not-current
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  const dirty = loaded && value !== original;

  return (
    <div style={{ marginTop: 10 }}>
      <button className="secondary" onClick={toggle}>
        {open ? "Hide full description" : "Edit full description"}
      </button>
      {open && (
        <div style={{ marginTop: 8 }}>
          <p className="muted" style={{ fontSize: 12 }}>
            Paste the complete posting text here. It replaces the stored description. This
            does not re-score automatically — Re-analyze when you&apos;re ready.
          </p>
          {!loaded ? (
            <span className="muted">Loading…</span>
          ) : (
            <textarea
              value={value}
              onChange={(e) => setValue(e.target.value)}
              rows={12}
              style={{ width: "100%", fontFamily: "monospace", fontSize: 13 }}
            />
          )}
          <div className="row" style={{ marginTop: 6 }}>
            <button onClick={save} disabled={!dirty || busy}>
              {busy ? "Saving…" : "Save description"}
            </button>
            {msg && <span className="muted">{msg}</span>}
          </div>
        </div>
      )}
    </div>
  );
}

const EMPTY_MANUAL: ManualJobIn = {
  title: "", url: "", company: "", location: "", work_type: "", salary: "", description: "",
};

function ManualJobForm({ onAdded }: { onAdded: (msg: string) => void }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<ManualJobIn>(EMPTY_MANUAL);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const set = (k: keyof ManualJobIn) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
      setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit() {
    setBusy(true);
    setErr(null);
    try {
      // Send only the fields you filled in.
      const body = Object.fromEntries(
        Object.entries(form).filter(([, v]) => (v ?? "").trim() !== "")
      ) as ManualJobIn;
      const job = await api.addManual(body);
      setForm(EMPTY_MANUAL);
      setOpen(false);
      onAdded(
        job.description_incomplete
          ? `Added "${job.title}". It has no description yet — paste one in Details to get it scored.`
          : `Added "${job.title}" — queued for analysis.`
      );
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button className="secondary" onClick={() => setOpen(true)}>
        + Add job manually
      </button>
    );
  }

  const canSubmit = !!(form.title?.trim() || form.url?.trim());

  return (
    <div className="panel">
      <strong>Add a job manually</strong>
      <div className="row" style={{ marginTop: 8 }}>
        <input placeholder="Title *" value={form.title} onChange={set("title")} style={{ minWidth: 240 }} />
        <input placeholder="Company" value={form.company} onChange={set("company")} />
        <input placeholder="Location" value={form.location} onChange={set("location")} />
        <select value={form.work_type} onChange={set("work_type")}>
          <option value="">Work type</option>
          {WORK_TYPES.map((w) => <option key={w} value={w}>{WORK_TYPE_LABEL[w]}</option>)}
        </select>
        <input placeholder="Salary" value={form.salary} onChange={set("salary")} />
      </div>
      <div className="row" style={{ marginTop: 6 }}>
        <input placeholder="Posting URL (optional)" value={form.url} onChange={set("url")}
               style={{ flex: 1 }} />
      </div>
      <label style={{ marginTop: 8 }}>Full job description</label>
      <textarea
        value={form.description}
        onChange={set("description")}
        rows={10}
        placeholder="Paste the complete posting. Without it, the job is saved but not scored."
        style={{ width: "100%", fontFamily: "monospace", fontSize: 13 }}
      />
      {err && <div className="error detail">{err}</div>}
      <div className="row" style={{ marginTop: 6 }}>
        <button onClick={submit} disabled={!canSubmit || busy}>
          {busy ? "Adding…" : "Add job"}
        </button>
        <button className="secondary" onClick={() => { setOpen(false); setErr(null); }}>
          Cancel
        </button>
        <span className="muted" style={{ fontSize: 12 }}>A title or a URL is required.</span>
      </div>
    </div>
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
  const [salaryFilter, setSalaryFilter] = useState(""); // "" | "yes" | "no"
  const [appFilter, setAppFilter] = useState(""); // "" | "yes" | "no"
  const [descFilter, setDescFilter] = useState(""); // "" | "incomplete" | "complete"
  const [sourceFilter, setSourceFilter] = useState("");
  const [sources, setSources] = useState<string[]>([]);
  const [showRemoved, setShowRemoved] = useState(false); // review list of removed jobs

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
      if (salaryFilter) params.has_salary = salaryFilter === "yes" ? "true" : "false";
      if (appFilter) params.has_application = appFilter === "yes" ? "true" : "false";
      if (descFilter) params.description_incomplete = descFilter === "incomplete" ? "true" : "false";
      if (sourceFilter) params.source = sourceFilter;
      if (showRemoved) params.removed = "true";
      const [j, s, src] = await Promise.all([api.jobs(params), api.status(), api.jobSources()]);
      setJobs(j);
      setStatus(s);
      setSources(src);
    } catch (e) {
      setErr(String(e));
    }
  }, [minScore, location, company, language, workType, eligibility, statusFilter,
      salaryFilter, appFilter, descFilter, sourceFilter, showRemoved]);

  const incompleteCount = jobs.filter((j) => j.description_incomplete).length;

  useEffect(() => {
    load();
  }, [load]);

  // While any job is queued/analyzing, poll so spinners resolve on their own — the worker
  // does the analysis, so this reflects its progress even if the page was just reopened.
  const hasPending = jobs.some(
    (j) => j.analysis_state === "pending" || j.application_state === "pending"
  );
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

  async function setRemoved(j: Job, removed: boolean) {
    const verb = removed ? "Remove" : "Restore";
    const note = removed
      ? "It is hidden from the dashboard but kept in the database; you can restore it later."
      : "It returns to the normal dashboard.";
    if (!window.confirm(`${verb} "${j.title}"?\n\n${note}`)) return;
    try {
      await api.setJobRemoved(j.id, removed);
      if (expanded === j.id) setExpanded(null);
      await load();
    } catch (e) {
      setErr(String(e));
    }
  }

  async function saveSalary(id: number, salary: string) {
    try {
      await api.setJobSalary(id, salary);
      await load();
    } catch (e) {
      setErr(String(e));
    }
  }

  async function setDescriptionIncomplete(id: number, value: boolean) {
    try {
      await api.setDescriptionIncomplete(id, value);
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
              · <button className="linklike" onClick={() => setShowRemoved(!showRemoved)}
                        title="Removed jobs are hidden but kept; click to review or restore them">
                  {status.jobs_removed} removed{showRemoved ? " (hide)" : " (review)"}
                </button>
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
        {incompleteCount > 0 && descFilter !== "incomplete" && (
          <div className="detail" style={{ marginTop: 6 }}>
            <span className="chip desc-incomplete">⚠ {incompleteCount} job(s) need a full description</span>{" "}
            <button className="secondary" onClick={() => setDescFilter("incomplete")}>
              Show them
            </button>
          </div>
        )}
        <div style={{ marginTop: 8 }}>
          <ManualJobForm onAdded={(m) => { setMsg(m); load(); }} />
        </div>
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
          <select value={salaryFilter} onChange={(e) => setSalaryFilter(e.target.value)}
                  title="Filter by whether a salary is recorded">
            <option value="">Any salary</option>
            <option value="yes">Has salary</option>
            <option value="no">No salary</option>
          </select>
          <select value={appFilter} onChange={(e) => setAppFilter(e.target.value)}
                  title="Filter by whether an application was generated">
            <option value="">Any application</option>
            <option value="yes">Has application</option>
            <option value="no">No application</option>
          </select>
          <select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}
                  title="Filter by where the job came from">
            <option value="">All sources</option>
            {sources.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select value={descFilter} onChange={(e) => setDescFilter(e.target.value)}
                  title="Filter by whether the description looks truncated">
            <option value="">Any description</option>
            <option value="incomplete">Needs full description</option>
            <option value="complete">Description complete</option>
          </select>
          <button className="secondary" onClick={load}>Apply</button>
        </div>
      </div>

      {showRemoved && (
        <div className="panel detail">
          Showing <strong>removed</strong> jobs only. Restore one to return it to the dashboard.{" "}
          <button className="secondary" onClick={() => setShowRemoved(false)}>Back to dashboard</button>
        </div>
      )}
      {msg && <div className="panel">{msg}</div>}
      {err && <div className="panel error">{err}</div>}

      <div className="panel">
        <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Score</th><th>Title</th><th>Company</th><th>Location</th>
              <th>Type</th><th>Eligibility</th><th>Salary</th><th>Lang</th>
              <th>Status</th><th>App</th><th>Found</th><th></th>
            </tr>
          </thead>
          <tbody>
            {jobs.length === 0 && (
              <tr><td colSpan={12} className="muted">
                {showRemoved ? "No removed jobs." : "No jobs yet. Run a search."}
              </td></tr>
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
                    <div className="muted" style={{ fontSize: 12 }}>
                      {j.source}
                      {j.description_incomplete && (
                        <span
                          className="chip desc-incomplete"
                          title={ANALYSIS_STATE.incomplete.label}
                          onClick={() => setExpanded(j.id)}
                          style={{ cursor: "pointer", marginLeft: 6 }}
                        >
                          ⚠ needs full description
                        </span>
                      )}
                    </div>
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
                  <td>
                    {j.application_state === "pending" ? (
                      <span className="analyzing" title={APPLICATION_STATE.pending.label}>
                        <span className="spinner" />
                        <span className="muted" style={{ fontSize: 12 }}>drafting…</span>
                      </span>
                    ) : (
                      <span
                        className={`chip app-${j.application_state}`}
                        title={APPLICATION_STATE[j.application_state]?.label || ""}
                        onClick={() => setExpanded(expanded === j.id ? null : j.id)}
                        style={{ cursor: "pointer" }}
                      >
                        {APPLICATION_STATE[j.application_state]?.short ?? "—"}
                      </span>
                    )}
                  </td>
                  <td className="muted">{new Date(j.discovered_at).toLocaleDateString()}</td>
                  <td>
                    <button className="secondary"
                            onClick={() => setExpanded(expanded === j.id ? null : j.id)}>
                      {expanded === j.id ? "Hide" : "Details"}
                    </button>{" "}
                    <button className="secondary" onClick={() => setRemoved(j, !j.removed)}
                            title={j.removed ? "Return this job to the dashboard"
                                             : "Hide this job (gone online / not relevant)"}>
                      {j.removed ? "Restore" : "Remove"}
                    </button>
                  </td>
                </tr>
                {expanded === j.id && (
                  <tr>
                    <td colSpan={12}>
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
                      {j.learning_gaps && j.learning_gaps.length > 0 && (
                        <div className="gaps">
                          <strong>Gaps to close (learn first):</strong>
                          <ul>
                            {j.learning_gaps.map((g) => (
                              <li key={g.skill}>
                                <span className={`chip gap-${g.level}`}>{g.level}</span>{" "}
                                <strong>{g.skill}</strong>
                                {g.why ? <span className="muted"> — {g.why}</span> : null}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      <div className="row" style={{ marginBottom: 10 }}>
                        <SalaryEditor job={j} onSave={saveSalary} />
                      </div>
                      {j.description_incomplete && (
                        <p className="desc-incomplete-note">
                          ⚠ This description looks truncated, so the job is not scored. Paste
                          the complete posting below — or, if it really is complete, mark it so.
                        </p>
                      )}
                      <DescriptionEditor
                        jobId={j.id}
                        incomplete={j.description_incomplete}
                        hasScore={j.match_score !== null}
                        onSaved={load}
                      />
                      <div className="row" style={{ marginTop: 6 }}>
                        <button className="secondary" onClick={() => reanalyze(j.id)}
                                disabled={j.analysis_state === "pending" || j.description_incomplete}
                                title={j.description_incomplete ? "Fix the description first" : ""}>
                          {j.analysis_state === "pending" ? "Analyzing…" : "Re-analyze"}
                        </button>
                        <button className="secondary"
                                onClick={() => setDescriptionIncomplete(j.id, !j.description_incomplete)}
                                title={j.description_incomplete
                                  ? "The description is short but complete — allow it to be scored"
                                  : "The description is cut off — hold it back from scoring"}>
                          {j.description_incomplete ? "Mark description complete" : "Mark description incomplete"}
                        </button>
                      </div>
                      <hr style={{ margin: "14px 0", border: "none", borderTop: "1px solid #e5e7eb" }} />
                      <ApplicationPanel jobId={j.id} />
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
