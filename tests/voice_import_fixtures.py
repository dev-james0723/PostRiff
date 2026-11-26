"""Voice import in the local dev harness: `scripts/postriff_dev_hosted.py --voice-import-fixture`.

`providers` adds dev accounts on Threads, Instagram, Bluesky and Mastodon (built on the harness's DevProvider, so its
consent page and its "second account" choice work as before). They grant the read scope voice import needs and no
publish scope. `mount` applies migration 140 to the loopback harness database (idempotent), switches POSTRIFF_VOICE_IMPORT
on for those four providers and gives the importer `HistoryTransport` and `resolve`, so the real readers page through the
canned history below; the harness ticker then advances the runs.

Everything here is synthetic: the piano studio, its posts, the account ids and the two server names (RFC 2606
documentation domains). Nothing reaches a network: the transport answers only the four history endpoints (404 for
anything else) and the resolver knows only the two fixture hosts.

PUBLISHED_ID is the media id the harness's DevTransport gives the first Threads post a harness session publishes
(container 1000, then media 91000). A workspace whose publish journal holds a Threads job with that provider reference
sees the canned post with this id classified `rafii_published` and left out of the voice evidence.
"""
from __future__ import annotations

import json
import socket
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from postriff_phase2 import voice_import

VALUES = {voice_import.FLAG: "1", voice_import.PROVIDERS_FLAG: "threads,instagram,bluesky,mastodon"}
PAGE = 5                                      # small pages, so every account is read over several pages
PDS = "pds.example.com"
SERVER = "social.example.org"
FIXTURE_ADDRESS = "93.184.216.34"             # the fixture resolver's answer for the two hosts above; never connected to
PUBLISHED_ID = "91000"
PLATFORMS = {"threads": "Threads", "instagram": "Instagram", "bluesky": "Bluesky", "mastodon": "Mastodon"}
READ_SCOPES = {"threads": ("threads_basic",), "instagram": ("instagram_business_basic",), "bluesky": ("atproto",),
               "mastodon": ("read:accounts", "read:statuses")}
# (first dev account, the consent page's "second account"); the Threads pair is the harness's own DevProvider identity.
ACCOUNTS = {"threads": ("17841400000000", "17841400000000002"), "instagram": ("17841400000077", "17841400000078"),
            "bluesky": ("did:plc:fixturestudiovoiceimport", "did:plc:fixturesecondstudiovoice"),
            "mastodon": (f"109000000000000001@{SERVER}", f"109000000000000002@{SERVER}")}
HANDLES = {"instagram": ("@fixture_studio", "@fixture_studio_two"), "bluesky": ("@studio.example.com", "@second.example.com"),
           "mastodon": (f"@studio@{SERVER}", f"@second@{SERVER}")}

