#!/usr/bin/env python

from collections import namedtuple
from datetime import datetime as dt
from zoneinfo import ZoneInfo

import pint
import requests
from suntime import Sun
import zipcodes


UNIT_NT = namedtuple("unit", "base SI US")
UNIT_MAP = {
    "degC": ("degree_Celsius", "degree_Celsius", "degree_Fahrenheit"),
    "km_h-1": ("kilometer_per_hour", "km / hour", "miles / hour"),
    "kilometer / hour": ("kilometer_per_hour", "km / hour", "miles / hour"),
    "m": ("meter", "km", "miles"),
    "Pa": ("pascal", "mbar", "inHg"),
    "percent": ("percent", "percent", "percent"),
    "degree_(angle)": ("degree", "degree", "degree"),
}
UNIT_NTS = {k: UNIT_NT(*v) for k, v in UNIT_MAP.items()}
UREG = pint.UnitRegistry()
UREG.define("percent = 1e-2 frac = %")
pint.Quantity.__format__ = lambda a, _: f"{a.magnitude:0.1f}{a.units:~}"


def dict_to_nt(name: str, dct: dict):
    items = dct.get("properties", dct).items()
    _dct = {k.removeprefix("@"): v for k, v in items}
    return namedtuple(name, _dct.keys())(**_dct)


class Weather:
    """
    collect data from the National Weather Service API
    and generate reports
    """

    WEATHER_BASE_URL = "https://api.weather.gov"

    def __init__(self, area, units="F"):
        self.area = area
        self.zipcode = self.area.zip_code
        self.tz = ZoneInfo(area.timezone)
        self.timestamp = dt.now(self.tz)
        self.coords = (self.area.lat, self.area.long)
        self.units = ["SI", "US"][(units or "us").lower() in ["f", "us"]]
        self.meta = None
        self.current = None
        self.station = None
        self.forecast = None
        self.suntime = None

    @staticmethod
    def area_info(zipcode):
        area_data = zipcodes.matching(f"{zipcode}")[0]
        return dict_to_nt("area", area_data)

    @classmethod
    def from_zipcode(cls, zipcode: [str, int], units: [str, None] = "F"):
        """
        :param zipcode: 5-digit string or integer with valid US zipcode
        :param units - for US: "F" or "US", metric: "M" or "SI"
        :return: Weather class instance
        """
        area = cls.area_info(zipcode)
        obj = cls(area=area, units=units)
        obj.fetch_weather()
        obj.calc_suntime()
        return obj

    @classmethod
    def wtr_get(cls, route: str, params: dict = None, key="properties"):
        route = route.removeprefix(cls.WEATHER_BASE_URL).removeprefix("/")
        url = f"{cls.WEATHER_BASE_URL}/{route}"
        resp = requests.get(url, params=params)
        if resp.status_code == 200:
            data = resp.json()
            return data if key is None else data[key]
        raise Exception("weather api fetch error")

    def _local_time(self, timestamp):
        return dt.fromisoformat(timestamp).astimezone(self.tz)

    def _to_units(self, v):
        if (val := v["value"]) is None:
            return val
        unit = UNIT_NTS[v["unitCode"].removeprefix("unit:")]
        quant = UREG.Quantity(val, UREG(unit.base))
        return quant.to(getattr(unit, self.units))

    def _process_current(self, data):
        obs = {
            k: self._to_units(v)
            for k, v in data.items()
            if isinstance(v, dict)
        }
        obs["desc"] = data["textDescription"]
        obs["timestamp"] = self._local_time(data["timestamp"])
        obs["raw_message"] = data["rawMessage"]
        obs["cloud_layers"] = [
            {"base": self._to_units(c["base"]), "amount": c["amount"]}
            for c in data["cloudLayers"]
        ]
        obs["data"] = self._serialize(obs)
        return obs

    @staticmethod
    def _serialize(data):
        EXCLUDED_FIELDS = ["elevation", "cloud_layers"]
        sdct = {}
        for k, v in data.items():
            if k in EXCLUDED_FIELDS or v is None:
                continue
            sdct[k] = v.magnitude if isinstance(v, pint.Quantity) else v
        return sdct

    def _process_forecast(self, data):
        def _period(per):
            wind_speed = UREG.Quantity(per["windSpeed"].replace("/h", "/hour"))
            unit = UNIT_NTS[f"{wind_speed.units}"]
            wind_speed = wind_speed.to(getattr(unit, self.units))
            temperature = UREG.Quantity(per["temperature"], "degree_Celsius")
            temperature = temperature.to(getattr(UNIT_NTS["degC"], self.units))
            pdct = {
                "start_time": self._local_time(per["startTime"]),
                "end_time": self._local_time(per["endTime"]),
                "is_daytime": per["isDaytime"],
                "desc": per["shortForecast"],
                "temperature": temperature,
                "wind_direction": per["windDirection"],
                "wind_speed": wind_speed,
            }
            return dict_to_nt("period", pdct)

        obs = {
            "elevation": self._to_units(data["elevation"]),
            "generated_at": self._local_time(data["generatedAt"]),
            "updated_at": self._local_time(data["updateTime"]),
            "periods": [_period(p) for p in data["periods"]],
        }
        return obs

    def fetch_weather(self):
        route = f"/points/{','.join(self.coords)}"
        resp = self.wtr_get(route)
        self.meta = dict_to_nt("meta", resp)
        resp = self.wtr_get(self.meta.forecastHourly, params={"units": "si"})
        params = {"units": self.units.lower()}
        imd = self.wtr_get(self.meta.forecast, params=params)["periods"][0]
        idct = {"immediate": f"{imd['name']}: {imd['detailedForecast']}"}
        forecast_data = self._process_forecast(resp)
        self.forecast = dict_to_nt("forecast", forecast_data | idct)
        resp = self.wtr_get(self.meta.observationStations, key="features")[0]
        self.station = dict_to_nt("station", resp)
        latest_url = f"{self.station.id}/observations/latest"
        resp = self.wtr_get(latest_url)
        current = self._process_current(resp)
        self.current = dict_to_nt("current", current)

    def calc_suntime(self):
        sun = Sun(float(self.area.lat), float(self.area.long))
        sdct = {
            w: getattr(sun, f"get_local_{w}_time")().astimezone(self.tz)
            for w in ["sunrise", "sunset"]
        }
        self.suntime = dict_to_nt("suntime", sdct)

    def text_report(self, forecast_periods: int = 24):
        ftemps = self.forecast.periods[:forecast_periods]
        hi_lo = [f([p.temperature for p in ftemps]) for f in [min, max]]
        msg = [
            f"Weather for {self.area.city} ({self.area.zip_code}) - "
            f"{self.timestamp.strftime('%a %I:%M%p').replace(' 0', ' ')}",
            f"Now: {self.current.temperature}, {self.current.desc.lower()}, "
            f"next 24h: {hi_lo[0]} to {hi_lo[1]}",
            f"Humidity: {self.current.relativeHumidity}, "
            f"visibility: {self.current.visibility}",
            f"Daytime {self.suntime.sunrise.strftime('%_I:%M%p').strip()} to "
            f"{self.suntime.sunset.strftime('%_I:%M%p').strip()}",
            self.forecast.immediate,
        ]
        return "\n".join(msg)

    def __repr__(self):
        return (
            f"{self.__class__.__name__}("
            f"zipcode='{self.zipcode}', units='{self.units}')"
        )
