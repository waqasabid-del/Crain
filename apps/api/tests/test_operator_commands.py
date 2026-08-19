"""The operator entry points, executed rather than trusted.

`live_check`, `email.probe` and `export_corrections` are the commands an
operator runs at exactly the moments confidence matters most - closing a
release gate, proving a relay, harvesting corrections into the evaluation set.
None of them had a single test: three modules at 0% coverage, discovered when
CI's coverage floor caught the suite from underneath. A command that only runs
in the moment it matters is the shape of tool that breaks in that moment.

These run the real functions end to end with the boundaries substituted - a
scripted model where `live_check` wants a live one proves every refusal branch;
a stub sender under the probe proves both verdicts without a relay.
"""

from __future__ import annotations

import uuid

import pytest
from cairn_api.db.models import Tenant
from cairn_api.email.message import Message
from cairn_api.pipeline.provider import ScriptedProvider
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


class TestLiveCheckRefusesWithoutALiveModel:
    async def test_a_scripted_backend_is_a_refusal_not_a_pass(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole point of the command is that a pass against a canned model
        would close the gate falsely. Exit 2, before any stage runs."""
        import cairn_api.pipeline.live_check as live_check
        from cairn_api.pipeline.embeddings import HashingEmbedder
        from cairn_api.pipeline.jobs import Providers

        monkeypatch.setattr(
            live_check,
            "select_providers",
            lambda settings: Providers(model=_scripted(), embedder=HashingEmbedder(), live=False),
        )

        assert await live_check.main() == 2

    async def test_the_stages_run_and_the_zero_ledger_fails_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A scripted provider pretending to be live drives every stage and
        then trips the last check: the ledger recorded no tokens, and a live
        check whose calls cost nothing did not check anything live."""
        import cairn_api.pipeline.live_check as live_check
        from cairn_api.pipeline.embeddings import HashingEmbedder
        from cairn_api.pipeline.jobs import Providers

        monkeypatch.setattr(
            live_check,
            "select_providers",
            lambda settings: Providers(model=_scripted(), embedder=HashingEmbedder(), live=True),
        )

        assert await live_check.main() == 1


def _scripted() -> ScriptedProvider:
    from cairn_api.evaluation.scripted import build_scripted_provider

    return build_scripted_provider()


class TestTheProbeReportsWhatTheSenderDid:
    async def test_console_backend_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A probe that passed against `ConsoleSender` would be the false pass
        the gate exists to rule out."""
        from cairn_api.email import probe
        from cairn_api.email.senders import ConsoleSender

        monkeypatch.setattr(probe, "build_sender", lambda settings: ConsoleSender())

        assert await probe.probe("nobody@example.test") == 2

    async def test_a_delivered_message_is_a_pass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cairn_api.email import probe

        sent: list[Message] = []

        class Delivers:
            async def send(self, message: Message) -> None:
                sent.append(message)

        monkeypatch.setattr(probe, "build_sender", lambda settings: Delivers())

        assert await probe.probe("inbox@example.test") == 0
        assert sent[0].to == "inbox@example.test"

    async def test_a_relay_refusal_is_a_failure_not_a_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cairn_api.email import probe

        class Refuses:
            async def send(self, message: Message) -> None:
                raise ConnectionRefusedError("relay closed the door")

        monkeypatch.setattr(probe, "build_sender", lambda settings: Refuses())

        assert await probe.probe("inbox@example.test") == 1


class TestExportCorrectionsEmitsReviewableJson:
    async def test_an_empty_workspace_exports_an_empty_case_list(
        self, platform: AsyncSession, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The harvest over a workspace with no corrections is a valid, empty
        payload on stdout - stderr carries the commentary, so stdout stays
        pipeable into the dataset review."""
        import json

        from cairn_api.evaluation import export_corrections

        tenant = Tenant(name="Export", slug=f"exp-{uuid.uuid4().hex[:10]}")
        platform.add(tenant)
        await platform.commit()

        code = await export_corrections.run(tenant.id, version="0.0-test")

        assert code == 0
        out = capsys.readouterr().out
        # Log lines share stdout under the test runner; the payload is the
        # JSON document between the first brace and the last.
        payload = json.loads(out[out.index("{") : out.rindex("}") + 1])
        assert payload["version"] == "0.0-test"
        assert payload["cases"] == []
