'''
This program prints tides for NOAA stations on given date ranges
'''

import argparse
import datetime
import json
from datetime import datetime as dt
import requests
import data_collect

DATEFMT = '%Y-%m-%d'  # example 2019-01-18
TIMEPARSEFMT_TBONE = '%Y-%m-%d %H:%M'  # example: 2019-01-18 22:36
TIMEPRINTFMT = '%a %Y-%m-%d %I:%M%p'

def getDayUrl(baseUrl, day, daysInFuture):
    today = day.strftime(DATEFMT).replace("-", "")
    future = (day + datetime.timedelta(days=daysInFuture)).strftime(DATEFMT).replace("-", "")
    return baseUrl + f'&begin_date={today}&end_date={future}'

def printTides(apiTideLines):
    for tide in apiTideLines:
        datet = dt.strptime(tide['t'], TIMEPARSEFMT_TBONE)
        typet = 'Low' if tide['type']=='L' else 'High'
        print('{}: {} tide {:.1f}ft'.format(dt.strftime(datet, TIMEPRINTFMT), typet, float(tide['v'])))

def getAndPrintTides(tideStationConfig, args):
    url = getDayUrl(tideStationConfig['url_noaa'], args.START, args.DAYS_IN_FUTURE)
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception('NOAA API is down')

    jsonArray = response.json()['predictions']
    printTides(jsonArray)

def main():
    data = json.loads(open(data_collect.absName('dive_sites.json')).read())

    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--start-date", dest="START", default=dt.now(),
                        type=lambda d: dt.strptime(d, '%Y-%m-%d').date(),
                        help="Start date to begin considering diveable conditions in the format yyyy-mm-dd")
    args = parser.parse_args()

    # ---------------------------------- MANUALLY CONFIGURABLE PARAMETERS ---------------------------------------------
    STATIONS = ['Ayock Point']
    args.START = dt(2023, 3, 27)
    # args.START = dt.now()
    args.DAYS_IN_FUTURE = 4
    args.INCLUDE_WORKDAYS = True
    # ------------------------------------------------------------------------------------------------------------------

    # Get tides for each site and each
    for tideStation in STATIONS:
        print('Tides for {}'.format(tideStation))
        for tideStationConfig in data['tide_stations']:
            if tideStation == tideStationConfig['name']:
                getAndPrintTides(tideStationConfig, args)


if __name__ == '__main__':
    main()