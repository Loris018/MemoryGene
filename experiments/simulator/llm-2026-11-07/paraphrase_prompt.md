You rewrite short chat messages. Do not use any tools.

Each item below is one message a user sent to a chat assistant, with the meaning it must keep. Rewrite each message so it sounds like natural, casual chat in the same language (Chinese stays Chinese, English stays English). Vary the wording; do not copy the original phrasing.

Rules:
- Keep the meaning exactly as described in "meaning". Do not add or remove information.
- Keep the text in "value" exactly as written, character for character.
- One message in, one message out. Keep it to one or two sentences.

Meanings:
- assert: the user states their own preference or fact.
- change_marked: the user says their preference or fact has changed to the value (words like "now", "changed", "moved" fit).
- change_unmarked: the user states the value as their preference or fact, WITHOUT any word suggesting a change (no "now", "these days", "changed", "switched", "moved", "现在", "改", "换", "搬", "最近").
- correct: the user corrects something they said earlier.
- hesitate: the user is unsure whether the value is their preference; keep the uncertainty.
- supplement: the user says the value is also nice, without making it their favourite.
- repeat: the user restates the value as still their preference or fact.
- third_party: the value is someone else's preference or fact, not the user's; keep who it is.
- mention: the user merely mentions the value, with no preference or fact about themselves.
- retract: the user says the value is no longer their preference or fact.

Output only a JSON array of objects with keys "id" and "text", in the same order as the input.

Input:
{{ITEMS}}
