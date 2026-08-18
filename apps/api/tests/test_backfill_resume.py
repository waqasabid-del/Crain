"""A parked backfill has to be able to start again.

**Found by the first real backfill.** `backfill.claimable_runs` selects runs a
worker may pick up - `PENDING`, `RUNNING` or `THROTTLED`, lease expired, throttle
elapsed - and nothing in the application ever called it. The only thing that
enqueued a backfill job was the connect endpoint, and it only does so for a run
it has just created.

So a run that parked kept its row and lost its job. `THROTTLED` is not an error
state - it is what exhausting the rate budget is supposed to do, and the module
docstring says the run "parks" and resumes - but there was nothing to resume it.
A customer's first 90 days would sit at `commits_imported = 0` forever, with a
healthy connection, no error text, and no alert: the shape of failure this
product exists to avoid.

The real one was parked by a configuration error and could not be restarted even
after the configuration was fixed. Reconnecting did nothing, because the run
already existed.
"""

from __future__ import annotations

import inspect

from cairn_api.github import backfill


class TestTheResumePathIsReachable:
    def test_something_in_production_calls_claimable_runs(self) -> None:
        """**A vertical-slice check, not a style check.**

        `claimable_runs` was correct, tested and unreachable. A layer nothing
        calls is not a layer; it is a function that passes its own tests while
        the behaviour it implements does not exist.
        """
        from cairn_api.jobs import main

        source = inspect.getsource(main)
        assert "claimable_runs" in source, (
            "backfill.claimable_runs has no production caller, so a parked or "
            "throttled backfill never resumes"
        )

    def test_the_sweep_runs_on_the_existing_maintenance_loop(self) -> None:
        """One periodic loop, not two. A second scheduler is a second thing to
        supervise, and the maintenance loop already claims its rows
        `FOR UPDATE SKIP LOCKED`, so running it from every worker is safe."""
        from cairn_api.jobs import main

        assert "_resume_backfills" in inspect.getsource(main.run_maintenance)
        assert "claimable_runs" in inspect.getsource(main._resume_backfills)

    def test_throttled_is_claimable(self) -> None:
        """The state exhausting the rate budget parks a run in. If this were
        excluded, the sweep would exist and still never resume the runs that
        most need resuming."""
        source = inspect.getsource(backfill.claimable_runs)
        for state in ("PENDING", "RUNNING", "THROTTLED"):
            assert state in source


class TestTheImportKeepsItsPriority:
    def test_a_resumed_run_is_still_bulk(self) -> None:
        """A resumed import must not overtake live activity. Fairness is about
        the queue as a whole: somebody's 90-day history is work nobody is
        waiting for, and a live push always outranks it."""
        from cairn_api.github import jobs as github_jobs

        assert "Priority.BULK" in inspect.getsource(github_jobs.enqueue)
