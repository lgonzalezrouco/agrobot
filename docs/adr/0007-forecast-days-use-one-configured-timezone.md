# Forecast days use one configured timezone

A Forecast day is a date in one local calendar, set by the `TIMEZONE` setting (an IANA name, default `America/Argentina/Buenos_Aires`). "Today" is the current date in that timezone. It decides which days ingestion asks the Weather Provider for, which days `evaluate` can still create Notifications for, and which days `notify` treats as past and expires. An invalid name stops the API and the workers at startup. Stored timestamps stay in UTC; only the meaning of a forecast day changes.

## Considered Options

- **UTC days.** Rejected: for an Argentine User the UTC date changes at 21:00 local time, so today's Notifications would stop being created and pending ones would expire three hours before the day actually ends.
- **A timezone per Location.** Rejected: it needs a timezone lookup for every Location, and every User is in one country today. Nothing requires it yet.

## Consequences

All Users share one calendar. Serving Users in timezones far from the configured one needs a timezone per Location, which changes how every job computes "today".
