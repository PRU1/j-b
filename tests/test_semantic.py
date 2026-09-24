import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from scrubber import schema
from scrubber.semantic import (approval_key, current_record, load_reviews, review_candidate,
                               review_inputs, validate_review, verdict)
from scrubber.verify import check_candidate
from scrubber.workflow import new_project, read_json, run, verify_project, write_json
from .fixtures import FakeBackend, compiled, fixture, supported_review


class SemanticTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.context, self.plan, self.outline, self.draft = fixture()
        self.project = new_project(Path(temp.name), "semantic", self.context)
        self.candidate = self.draft["candidates"][0]
        self.path = "section/0/entry/0/bullet/0"
        self.bullet = self.candidate["sections"][0]["entries"][0]["bullets"][0]
        self.backend = FakeBackend([])

    def inputs(self):
        return review_inputs(self.candidate, self.path, self.bullet, self.plan,
                             self.context["master"], self.context["job"])

    def review(self):
        return review_candidate(self.project, self.backend, self.candidate, self.plan,
                                self.context, emit=lambda _: None)

    def check(self, records, approvals=()):
        return check_candidate(self.candidate, self.plan, self.context["master"],
            self.context["job"], self.outline["candidates"][0], approved=True,
            layout=compiled(), semantic_reviews=records, semantic_approvals=approvals)

    def test_supported_paraphrase_passes_without_bullet_approval(self):
        self.bullet["text"] = "Developed a Python dashboard for sensor data visualization."
        report = self.check(self.review())
        self.assertEqual(report["status"], "pass")
        self.assertEqual(len(self.backend.semantic_calls), 2)

    def test_verbatim_bullets_are_reviewed_and_cached(self):
        records = self.review()
        self.assertEqual(len(self.backend.semantic_calls), 2)
        self.assertEqual(self.review(), records)
        self.assertEqual(len(self.backend.semantic_calls), 2)
        self.bullet["text"] = "Built a Python dashboard."
        self.review()
        self.assertEqual(len(self.backend.semantic_calls), 3)

    def test_all_semantic_dependencies_invalidate(self):
        record = self.review()[self.path]
        original = self.inputs()
        for field in ("bullet", "entry", "requirements", "master", "job", "policy_version"):
            altered = deepcopy(original)
            altered[field] = "changed"
            with self.subTest(field=field):
                self.assertIsNone(current_record(record, altered))

    def test_missing_stale_and_corrupt_reviews_never_pass(self):
        records = self.review()
        for value in ({}, {self.path: {"inputs_sha256": "fake"}},
                      {self.path: {**records[self.path], "result": {}}}):
            self.assertEqual(self.check(value)["status"], "pending")
        self.bullet["text"] += " Led the team."
        self.assertEqual(self.check(records)["status"], "pending")

    def test_partial_review_invalid_evidence_and_missing_relevance_rejected(self):
        for mutation in (
            lambda r: r["assertions"][0].update(span="Python"),
            lambda r: r["assertions"][0].update(evidence=[]),
            lambda r: r["assertions"][0]["evidence"][0].update(quote="Made-up quote"),
            lambda r: r.update(relevance=[]),
            lambda r: r["support"].update(verdict="probably"),
            lambda r: r.update(text="Changed text"),
        ):
            result = supported_review(self.bullet)
            mutation(result)
            with self.assertRaises(ValueError):
                validate_review(result, self.inputs())

    def test_unsupported_component_or_whole_bullet_cannot_be_human_approved(self):
        from scrubber.verify import digest
        for component in ("assertions", "support", "relevance"):
            records = self.review()
            record = deepcopy(records[self.path])
            item = record["result"][component]
            if isinstance(item, list):
                item = item[0]
            item.update(verdict="unsupported", reason="Invented scope or irrelevant keyword")
            record["result_sha256"] = digest(record["result"])
            records[self.path] = record
            self.assertEqual(verdict(record), "unsupported")
            self.assertEqual(self.check(records, [approval_key(record)])["status"], "fail")

    def test_uncertainty_needs_specific_current_approval(self):
        from scrubber.verify import digest
        records = self.review()
        record = records[self.path]
        record["result"]["support"].update(verdict="uncertain", reason="Project context ambiguous")
        record["result_sha256"] = digest(record["result"])
        self.assertEqual(self.check(records)["status"], "review")
        key = approval_key(record)
        self.assertEqual(self.check(records, [key])["status"], "pass")
        record["result"]["support"]["reason"] = "New ambiguity"
        record["result_sha256"] = digest(record["result"])
        self.assertEqual(self.check(records, [key])["status"], "review")

    def test_semantic_failure_repairs_only_failed_bullet_and_rechecks(self):
        bad = deepcopy(self.draft)
        bad["candidates"][0]["sections"][0]["entries"][0]["bullets"][0]["text"] += " Led the team."
        replacement = deepcopy(self.bullet)

        class ReviewingBackend(FakeBackend):
            def ask(inner, instruction, data, shape):
                result = super().ask(instruction, data, shape)
                if shape == schema.SEMANTIC_REVIEW and "Led the team" in data["bullet"]["text"]:
                    result["support"].update(verdict="unsupported", reason="Leadership not sourced")
                return result

        backend = ReviewingBackend([self.plan, self.outline, bad, {"repair_0": replacement}])
        with patch("scrubber.workflow.compile_tex", side_effect=compiled):
            results = run(self.project, backend, ask=lambda _: "yes", emit=lambda _: None)
        self.assertEqual(set(results.values()), {"pass"})
        self.assertEqual(len(backend.semantic_calls), 7)
        self.assertEqual(set(backend.calls[3][2]["properties"]), {"repair_0"})
        self.assertIn("Leadership not sourced", backend.calls[3][1]["failed_claims"][0]["errors"][0])
        self.assertEqual(read_json(self.project / "draft.json"), self.draft)
        self.assertFalse((self.project / "semantic-errors.json").exists())

    def test_old_session_requires_review_and_verify_never_calls_model(self):
        backend = FakeBackend([self.plan, self.outline, self.draft])
        with patch("scrubber.workflow.compile_tex", side_effect=compiled):
            run(self.project, backend, ask=lambda _: "yes", emit=lambda _: None)
            for candidate in self.draft["candidates"]:
                (self.project / candidate["name"] / "semantic-review.json").unlink()
            state = read_json(self.project / "state.json")
            state["version"] = 1
            write_json(self.project / "state.json", state)
            self.assertEqual(set(verify_project(self.project, emit=lambda _: None).values()), {"pending"})
            run(self.project, backend, ask=lambda _: self.fail("Unexpected approval"), emit=lambda _: None)
        self.assertEqual(len(backend.semantic_calls), 12)
        self.assertEqual(read_json(self.project / "state.json")["version"], 2)

    def test_exhausted_semantic_repairs_retain_failure_and_can_resume(self):
        bad = deepcopy(self.draft)
        bullet = bad["candidates"][0]["sections"][0]["entries"][0]["bullets"][0]
        bullet["text"] += " Led the team."

        class RejectingBackend(FakeBackend):
            def ask(inner, instruction, data, shape):
                result = super().ask(instruction, data, shape)
                if shape == schema.SEMANTIC_REVIEW and "Led the team" in data["bullet"]["text"]:
                    result["support"].update(verdict="unsupported", reason="Leadership not sourced")
                return result

        backend = RejectingBackend([self.plan, self.outline, bad, {"repair_0": bullet}])
        with patch("scrubber.workflow.compile_tex", side_effect=compiled):
            with self.assertRaisesRegex(ValueError, "Semantic review failed"):
                run(self.project, backend, max_repairs=1, ask=lambda _: "yes", emit=lambda _: None)
            self.assertEqual(read_json(self.project / "faithful/verification.json")["status"], "fail")
            self.assertEqual(read_json(self.project / "draft.json"), bad)
            self.assertTrue((self.project / "semantic-errors.json").exists())
            resumed = FakeBackend([{"repair_0": deepcopy(self.bullet)}])
            results = run(self.project, resumed, ask=lambda _: "yes", emit=lambda _: None)
        self.assertEqual(set(results.values()), {"pass"})
        self.assertEqual(len(resumed.semantic_calls), 1)
        self.assertFalse((self.project / "semantic-errors.json").exists())

    def test_uncertain_relevance_is_presented_and_acceptance_survives_resume(self):
        class UncertainBackend(FakeBackend):
            def ask(inner, instruction, data, shape):
                result = super().ask(instruction, data, shape)
                if shape == schema.SEMANTIC_REVIEW:
                    result["relevance"][0].update(verdict="uncertain", reason="Transferability needs confirmation")
                return result

        backend = UncertainBackend([self.plan, self.outline, self.draft])
        messages = []
        with patch("scrubber.workflow.compile_tex", side_effect=compiled):
            results = run(self.project, backend, ask=lambda _: "yes", emit=messages.append)
            self.assertEqual(set(results.values()), {"pass"})
            run(self.project, backend, ask=lambda _: self.fail("Approval unexpectedly repeated"), emit=lambda _: None)
        self.assertTrue(any("Transferability needs confirmation" in message for message in messages))
        self.assertEqual(len(backend.semantic_calls), 6)

    def test_labeled_evaluation_examples_have_valid_source_and_keyword_inputs(self):
        import json
        from .evaluate_semantic import example_inputs
        from scrubber.verify import contains
        examples = json.loads((Path(__file__).parent / "data/semantic_cases.json").read_text())
        self.assertEqual(len(examples), 7)
        for case in examples:
            inputs = example_inputs(case)
            self.assertTrue(contains(inputs["bullet"]["text"], case["keyword"]))
            self.assertTrue(contains(inputs["job"], case["keyword"]))
            for evidence in inputs["bullet"]["evidence"]:
                self.assertIn(evidence["quote"], inputs["master"][evidence["source"]])

    def test_lean_initial_pass_uses_keyword_only_certificate(self):
        backend = FakeBackend([self.plan, self.outline, self.draft])
        from types import SimpleNamespace
        with patch("scrubber.workflow.compile_tex", side_effect=compiled), patch(
                "scrubber.workflow.shutil.which", return_value="lean"), patch(
                "scrubber.workflow.subprocess.run", return_value=SimpleNamespace(
                    returncode=0, stdout="", stderr="")) as lean:
            run(self.project, backend, lean=True, ask=lambda _: "yes", emit=lambda _: None)
        names = [call.args[0][1] for call in lean.call_args_list]
        self.assertEqual(names[:3], ["keywords.lean"] * 3)
        self.assertEqual(names[-3:], ["constraints.lean"] * 3)
        self.assertNotIn("recorded_constraints_hold", (self.project / "faithful/keywords.lean").read_text())


if __name__ == "__main__":
    unittest.main()
