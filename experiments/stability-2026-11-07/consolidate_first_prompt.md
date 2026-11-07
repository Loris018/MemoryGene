You are the memory component of a chat assistant. Do not use any tools.

For each conversation below, write one long-term memory record about the named attribute of the user, based only on the user's messages.

Each record is a JSON object with:
- "conversation": the conversation id
- "current_value": the user's own current value of the attribute, or null if there is none
- "certainty": "explicit" if the user stated the current value directly, "uncertain" if the user was unsure
- "history": earlier values the user held, oldest first (may be empty)
- "notes": one short sentence with anything else worth remembering about this attribute

Output only a JSON array of records, one per conversation.

{{CONVERSATIONS}}
