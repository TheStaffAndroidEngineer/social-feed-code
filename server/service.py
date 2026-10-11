"""Fieldnotes: bounded immutable ranked snapshots with live visibility overlays."""

import uuid
from urllib.parse import urlsplit, parse_qs
from base import BaseService, Problem, fields, integer, text, run

TITLES = [
    "A quiet corner of the city",
    "Morning light on the river",
    "The weekend repair table",
    "Walking the old market",
    "A shelf made from offcuts",
    "Where the trail turns north",
    "The courtyard after rain",
    "Learning to mend a sleeve",
    "Small gardens on rooftops",
    "The long way to the station",
    "A shared pot of soup",
    "Notes from the community studio",
]


BODIES = ['Between the bus stop and the bakery, a narrow passage opens into a planted courtyard. The street is still audible, but nobody needs to hurry through. A bench faces the afternoon shade rather than the road.', 'At first light the river looks flat enough to be a sheet of metal. A rower breaks the reflection into short bright lines. From the bridge, the city seems to wake one window at a time.', 'The repair table starts with three tools and a jar of spare buttons. Neighbours arrive with a loose handle, a torn pocket and a lamp that will not switch on. The most useful thing on the table turns out to be somebody who has fixed it before.', 'The old market is easiest to understand on foot. Deliveries enter through the back lanes while the front doors open to shoppers. Following a small hand-painted sign leads to a stall that has no window on the main street.', 'The offcuts are different lengths, so the shelf begins with sorting rather than sawing. Two straight pieces become the uprights. The small gaps between the remaining boards leave room for the wall to show through.', 'The trail turns north just after the stone bridge. Beyond that point the road noise fades and the ground stays damp under the trees. A fallen branch makes a useful seat for the walk back.', 'Rain leaves a second courtyard on the paving stones. The windows and pots appear upside down until a passing bicycle disturbs them. By lunchtime only the sheltered corners still hold water.', 'A small tear at the cuff becomes visible when the fabric is stretched flat. The first stitches hold the edges; the next row shares the load with the sound cloth around it. The repair does not disappear, and it does not need to.', 'The roof garden is a collection of borrowed containers. Each one catches a different amount of sun, so the herbs move as the season changes. Watering is shared by the people who pass through the stairwell each morning.', 'The longer walk to the station follows the quieter side of the canal. It adds ten minutes and removes two crossings. On days without a deadline, the difference feels like time returned rather than time spent.', 'One person brings lentils, another brings bread, and somebody remembers a larger pot. Lunch becomes a reason to stop work at the same time. The recipe is written down only after everyone has eaten.', 'The studio noticeboard holds a plan, a spare key and a question nobody has answered yet. Work-in-progress stays on the tables overnight. In the morning, a note from the previous shift saves a conversation from starting again.']


