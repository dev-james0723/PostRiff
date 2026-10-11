# Rafii Telegram integration

Read `READINESS.md` for the current verified status and `engineering-matrix.md` for implemented versus unfinished capabilities. This branch is a reviewable implementation candidate and cannot be declared production ready from synthetic tests.

Official references: [Telegram Login OIDC](https://core.telegram.org/bots/telegram-login), [Bot API](https://core.telegram.org/bots/api), [Secretary Mode and Managed Bots](https://core.telegram.org/bots/features).

Identity login and channel/group/Business grants are distinct. Existing server-side vault, tenant authorization, publishing review, durable worker, bounded retry and provider receipt handling are reused. No private Telegram user sessions are accepted. Credential input stays outside the repository.

Run cloud validation from this checkout using `jcb ci`. Dirty/uncommitted source is transported without secrets; no Git push or local heavy fallback is required. Current cloud harness: `scripts/cloud-telegram-validation.sh`. Historical checks must not be used to certify current source.
