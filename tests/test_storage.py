from sqlalchemy import inspect, select

from conftest import _run_migrations
from storage.db import get_engine, get_session
from storage.models import Concept

EXPECTED_TABLES = {
    "concepts": {
        "id", "name", "category", "confidence_score", "goal_tags",
        "source_type", "first_seen", "last_reinforced", "embedding_id",
    },
    "merge_queue": {
        "id", "candidate_name", "candidate_category", "matched_concept_id",
        "llm_confidence", "llm_reasoning", "status", "created_at",
        "adjudication_log_id", "source_type",
    },
    "adjudication_log": {
        "id", "candidate_name", "candidate_description", "retrieved_neighbors",
        "model_decision", "model_confidence", "model_reasoning",
        "human_resolution", "resolved_at", "created_at",
    },
    "skills": {"id", "name", "proficiency", "last_used", "source"},
    "goals": {"id", "description", "category", "priority", "concept_requirements"},
    "content_log": {
        "id", "source_path", "source_type", "ingested_at",
        "extracted_concepts", "summary",
    },
    "opportunities": {
        "id", "title", "description", "skill_match_pct", "missing_skills", "status",
        "required_skills", "created_at", "source_concepts", "execution_plan",
    },
}


def test_migrations_create_all_tables_with_expected_columns(engine):
    inspector = inspect(engine)

    tables = set(inspector.get_table_names()) - {"alembic_version"}
    assert tables == set(EXPECTED_TABLES)

    for table, expected_columns in EXPECTED_TABLES.items():
        columns = {col["name"] for col in inspector.get_columns(table)}
        assert columns == expected_columns, f"{table} columns mismatch"


def test_insert_and_read_back_a_concept_row(session):
    concept = Concept(
        name="gradient descent",
        category="ML",
        confidence_score=0.7,
        source_type="paper",
    )
    session.add(concept)
    session.commit()

    row = session.get(Concept, concept.id)

    assert row.name == "gradient descent"
    assert row.category == "ML"
    assert row.confidence_score == 0.7
    assert row.source_type == "paper"


def test_upgrading_twice_is_idempotent_and_preserves_data(tmp_path):
    db_path = tmp_path / "learning_os.db"
    _run_migrations(db_path)

    engine = get_engine(db_path)
    with get_session(engine) as session:
        session.add(Concept(name="backpropagation"))
        session.commit()

    _run_migrations(db_path)

    with get_session(engine) as session:
        row = session.scalar(
            select(Concept).where(Concept.name == "backpropagation")
        )
        assert row is not None


def test_embed_concept_and_query_round_trips_to_correct_sqlite_row(session, collection, tmp_path):
    ml_concept = Concept(name="gradient descent")
    art_concept = Concept(name="watercolor painting")
    session.add_all([ml_concept, art_concept])
    session.commit()

    collection.add(ids=[str(ml_concept.id)], documents=["gradient descent"])
    collection.add(ids=[str(art_concept.id)], documents=["watercolor painting"])

    ml_concept.embedding_id = str(ml_concept.id)
    art_concept.embedding_id = str(art_concept.id)
    session.commit()

    results = collection.query(query_texts=["backpropagation"], n_results=1)
    nearest_id = int(results["ids"][0][0])

    assert nearest_id == ml_concept.id
    row = session.get(Concept, nearest_id)
    assert row.name == "gradient descent"
    assert row.embedding_id == str(ml_concept.id)
