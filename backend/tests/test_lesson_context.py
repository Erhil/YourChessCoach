from app.config import settings
from app.lessons.ask import lesson_context, passage_catalog
from app.lessons.loader import list_lessons


def test_authored_catalog_contexts_keep_prose_and_exclude_interactive_metadata():
    lessons = list_lessons(settings.lessons_dir)
    assert len(lessons) == 31
    seen = set()
    for lesson in lessons:
        context = lesson_context(lesson)
        catalog = [entry["text"] for entry in passage_catalog(context)]
        prose = []
        for segment in lesson["segments"]:
            seen.add(segment["type"])
            if segment["type"] == "markdown":
                prose.extend(
                    p.strip()
                    for p in segment["text"].split("\n\n")
                    if p.strip()
                    and not all(line.startswith("#") for line in p.strip().splitlines())
                )
            elif segment["type"] == "line":
                assert segment["fen"] not in context
                assert segment["title"] not in catalog
                for move in segment["moves"]:
                    assert move["text"] not in catalog
        assert prose
        assert catalog == prose
    assert seen == {"markdown", "chess", "line"}
