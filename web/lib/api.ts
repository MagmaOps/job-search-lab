// Thin API client. Base URL comes from NEXT_PUBLIC_API_URL (defaults to localhost dev).

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface DimensionScore {
  dimension: string;
  score: number;
  weight: number;
  reason: string;
}

export interface LearningGap {
  skill: string;
  level: "basic" | "average";
  why: string;
}

export interface JobDetail {
  id: number;
  title: string;
  company: string | null;
  description: string | null;
}

export interface Job {
  id: number;
  source: string;
  url: string | null;
  title: string;
  company: string | null;
  location: string | null;
  language: string | null;
  salary: string | null;
  work_type: string | null; // remote | hybrid | onsite | null
  status: string;
  discovered_at: string;
  analysis_state: "current" | "outdated" | "stale" | "none" | "error" | "pending";
  application_state: "none" | "pending" | "done" | "error";
  match_score: number | null;
  translated_summary: string | null;
  explanation: string | null;
  matching_skills: string[] | null;
  missing_requirements: string[] | null;
  dimension_scores: DimensionScore[] | null;
  learning_gaps: LearningGap[] | null;
  posting_country: string | null;
  eligibility: "worldwide" | "restricted" | "unclear" | null;
  eligibility_note: string | null;
}

export interface Application {
  job_id: number;
  cv_id: number;
  processing_status: "pending" | "done" | "error";
  error_message: string | null;
  cover_letter_md: string | null;
  cv_summary_md: string | null;
  cv_full_md: string | null;
  reviewer_notes: string | null;
  model: string | null;
  updated_at: string | null;
}

export interface Query {
  id: number;
  name: string;
  source: string;
  enabled: boolean;
  keywords: string | null;
  work_type: string | null;
  location: string | null;
  source_config: Record<string, unknown> | null;
  reference_url: string | null;
}

export interface Status {
  last_run_at: string | null;
  last_run_trigger: string | null;
  jobs_total: number;
  jobs_new: number;
  jobs_analyzed: number;
  errors: unknown[];
  ai_enabled: boolean;
}

export interface Profile {
  id: number;
  cv_id: number;
  must_have_skills: string[] | null;
  nice_to_have_skills: string[] | null;
  dealbreakers: string[] | null;
  min_seniority: string | null;
  notes: string | null;
}

export interface RunResult {
  jobs_found: number;
  jobs_new: number;
  analyzed: number;
  errors: unknown[];
}

export interface Prompt {
  key: string;
  label: string;
  description: string;
  required_placeholders: string[];
  template: string;
  is_customized: boolean;
  updated_at: string | null;
}

export interface CV {
  id: number;
  source_filename: string | null;
  derived_profile: Record<string, unknown> | null;
  uploaded_at: string;
  is_active: boolean;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  jobs: (params: Record<string, string> = {}) => {
    const qs = new URLSearchParams(params).toString();
    return req<Job[]>(`/jobs${qs ? `?${qs}` : ""}`);
  },
  setJobStatus: (id: number, status: string) =>
    req<Job>(`/jobs/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
  setJobSalary: (id: number, salary: string) =>
    req<Job>(`/jobs/${id}`, { method: "PATCH", body: JSON.stringify({ salary }) }),
  getJob: (id: number) => req<JobDetail>(`/jobs/${id}`),
  setJobDescription: (id: number, description: string) =>
    req<Job>(`/jobs/${id}`, { method: "PATCH", body: JSON.stringify({ description }) }),
  reanalyze: (id: number) => req(`/jobs/${id}/reanalyze`, { method: "POST" }),
  addManual: (body: Record<string, unknown>) =>
    req<Job>(`/jobs/manual`, { method: "POST", body: JSON.stringify(body) }),

  // Application generation (tailored cover letter + CV summary per job).
  getApplication: (jobId: number) =>
    req<Application | null>(`/jobs/${jobId}/application`),
  generateApplication: (jobId: number) =>
    req<Application>(`/jobs/${jobId}/application`, { method: "POST" }),
  updateApplication: (jobId: number, body: Partial<Pick<Application, "cover_letter_md" | "cv_summary_md" | "cv_full_md">>) =>
    req<Application>(`/jobs/${jobId}/application`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  analyze: () => req<{ queued: number }>(`/analyze`, { method: "POST" }),

  status: () => req<Status>(`/status`),

  queries: () => req<Query[]>(`/queries`),
  createQuery: (body: Record<string, unknown>) =>
    req<Query>(`/queries`, { method: "POST", body: JSON.stringify(body) }),
  updateQuery: (id: number, body: Record<string, unknown>) =>
    req<Query>(`/queries/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteQuery: (id: number) => req(`/queries/${id}`, { method: "DELETE" }),
  runQuery: (id: number) =>
    req<RunResult>(`/queries/${id}/run`, { method: "POST" }),

  prompts: () => req<Prompt[]>(`/prompts`),
  updatePrompt: (key: string, template: string) =>
    req<Prompt>(`/prompts/${key}`, { method: "PUT", body: JSON.stringify({ template }) }),
  resetPrompt: (key: string) => req<Prompt>(`/prompts/${key}/reset`, { method: "POST" }),

  cv: () => req<CV | null>(`/cv`),
  profile: () => req<Profile | null>(`/profile`),
  updateProfile: (body: Record<string, unknown>) =>
    req<Profile>(`/profile`, { method: "PATCH", body: JSON.stringify(body) }),
};
