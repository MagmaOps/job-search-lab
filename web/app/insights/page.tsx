"use client";

import { useCallback, useEffect, useState } from "react";
import { api, Insights } from "@/lib/api";

const SEVERITY_META: Record<string, { cls: string; label: string }> = {
  basic: { cls: "gap-basic", label: "basic" },
  average: { cls: "gap-average", label: "average" },
};

export default function InsightsPage() {
  const [data, setData] = useState<Insights | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setErr(null);
    try {
      setData(await api.insights());
    } catch (e) {
      setErr(String(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function refresh() {
    setBusy(true);
    setErr(null);
    try {
      setData(await api.refreshInsights());
    } catch (e) {
      setErr(String(e).replace(/^Error:\s*\d+\s*[^:]*:\s*/, ""));
    } finally {
      setBusy(false);
    }
  }

  async function clear() {
    if (!confirm("Clear the saved insights snapshot? This cannot be undone.")) return;
    setBusy(true);
    setErr(null);
    try {
      await api.clearInsights();
      setData(null);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  const items = data?.items ?? [];

  return (
    <>
      <h1>Insights</h1>

      <div className="panel muted">
        Skills and tech most often required by jobs you&apos;ve analyzed that your CV does
        not cover, ranked by how many postings asked for them. A{" "}
        <span className="chip gap-basic">basic</span> or{" "}
        <span className="chip gap-average">average</span> tag marks gaps that are baseline or
        common for the role, so they&apos;re the highest-leverage things to learn. This is a
        saved snapshot: it updates only when you click Refresh, and it is never cleared
        automatically.
      </div>

      <div className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="muted">
            {data
              ? `${data.jobs_analyzed} analyzed job(s) · ${items.length} distinct gap(s) · computed ${new Date(data.computed_at).toLocaleString()}`
              : data === null
                ? "No snapshot yet. Click Refresh to compute from your analyzed jobs."
                : "Loading…"}
          </div>
          <div className="row">
            <button onClick={refresh} disabled={busy}>
              {busy ? "Working…" : "Refresh insights"}
            </button>
            {data && (
              <button className="secondary" onClick={clear} disabled={busy}>
                Clear
              </button>
            )}
          </div>
        </div>
        {data?.stale_cv && (
          <div className="detail" style={{ color: "var(--warn)" }}>
            This snapshot was computed against a previous CV. Refresh to update it against
            the active CV.
          </div>
        )}
        {data && data.grouping === "deterministic" && data.grouping_error && (
          <div className="detail" style={{ color: "var(--bad)" }}>
            <strong>AI grouping did not run:</strong> {data.grouping_error}
            <br />
            <span className="muted">
              Skill variants may appear as separate rows. Check the API pod has
              ANTHROPIC_API_KEY set and the <code>insights_canonicalize</code> prompt is
              registered, then Refresh again.
            </span>
          </div>
        )}
        {data && data.grouping === "ai" && (
          <div className="detail" style={{ color: "var(--good)" }}>
            AI semantic grouping applied — semantic duplicates merged.
          </div>
        )}
      </div>

      {err && <div className="panel error">{err}</div>}

      {data && items.length > 0 && (
        <div className="panel">
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Skill / tech</th>
                  <th>Asked in</th>
                  <th>Severity</th>
                  <th>Why it matters</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => (
                  <tr key={it.skill}>
                    <td><strong>{it.skill}</strong></td>
                    <td>{it.count} job{it.count === 1 ? "" : "s"}</td>
                    <td>
                      {it.severity ? (
                        <span className={`chip ${SEVERITY_META[it.severity]?.cls}`}>
                          {SEVERITY_META[it.severity]?.label}
                        </span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td className="muted">{it.why || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {data && items.length === 0 && (
        <div className="panel muted">
          No gaps found across your analyzed jobs — either nothing is missing, or no jobs
          have been analyzed against the active CV yet.
        </div>
      )}
    </>
  );
}
