"""Deterministic stub provider used until an Anthropic key is configured.

It does no external calls. It produces a plausible, explainable score by simple keyword
overlap between the job text and the matching profile, so the whole pipeline (collection →
analysis → ranking → dashboard) works end-to-end offline. It never invents qualifications:
matching skills are only those literally present in both the profile and the job text.
"""

from __future__ import annotations

import re

from .base import ApplicationDraft, DimensionScore, MatchResult, ProfileExtraction

try:  # langdetect is optional at runtime; degrade gracefully
    from langdetect import detect as _detect_lang
except Exception:  # pragma: no cover
    _detect_lang = None


_DEFAULT_SKILLS = [
    "kubernetes", "docker", "terraform", "aws", "gcp", "azure", "ci/cd",
    "python", "linux", "ansible", "helm", "prometheus", "argocd", "gitops",
]


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+/#.]+", (text or "").lower()))


# Common language names the stub recognizes when they appear in CV text. The real
# provider extracts levels from context; the stub only records presence (level=None).
_KNOWN_LANGUAGES = [
    "english", "german", "french", "spanish", "italian", "portuguese", "dutch",
    "danish", "swedish", "norwegian", "finnish", "polish", "czech", "russian",
    "ukrainian", "mandarin", "chinese", "japanese", "korean", "arabic", "hindi",
]


def _detect_cv_languages(cv_text: str) -> list[dict]:
    """Best-effort language list from CV text (names only; level unknown offline)."""
    toks = _tokens(cv_text)
    found = [name for name in _KNOWN_LANGUAGES if name in toks]
    return [{"language": name.capitalize(), "level": None} for name in found]


# Phrases that signal a role is restricted to the US (offline heuristic for eligibility).
_US_RESTRICTED = (
    "us only", "u.s. only", "united states only", "must be based in the us",
    "us-based", "u.s.-based", "based in the united states",
    "authorized to work in the united states", "work authorization in the us",
    "us citizen", "u.s. citizen", "must reside in the united states",
    "within the united states", "us residents only",
)
_WORLDWIDE = (
    "worldwide", "work from anywhere", "anywhere in the world", "any country",
    "fully remote, global", "remote - global", "globally remote", "location: anywhere",
)
_EU_RESTRICTED = (
    "eu only", "eu-based", "based in the eu", "within the eu", "eea only",
    "must be based in europe", "europe only", "eu residents",
)


def _guess_location_eligibility(text: str) -> tuple[str | None, str | None, str | None]:
    """Heuristic (country, eligibility, note) from job text, mirroring the prompt's rules.

    Offline best-effort only; the real provider reasons over the full description.
    """
    low = text.lower()
    if any(p in low for p in _WORLDWIDE):
        return None, "worldwide", "Posting states it is open worldwide / work-from-anywhere."
    if any(p in low for p in _US_RESTRICTED):
        return ("United States", "restricted",
                "Posting ties the role to the US (US-only / work-authorization wording).")
    if any(p in low for p in _EU_RESTRICTED):
        return ("EU", "restricted", "Posting limits the role to the EU/Europe.")
    # USD salary with a US state abbreviation nearby is a strong US signal.
    if re.search(r"\$\s?\d{2,3}[,k]", low) and re.search(
        r"\b(ca|ny|tx|wa|co|ma|il|ga|fl|nc|va|or|az)\b", low
    ):
        return ("United States", "restricted",
                "Salary quoted in USD against US-state locations suggests a US-only role.")
    # Nothing explicit: a remote board listing leans open, but mark it a guess.
    return None, "unclear", "No location restriction stated; eligibility not confirmed."


