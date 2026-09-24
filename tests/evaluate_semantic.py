"""Opt-in live reviewer evaluation on synthetic, manually labeled examples.

python -m tests.evaluate_semantic --backend codex [--model MODEL]
Uses the selected authenticated CLI and may incur model usage. Prints JSON;
never writes application artifacts. This small set is not an accuracy benchmark.
"""
import argparse
import json
from pathlib import Path

from scrubber.backend import Backend
from scrubber.schema import SEMANTIC_REVIEW
from scrubber.semantic import POLICY_VERSION, REVIEW_PROMPT, validate_review


def example_inputs(case):
    evidence = [{"source": "master/example.txt", "quote": q} for q in case["quotes"]]
    return {"policy_version": POLICY_VERSION,
            "bullet": {"text": case["bullet"], "evidence": evidence, "requirements": ["R1"]},
            "entry": {"section": "Projects", "title": "Example project", "detail": "See source context"},
            "requirements": [{"id": "R1", "keyword": case["keyword"],
                              "job_quote": case["job_quote"], "section": "any"}],
            "master": {"master/example.txt": case["source"]}, "job": case["job_quote"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["codex", "claude"], default="codex")
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    backend = Backend(args.backend, args.model, args.timeout)
    cases = json.loads((Path(__file__).parent / "data/semantic_cases.json").read_text())
    results = []
    for case in cases:
        inputs = example_inputs(case)
        try:
            result = backend.ask(REVIEW_PROMPT, inputs, SEMANTIC_REVIEW)
            validate_review(result, inputs)
            support_verdicts = [result["support"]["verdict"],
                                *[a["verdict"] for a in result["assertions"]]]
            support = next((v for v in ("unsupported", "uncertain") if v in support_verdicts), "supported")
            observed = {"support": support, "relevance": result["relevance"][0]["verdict"]}
            results.append({"name": case["name"], "expected": {k: case[k] for k in observed},
                            "observed": observed, "matched": all(case[k] == v for k, v in observed.items()),
                            "review": result})
        except (ValueError, RuntimeError) as exc:
            results.append({"name": case["name"], "matched": False, "error": str(exc)})
    print(json.dumps({"policy_version": POLICY_VERSION, "backend": args.backend, "model": args.model,
                      "matched": sum(r["matched"] for r in results), "total": len(results),
                      "results": results}, indent=2))
    return 0 if all(r["matched"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
