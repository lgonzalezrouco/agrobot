# Agrobot

Agricultural management for farmers. This context covers weather alerts: warning users when the forecast for one of their fields crosses a level they care about.

## Language

### Farms and weather

**User**:
A person who owns fields and receives notifications. A user is identified by their WhatsApp phone number.
_Avoid_: Farmer, customer, account

**Field**:
A plot of land owned by a user, placed at a single location.
_Avoid_: Campo, farm, plot, lot

**Location**:
A point on a fixed geographic grid that forecasts are issued for. Each field belongs to the location nearest it, so neighboring fields share one location.
_Avoid_: Zone, region, coordinates

**Weather Event Type**:
A kind of weather phenomenon the system forecasts, from a fixed set (frost, rain, hail, …).
_Avoid_: Event, phenomenon, condition

**Forecast**:
The probability that a weather event type occurs at a location on a given future day. Days follow the system's single local calendar, not UTC.
_Avoid_: Weather data, prediction, reading

**Weather Provider**:
The external service that issues forecasts for locations.
_Avoid_: Weather API, weather service, source

### Alerting

**Alert**:
A user's standing request to be told when a field's forecast for a weather event type reaches a threshold.
_Avoid_: Alert rule, subscription, trigger

**Threshold**:
The probability (0–100%) at or above which an alert fires.
_Avoid_: Limit, trigger level

**Notification**:
The record created when a forecast for one day reaches an alert's threshold, which is then delivered to the user inside a message. An alert produces at most one notification per forecast day. Delivery keeps being retried until that day has passed; a notification still undelivered by then is expired. A notification whose delivery is permanently rejected (for example, the phone number no longer exists) is failed and never retried. Pausing an alert withdraws its undelivered notifications, and raising its threshold withdraws those whose probability is now below it.
_Avoid_: Alert (for the fired instance), event

**Message**:
What the user actually receives: one delivery that groups several of that user's notifications still waiting to be delivered. A message succeeds or fails as a whole, for all the notifications it carries.
_Avoid_: Notification (for the delivery), digest, alert
