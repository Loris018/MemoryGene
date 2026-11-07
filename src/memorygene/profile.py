"""Read-only user profile: current memories grouped by category, with evidence.

Categories follow the first segment of the topic name:

  profile.*     basic facts (city, job, birthday)
  preference.*  likes and dislikes
  recent.*      the user's recent situation (worries, mood, what they are busy
                with); written with a default 30-day expiry and renewed when
                the user mentions it again
  life.*        personal experiences mentioned in conversation
  project.*     projects the user works on

Expired recent items are listed separately as past situations; they stay in
the history but are no longer the user's current state.
"""

from .core import instant, now_string
from .impressions import listing
from .reconsolidate import slots

CATEGORIES = {"profile": "basic", "preference": "preferences", "recent": "recent",
              "life": "life", "project": "projects"}
RECENT_DAYS = 30


def category(topic):
    return CATEGORIES.get(topic.split(".", 1)[0], "other")


def profile(store, namespace, subject, *, now=None, visible_session=""):
    clock = instant(now or now_string())
    groups = {name: [] for name in [*CATEGORIES.values(), "other"]}
    past = []
    for slot in slots(store, namespace, subject, now=clock.isoformat(),
                      visible_session=visible_session):
        group = category(slot["topic"])
        head = slot["head"]
        if head:
            c = head["candidate"]
            item = {"topic": slot["topic"], "value": c["value"], "source": c["source"],
                    "since": c["at"], "certainty": c["certainty"]}
            if c["expires_at"]:
                item["expires_at"] = c["expires_at"]
                item["days_left"] = max(0, (instant(c["expires_at"]) - clock).days)
            groups[group].append(item)
            continue
        confirmed = [e for e in slot["events"] if e["status"] == "confirmed"]
        if group == "recent" and confirmed:
            last = confirmed[-1]["candidate"]
            if last["expires_at"] and instant(last["expires_at"]) <= clock:
                past.append({"topic": slot["topic"], "value": last["value"],
                             "source": last["source"], "ended": last["expires_at"]})
    views = listing(store, namespace, subject, now=clock.isoformat(), include_stale=False)
    return {"ok": True, "command": "profile", "profile": groups, "past_situations": past,
            "impressions": views}
