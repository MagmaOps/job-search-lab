"""CV ingestion: extract text from PDF/DOCX, derive a profile, store data only.

The uploaded file is never persisted — only extracted_text + derived_profile + an
editable matching_profile row (design: CV = extracted data only).
"""

from __future__ import annotations

import io

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..ai import get_provider, prompts
from ..models import CV, MatchingProfile
from . import prompt_service


class UnsupportedFileError(ValueError):
    pass


def extract_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return _extract_pdf(data)
    if name.endswith(".docx"):
        return _extract_docx(data)
    raise UnsupportedFileError("Only PDF and DOCX files are supported.")


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages).strip()


def _extract_docx(data: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs).strip()


def ingest_cv(db: Session, filename: str, data: bytes) -> CV:
    """Extract text, derive a baseline profile, store, and mark active."""
    text = extract_text(filename, data)
    if not text:
        raise ValueError("Could not extract any text from the uploaded file.")

    provider = get_provider()
    profile_template = prompt_service.get_template(db, prompts.PROFILE)
    extraction = provider.extract_profile(text, template=profile_template)

    # Deactivate previous CVs; the newest upload becomes active.
    db.execute(update(CV).values(is_active=False))

    cv = CV(
        source_filename=filename,
        extracted_text=text,
        derived_profile={
            "skills": extraction.skills,
            "seniority": extraction.seniority,
            "years_experience": extraction.years_experience,
            "summary": extraction.summary,
        },
        is_active=True,
    )
    db.add(cv)
    db.flush()  # assign cv.id

    # Seed an editable matching profile from the derived baseline.
    profile = MatchingProfile(
        cv_id=cv.id,
        must_have_skills=[],
        nice_to_have_skills=list(extraction.skills),
        dealbreakers=[],
        min_seniority=extraction.seniority,
        notes=None,
    )
    db.add(profile)
    db.commit()
    db.refresh(cv)
    return cv


def get_active_cv(db: Session) -> CV | None:
    return db.query(CV).filter(CV.is_active.is_(True)).one_or_none()


def effective_profile(cv: CV) -> dict:
    """Merge the derived baseline with the user's editable overrides."""
    derived = cv.derived_profile or {}
    mp = cv.matching_profile
    return {
        "skills": derived.get("skills", []),
        "seniority": derived.get("seniority"),
        "must_have_skills": (mp.must_have_skills if mp else []) or [],
        "nice_to_have_skills": (mp.nice_to_have_skills if mp else []) or [],
        "dealbreakers": (mp.dealbreakers if mp else []) or [],
        "min_seniority": (mp.min_seniority if mp else None),
        "notes": (mp.notes if mp else None),
    }
