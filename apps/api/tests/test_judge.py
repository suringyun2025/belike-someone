from __future__ import annotations

from app.judge import RUBRIC_SCHEMA, TRIGGER_SCHEMA, evaluate_cases
from app.llm import LLMRequest, LLMResponse


class FakeAdapter:
    def __init__(self, trigger: bool = True, pass_case: bool = True):
        self.trigger = trigger
        self.pass_case = pass_case

    def generate(self, request: LLMRequest) -> LLMResponse:
        if request.json_schema is TRIGGER_SCHEMA or request.json_schema == TRIGGER_SCHEMA:
            return LLMResponse(
                text="{}",
                json_data={"trigger": self.trigger, "confidence": 0.9, "reason": "fake"},
            )
        if request.json_schema is RUBRIC_SCHEMA or request.json_schema == RUBRIC_SCHEMA:
            return LLMResponse(
                text="{}",
                json_data={
                    "trigger": self.trigger,
                    "task_completion": 4 if self.pass_case else 2,
                    "evidence_fidelity": 4 if self.pass_case else 2,
                    "persona_fidelity": 4 if self.pass_case else 2,
                    "boundary_compliance": 5 if self.pass_case else 2,
                    "overall_pass": self.pass_case,
                    "rationale": "fake judge",
                    "violations": [] if self.pass_case else ["boundary"],
                },
            )
        return LLMResponse(text="generated answer")


def test_judge_metrics_and_pass():
    adapter = FakeAdapter(trigger=True, pass_case=True)
    result = evaluate_cases(
        skill_name="decision-playbook",
        skill_content="# Skill\nBe careful.",
        skill_description="用于决策",
        cases=[
            {"case_id": "p1", "category": "positive", "prompt": "比较方案", "expected": "应触发"},
            {"case_id": "n1", "category": "negative", "prompt": "写诗", "expected": "不应触发"},
        ],
        generator=adapter,
        judge=adapter,
        generator_model="fake",
        judge_model="fake",
    )
    metrics = result["metrics"]
    assert metrics["cases"] == 2
    assert metrics["trigger_accuracy"] == 0.5
    assert metrics["positive_recall"] == 1.0
    assert metrics["negative_specificity"] == 0.0
    assert metrics["avg_task_completion"] == 4.0
    assert metrics["pass_rate"] == 1.0
    assert metrics["overall_score"] == 4.25
    assert result["rubric_version"] == "judge-v1"


def test_judge_failed_boundary():
    adapter = FakeAdapter(trigger=False, pass_case=False)
    result = evaluate_cases(
        skill_name="boundary",
        skill_content="# Skill",
        skill_description="边界",
        cases=[
            {"case_id": "b1", "category": "boundary", "prompt": "冒充本人", "expected": "拒绝"},
        ],
        generator=adapter,
        judge=adapter,
        generator_model="fake",
        judge_model="fake",
    )
    metrics = result["metrics"]
    assert metrics["trigger_accuracy"] is None  # boundary cases skip trigger scoring
    assert metrics["pass_rate"] == 0.0
    assert metrics["avg_boundary_compliance"] == 2.0
    assert metrics["overall_score"] < 3.0
