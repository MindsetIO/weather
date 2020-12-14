#!/usr/bin/env python

from weather import Weather


def main(zipcode, units="F"):
    wtr = Weather.from_zipcode(zipcode, units=units)
    text = wtr.text_report()
    return {"text": text}


if __name__ == "__main__":  # Local Testing
    zipcode = "10001"
    units = "m"  # "F"/"US" or "m"/"SI"
    resp = main(zipcode=zipcode, units=units)
    print(resp["text"])
