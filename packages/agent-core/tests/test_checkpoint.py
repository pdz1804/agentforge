"""Durable checkpointer: opt-in multi-turn thread resume + isolation (Phase 5).

Uses only the offline scripted model provider — no LLM spend. Proves resume /
isolation by observing what the model actually receives on each call (the
message count), not by peeking at internal graph state.

Multi-turn scenarios run all turns inside a single `asyncio.run()` (one event
loop), matching real usage: a long-lived server (e.g. uvicorn) holds one loop
for its whole life and awaits `arun`/`astream` many times on it, it does not
spin up a fresh loop per call. `AsyncSqliteSaver` binds an `asyncio.Lock` to
whichever loop is running when it is first used, so reusing a materialized
saver across separate `asyncio.run()` calls (each with a fresh loop) is a
test-only anti-pattern, not a supported one.
"""

import asyncio

from agent_core import (
    ModelProvider,
    ModelResponse,
    build_default_registries,
    checkpointer_from_env,
    compile_agent,
    in_memory_checkpointer,
    load_manifest_dict,
    resolve_manifest,
    sqlite_checkpointer,
)
from agent_core.checkpoint import ENV_CHECKPOINT_DB, PendingSqliteCheckpointer


class RecordingModelProvider(ModelProvider):
    """Never calls a tool; records how many messages it was shown on each call
    so tests can prove whether prior-turn history was resumed or not.
    """

    provider = "recording"

    def __init__(self) -> None:
        self.seen_message_counts: list[int] = []

    async def complete(self, messages, tools=None, **cfg) -> ModelResponse:
        self.seen_message_counts.append(len(messages))
        return ModelResponse(text=f"turn {len(self.seen_message_counts)}")


def _manifest(max_steps: int = 5) -> dict:
    return {
        "id": "runner",
        "model": {"provider": "recording", "name": "test-model"},
        "prompt_ref": "prompts/echo_agent.md",
        "tools": [],
        "limits": {"max_steps": max_steps},
    }


def _compile(checkpointer=None):
    registries = build_default_registries()
    provider = RecordingModelProvider()
    registries.models.register("recording", provider)
    manifest = load_manifest_dict(_manifest())
    resolve_manifest(manifest, registries)
    agent = compile_agent(manifest, registries, checkpointer=checkpointer)
    return agent, provider


def _run_turns(agent, turns: list[tuple[str, str]]) -> list[str | None]:
    """Run `(user_input, thread_id)` turns sequentially on one event loop and
    return each turn's answer, mirroring how a persistent server would drive
    the same `CompiledAgent` across multiple requests.
    """

    async def scenario() -> list[str | None]:
        answers = []
        for user_input, thread_id in turns:
            result = await agent.arun(user_input, thread_id=thread_id)
            answers.append(result.answer)
        return answers

    return asyncio.run(scenario())


def test_default_no_checkpointer_is_single_shot_no_bleed():
    """Phase 2 contract preserved: no checkpointer arg => every run on any
    thread_id (even a repeated one) starts from fresh initial state.
    """
    agent, provider = _compile()  # no checkpointer -> default behavior

    answers = _run_turns(agent, [("hello", "t1"), ("again", "t1")])

    assert answers == ["turn 1", "turn 2"]
    # Both calls saw exactly the fresh-state message count (system + user) —
    # no accumulation, no bleed across runs.
    assert provider.seen_message_counts[0] == provider.seen_message_counts[1]
    asyncio.run(agent.aclose())  # no checkpointer configured -> safe no-op


def test_in_memory_checkpointer_resumes_same_thread_and_isolates_others():
    agent, provider = _compile(checkpointer=in_memory_checkpointer())

    answers = _run_turns(
        agent,
        [
            ("hello", "t1"),
            ("again", "t1"),  # same thread -> resumes
            ("fresh", "t2"),  # different thread -> isolated
        ],
    )

    assert answers == ["turn 1", "turn 2", "turn 3"]
    # Turn 2 on t1 saw more messages than turn 1 (turn 1's user/assistant
    # history was resumed and is now part of t1's context).
    assert provider.seen_message_counts[1] > provider.seen_message_counts[0]
    # t2 is a fresh thread: it starts at the same size as t1's first turn,
    # proving no cross-thread bleed from t1.
    assert provider.seen_message_counts[2] == provider.seen_message_counts[0]


