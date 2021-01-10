#!/usr/bin/env python

from pprint import pprint as pp

from weather import Weather


def main(zipcode, units="F"):
    wtr = Weather.from_zipcode(zipcode, units=units)
    text = wtr.text_report()
    return {"text": text, **wtr.current.data}


if __name__ == "__main__":  # Local Testing
    zipcode = "10001"
    units = "m"  # "F"/"US" or "m"/"SI"
    resp = main(zipcode=zipcode, units=units)
    pp(resp)
