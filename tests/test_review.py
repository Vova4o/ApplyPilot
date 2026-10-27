from applypilot.config import effective_search
from applypilot.review import write_review


def test_review_escapes_vacancy_content_and_keeps_unknown_conditions(tmp_path):
    output = write_review([
        {"id": "1", "name": "<script>alert(1)</script>", "url": "https://hh.ru/vacancy/1",
         "description": "<b>unknown</b>"}
    ], {"search": {"only_remote": True}}, tmp_path / "review.html", top=20)

    html = output.read_text(encoding="utf-8")
    assert "&lt;script&gt;" in html
    assert "<script>" not in html
    assert "search_filter=unknown" in html


def test_review_separates_matches_provisional_and_rejected_rows(tmp_path):
    search = effective_search({}, "ai-agents-llmops")
    profile = {"search": search, **search}
    output = write_review([
        {"id": "1", "name": "LLMOps Engineer", "url": "https://hh.ru/vacancy/1",
         "description": "Python LLM RAG Kubernetes"},
        {"id": "2", "name": "AI Agent Engineer", "url": "https://hh.ru/vacancy/2",
         "description": ""},
        {"id": "3", "name": "DevOps Engineer", "url": "https://hh.ru/vacancy/3",
         "description": ""},
    ], profile, tmp_path / "review.html", top=20)

    content = output.read_text(encoding="utf-8")
    assert "Подходящие: top (Selected): 1" in content
    assert "Недостаточно данных (Provisional): 1" in content
    assert "Отклонённые (Rejected): 1" in content
    assert "Полное описание не загружено" in content
    assert "ranking=reject" in content
    assert "role:title_not_target" in content


def test_review_uses_search_min_score_unless_top_level_override_exists(tmp_path):
    item = {"id": "1", "name": "Go backend developer", "url": "https://hh.ru/vacancy/1",
            "description": "Go backend", "score": 40}
    profile = {"search": {"min_score": 50}}

    output = write_review([item], profile, tmp_path / "nested-threshold.html")
    content = output.read_text(encoding="utf-8")
    assert "Подходящие: top (Selected): 0" in content
    assert "Недостаточно данных (Provisional): 1" in content

    output = write_review([item], {**profile, "min_score": 0},
                          tmp_path / "top-level-override.html")
    content = output.read_text(encoding="utf-8")
    assert "Подходящие: top (Selected): 1" in content
