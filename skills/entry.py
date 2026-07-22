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


def _band_label(proficiency) -> str:
    for label, value in PROFICIENCY_BANDS.values():
        if proficiency == value:
            return label
    return "unknown"


def _prompt_band(input_fn) -> str | None:
    options = " / ".join(
        f"[{key}]{label}" for key, (label, _) in PROFICIENCY_BANDS.items()
    )
    while True:
        try:
            key = input_fn(f"  proficiency {options} > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if key in PROFICIENCY_BANDS:
            return key
        print("  Unrecognized - pick one of the options above.")


def _print_summary(counts):
    print(
        f"\nadded {counts['added']}, updated {counts['updated']}, "
        f"unchanged {counts['unchanged']}"
    )


def run_skill_entry_loop(session, input_fn=input) -> dict[str, int]:
    counts = {"added": 0, "updated": 0, "unchanged": 0}
    print(f"{len(existing_skills(session))} skills on record.")

    while True:
        try:
            name = input_fn("\nSkill (blank to finish) > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not name:
            break

        existing = find_skill(session, name)
        if existing is not None:
            label = _band_label(existing.proficiency)
            print(f'  "{existing.name}" already on record ({label}).')
            try:
                answer = input_fn("  update proficiency? [y/N] > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if answer != "y":
                counts["unchanged"] += 1
                continue

            band_key = _prompt_band(input_fn)
            if band_key is None:
                break
            new_label, value = PROFICIENCY_BANDS[band_key]
            existing.proficiency = value
            session.commit()
            counts["updated"] += 1
            print(f"  updated: {existing.name} ({new_label})")
            continue

        band_key = _prompt_band(input_fn)
        if band_key is None:
            break
        skill, _ = add_skill(session, name, band_key)
        counts["added"] += 1
        print(f"  added: {skill.name} ({PROFICIENCY_BANDS[band_key][0]})")

    _print_summary(counts)
    return counts
