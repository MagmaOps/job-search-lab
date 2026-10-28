# Task: Personal AI Job Search App

## Goal
Build a personal job-search application running on my homelab server. It should collect jobs automatically, save them in a database, match them against my CV using AI, and display results in a web dashboard.

## Requirements

### 1. Deployment
- Run the application on my homelab.
- Use Docker Compose for easy deployment.
- No OAuth or login system for the web UI.
- Keep API keys and secrets on the server.
- Document configuration and deployment in a README.

### 2. CV Management
- Allow me to upload or replace my CV through the web UI.
- Support PDF and DOCX files.
- Extract CV text and use it for job matching.
- Store uploaded files securely.

### 3. Job Search Queries
- Store search queries and settings in the database.
- Allow me to add, edit, enable, disable, and delete queries through the web UI.
- Start with one predefined LinkedIn-focused search query.
- Make the source integration modular so other job sources can be added later.

### 4. Scheduled Job Collection
- Run searches a few times per day.
- Make the schedule configurable.
- Include a button to trigger a manual search.
- Save job title, company, location, description, URL, source, and discovery date when available.
- Respect source terms and access restrictions. Do not bypass logins or anti-bot protections. If LinkedIn cannot be accessed reliably through a permitted method, explain the limitation and support alternative sources or manually supplied job URLs.

### 5. Database and Deduplication
- Save all discovered jobs in the database.
- Normalize job URLs and use them to identify duplicate listings.
- Use a source-specific job ID when available.
- Use a fallback fingerprint based on source, company, title, and location when necessary.
- Enforce uniqueness in the database.
- Do not analyze or translate jobs that have already been processed and have not changed.
- Save processing status and errors so failed jobs can be retried.
- Allow manual re-analysis when requested.
- If the CV changes, allow existing jobs to be re-analyzed against the new CV.

### 6. AI Matching and Translation
- Compare job descriptions with my CV using an AI model.
- Support jobs written in different languages.
- Detect the job language when possible.
- Translate relevant job information when useful for matching.
- Show the original job information and a translated summary in the dashboard.
- Save translation and matching results in the database to avoid repeated AI calls.
- Generate a match score, explanation, matching skills, and missing requirements.
- Never invent qualifications or experience.
- Make the AI provider configurable and keep its API key server-side.

### 7. Web Dashboard
- Display jobs ranked by match score.
- Show title, company, location, language, score, summary, discovery date, and original job link.
- Provide filters for score, location, company, language, and status.
- Allow me to mark jobs as saved, dismissed, applied, or interview.
- Show the last search time and any errors.
- Include pages for the dashboard, CV upload, and search-query management.

### 8. Suggested Technology
Choose a simple, maintainable stack suitable for a homelab:
- Frontend: Next.js or an equivalent framework.
- Backend: Python FastAPI.
- Database: PostgreSQL.
- Scheduling: a scheduler or worker service.
- Deployment: Docker Compose.
- AI: a configurable model API.

Avoid unnecessary services and paid dependencies.

### 9. Implementation Plan
1. Propose a simple architecture.
2. Implement the database and migrations.
3. Build the CV upload and search-query management UI.
4. Implement job collection and scheduling.
5. Implement URL normalization and database-level deduplication.
6. Add AI matching and multilingual translation.
7. Build the results dashboard.
8. Add tests for deduplication, processing, and retries.
9. Provide setup, configuration, backup, and deployment instructions.

Use sample jobs to test the application before connecting live sources.

## Definition of Done
The application runs on my homelab, lets me upload a CV and edit search queries, collects jobs automatically, saves all results in the database, avoids repeated AI processing of unchanged jobs, matches jobs across languages, and displays ranked results in the web UI.

Start with the simplest working version. Explain LinkedIn access limitations before implementing its connector. Ask before introducing paid services or major additional features.
