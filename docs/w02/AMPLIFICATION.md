# W-02 lane: what the limiter's P2 ("book, then send at your slot") asks of the lane

Status: review note of 2026-10-28 for the Captain. **Nothing is built.** Sources: the S1 receipt of `3dac3ccf` (12 loops, 5,000
posts), the limiter's model (`scratchpad/limiter/sat/des.py`), my own model and runs below (scratch, not committed), and the
code of `lane.py`, `hosted_worker.py` and `social_connectors.py` at `3dac3ccf` (the first two are as at `60d1469b`).

## What the lane saw (so P2 is aimed at the right thing)

- S1: 9,714 create steps for 5,000 posts (1.94 passes per post; 4,714 releases; 15,021 steps, 3.0 per post, ideal 2.0). Refusal
  per admission, by stage: about 12 percent for the five witness reads, **0.5 percent for the create permit** (25 of 5,025).
- Both wait in place for one second, but the reads poll with **three tries** (`policy.read_attempts`, `_discord_http`) and the
  create permit polls with no cap on tries (`PacedSocial`). A refused read gives up early: the loop's next request comes 0.90 s
  after an abandoned pass against 0.54 s after a create (medians), so the tries bind, not the one-second deadline (inference).
  Twelve loops wake for the same freed slot, one wins: the limiter's diagnosis, and the lane's counters fit it.
- F2 is not the amplifier: a pass started within 3 s of a release of its workspace was refused 45.0 percent of the time (n=3,271)
  against 42.4 percent for first passes (n=5,000). In the lane fixture with the limiter head's coordinator, F2 off was no better
  (cap 18: 3.55 passes per post against 3.2 to 3.5 with F2; cap 22: 2.21 against 1.45 to 1.72).
- Same fixture, 12 loops, saturated (cap 22 is S1-like: 1.45 to 1.72 passes per post): `read_attempts` 5 gives 1.10 and 12
  to 16 percent more creates a second; unlimited tries to 4 s with a 0.2 s spread gives 1.01 and 5.0 requests per create (+14 to
  19 percent). At cap 18 and at 24 loops the baseline collapses (3.2 to 3.5 and 3.2 passes per post); the spread version stays
  at 1.0 to 1.05.

## 1. What a reservation that blocks up to 1 s inside the coordinator call touches

| Place | Effect | What I would change |
|---|---|---|
| Who may book: `lane.PacedSocial`, `_discord_http` | The minute worker is a background caller too and must not book (`FlagOffIsTheFrozenBase`); a warm instance shares one provider between the minute cron, the lane cron and web requests, so a provider attribute would leak. | An explicit per-call opt-in: `PacedSocial` wraps `prepare_discord_dispatch`, `reserve_discord_send` and `reconcile_discord` and sets a context variable (or kwarg) that `_discord_http` hands to `reserve_read` / `admit_bot_request`; default none = today's immediate refusal. About 15 lines in lane.py, 3 in `_discord_http`. "Nothing in lane.py" holds only if the coordinator can tell the caller another way; I see none. |
| Deadline the lane passes: `_discord_http`, `PacedSocial` | `wait_deadline` (1 s) is set before the first try and only limits the polling after a refusal; a booked first try that succeeds is unaffected. `read_attempts` (3) still caps the polling for refusals beyond the horizon. | None. |
| Loop budget: `lane.run`, `STEP_RESERVE_SECONDS` | The budget is read before each step only. The 160 s reserve is 7 requests at the 20 s transport timeout plus database time; P2 adds at most 7 x 1 s to that worst case (147 of 160 s). | No change (default budget 50 s; at the 90 s maximum 23 s of margin remain). Update the comment. |
| Lease: `renew_discord_lease`, claim lease `min(now+45, approval end)` | A pass gains at most 5 s; the one renewal sits after the preflight and before `reserve_discord_send`; there is no heartbeat and none is needed. A post whose approval ends inside the pass loses its lease as today (`leaseLost`, never sent late). | None. The coordinator must refuse a booking whose wire time plus seal and consume passes the permit's expiry (`permit_ttl_seconds` may be 0.05 s). |
| F5 (no renewal after the seal) | It rests on seal to consume taking 0.16 s. | Contract for P2: the sleep is in `reserve`, never in `consume` and never between seal and consume. |
| `PacedSocial` create wait | Its 1 s deadline starts at entry; a booked call that used it makes a later refusal raise at once (release). | Keep as the fallback for refusals beyond the horizon. |
| Counters | `permitWaits` and `rateWaits` fall to about 0 and stop showing saturation. | Count booked waits and seconds in the coordinator; add two entries to `lane.COUNTERS` and the invocation result. |
| `outlook()` | Reads the application row's `remaining` / `reset` and waits until `reset` when `remaining` is 0. | None, if the stored values keep the meaning the limiter's model gives them (bookable within the horizon, else `reset` = when it will be). Pin it with an Outlook test. |
| F2, K1, quarantine, frozen path | F2 sees `application` scope on a refusal beyond the horizon and restores far less (4,305 in S1). K1 and the quarantine act before the claim. | None. |

