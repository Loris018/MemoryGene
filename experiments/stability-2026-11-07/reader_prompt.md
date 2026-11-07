You are a chat assistant answering from your stored memory. Do not use any tools.

For each item below, use only the information given for that item to answer two questions about the user: what is the user's current value of the named attribute, and is the user sure about it?

Output only a JSON array of objects with:
- "conversation": the item id
- "value": the user's current value, or null if there is none
- "sure": true if the user is sure, false if the user is unsure or there is no value

{{ITEMS}}
