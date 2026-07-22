from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Concept(Base):
    __tablename__ = "concepts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    category: Mapped[str | None]
    confidence_score: Mapped[float | None]
    goal_tags: Mapped[str | None]
    source_type: Mapped[str | None]
    first_seen: Mapped[datetime | None]
    last_reinforced: Mapped[datetime | None]
    embedding_id: Mapped[str | None]


class MergeQueue(Base):
    __tablename__ = "merge_queue"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_name: Mapped[str]
    candidate_category: Mapped[str | None]
    matched_concept_id: Mapped[int | None] = mapped_column(ForeignKey("concepts.id"))
    llm_confidence: Mapped[float | None]
    llm_reasoning: Mapped[str | None]
    status: Mapped[str] = mapped_column(default="pending")
    created_at: Mapped[datetime | None]
    adjudication_log_id: Mapped[int | None] = mapped_column(
        ForeignKey("adjudication_log.id")
    )
    source_type: Mapped[str | None]


class AdjudicationLog(Base):
    __tablename__ = "adjudication_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_name: Mapped[str]
    candidate_description: Mapped[str | None]
    retrieved_neighbors: Mapped[str | None]
    model_decision: Mapped[str | None]
    model_confidence: Mapped[float | None]
    model_reasoning: Mapped[str | None]
    human_resolution: Mapped[str | None]
    resolved_at: Mapped[datetime | None]
    created_at: Mapped[datetime | None]


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    proficiency: Mapped[float | None]
    last_used: Mapped[datetime | None]
    source: Mapped[str | None]


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    description: Mapped[str]
    category: Mapped[str | None]
    priority: Mapped[int | None]
    concept_requirements: Mapped[str | None]


class ContentLog(Base):
    __tablename__ = "content_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_path: Mapped[str | None]
    source_type: Mapped[str | None]
    ingested_at: Mapped[datetime | None]
    extracted_concepts: Mapped[str | None]
    summary: Mapped[str | None]


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str | None]
    description: Mapped[str | None]
    skill_match_pct: Mapped[float | None]
    missing_skills: Mapped[str | None]
    status: Mapped[str] = mapped_column(default="generated")
    required_skills: Mapped[str | None]
    created_at: Mapped[datetime | None]
    source_concepts: Mapped[str | None]
