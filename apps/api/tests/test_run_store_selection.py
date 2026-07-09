"""Phase 8: confirm the API's default run store is unchanged (in-memory)
unless DATABASE_URL / AGENTFORGE_RUN_STORE is set at process start.

app.main selects its store once at import time (module level, same as the
pre-Phase-8 code), so this only asserts on that already-built instance
rather than re-importing under different env (re-importing would require
reloading the module, which would also rebuild registries/eval_judge_fn —
out of scope here).
"""

from agent_core.observability import InMemoryRunStore

from app.main import run_store


def test_default_run_store_is_in_memory():
    # No DATABASE_URL / AGENTFORGE_RUN_STORE is exported into the test
    # process env, so app.main.select_run_store() must have fallen back to
    # (or simply defaulted to) the same InMemoryRunStore as before Phase 8.
    assert isinstance(run_store, InMemoryRunStore)
