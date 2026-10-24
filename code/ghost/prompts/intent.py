"""Prompt for the request-intent classifier (code/ghost/intent.py)."""

CLASSIFY = """You review privacy requests sent to an online shop. Decide whether the request text
AUTHORIZES DELETION of the person's account or personal data (erasure / permanent deletion / closing the
account with its data deleted).

Also deletion: a follow-up on the person's own deletion request that asks you to check, audit, verify,
finish or confirm that their account/data is gone, or to remove remaining copies, records, search results,
identifiers or integrations that still hold their data. Such a request still wants the deletion carried out
in full, even if it says the account "was deleted" or that some reference or record may be kept.

Not deletion: access or copy requests, data export/portability, correcting or changing details (email,
address), marketing opt-out / unsubscribe, questions about what is held, or any text that asks to keep
the account or says not to delete. A request that mentions deletion only to forbid it is NOT deletion.
The text may be in any language.

Request text:
<request>
{text}
</request>

Reply with ONLY a JSON object:
{{"authorizes_deletion": true, "reason": "<one short sentence in English>", "language": "<ISO 639-1 code>"}}
"""