# --- the studio's history, newest first ------------------------------------------------------------------------------
# Threads: (id, timestamp, kind, text, media_type). The reader keeps reposts without their words.
THREADS = (
    (PUBLISHED_ID, "2026-11-22T10:00:00+0000", "original",
     "Saturday open studio is back: bring a friend, try the upright piano, and stay for tea after the last session.", "TEXT_POST"),
    ("18100000000000011", "2026-11-18T09:15:00+0000", "original",
     "Small habit that works: end every practice with one piece you already love playing.", "TEXT_POST"),
    ("18100000000000010", "2026-11-12T12:40:00+0000", "original",
     "New practice room, new lamp, same old metronome that never lets anyone rush.", "IMAGE"),
    ("18100000000000009", "2026-11-05T08:05:00+0000", "original", "今朝有位學生終於彈完成首曲，佢自己都唔信，我哋成班人拍晒手。", "TEXT_POST"),
    ("18100000000000008", "2026-10-29T17:30:00+0000", "original",
     "A quiet reminder that the studio is closed on public holidays. Lessons move to the following week, nothing is lost.", "TEXT_POST"),
    ("18100000000000007", "2026-10-21T11:00:00+0000", "original", "本月學生音樂會將於二十八日舉行，歡迎家長及朋友出席，入場免費。", "TEXT_POST"),
    ("18100000000000006", "2026-10-14T15:20:00+0000", "quote",
     "This is exactly why we keep the first lesson free: nobody should pay to find out whether they enjoy it.", "TEXT_POST"),
    ("18100000000000005", "2026-10-08T09:45:00+0000", "repost", "", "REPOST_FACADE"),
    ("18100000000000004", "2026-09-30T13:10:00+0000", "original",
     "Yes, the Tuesday group still has two places. Send us a message and we will hold one for you.", "TEXT_POST"),
    ("18100000000000003", "2026-09-19T10:00:00+0000", "original", "練琴唔使一次練好耐，每日十五分鐘慢慢嚟，比一個禮拜搏一晚有用得多。", "TEXT_POST"),
    ("18100000000000002", "2026-09-08T16:25:00+0000", "original",
     "We moved the beginners' class to 4 pm so families can come after lunch. Same room, same teacher.", "TEXT_POST"),
    ("18100000000000001", "2026-08-27T09:00:00+0000", "original", "我哋今個禮拜六開放琴室，歡迎帶埋朋友嚟試琴，飲杯茶先走。", "TEXT_POST"),
)
# Instagram: (id, timestamp, media_type, caption). Media without a caption carries no writing and is left out.
INSTAGRAM = (
    ("17900000000000012", "2026-11-20T07:30:00+0000", "IMAGE",
     "Teaching adults is our favourite surprise of the year: they practise harder than anyone."),
    ("17900000000000011", "2026-11-09T10:10:00+0000", "IMAGE", "新學期報名現已開始，名額有限，有興趣可以留言或者私訊我哋。"),
    ("17900000000000010", "2026-10-30T18:00:00+0000", "CAROUSEL_ALBUM", "Studio rules, version three: shoes off, phones away, questions always welcome."),
    ("17900000000000009", "2026-10-18T09:00:00+0000", "IMAGE",
     "Practice tip: record yourself once a week. You will hear things you never notice while playing."),
    ("17900000000000008", "2026-10-02T12:00:00+0000", "IMAGE", "多謝各位家長今年嘅支持，聖誕假期後一月八號照常上課。"),
    ("17900000000000007", "2026-09-22T08:45:00+0000", "IMAGE", ""),
    ("17900000000000006", "2026-09-10T19:30:00+0000", "VIDEO",
     "Thirty seconds of scales, slowed down, so you can hear what even fingers sound like."),
    ("17900000000000005", "2026-08-28T11:20:00+0000", "IMAGE", "每一位學生的進度都不同，我們會按個人步伐調整課程，不作比較。"),
    ("17900000000000004", "2026-08-15T14:00:00+0000", "IMAGE",
     "Our youngest student asked why the piano has black keys. We spent the whole lesson on that question."),
    ("17900000000000003", "2026-08-01T09:30:00+0000", "VIDEO", ""),
    ("17900000000000002", "2026-07-19T16:40:00+0000", "CAROUSEL_ALBUM", "夏季音樂會花絮：調音、排櫈、仲有改咗好多次嘅場刊。"),
    ("17900000000000001", "2026-07-05T10:00:00+0000", "IMAGE",
     "Behind the scenes before the summer recital: tuning, chairs, and far too many programme drafts."),
)
# Bluesky: (record key, createdAt, kind, text). "foreign" is a record another repository wrote: the reader skips it.
BLUESKY = (
    ("3lfixture0011", "2026-11-21T08:30:00.000Z", "original", "A slow week is still a good week. Ten careful minutes beat an hour of rushing."),
    ("3lfixture0010", "2026-11-14T19:00:00.000Z", "reply", "No exam pressure here: exams are optional, and most of our students never take one."),
    ("3lfixture0009", "2026-11-03T09:10:00.000Z", "original", "老師們今年會一起進修伴奏技巧，希望明年可以為學生提供更多合奏機會。"),
    ("3lfixture0008", "2026-10-25T13:45:00.000Z", "image",
     "The old upright finally has a name. The students voted, and the winner was simply Brown."),
    ("3lfixture0007", "2026-10-11T10:30:00.000Z", "original", "下個月起逢星期四晚加開成人初班，完全零基礎都啱，唔使驚。"),
    ("3lfixture0006", "2026-09-27T18:20:00.000Z", "original",
     "We are trying a shorter recital format: eight players, forty minutes, then everyone stays for snacks."),
    ("3lfixture0005", "2026-09-13T08:00:00.000Z", "foreign", "A record from another repository; the reader never keeps it."),
    ("3lfixture0004", "2026-09-02T12:15:00.000Z", "quote",
     "Good question from a parent this week: how long before a child enjoys practising? Usually about a month."),
    ("3lfixture0003", "2026-08-20T07:40:00.000Z", "original", "琴室今日換咗新窗簾，下晝陽光冇咁刺眼，練琴舒服好多。"),
    ("3lfixture0002", "2026-08-09T15:00:00.000Z", "reply", "Thank you, we will add an earlier slot on Wednesdays for exactly that reason."),
    ("3lfixture0001", "2026-07-28T09:00:00.000Z", "original",
     "Writing the autumn timetable today. If you have a time that never works for you, tell us before Friday."),
)
# Mastodon: (status id, created_at, kind, text). The newest repeats a Threads post word for word (one piece of
# evidence, two places); "private" is a followers-only status the reader never imports.
MASTODON = (
    ("113000000000000013", "2026-11-23T10:00:00.000Z", "original",
     "Small habit that works: end every practice with one piece you already love playing."),
    ("113000000000000012", "2026-11-16T09:30:00.000Z", "original",
     "Our studio newsletter is now a short monthly note instead of a weekly one. Less inbox, more practice."),
    ("113000000000000011", "2026-11-08T14:00:00.000Z", "repost", ""),
    ("113000000000000010", "2026-10-31T11:45:00.000Z", "reply",
     "Yes, the room is wheelchair accessible, and the lift is just to the left of the entrance."),
    ("113000000000000009", "2026-10-22T08:20:00.000Z", "original", "琴室週末都開放俾學生練琴，記得預早喺群組度登記時間。"),
    ("113000000000000008", "2026-10-15T20:10:00.000Z", "private", "Followers-only note about next week's rota."),
    ("113000000000000007", "2026-10-06T10:30:00.000Z", "original",
     "We tested three practice apps with students this term. The simplest one won, by a long way."),
    ("113000000000000006", "2026-09-24T09:00:00.000Z", "original", "本季度的學生作品分享會改為線上進行，詳情將於下週公布。"),
    ("113000000000000005", "2026-09-12T17:00:00.000Z", "original",
     "Ear training does not need software. Sing the note before you play it, every day, for a week."),
    ("113000000000000004", "2026-09-01T12:00:00.000Z", "repost", ""),
    ("113000000000000003", "2026-08-21T16:30:00.000Z", "reply",
     "We will post the recording next week, once every family has said yes to sharing it."),
    ("113000000000000002", "2026-08-10T09:15:00.000Z", "original", "佢哋問點解學琴要由慢板開始，答案好簡單：慢先聽得清楚自己彈緊乜。"),
    ("113000000000000001", "2026-07-30T08:00:00.000Z", "original",
     "First post from the studio account here. We teach piano, we drink a lot of tea, and we answer every question."),
)


