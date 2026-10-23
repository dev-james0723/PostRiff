# W-02 Sending thousands of posts in the same minute: the plan (design note, nothing built)

Written 23:17Z, 2026-10-22, after the owner asked how 5,000 customers who schedule a post for 09:30 can all be served. No code, build or deployment follows from this file. It is a new release candidate and starts only if the owner says so.

Tags: [certain] arithmetic from numbers in this repository; [likely] a figure I read in Discord's documents earlier in this session and could not re-read today (docs hosts do not resolve from this sandbox); [guess] my reasoning, untested.

> **Correction, 2026-10-23, from the W-02 build (branch `claude/discord-w02-parallel-20261023`, `docs/w02/` there):** a post costs **six** Discord requests today, not two: four permission reads before every create (the server, the bot's membership, the authorizing person's membership, the channel list; `social_connectors.py`, `destinations()`), the create, and the read-back. The "5,000 posts" and "100,000 posts" times in section 1 assumed two, so multiply every drain time below by three: at 25 requests a second 5,000 posts take about 23 minutes (simulated) and 100,000 posts about 6.7 hours; at 50 a second about 12 minutes and 3.3 hours. The single-worker figure of 6 to 12 posts a minute is a limit on worker STEPS (about 25 a minute, two steps per post) and is unchanged. Reducing the six (caching the permission evidence for a short time, or one request per post) changes the security and evidence design and needs its own qualification; see `OPEN-QUESTIONS.md` Q2 on the branch.

## 1. What is being sent, and the real ceiling

- A scheduled post goes into the customer's own server channel through Rafii's one shared bot. It is not a message to a person's account.
- Discord limits one bot to about 50 requests a second [likely]; Rafii's policy keeps half of that (25) [certain, `scripts/discord_rate_policy.py` defaults]. Every post costs at least two requests today: the create and a separate read-back [certain, `MEASUREMENTS.md`].
- So no design sends 5,000 posts in one second. The goal is "all of them within a few minutes, none lost, none sent twice".

| 5,000 posts | Requests per post | Rate | Time to send all |
|---|---|---|---|
| today's single worker | 2 | 6 to 12 posts a minute | 7 to 14 hours [certain] |
| parallel workers, today's policy | 2 | 25 requests a second | about 6.7 minutes [certain] |
| parallel workers, bot limit used fully | 2 | 50 requests a second | about 3.3 minutes [certain] |
| parallel, read-back only when the outcome is uncertain | 1 | 25 requests a second | about 3.3 minutes [certain] |
| both of the above | 1 | 50 requests a second | about 1.7 minutes [certain] |

10,000 posts take twice as long. A higher limit can be asked from Discord for large verified bots [likely]; that is the only way past 50 a second for requests that carry the bot token.

## 2. Why it is slow today, and what is already in place

- One cron entry runs `/api/cron/worker` once a minute; one invocation runs at most 25 steps in 45 seconds, sequentially, and shares that budget with every other provider and with the maintenance work in the same route [certain, `hosted_worker.py`, `hosted_app.py`]. The limits are code constants, not function limits (the function may run 300 seconds).
- Safe for many workers already: workspaces are claimed with `FOR UPDATE ... SKIP LOCKED`, every worker has its own id, and each job carries a lease owner and a lease id that every later step re-checks [certain, `hosted_worker.py`]. The capacity run on the earlier Discord branch used 16 workers [certain, handoff note]. A Discord-only lane (`tick_discord`) exists and is not wired to any cron.
- The shared request coordinator already denies a request before it is sent when the budget is used up, so more workers cannot push Rafii past its own policy [certain].
- Different customers are different workspace rows, so 5,000 customers do not contend with each other [likely].

## 3. The plan, in the order I would do it

1. **Parallel Discord workers (the main change).** A Discord-only route that loops claim, reserve, send, record for up to about 4 minutes per invocation, and a dispatcher that starts 12 to 16 of them when work is due and chains a successor when it stops with work left. Needs: new route and dispatcher, budget limits raised for that lane only, tests on PostgreSQL that two workers never send one post twice, and a capacity run with the mock set to 50 requests a second (approved as row 9; it runs through the owner's Depot account).
2. **Spread the peak on purpose (product, cheap).** Store a random offset of up to two minutes on a scheduled time, and say so in the schedule dialog ("sent between 09:30 and 09:32"). It turns a spike into a plateau without any extra capacity.
3. **Prepare before the minute.** Do the checks and media work ahead of the due time so only the send is left in the burst.
4. **One request per post.** Read the message back only when the create outcome is uncertain. This changes the evidence design (PRD A09 asks for a read-back), so it needs its own qualification.
5. **Approval windows that match.** A post whose approval expires while it waits is held for a fresh approval. Check how long an approval lives after the scheduled time, and extend it by the length of a normal queue.
6. **Ask Discord for a higher limit** once the app is busy, and **test whether webhook sends count against the bot's limit** [guess: they may not, because they carry no bot token]. If they do not, webhook mode is also the burst-relief path.
7. **If serverless fan-out is not enough:** one small always-on worker reading the same queue can do 50 requests a second by itself. That is new infrastructure and cost and needs the owner's yes.

## 4. Risks

- More workers raise the cost of a bug: a duplicate send is worse than a late one. The lease checks and the tests above are the defence; nothing here weakens them.
- Database connections and function concurrency: sixteen workers are small, but the database compute size is still unknown (packet row 11).
- Shared egress addresses: sustained bursts from addresses shared with other customers of the host raise the chance of an address-level restriction; the invalid-request budget and circuits stay on.
- It is a new release candidate: a new freeze, new exact-SHA CI and builds that the current approvals do not cover.

## 5. What would change the plan

A measured step latency far above 1 second (fewer posts per worker); Discord stating that webhook sends are outside the bot limit (webhook mode first); the owner's customers scheduling mostly at random times (step 2 alone may be enough for a long while).