## 2. Anything still worth doing in the lane after P2?

No. Re-run S1 first.
- Slow first member reads (3.4 percent of 6,468 wait over 1 s, p99 1.4 s; the other reads never do). It is not the
  application window and not a cold bucket (34 percent of the slow ones were a workspace's first member read, 31 percent of the
  others), so P2 will not remove it; it has the highest stage refusal (15.5 percent). Saving if fixed: about 0.1 request per
  post (270 excess releases x 2 requests thrown away). A coordinator question, not lane code.
- Evidence reuse on a re-claim (the budget review's A2): if releases fall to 5 percent of posts and each throws away 2.3
  requests, it saves 0.1 request per post and costs a durable witness record on the job, a staleness rule and reviewer work.
  Not worth it.
- The one lane-side saving that stays is independent of P2: the bot identity pair, 0.22 request per post (every invocation is a
  new process, so the 60 s cache never helps); a shared one-minute cache would save about 0.2 of 6.4.

## 3. Risks from the lane side, and the tests the lane suite needs

Risks (my model, calibrated on S1: 12 loops give 1.8 passes per post and 2.92 creates a second; booking gives 1.01, 6.03 and 3.66):
1. **Booking reads but not create permits starves the creates**: 16 loops 2.45 creates a second (9.3 requests per post), 24 loops
   0.06 (79 passes per post). Creates must book too. With both: 16 loops 3.63, 24 loops 3.48 (1.14 passes, witness age p50 6 s),
   32 loops 0.78 (14.6 passes). Keep `SHARDS` at 16 or fewer (`MAX_SHARDS` is 32) until it is re-measured.
2. A process killed during a booked sleep leaves a `sent` admission with no wire request for up to 1 s of booked time; harmless
   with the limiter's age bound on unanswered admissions, one more leaked admission without it.
3. Tests with a fake clock: the coordinator sleeps in real time; it needs an injectable sleep and clock.
4. Witness age grows with the sleeps (model: p50 2.6 s, max 3.2 s at 12 loops, as today; 6 s at 24 loops). No bound exists in the code.

Tests: offline: (a) `PacedSocial` sets the booking context around prepare, reserve and reconcile only; a direct provider call and
a second thread do not see it; `FlagOffIsTheFrozenBase` unchanged. (b) A coordinator double that blocks 1 s per reservation: a pass
takes 6 s and the invocation still ends inside budget plus one step. (c) `Outlook` on rows that show a booked horizon. (d) The new
counters. (e) A booking whose wire time passes the permit's expiry is refused. PostgreSQL: (f) S1-shaped saturation (cap 22,
12 loops, mock latency): at most 1.1 passes per post, 0 duplicates, wire peak within the cap. (g) The same at 16 loops; the limit
documented at 24 or more. (h) An approval ending inside the pass: held, never sent late. (i) A loop killed inside a booked sleep:
nothing sent, a later claim sends once. (j) F5: no sleep between seal and consume (instrument it). (k) K1 pause during a booked
wait: nothing new is claimed. (l) The F2 and quarantine tests unchanged (their refusals are injected at reserve level).
