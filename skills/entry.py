from sqlalchemy import func, select

from storage.models import Skill

PROFICIENCY_BANDS = {
    "s": ("strong", 85.0),
    "w": ("working", 60.0),
    "f": ("familiar", 35.0),
}

SOURCE = "user_confirmed"


def existing_skills(session) -> list[Skill]:
    return list(session.scalars(select(Skill).order_by(Skill.name)))


def find_skill(session, name: str) -> Skill | None:
    return session.scalars(
        select(Skill).where(func.lower(Skill.name) == name.strip().lower())
    ).first()


def add_skill(session, name: str, band_key: str) -> tuple[Skill, bool]:
    if band_key not in PROFICIENCY_BANDS:
        raise ValueError(f"Unknown proficiency band: {band_key!r}")

    existing = find_skill(session, name)
    if existing is not None:
        return existing, False

    _, value = PROFICIENCY_BANDS[band_key]
    skill = Skill(name=name.strip(), proficiency=value, source=SOURCE)
    session.add(skill)
    session.commit()
    return skill, True
