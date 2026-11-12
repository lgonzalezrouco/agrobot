import enum

from sqlalchemy import Enum


class WeatherEventType(enum.StrEnum):
    FROST = "frost"
    RAIN = "rain"
    HAIL = "hail"
    HEAT_WAVE = "heat_wave"
    STRONG_WIND = "strong_wind"


def weather_event_type_column_type() -> Enum:
    return Enum(
        WeatherEventType,
        name="weather_event_type",
        values_callable=lambda members: [member.value for member in members],
    )
