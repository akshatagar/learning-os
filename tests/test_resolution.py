from resolution.adjudicate import _query_neighbors, call_ollama_adjudicate


def test_query_neighbors_returns_empty_list_when_collection_is_empty(collection):
    neighbors = _query_neighbors(collection, "gradient descent", k=5)
    assert neighbors == []


def test_query_neighbors_returns_top_k_with_similarity_scores(collection):
    collection.add(ids=["1"], documents=["gradient descent"])
    collection.add(ids=["2"], documents=["watercolor painting"])

    neighbors = _query_neighbors(collection, "backpropagation", k=5)

    assert len(neighbors) == 2
    top = neighbors[0]
    assert top["id"] == 1
    assert top["name"] == "gradient descent"
    assert 0.0 < top["similarity_score"] <= 1.0


def test_call_ollama_adjudicate_matches_identical_candidate_name():
    neighbors = [{"id": 1, "name": "gradient descent", "similarity_score": 1.0}]

    result = call_ollama_adjudicate("gradient descent", None, neighbors)

    assert result["decision"] == "match"
    assert result["matched_concept_id"] == 1
    assert result["confidence"] >= 0.5
    assert isinstance(result["reasoning"], str) and result["reasoning"]