class Service(BaseService):
    KIND = "fieldnotes"

    def seed(self):
        return {
            "posts": [
                {
                    "id": f"post-{i+1:02}",
                    "title": title,
                    "topic": ["Places", "Making", "People"][i % 3],
                    "author": ["Mira", "Dev", "Anika"][i % 3],
                    "score": 100 - i * 3,
                    "visible": True,
                    "liked": False,
                    "body": BODIES[i],
                }
                for i, title in enumerate(TITLES)
            ],
            "sessions": {},
            "revision": 1,
        }

    def view(self, state, now):
        return {
            "topics": ["All", "Places", "Making", "People"],
            "revision": state["revision"],
            "visibleCount": sum(p["visible"] for p in state["posts"]),
        }

    def page(self, state, session_id, offset, topic, now):
        session = state["sessions"].get(session_id)
        if not session:
            raise Problem("Unknown reading snapshot", 404)
        if session.get("expired", False) or now >= session["expiresAt"]:
            raise Problem("Reading snapshot expired; refresh the feed", 410)
        if session["topic"] != topic:
            raise Problem("Cursor belongs to another topic", 409)
        integer(offset, 0, len(session["ids"]))
        ids = session["ids"][offset : offset + 3]
        posts = {p["id"]: p for p in state["posts"]}
        # Consume snapshot positions even if a live visibility overlay removes a row.
        items = [posts[key] for key in ids if posts[key]["visible"]]
        next_offset = offset + len(ids)
        return {
            "sessionId": session_id,
            "topic": topic,
            "snapshotRevision": session["revision"],
            "items": items,
            "nextOffset": next_offset,
            "more": next_offset < len(session["ids"]),
            "expiresAt": session["expiresAt"],
            "consumedPositions": len(ids),
        }

    def route(self, method, path, body):
        url = urlsplit(path)
        if method == "GET" and url.path.startswith("/feed/"):
            query = parse_qs(url.query, keep_blank_values=True)
            fields(query, {"offset", "topic"})
            if any(len(v) != 1 for v in query.values()) or not query["offset"][0].isdigit():
                raise Problem("Invalid cursor")
            with self.transaction() as db:
                import json

                controls = self.controls(db)
                if controls.get("unavailable"):
                    raise Problem("Fixture unavailable", 503)
                now = self.now(controls)
                state = json.loads(db.execute("SELECT value FROM state WHERE id=1").fetchone()[0])
                session_id = url.path.removeprefix("/feed/")
                session = state["sessions"].get(session_id)
                if session and (session.get("expired", False) or now >= session["expiresAt"]):
                    session["expired"] = True
                    from base import canonical

                    db.execute("UPDATE state SET value=? WHERE id=1", (canonical(state),))
                else:
                    page = self.page(
                        state, session_id, int(query["offset"][0]), query["topic"][0], now
                    )
                    return 200, {"kind": self.KIND, "observedAt": now, "data": page}, False
            # Commit the terminal expiry before reporting it; raising inside would roll it back.
            raise Problem("Reading snapshot expired; refresh the feed", 410)
        return super().route(method, path, body)

    def apply(self, state, action, args, now):
        if action == "open":
            fields(args, {"topic"})
            topic = text(args["topic"], 20)
            if topic not in {"All", "Places", "Making", "People"}:
                raise Problem("Unknown topic")
            # Keep expired IDs recognizable so their callers receive an explicit expiry outcome.
            if len(state["sessions"]) >= 100:
                return {"accepted": False, "reason": "Fixture snapshot limit reached"}
            session_id = str(uuid.uuid4())
            posts = sorted(
                (
                    p
                    for p in state["posts"]
                    if p["visible"] and (topic == "All" or p["topic"] == topic)
                ),
                key=lambda p: (-p["score"], p["id"]),
            )
            state["sessions"][session_id] = {
                "topic": topic,
                "ids": [p["id"] for p in posts],
                "revision": state["revision"],
                "expiresAt": now + 120000,
            }
            return {"accepted": True, "sessionId": session_id, "topic": topic}
        if action == "like":
            fields(args, {"postId", "liked"})
            text(args["postId"], 40)
            if type(args["liked"]) is not bool:
                raise Problem("liked must be boolean")
            post = next((p for p in state["posts"] if p["id"] == args["postId"]), None)
            if not post or not post["visible"]:
                return {"accepted": False, "reason": "Post is no longer available"}
            post["liked"] = args["liked"]
            state["revision"] += 1
            return {"accepted": True, "postId": post["id"], "liked": post["liked"]}
        if action == "hide":
            fields(args, {"postId"})
            text(args["postId"], 40)
            post = next((p for p in state["posts"] if p["id"] == args["postId"]), None)
            if not post:
                return {"accepted": False, "reason": "Unknown post"}
            post["visible"] = False
            state["revision"] += 1
            return {"accepted": True, "postId": post["id"]}
        if action == "publish":
            fields(args, {"postId", "title", "topic", "score"})
            post_id = text(args["postId"], 40)
            title = text(args["title"], 100)
            topic = text(args["topic"], 20)
            score = integer(args["score"], 0, 1000)
            if topic not in {"Places", "Making", "People"}:
                raise Problem("Unknown topic")
            if any(p["id"] == post_id for p in state["posts"]):
                return {"accepted": False, "reason": "Post identity exists"}
            if len(state["posts"]) >= 100:
                return {"accepted": False, "reason": "Fixture post limit reached"}
            state["posts"].append(
                {
                    "id": post_id,
                    "title": title,
                    "topic": topic,
                    "score": score,
                    "author": "Guest editor",
                    "visible": True,
                    "liked": False,
                    "body": "A newly published local fixture story.",
                }
            )
            state["revision"] += 1
            return {"accepted": True, "postId": post_id}
        raise Problem("Unknown action")


if __name__ == "__main__":
    run(Service, 8916)
