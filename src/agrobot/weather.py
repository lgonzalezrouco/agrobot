import enum


class WeatherEventType(enum.StrEnum):
    FROST = "frost"
    RAIN = "rain"
    HAIL = "hail"
    HEAT_WAVE = "heat_wave"
    STRONG_WIND = "strong_wind"