# --- provider-shaped rows ------------------------------------------------------------------------------------------------
def _threads_rows():
    rows = []
    for post_id, when, kind, text, media in THREADS:
        row = {"id": post_id, "timestamp": when, "media_type": media, "permalink": f"https://www.threads.net/@fixture_studio/post/{post_id}",
               "is_quote_post": kind == "quote"}
        if text:
            row["text"] = text
        rows.append(row)
    return rows


def _instagram_rows():
    account = ACCOUNTS["instagram"][0]
    rows = []
    for number, (post_id, when, media, caption) in enumerate(INSTAGRAM, start=1):
        row = {"id": post_id, "timestamp": when, "media_type": media, "permalink": f"https://www.instagram.com/p/FIXTURE{number:03d}/",
               "owner": {"id": account}}
        if caption:
            row["caption"] = caption
        rows.append(row)
    return rows


def _bluesky_rows():
    did = ACCOUNTS["bluesky"][0]
    parent = {"uri": f"at://{did}/app.bsky.feed.post/3lfixturethread", "cid": "bafyfixtureparent"}
    rows = []
    for key, when, kind, text in BLUESKY:
        author = "did:plc:anotherfixtureaccountxyz" if kind == "foreign" else did
        value = {"$type": "app.bsky.feed.post", "text": text, "createdAt": when}
        if kind == "reply":
            value["reply"] = {"root": parent, "parent": parent}
        elif kind == "quote":
            value["embed"] = {"$type": "app.bsky.embed.record", "record": parent}
        elif kind == "image":
            value["embed"] = {"$type": "app.bsky.embed.images", "images": [{"alt": "", "image": {"$type": "blob"}}]}
        rows.append({"uri": f"at://{author}/app.bsky.feed.post/{key}", "cid": "bafyfixture" + key[-4:], "value": value})
    return rows


