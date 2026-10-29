"""Load, validate, persist, and reset editable prompt templates."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..ai import prompts
from ..models import PromptTemplate


def get_template(db: Session, key: str) -> str:
    """Return the stored template for `key`, or the built-in default if none stored."""
    spec = prompts.SPECS.get(key)
    if spec is None:
        raise prompts.PromptValidationError(f"Unknown prompt '{key}'.")
    row = db.get(PromptTemplate, key)
    return row.template if row and row.template else spec.default


def list_prompts(db: Session) -> list[dict]:
    """All prompt specs with current (stored or default) text and metadata for the UI."""
    result: list[dict] = []
    for key, spec in prompts.SPECS.items():
        row = db.get(PromptTemplate, key)
        result.append(
            {
                "key": key,
                "label": spec.label,
                "description": spec.description,
                "required_placeholders": sorted(spec.required_placeholders),
                "template": row.template if row and row.template else spec.default,
                "is_customized": bool(row and row.template != spec.default),
                "updated_at": row.updated_at.isoformat() if row else None,
            }
        )
    return result


def set_template(db: Session, key: str, template: str) -> PromptTemplate:
    """Validate then persist a template. Raises PromptValidationError if invalid."""
    prompts.validate(key, template)  # raises on missing/unknown placeholders
    row = db.get(PromptTemplate, key)
    if row is None:
        row = PromptTemplate(key=key, template=template)
        db.add(row)
    else:
        row.template = template
    db.commit()
    db.refresh(row)
    return row


def reset_template(db: Session, key: str) -> str:
    """Delete any override so the built-in default is used again."""
    row = db.get(PromptTemplate, key)
    if row is not None:
        db.delete(row)
        db.commit()
    return prompts.SPECS[key].default
