# Agrobot

Agricultural management for farmers. This context covers weather alerts: warning users when the forecast for one of their fields crosses a level they care about.

## Language

### Farms and weather

**User**:
A person who owns fields and receives notifications.
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
The probability that a weather event type occurs at a location on a given future day.
_Avoid_: Weather data, prediction, reading

### Alerting

**Alert**:
A user's standing request to be told when a field's forecast for a weather event type reaches a threshold.
_Avoid_: Alert rule, subscription, trigger

**Threshold**:
The probability (0–100%) at or above which an alert fires.
_Avoid_: Limit, trigger level

**Notification**:
The record created when a forecast reaches an alert's threshold, which is then delivered to the user.
_Avoid_: Alert (for the fired instance), message, event
