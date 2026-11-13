# The API is internal, called only by the WhatsApp bot

The API has one intended client, the WhatsApp bot, which owns User identity (a User is their WhatsApp phone number) and calls the API on the User's behalf. The bot is outside this project ([`docs/TASK.md`](../TASK.md) asks for no WhatsApp integration), so until it exists the tests, `curl` and `/docs` send the key the way the bot will. The API trusts one shared secret, the `API_KEY` setting. It has no default, so the API refuses to start without it, and the worker never reads it. Every endpoint except `/health` requires a matching `X-API-Key` header, compared with `secrets.compare_digest` so the key can't be guessed by timing; a missing or wrong key gets 401. `/health` stays open for load balancers and container probes.

## Considered Options

- **Per-User login (passwords or tokens per User).** Rejected: Users never talk to the API directly, and WhatsApp already proves who sent a message, so a login would add credentials Users never see and the bot would have to store.
- **No authentication, network isolation only.** Rejected: one misconfigured network rule would expose every User's Fields and Alerts.

## Consequences

Any holder of the key can act as any User; the bot is trusted to pass the right User. Changing the key means a short outage: the API and its client restart with the new key, and requests get 401 while they disagree. A second client means revisiting this decision.
