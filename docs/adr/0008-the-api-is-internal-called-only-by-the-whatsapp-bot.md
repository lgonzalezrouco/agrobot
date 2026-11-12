# The API is internal, called only by the WhatsApp bot

The API has one client: the WhatsApp bot. The bot owns User identity (a User is their WhatsApp phone number) and calls the API on the User's behalf. The API trusts one shared secret, the `API_KEY` setting, which has no default, so the API refuses to start without it. The worker never reads it. Every endpoint except `/health` requires an `X-API-Key` header matching it, compared with `secrets.compare_digest` so a wrong key can't be guessed by timing. A missing or wrong key gets 401. `/health` stays open for load balancers and container probes.

## Considered Options

- **Per-User login (passwords or tokens per User).** Rejected: Users never talk to the API directly. WhatsApp already proves who sent a message, so a second login would add credentials Users never see and the bot would have to store.
- **No authentication, network isolation only.** Rejected: one misconfigured network rule would expose every User's Fields and Alerts.

## Consequences

Any holder of the key can act as any User; the bot is trusted to pass the right User. Changing the key means a short outage: the API and the bot must be restarted with the new key, and requests fail with 401 while they disagree. Adding a second client means revisiting this decision.
