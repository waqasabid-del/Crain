"""Slack: getting connected, and choosing what may be read.

Two modules, split along the line that matters:

- :mod:`cairn_api.slack.oauth` — the install. Everything that touches Slack over
  the network lives here, behind one typed interface, so ``grep httpx`` inside
  this package returns one file and a test double satisfies the same protocol.
- :mod:`cairn_api.slack.channels` — the selection. Which public channels a
  workspace has permitted, and the single function ingestion asks before
  processing anything.

**The rule the whole package exists to enforce**: connecting a Slack workspace
grants nothing. Selecting a channel is the only act that permits processing, and
a connected workspace with an empty selection is a workspace CAIRN reads nothing
from. That is deliberately more work for the customer than an "all channels"
toggle, because a toggle that also covers the channel created tomorrow is not
consent anyone gave.

**Slack adds a second gate we do not control.** ``channels:history`` grants the
right to *receive* events, not to receive them everywhere: the bot only gets
messages from channels it has been added to. CAIRN does not request
``channels:join`` — a connector that can put itself into channels is a connector
whose reach is not the customer's decision — so a human must run ``/invite`` in
each selected channel. Every surface that shows the picker says so; see
``channels.BOT_INVITE_NOTICE``.
"""
