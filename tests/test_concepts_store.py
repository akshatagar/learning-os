from concepts.store import list_concepts
from storage.models import Concept


def test_concepts_are_ordered_weakest_first(session):
    session.add_all([
        Concept(name="Strong", confidence_score=1.0),
        Concept(name="Weak", confidence_score=0.5),
        Concept(name="Middling", confidence_score=0.8),
    ])
    session.commit()

    assert [c.name for c in list_concepts(session)] == [
        "Weak", "Middling", "Strong",
    ]


def test_equal_confidence_breaks_on_name(session):
    session.add_all([
        Concept(name="Beta", confidence_score=0.8),
        Concept(name="Alpha", confidence_score=0.8),
    ])
    session.commit()

    assert [c.name for c in list_concepts(session)] == ["Alpha", "Beta"]


def test_unmeasured_concepts_sort_ahead_of_the_weakest(session):
    """An unmeasured concept is not a confident one."""
    session.add_all([
        Concept(name="Measured", confidence_score=0.5),
        Concept(name="Unmeasured", confidence_score=None),
    ])
    session.commit()

    assert [c.name for c in list_concepts(session)] == [
        "Unmeasured", "Measured",
    ]


def test_an_empty_store_lists_nothing(session):
    assert list_concepts(session) == []