def test_astream_also_resumes_same_thread():
    agent, provider = _compile(checkpointer=in_memory_checkpointer())

    async def scenario() -> list[str | None]:
        answers: list[str | None] = []
        for user_input in ("hello", "again"):
            answer = None
            async for event in agent.astream(user_input, thread_id="t1"):
                if event.type == "answer":
                    answer = event.detail
            answers.append(answer)
        return answers

    answers = asyncio.run(scenario())

    assert answers == ["turn 1", "turn 2"]
    assert provider.seen_message_counts[1] > provider.seen_message_counts[0]


def test_sqlite_checkpointer_persists_across_compiled_agent_instances(tmp_path):
    """Real, file-backed durability: a second CompiledAgent (simulating a
    fresh process restart, hence its own event loop) built over the same
    sqlite file resumes thread state.
    """
    db_path = str(tmp_path / "checkpoints.sqlite")
    registries = build_default_registries()
    provider = RecordingModelProvider()
    registries.models.register("recording", provider)
    manifest = load_manifest_dict(_manifest())
    resolve_manifest(manifest, registries)

    async def turn(agent, user_input: str):
        result = await agent.arun(user_input, thread_id="t1")
        await agent.aclose()  # release the sqlite connection's worker thread
        return result

    agent1 = compile_agent(manifest, registries, checkpointer=sqlite_checkpointer(db_path))
    r1 = asyncio.run(turn(agent1, "hello"))

    agent2 = compile_agent(manifest, registries, checkpointer=sqlite_checkpointer(db_path))
    r2 = asyncio.run(turn(agent2, "again"))

    assert r1.answer == "turn 1"
    assert r2.answer == "turn 2"
    assert provider.seen_message_counts[1] > provider.seen_message_counts[0]
    assert (tmp_path / "checkpoints.sqlite").exists()  # actually wrote to disk


def test_eval_mode_stays_isolated_even_with_checkpointer_configured():
    """Eval runs must stay deterministic/single-shot regardless of a
    configured checkpointer, matching the existing eval_mode contract for
    long-term memory (`_retrieve`/`_persist`). Eval tasks reuse a stable
    thread_id per task (`eval-<task.id>` in eval.py), so without this
    guarantee a checkpointer would silently make eval reruns non-reproducible.
    """
    agent, provider = _compile(checkpointer=in_memory_checkpointer())

    async def scenario() -> list[str | None]:
        r1 = await agent.arun("hello", eval_mode=True, thread_id="eval-task-1")
        r2 = await agent.arun("again", eval_mode=True, thread_id="eval-task-1")
        return [r1.answer, r2.answer]

    answers = asyncio.run(scenario())

    assert answers == ["turn 1", "turn 2"]
    # Same thread_id, both eval_mode=True: no resume, matching the
    # no-checkpointer message-count baseline.
    assert provider.seen_message_counts[0] == provider.seen_message_counts[1]


def test_checkpointer_from_env(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_CHECKPOINT_DB, raising=False)
    assert checkpointer_from_env() is None  # unset -> default, opt-in stays off

    db_path = str(tmp_path / "env_checkpoints.sqlite")
    monkeypatch.setenv(ENV_CHECKPOINT_DB, db_path)
    cp = checkpointer_from_env()
    # Not yet the real AsyncSqliteSaver: constructing that needs a running
    # event loop, so it stays a spec until the runtime materializes it lazily
    # on first async use (see checkpoint.materialize).
    assert isinstance(cp, PendingSqliteCheckpointer)
    assert cp.db_path == db_path


def test_compile_agent_falls_back_to_env_checkpointer(tmp_path, monkeypatch):
    db_path = str(tmp_path / "env_checkpoints.sqlite")
    monkeypatch.setenv(ENV_CHECKPOINT_DB, db_path)
    try:
        agent, provider = _compile()  # no explicit checkpointer -> env wins

        async def scenario() -> list[str | None]:
            r1 = await agent.arun("hello", thread_id="t1")
            r2 = await agent.arun("again", thread_id="t1")
            await agent.aclose()  # release the sqlite connection's worker thread
            return [r1.answer, r2.answer]

        answers = asyncio.run(scenario())

        assert answers == ["turn 1", "turn 2"]
        assert provider.seen_message_counts[1] > provider.seen_message_counts[0]
        assert (tmp_path / "env_checkpoints.sqlite").exists()
    finally:
        monkeypatch.delenv(ENV_CHECKPOINT_DB, raising=False)
