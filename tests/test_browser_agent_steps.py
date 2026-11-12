"""The agent's steps take several actions (`browser_job.AGENT_LIMITS`): a value refused as not his
is said to the agent as a result, never an error, since browser-use drops the rest of a step's
actions after an error. On 12 Nov one refused telephone made every step one action, fifteen
steps for one form. Checked on browser-use's own `Agent.multi_act`."""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace as NS

from browser_use import Agent
from browser_use.agent.views import ActionResult

from app.features import browser_job


class _Action:
    def __init__(self, name):
        self.name = name

    def model_dump(self, exclude_unset=True):
        return {self.name: {"index": 1}}


def _steps(first):
    """The actions browser-use runs of three in one step, the first answered ``first``."""
    ran = []

    async def act(action, **kwargs):
        ran.append(action.name)
        return first if len(ran) == 1 else ActionResult(extracted_content="ok")

    async def nothing(*args, **kwargs):
        return None

    async def url():
        return "https://httpbin.org/forms/post"
    agent = NS(browser_session=NS(_cached_browser_state_summary=None, get_current_page_url=url,
                                  agent_focus_target_id="t1"),
               browser_profile=NS(wait_between_actions=0), _check_stop_or_pause=nothing, _log_action=nothing,
               _demo_mode_log=nothing, tools=NS(act=act, registry=NS(registry=NS(actions={}))),
               settings=NS(page_extraction_llm=None), file_system=None, sensitive_data=None,
               available_file_paths=None, extraction_schema=None, logger=logging.getLogger("t"),
               _is_connection_like_error=lambda e: False, state=NS(n_steps=1))
    asyncio.run(Agent.multi_act(agent, [_Action("input"), _Action("input"), _Action("click")]))
    return ran


def test_a_refused_value_leaves_the_rest_of_the_step_to_run():
    assert _steps(ActionResult(**browser_job.NOT_HIS_RESULT)) == ["input", "input", "click"]


def test_an_error_would_have_dropped_them():
    assert _steps(ActionResult(error="Not done")) == ["input"]


def test_the_agent_takes_several_actions_a_step():
    assert browser_job.AGENT_LIMITS["max_actions_per_step"] == browser_job.MAX_ACTIONS > 1
