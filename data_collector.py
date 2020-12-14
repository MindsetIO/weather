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
    "degC": UNIT_NT("degree_Celsius", "degree_Celsius", "degree_Fahrenheit"),
    "km_h-1": UNIT_NT("kilometer_per_hour", "km / hour", "miles / hour"),
    "kilometer / hour": UNIT_NT(
        "kilometer_per_hour", "km / hour", "miles / hour"
    ),
    "m": UNIT_NT("meter", "km", "miles"),
    "Pa": UNIT_NT("pascal", "mbar", "inHg"),
    "percent": UNIT_NT("percent", "percent", "percent"),
    "degree_(angle)": UNIT_NT("degree", "degree", "degree"),
}
UREG = pint.UnitRegistry()
UREG.define("percent = 1e-2 frac")


def dict_to_nt(name: str, dct: dict):
    items = dct.get("properties", dct).items()
    _dct = {k.removeprefix("@"): v for k, v in items}
    return namedtuple(name, _dct.keys())(**_dct)


class Weather:

    WEATHER_BASE_URL = "https://api.weather.gov"

    def __init__(self, area, units="us"):
        self.area = area
        self.zipcode = self.area.zip_code
        self.tz = ZoneInfo(area.timezone)
        self.coords = (self.area.lat, self.area.long)
        self.units = ["SI", "US"][(units or "us").lower() in ["f", "us"]]
        self.data = self.fetch_weather()
        self.suntime = self.calc_suntime()

    @staticmethod
    def area_info(zipcode):
        area_data = zipcodes.matching(f"{zipcode}")[0]
        return dict_to_nt("area", area_data)

    @classmethod
    def from_zipcode(cls, zipcode, units: str = "F"):
        area = cls.area_info(zipcode)
        return cls(area=area, units=units)

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
        unit = UNIT_MAP[v["unitCode"].removeprefix("unit:")]
        quant = UREG.Quantity(val, UREG(unit.base))
        return quant.to(getattr(unit, self.units))

    def _process_current_conditions(self, data):
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
        return obs

    def _process_forecast(self, data):
        def _period(per):
            wind_speed = UREG.Quantity(per["windSpeed"].replace("/h", "/hour"))
            unit = UNIT_MAP[f"{wind_speed.units}"]
            wind_speed = wind_speed.to(getattr(unit, self.units))
            temperature = UREG.Quantity(per["temperature"], "degree_Celsius")
            temperature = temperature.to(getattr(UNIT_MAP["degC"], self.units))
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
        meta = dict_to_nt("meta", resp)
        resp = self.wtr_get(meta.forecastHourly, params={"units": "si"})

        params = {"units": self.units.lower()}
        imd = self.wtr_get(meta.forecast, params=params)["periods"][0]
        idct = {"immediate": f"{imd['name']}: {imd['detailedForecast']}"}
        forecast_data = self._process_forecast(resp)
        forecast = dict_to_nt("forecast", forecast_data | idct)
        resp = self.wtr_get(meta.observationStations, key="features")[0]
        station = dict_to_nt("station", resp)
        latest_url = f"{station.id}/observations/latest"
        resp = self.wtr_get(latest_url)

        now = dict_to_nt("now", self._process_current_conditions(resp))
        data = {type(k).__name__: k for k in [meta, station, now, forecast]}
        return dict_to_nt("data", data)

    def calc_suntime(self):
        sun = Sun(float(self.area.lat), float(self.area.long))
        sdct = {
            w: getattr(sun, f"get_local_{w}_time")().astimezone(self.tz)
            for w in ["sunrise", "sunset"]
        }
        return dict_to_nt("suntime", sdct)
