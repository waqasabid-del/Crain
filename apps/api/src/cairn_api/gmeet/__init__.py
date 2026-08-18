"""The Google Meet connector: authorise, subscribe to consented meetings, receive.

Three modules, and the split is the same one `gchat/` uses because the failure
modes are the same: :mod:`~cairn_api.gmeet.oauth` is the only code that talks to
Google's OAuth endpoints, :mod:`~cairn_api.gmeet.subscriptions` is the only code
that talks to Workspace Events, and :mod:`~cairn_api.gmeet.pubsub` verifies what
arrives back.

**What this package does not do**, stated here because every one of these is a
thing a reader will assume is somewhere in it: it does not fetch a transcript, a
recording, or any artifact content; it does not transcribe; it does not join a
meeting; it does not read a calendar; it does not observe participants, joins,
leaves or attendance; and it does not spend a model call. It subscribes to one
announcement — "a transcript file was generated" — for meetings whose every
participant has agreed, and records that the announcement happened.
"""
