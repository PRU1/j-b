from copy import deepcopy
from pathlib import Path


def fixture():
    root = Path(__file__).resolve().parents[1]
    source = (root / "examples/master/resume.tex").read_text()
    job = (root / "examples/jobs/software-intern.txt").read_text()
    context = {"master": {"master/resume.tex": source}, "references": {}, "preferences": "Python roles",
               "job": job, "instructions": "Emphasize software projects", "job_url": None,
               "max_pages": 1, "font_size": 12, "backend": "codex", "model": None}
    plan = {"company": "Example Robotics", "role": "Software Intern", "requirements": [
        {"id": "R1", "keyword": "Python", "job_quote": "Build Python tools for sensor data analysis.", "section": "Projects"},
        {"id": "R2", "keyword": "unit tests", "job_quote": "Add unit tests for data processing.", "section": "Projects"}],
        "gaps": ["C++ is not supported by the master resume."]}
    outline = {"candidates": [{"name": name, "rationale": "Select relevant projects.",
                "sections": [{"title": "Projects", "entries": ["Sensor Dashboard"]}]}
                for name in ("faithful", "balanced", "targeted")]}

    def claim(text, quote=None, source="master/resume.tex"):
        return {"text": text, "evidence": [{"source": source, "quote": quote or text}]}

    bullets = [
        {**claim("Built a Python dashboard to visualize sensor data and identify missing readings."), "requirements": ["R1"]},
        {**claim("Added unit tests to validate data processing and catch malformed sensor records."), "requirements": ["R2"]}]
    candidate = {"name": "faithful", "header": [claim("Example Student"), claim("example@example.invalid")],
                 "sections": [{"title": "Projects", "entries": [{"title": claim("Sensor Dashboard"),
                  "detail": claim("Personal project"), "bullets": bullets}]}],
                 "cover_letter": [claim("I am applying for Software Intern at Example Robotics.",
                                        "Example Robotics — Software Intern", "job.txt"),
                                  claim("Built a Python dashboard to visualize sensor data and identify missing readings.")]}
    draft = {"candidates": []}
    for name in ("faithful", "balanced", "targeted"):
        copy = deepcopy(candidate)
        copy["name"] = name
        draft["candidates"].append(copy)
    return context, plan, outline, draft


class FakeBackend:
    name = "test-double"

    def __init__(self, values):
        self.values, self.calls = list(values), []
        self.semantic_calls = []

    def ask(self, instruction, data, shape):
        from scrubber import schema
        if shape == schema.SEMANTIC_REVIEW:
            self.semantic_calls.append((instruction, deepcopy(data), shape))
            return supported_review(data["bullet"])
        self.calls.append((instruction, data, shape))
        if not self.values:
            raise AssertionError("Unexpected backend call")
        return deepcopy(self.values.pop(0))


def supported_review(bullet):
    return {"text": bullet["text"], "assertions": [
        {"span": bullet["text"], "evidence": deepcopy(bullet["evidence"]),
         "verdict": "supported", "reason": "Fixture: source supports this assertion."}],
        "support": {"verdict": "supported", "reason": "Fixture: coherent use of source facts."},
        "relevance": [{"requirement": rid, "verdict": "supported",
                       "reason": "Fixture: addresses the mapped job requirement."}
                      for rid in bullet["requirements"]]}


def compiled(*args, **kwargs):
    return {"compiled": True, "pages": 1, "max_pages": 1,
            "bullet_lines": {"0": 1, "1": 2}, "overflow": False}