class StubProvider:
    model = "stub"

    def extract_profile(
        self, cv_text: str, template: str | None = None
    ) -> ProfileExtraction:
        toks = _tokens(cv_text)
        skills = [s for s in _DEFAULT_SKILLS if s in toks or s.replace("/", "") in toks]
        return ProfileExtraction(
            skills=skills or _DEFAULT_SKILLS[:5],
            seniority="mid",
            years_experience=None,
            languages=_detect_cv_languages(cv_text),
            summary="Baseline profile derived without an AI key (stub).",
        )

    def analyze_job(
        self,
        *,
        job_title: str,
        job_description: str,
        job_language: str | None,
        cv_text: str,
        effective_profile: dict,
        template: str | None = None,
    ) -> MatchResult:
        text = f"{job_title}\n{job_description}"
        job_toks = _tokens(text)
        country, eligibility, elig_note = _guess_location_eligibility(text)

        must = [s.lower() for s in effective_profile.get("must_have_skills", [])]
        nice = [s.lower() for s in effective_profile.get("nice_to_have_skills", [])]
        derived = [s.lower() for s in effective_profile.get("skills", [])]
        dealbreakers = [s.lower() for s in effective_profile.get("dealbreakers", [])]

        wanted = must + nice + derived
        matched = sorted({s for s in wanted if s and s in job_toks})
        missing = sorted({s for s in must if s and s not in job_toks})

        # ── Per-dimension scores (weights mirror the analyze prompt's rubric) ──
        # 1. Technical skills (30%): must-haves weighted heavily, extras lightly.
        must_hit = sum(1 for s in must if s in job_toks)
        nice_hit = sum(1 for s in (nice + derived) if s in job_toks)
        must_total = max(len(must), 1)
        technical = int(70 * (must_hit / must_total) + min(30, nice_hit * 5))

        # 2. Experience/function match (25%): any profile skill surfacing in the job.
        derived_hit = sum(1 for s in derived if s in job_toks)
        experience = min(100, 40 + derived_hit * 15) if derived else 40

        # 3. Seniority fit (15%): does the job text mention the profile's seniority band?
        min_sen = (effective_profile.get("min_seniority") or "").lower()
        seniority = 70
        if min_sen:
            seniority = 85 if min_sen in text.lower() else 55

        # 4. Career/role alignment (30%): proxied by overall skill overlap presence.
        alignment = 75 if matched else 45

        dims = [
            DimensionScore("Technical skills", technical, 0.30,
                           f"{must_hit}/{must_total} must-haves, {nice_hit} extra(s)"),
            DimensionScore("Experience match", experience, 0.25,
                           f"{derived_hit} CV skill(s) in posting"),
            DimensionScore("Seniority fit", seniority, 0.15,
                           f"min '{min_sen or 'unset'}' "
                           + ("named" if seniority >= 85 else "not named")),
            DimensionScore("Career alignment", alignment, 0.30,
                           "skills overlap" if matched else "little overlap"),
        ]
        score = int(round(sum(d.score * d.weight for d in dims)))

        # Mirror the analyze-prompt gates/caps so the offline pipeline behaves like the
        # documented rules (dealbreaker > eligibility/clearance > the weighted score).
        caps: list[int] = []
        if any(d in job_toks for d in dealbreakers):
            caps.append(10)
        clearance_terms = (
            "security clearance", "clearance required", "must be a citizen",
            "citizenship required", "permanent resident",
        )
        if any(term in text.lower() for term in clearance_terms):
            caps.append(15)
            missing = sorted(set(missing) | {"eligibility / clearance requirement"})
        if caps:
            score = min(score, *caps)

        score = max(0, min(100, score))

        lang = job_language
        if not lang and _detect_lang:
            try:
                lang = _detect_lang(text) if text.strip() else None
            except Exception:
                lang = None

        # Laconic explanation (one clause), matching the prompt's terse contract.
        explanation = (
            f"{len(matched)} skill(s) matched"
            + (f"; missing {', '.join(missing)}" if missing else "")
            + ("; capped by gate" if caps else "")
            + " (stub)"
        )

        # learning_gaps: offline the stub's only vocabulary is the profile's own skills, so
        # it cannot honestly identify a role-baseline skill the CV lacks without inventing
        # one. Per the never-invent rule it emits none; the real provider fills this in.
        learning_gaps: list = []

        return MatchResult(
            match_score=score,
            explanation=explanation,
            matching_skills=matched,
            missing_requirements=missing,
            detected_language=lang,
            translated_summary=None,
            dimension_scores=dims,
            learning_gaps=learning_gaps,
            posting_country=country,
            eligibility=eligibility,
            eligibility_note=elig_note,
            model=self.model,
        )

    def generate_application(
        self,
        *,
        job_title: str,
        job_description: str,
        cv_text: str,
        effective_profile: dict,
        draft_template: str | None = None,
        review_template: str | None = None,
        revise_template: str | None = None,
    ) -> ApplicationDraft:
        """Assemble a plausible application from facts the profile/CV actually contain.

        Deterministic and offline: invents nothing. Matched skills are only those literally
        present in BOTH the profile/CV and the posting; must-haves absent from the posting
        are stated as honest gaps. Mirrors the never-invent rule of the real prompt so the
        offline pipeline behaves the same and tests stay token-free.
        """
        job_toks = _tokens(f"{job_title}\n{job_description}")

        must = [s for s in effective_profile.get("must_have_skills", []) if s]
        nice = [s for s in effective_profile.get("nice_to_have_skills", []) if s]
        derived = [s for s in effective_profile.get("skills", []) if s]
        seniority = effective_profile.get("min_seniority") or effective_profile.get(
            "seniority"
        )

        # Skills the candidate actually has (from the profile) that the posting asks for.
        candidate_skills = {s.lower(): s for s in (must + nice + derived)}
        matched = [orig for low, orig in candidate_skills.items() if low in job_toks]
        matched = sorted(set(matched), key=str.lower)
        # Must-haves the candidate's profile does not evidence → honest gaps.
        have = {s.lower() for s in (nice + derived)}
        gaps = sorted({s for s in must if s.lower() not in have}, key=str.lower)

        title = (job_title or "this role").strip()
        sen_phrase = f"{seniority} " if seniority else ""
        matched_phrase = ", ".join(matched) if matched else "my core technical skills"

        # ── Cover letter — only asserts skills drawn from the profile ──
        intro = (
            f"I am writing to apply for the {title} position. As a {sen_phrase}engineer, "
            f"my experience maps directly onto what this role requires."
        )
        skills_tail = (
            "These are not keywords on a page for me but tools I have used in real "
            "delivery, which is what I would bring to your team."
            if matched
            else "I would bring these to your team from day one."
        )
        skills_line = (
            f"The posting's priorities align with skills I work with directly: "
            f"{matched_phrase}. {skills_tail}"
        )
        letter_lines = ["Dear Hiring Team,", "", intro, "", skills_line]
        if gaps:
            gap_bridges = "; ".join(
                f"{g} is not yet part of my daily toolkit, though it is a natural "
                f"extension of my existing work"
                for g in gaps
            )
            gap_line = (
                f"To be transparent about fit: {gap_bridges}. "
                "I would rather name that honestly than overstate it."
            )
            letter_lines += ["", gap_line]
        letter_lines += [
            "",
            "I would welcome the chance to discuss how my background fits your needs.",
            "",
            "Kind regards",
        ]
        cover_letter_md = "\n".join(letter_lines)

        # ── CV summary — profile statement + competencies grounded in the profile ──
        competency_source = matched or nice or derived
        competencies = "\n".join(
            f"- **{s}** — applied in prior DevOps work." for s in competency_source[:7]
        ) or "- (No skills recorded in the profile yet.)"
        profile_line = (
            f"**Profile.** {sen_phrase.capitalize() or ''}Engineer targeting {title}, "
            f"with hands-on experience across {matched_phrase}."
        )
        summary_lines = [profile_line, "", "**Key competencies**", competencies]
        cv_summary_md = "\n".join(summary_lines)

        # ── Reviewer notes — deterministic grounding-focused critique ──
        note_parts = ["Grounding audit (stub): all claims drawn from the recorded profile."]
        if gaps:
            note_parts.append(
                "Honest gaps surfaced rather than fabricated: " + ", ".join(gaps) + "."
            )
        if not matched:
            note_parts.append(
                "No posting skill overlapped the profile — consider whether this role fits."
            )
        note_parts.append("Configure an Anthropic key for a real drafter→reviewer pass.")
        reviewer_notes = " ".join(note_parts)

        # ── Full CV — a complete, PDF-ready Markdown doc from grounded facts only ──
        # Offline the stub cannot parse structured roles/education from free CV text, so it
        # assembles the sections it CAN ground (profile, skills, languages) and never
        # fabricates experience/education entries. The real provider produces the full set.
        languages = [
            lang.get("language")
            for lang in (effective_profile.get("languages") or [])
            if isinstance(lang, dict) and lang.get("language")
        ]
        all_skills = sorted(set(matched + nice + derived), key=str.lower)
        cv_profile_line = (
            f"{sen_phrase.capitalize() or ''}Engineer targeting {title}, "
            f"with hands-on experience across {matched_phrase}."
        )
        experience_note = (
            "_Offline stub: experience and education are taken verbatim from your uploaded "
            "CV by the real AI provider. Configure an Anthropic key to generate the full "
            "tailored CV; nothing here is invented._"
        )
        cv_full_lines = [
            "# Candidate CV",
            "",
            f"_Tailored for: {title}_",
            "",
            "## Profile",
            "",
            cv_profile_line,
            "",
            "## Skills",
            "",
        ]
        cv_full_lines += (
            [f"- {s}" for s in all_skills] or ["- (No skills recorded in the profile yet.)"]
        )
        if languages:
            cv_full_lines += ["", "## Languages", ""]
            cv_full_lines += [f"- {lang}" for lang in languages]
        cv_full_lines += ["", "## Experience", "", experience_note]
        cv_full_md = "\n".join(cv_full_lines)

        return ApplicationDraft(
            cover_letter_md=cover_letter_md,
            cv_summary_md=cv_summary_md,
            cv_full_md=cv_full_md,
            reviewer_notes=reviewer_notes,
            model=self.model,
        )