def _mastodon_rows():
    rows = []
    for status_id, when, kind, text in MASTODON:
        row = {"id": status_id, "created_at": when, "visibility": "private" if kind == "private" else "public",
               "url": f"https://{SERVER}/@studio/{status_id}", "content": "" if kind == "repost" else f"<p>{text}</p>",
               "in_reply_to_id": "112999999999999999" if kind == "reply" else None, "media_attachments": [], "reblog": None}
        if kind == "repost":
            row["reblog"] = {"id": "112999999999999998", "content": "<p>Words another account wrote; never kept.</p>"}
        rows.append(row)
    return rows


ROWS = {"threads": _threads_rows(), "instagram": _instagram_rows(), "bluesky": _bluesky_rows(), "mastodon": _mastodon_rows()}


def _answer(status, body, headers=None):
    return {"status": status, "headers": headers or {}, "body": body}


def _offset(cursor):
    """Meta and Bluesky cursors here are "after-<offset>"; None for anything else."""
    if cursor is None:
        return 0
    value = cursor.removeprefix("after-")
    return int(value) if cursor.startswith("after-") and value.isdigit() else None


class HistoryTransport:
    """The voice import readers' transport in the harness: canned pages of the four histories, newest first, PAGE rows at
    a time, in each provider's own shape. Any other request is answered 404, so a reader that asks for something
    unexpected fails loudly instead of reading an empty history."""

    def __call__(self, method, url, headers=None, form=None, body=None, **_ignored):
        parts = urlsplit(url)
        query = {key: values[0] for key, values in parse_qs(parts.query).items()}
        segments = parts.path.strip("/").split("/")
        if method != "GET":
            return _answer(404, {"error": {"message": "Not part of the voice import fixture."}})
        if parts.hostname == "graph.threads.net" and segments[1:] == ["me", "threads"]:
            second = str(query.get("access_token", "")).endswith("-good-code-2")
            return self._meta([] if second else ROWS["threads"], query.get("after"))
        if parts.hostname == "graph.instagram.com" and len(segments) == 3 and segments[2] == "media":
            return self._meta(ROWS["instagram"] if segments[1] == ACCOUNTS["instagram"][0] else [], query.get("after"))
        if parts.hostname == PDS and parts.path == "/xrpc/com.atproto.repo.listRecords" and query.get("collection") == "app.bsky.feed.post":
            return self._bluesky(ROWS["bluesky"] if query.get("repo") == ACCOUNTS["bluesky"][0] else [], query.get("cursor"))
        if parts.hostname == SERVER and len(segments) == 5 and segments[:3] == ["api", "v1", "accounts"] and segments[4] == "statuses":
            local = ACCOUNTS["mastodon"][0].split("@")[0]
            return self._mastodon(ROWS["mastodon"] if segments[3] == local else [], segments[3], query.get("max_id"))
        return _answer(404, {"error": {"message": "Not part of the voice import fixture."}})

    @staticmethod
    def _meta(rows, cursor):
        start = _offset(cursor)
        if start is None:
            return _answer(400, {"error": {"message": "Unknown cursor.", "code": 100}})
        chunk, following = rows[start:start + PAGE], start + PAGE
        paging = {"cursors": {"before": f"after-{start}"}}
        if following < len(rows):
            paging["cursors"]["after"] = f"after-{following}"
            paging["next"] = f"https://fixture.invalid/next?after=after-{following}"     # never followed by the readers
        return _answer(200, {"data": chunk, "paging": paging})

    @staticmethod
    def _bluesky(rows, cursor):
        start = _offset(cursor)
        if start is None:
            return _answer(400, {"error": "InvalidRequest", "message": "Unknown cursor."})
        following = start + PAGE
        return _answer(200, {"records": rows[start:following], **({"cursor": f"after-{following}"} if following < len(rows) else {})})

    @staticmethod
    def _mastodon(rows, local, max_id):
        ids = [row["id"] for row in rows]
        if max_id is not None and max_id not in ids:
            return _answer(400, {"error": "Unknown max_id."})
        start = ids.index(max_id) + 1 if max_id is not None else 0
        chunk = rows[start:start + PAGE]
        base = f"https://{SERVER}/api/v1/accounts/{quote(local, safe='')}/statuses?limit=40"
        if start + PAGE < len(rows):
            link = f'<{base}&max_id={chunk[-1]["id"]}>; rel="next", <{base}&min_id={chunk[0]["id"]}>; rel="prev"'
        else:
            link = f'<{base}&min_id={chunk[0]["id"] if chunk else "0"}>; rel="prev"'
        return _answer(200, chunk, {"link": link})


