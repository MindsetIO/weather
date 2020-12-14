#!/usr/bin/env python

from data_collector import Weather


def weather_report_text(wtr):
    msg = [f"Weather for {wtr.area.city} ({wtr.area.zip_code})"]
    temp = f"{wtr.data.now.temperature:~}"
    ftemps = wtr.data.forecast.periods[:24]
    next24 = [f([p.temperature for p in ftemps]) for f in [min, max]]
    msg.append(
        f"Now: {temp}, {wtr.data.now.desc.lower()}, "
        f"next 24h: {next24[0]:~} to {next24[1]:~}"
    )
    msg.append(
        f"Humidity: {wtr.data.now.relativeHumidity.magnitude:0.1f}%, "
        f"visibility: {wtr.data.now.visibility:~0.1f}"
    )
    msg.append(
        f"Daytime {wtr.suntime.sunrise.strftime('%_I:%M%p').strip()} to "
        f"{wtr.suntime.sunset.strftime('%_I:%M%p').strip()}"
    )
    msg.append(wtr.data.forecast.immediate)
    return "\n".join(msg)


def main(zipcode, units="F"):
    wtr = Weather.from_zipcode(zipcode, units=units)
    return {"text": weather_report_text(wtr)}


if __name__ == "__main__":  # Local Testing
    zipcode = 95134
    print(main(zipcode=zipcode, units="m"))
