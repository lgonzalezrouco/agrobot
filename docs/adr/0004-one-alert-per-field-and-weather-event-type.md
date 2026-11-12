# One alert per field and weather event type

A field can have at most one Alert for each Weather Event Type, enforced by a unique constraint. To change the level at which a user is notified, they edit the alert's threshold instead of adding a second alert. We rejected allowing several thresholds per event type (for example frost at 50% *and* at 80%): it complicates deduplicating notifications and is ambiguous for the user. Lifting this rule later means dropping the constraint and redefining how notifications are deduplicated.