def resolve(host, port, *args, **kwargs):
    """socket.getaddrinfo for the readers' public-address check: the two fixture hosts only, never a DNS query."""
    if host not in (PDS, SERVER):
        raise OSError(f"{host} is not part of the voice import fixture")
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (FIXTURE_ADDRESS, port))]


def providers(dev_provider, base):
    """The four dev accounts, as subclasses of the harness's DevProvider. Only the read scope is granted (plain dev
    codes report no scopes, which OAuth must refuse), so publishing stays where it was. Bluesky and Mastodon keep their
    connection as a session document, as their real adapters do; it never expires, so a refresh never replaces it."""

    class FixtureAccount(dev_provider):
        def __init__(self, pid, platform, base):
            if pid == "threads":
                super().__init__(pid, platform, base)       # the harness's Threads capabilities stay as they are
            else:
                self.id, self.platform, self.base = pid, platform, base
                self.scopes = {"identity": list(READ_SCOPES[pid]), "posts_read": list(READ_SCOPES[pid])}

        def exchange(self, code, verifier, redirect):
            grant = super().exchange(code, verifier, redirect)
            grant["scopes"] = sorted(set(grant.get("scopes") or ()) | set(READ_SCOPES[self.id]))
            account = ACCOUNTS[self.id][1 if str(code).endswith("-2") else 0]
            if self.id == "instagram":
                grant["expiresIn"] = 60 * 86400              # a long-lived token: never refreshed during a session
            elif self.id == "bluesky":
                session = {"v": 1, "did": account, "pds": f"https://{PDS}", "at": grant["accessToken"]}
                grant.update(accessToken=json.dumps(session), refreshToken=None, expiresIn=None)
            elif self.id == "mastodon":
                session = {"v": 1, "at": grant["accessToken"], "instance": SERVER, "scope": grant["scopes"]}
                grant.update(accessToken=json.dumps(session), refreshToken=None, expiresIn=None)
            return grant

        def identity(self, access_token):
            if self.id == "threads":
                return super().identity(access_token)
            second = "good-code-2" in str(access_token)
            return {"providerAccountId": ACCOUNTS[self.id][1 if second else 0], "handle": HANDLES[self.id][1 if second else 0],
                    "accountType": "profile"}

    return {pid: FixtureAccount(pid, platform, base) for pid, platform in PLATFORMS.items()}


def mount(service, connection):
    """Apply migration 140 to the loopback harness database (idempotent), then switch voice import on with the fixture
    transport and resolver. Returns the importer; the harness ticker calls its `tick`."""
    migration = (Path(__file__).resolve().parents[1] / "migrations/postriff/140_voice_import.sql").read_text(encoding="utf-8")
    with connection() as db:
        if db.info.host != "127.0.0.1":
            raise RuntimeError("The voice import fixture runs only on the loopback harness database.")
        db.execute(migration)
    importer = voice_import.mount(service, connection, VALUES, transport=HistoryTransport())
    importer.resolver = resolve
    return importer
