"use client";

import { useEffect, useState } from "react";
import { api, Prompt } from "@/lib/api";

function PromptEditor({ prompt, onChanged }: { prompt: Prompt; onChanged: () => void }) {
  const [text, setText] = useState(prompt.template);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const dirty = text !== prompt.template;

  async function save() {
    setBusy(true);
    setMsg(null);
    setErr(null);
    try {
      await api.updatePrompt(prompt.key, text);
      setMsg("Saved. New analyses will use this prompt.");
      onChanged();
    } catch (e) {
      setErr(String(e).replace(/^Error:\s*\d+\s*[^:]*:\s*/, ""));
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    if (!confirm(`Reset "${prompt.label}" to the built-in default?`)) return;
    setBusy(true);
    setMsg(null);
    setErr(null);
    try {
      const p = await api.resetPrompt(prompt.key);
      setText(p.template);
      setMsg("Reset to default.");
      onChanged();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>
          {prompt.label}{" "}
          {prompt.is_customized ? (
            <span className="badge" style={{ background: "rgba(79,156,249,0.2)", color: "var(--accent)" }}>
              customized
            </span>
          ) : (
            <span className="badge">default</span>
          )}
        </h2>
        {prompt.updated_at && (
          <span className="muted" style={{ fontSize: 12 }}>
            updated {new Date(prompt.updated_at).toLocaleString()}
          </span>
        )}
      </div>

      <p className="muted" style={{ marginTop: 8 }}>{prompt.description}</p>

      <div className="detail" style={{ marginBottom: 8 }}>
        Required placeholders (must appear exactly):{" "}
        {prompt.required_placeholders.map((p) => (
          <span key={p} className="chip">{`{${p}}`}</span>
        ))}
      </div>

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={Math.min(24, Math.max(8, text.split("\n").length + 1))}
        style={{ width: "100%", fontFamily: "monospace", fontSize: 13 }}
      />

      <div className="row" style={{ marginTop: 10 }}>
        <button onClick={save} disabled={busy || !dirty}>
          {busy ? "Saving…" : "Save"}
        </button>
        <button className="secondary" onClick={reset} disabled={busy}>
          Reset to default
        </button>
        {dirty && <span className="muted">unsaved changes</span>}
      </div>

      {msg && <div className="detail" style={{ color: "var(--good)" }}>{msg}</div>}
      {err && <div className="detail error">{err}</div>}
    </div>
  );
}

export default function PromptsPage() {
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setErr(null);
    try {
      setPrompts(await api.prompts());
    } catch (e) {
      setErr(String(e));
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <>
      <h1>AI Prompts</h1>
      <div className="panel muted">
        Edit the prompts sent to Claude. Changes are validated (required placeholders must
        stay) and stored in the database. They apply to the <strong>next</strong> analysis —
        existing scores are not recomputed automatically. Use &quot;Analyze jobs vs CV&quot;
        on the Dashboard, or per-job &quot;Re-analyze&quot;, to apply a new prompt.
      </div>

      {err && <div className="panel error">{err}</div>}

      {prompts.map((p) => (
        <PromptEditor key={p.key} prompt={p} onChanged={load} />
      ))}
    </>
  );
}
