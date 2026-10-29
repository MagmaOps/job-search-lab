"use client";

import { useEffect, useState } from "react";
import { api, Query } from "@/lib/api";

const SOURCES = ["rss", "remoteok", "remotive", "arbeitnow", "linkedin"];

export default function QueriesPage() {
  const [queries, setQueries] = useState<Query[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // new-query form
  const [name, setName] = useState("");
  const [source, setSource] = useState("remoteok");
  const [configJson, setConfigJson] = useState('{"tag": "devops"}');

  async function load() {
    setErr(null);
    try {
      setQueries(await api.queries());
    } catch (e) {
      setErr(String(e));
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function toggle(q: Query) {
    await api.updateQuery(q.id, { enabled: !q.enabled });
    load();
  }

  async function remove(q: Query) {
    if (!confirm(`Delete query "${q.name}"?`)) return;
    await api.deleteQuery(q.id);
    load();
  }

  async function run(q: Query) {
    setBusy(true);
    setErr(null);
    try {
      const res = await api.runQuery(q.id);
      alert(
        `Found ${res.jobs_found}, new ${res.jobs_new}, analyzed ${res.analyzed}.`
      );
      load();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function create() {
    setErr(null);
    let cfg: Record<string, unknown> = {};
    try {
      cfg = configJson.trim() ? JSON.parse(configJson) : {};
    } catch {
      setErr("Source config is not valid JSON.");
      return;
    }
    try {
      await api.createQuery({ name, source, source_config: cfg, enabled: true });
      setName("");
      setConfigJson('{"tag": "devops"}');
      load();
    } catch (e) {
      setErr(String(e));
    }
  }

  return (
    <>
      <h1>Search Queries</h1>

      {err && <div className="panel error">{err}</div>}

      <div className="panel">
        <table>
          <thead>
            <tr>
              <th>Name</th><th>Source</th><th>Config</th><th>Enabled</th><th></th>
            </tr>
          </thead>
          <tbody>
            {queries.map((q) => (
              <tr key={q.id}>
                <td>
                  {q.name}
                  {q.reference_url && (
                    <div style={{ fontSize: 12 }}>
                      <a href={q.reference_url} target="_blank" rel="noreferrer">
                        reference link
                      </a>
                    </div>
                  )}
                </td>
                <td>
                  {q.source}
                  {q.source === "linkedin" && (
                    <span className="badge" style={{ marginLeft: 6 }}>manual</span>
                  )}
                </td>
                <td className="muted" style={{ fontSize: 12, maxWidth: 260 }}>
                  {JSON.stringify(q.source_config)}
                </td>
                <td>
                  <input type="checkbox" checked={q.enabled} onChange={() => toggle(q)} />
                </td>
                <td>
                  <div className="row">
                    {q.source !== "linkedin" && (
                      <button className="secondary" disabled={busy} onClick={() => run(q)}>
                        Run
                      </button>
                    )}
                    <button className="secondary" onClick={() => remove(q)}>Delete</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h2>Add query</h2>
        <div className="field">
          <label>Name</label>
          <input value={name} onChange={(e) => setName(e.target.value)}
                 style={{ width: "100%" }} />
        </div>
        <div className="field">
          <label>Source</label>
          <select value={source} onChange={(e) => setSource(e.target.value)}>
            {SOURCES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div className="field">
          <label>Source config (JSON)</label>
          <textarea value={configJson} onChange={(e) => setConfigJson(e.target.value)}
                    rows={3} style={{ width: "100%" }} />
        </div>
        <button onClick={create} disabled={!name}>Add query</button>
      </div>
    </>
  );
}
