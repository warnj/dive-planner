'''
This program prints tides for NOAA stations on given date ranges.

Uses the TideInterpreter abstraction layer for fetching tide predictions
from various sources (currently NOAA, with placeholder for Canadian tides).
'''

import argparse
import json
from datetime import datetime as dt
import data_collect
from interpreter_tides import get_tide_interpreter, print_tides_dive_fmt, TIME_FILTER_ALL


def getAndPrintTides(tideStationConfig, startDay, daysInFuture, timeFilter=TIME_FILTER_ALL):
    interpreter = get_tide_interpreter(tideStationConfig)
    tides = interpreter.getTides(startDay, days_in_future=daysInFuture, time_filter=timeFilter)
    print_tides_dive_fmt(tides)

def main():
    data = json.loads(open(data_collect.absName('dive_sites.json')).read())

    parser = argparse.ArgumentParser(description='Print tide predictions for specified stations')
    parser.add_argument("-d", "--start-date", dest="START", default=dt.now(),
                        type=lambda d: dt.strptime(d, '%Y-%m-%d'),
                        help="Start date to begin tide predictions in the format yyyy-mm-dd")
    parser.add_argument("-n", "--days", dest="DAYS_IN_FUTURE", default=3, type=int,
                        help="Number of days to fetch (default: 3)")
    args = parser.parse_args()

    # ---------------------------------- MANUALLY CONFIGURABLE PARAMETERS ---------------------------------------------
    STATIONS = []
    # STATIONS.append('Walker Group')
    # STATIONS.append('Port Hardy')
    # STATIONS.append('Alert Bay')
    # STATIONS.append('Kelsey Bay')
    # STATIONS.append('Gold River')
    # STATIONS.append('Seymour Narrows')
    # STATIONS.append('Campbell River')
    STATIONS.append('Northwest Bay')
    # STATIONS.append('Nanaimo')
    # STATIONS.append('Brentwood Bay')

    # STATIONS.append('Bowman Bay')
    # STATIONS.append('Hanbury Point, North San Juan Island')
    # STATIONS.append('Kanaka Bay, South San Juan Island')
    # STATIONS.append('Neah Bay')
    # STATIONS.append('Sekiu')
    # STATIONS.append('Crescent Bay')
    # STATIONS.append('Ayock Point')
    # STATIONS.append('La Push (Quillayute River)')
    # STATIONS.append('James Island (La Push)')
    # STATIONS.append('Destruction Island')
    # STATIONS.append('Des Moines')
    # args.START = dt(2025, 6, 19)
    args.START = dt.now()
    args.DAYS_IN_FUTURE = 3
    # ------------------------------------------------------------------------------------------------------------------

    # Get tides for each station
    for tideStation in STATIONS:
        print('Tides for {}'.format(tideStation))
        for tideStationConfig in data['tide_stations']:
            if tideStation == tideStationConfig['name']:
                getAndPrintTides(tideStationConfig, args.START, args.DAYS_IN_FUTURE)


if __name__ == '__main__':
    main()
