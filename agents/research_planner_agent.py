# -*- coding: utf-8 -*-
"""
agents/research_planner_agent.py - 研究规划 Agent
"""

from __future__ import annotations

from agents.base_agent import BaseAgent
from core.prompt_loader import load as load_prompts
from models.domain import CompetitorList, Priority, QAIssue, ResearchTask


DEFAULT_TOPICS: dict[str, str] = {
    "product_features": "产品功能、定位、集成与差异化",
    "pricing_info": "定价层级、免费版、付费版、计费模型",
    "market_share": "市场份额、客户规模、增长与 traction",
    "user_reviews": "用户评价、好评、投诉与使用反馈",
    "channels": "渠道、生态合作、销售方式与目标客群",
}


class ResearchPlannerAgent(BaseAgent):
    def __init__(self):
        prompts = load_prompts("research_planner_agent")
        super().__init__(
            agent_id="ResearchPlannerAgent",
            system_prompt=prompts["system_prompt"],
        )

    async def run(
        self,
        product_description: str,
        competitor_list: CompetitorList,
        focus_topics: list[str] | None = None,
        qa_issues: list[QAIssue] | None = None,
        retry_count: int = 0,
    ) -> list[ResearchTask]:
        topics = focus_topics or list(DEFAULT_TOPICS.keys())
        issue_topics = self._issue_topics(qa_issues or [])
        tasks: list[ResearchTask] = []

        for competitor in competitor_list.competitors:
            for topic in topics:
                priority = Priority.P2.value if retry_count == 0 else Priority.P1.value
                if topic in issue_topics:
                    priority = Priority.P0.value
                query = f"{competitor.name} {DEFAULT_TOPICS.get(topic, topic)}"
                task_id = f"{competitor.name}:{topic}:{retry_count}"
                tasks.append(
                    ResearchTask(
                        id=task_id,
                        competitor=competitor.name,
                        topic=topic,
                        query=query,
                        priority=priority,
                        retry_count=retry_count,
                    )
                )
        self._log(f"已规划研究任务 {len(tasks)} 个")
        return tasks

    @staticmethod
    def _issue_topics(issues: list[QAIssue]) -> set[str]:
        topics = set()
        for issue in issues:
            for related in issue.related_ids:
                if ":" in related:
                    topics.add(related.split(":", 1)[1])
        return topics
