"use client";

import { useEffect, useRef, useState } from "react";
import { API_URL, api, CV, Profile } from "@/lib/api";

function csvToList(v: string): string[] {
  return v.split(",").map((s) => s.trim()).filter(Boolean);
}

export default function CvPage() {
  const [cv, setCv] = useState<CV | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const [must, setMust] = useState("");
  const [nice, setNice] = useState("");
  const [deal, setDeal] = useState("");
  const [seniority, setSeniority] = useState("");
  const [notes, setNotes] = useState("");

  async function load() {
    setErr(null);
    try {
      const [c, p] = await Promise.all([api.cv(), api.profile()]);
      setCv(c);
      setProfile(p);
      if (p) {
        setMust((p.must_have_skills || []).join(", "));
        setNice((p.nice_to_have_skills || []).join(", "));
        setDeal((p.dealbreakers || []).join(", "));
        setSeniority(p.min_seniority || "");
        setNotes(p.notes || "");
      }
    } catch (e) {
      setErr(String(e));
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function upload() {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`${API_URL}/cv`, { method: "POST", body: fd });
      if (!res.ok) throw new Error(await res.text());
      setMsg("CV uploaded and text extracted. The file itself was not stored.");
      await load();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveProfile() {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      await api.updateProfile({
        must_have_skills: csvToList(must),
        nice_to_have_skills: csvToList(nice),
        dealbreakers: csvToList(deal),
        min_seniority: seniority || null,
        notes: notes || null,
      });
      setMsg("Matching profile saved.");
      await load();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>CV &amp; Matching Profile</h1>

      <div className="panel">
        <h2>Upload CV</h2>
        <p className="muted">
          PDF or DOCX. Only the extracted text and derived profile are stored — the file
          is discarded after extraction.
        </p>
        <div className="row">
          <input ref={fileRef} type="file" accept=".pdf,.docx" />
          <button onClick={upload} disabled={busy}>{busy ? "Working…" : "Upload"}</button>
        </div>
        {cv ? (
          <div className="detail">
            Active CV: {cv.source_filename || "—"} · uploaded{" "}
            {new Date(cv.uploaded_at).toLocaleString()}
            {Array.isArray(cv.derived_profile?.skills) &&
              (cv.derived_profile.skills as string[]).length > 0 && (
              <div>
                Derived skills:{" "}
                {(cv.derived_profile.skills as string[]).map((s) => (
                  <span key={s} className="chip">{s}</span>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="detail">No active CV yet.</div>
        )}
      </div>

      <div className="panel">
        <h2>Matching profile</h2>
        <p className="muted">
          Baseline is auto-derived from your CV. Override it here with your explicit
          requirements. Dealbreakers cap a job&apos;s score hard.
        </p>
        {!profile && <div className="detail">Upload a CV to create a profile.</div>}
        {profile && (
          <>
            <div className="field">
              <label>Must-have skills (comma separated)</label>
              <input value={must} onChange={(e) => setMust(e.target.value)}
                     style={{ width: "100%" }} />
            </div>
            <div className="field">
              <label>Nice-to-have skills</label>
              <input value={nice} onChange={(e) => setNice(e.target.value)}
                     style={{ width: "100%" }} />
            </div>
            <div className="field">
              <label>Dealbreakers</label>
              <input value={deal} onChange={(e) => setDeal(e.target.value)}
                     style={{ width: "100%" }} />
            </div>
            <div className="field">
              <label>Minimum seniority</label>
              <input value={seniority} onChange={(e) => setSeniority(e.target.value)} />
            </div>
            <div className="field">
              <label>Notes</label>
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)}
                        rows={3} style={{ width: "100%" }} />
            </div>
            <button onClick={saveProfile} disabled={busy}>Save profile</button>
          </>
        )}
      </div>

      {msg && <div className="panel">{msg}</div>}
      {err && <div className="panel error">{err}</div>}
    </>
  );
}
