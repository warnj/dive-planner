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
TIMEPRINTFMT = '%a %Y-%m-%d %I:%M%p'  # example: Fri 2019-01-18 09:36AM
TIMEFMT = '%I:%M%p'  # example 09:36AM

def getDayUrl(baseUrl, day, daysInFuture):
    today = day.strftime(DATEFMT).replace("-", "")
    future = (day + datetime.timedelta(days=daysInFuture)).strftime(DATEFMT).replace("-", "")
    return baseUrl + f'&begin_date={today}&end_date={future}'

def printTides(apiTideLines):
    for tide in apiTideLines:
        datet = dt.strptime(tide['t'], TIMEPARSEFMT_TBONE)
        typet = 'Low' if tide['type']=='L' else 'High'
        print('{}: {} tide {:.1f} ft'.format(dt.strftime(datet, TIMEPRINTFMT), typet, float(tide['v'])))

# prints the tides of each day in the format "time (height) > time (height)"
def printTideDiveFmt(apiTideLines):
    prevTide = None
    for tide in apiTideLines:
        datet = dt.strptime(tide['t'], TIMEPARSEFMT_TBONE)
        if prevTide and prevTide['t'][:10] == tide['t'][:10]:  # same day
            print(' > {} ({:.1f} ft)'.format(dt.strftime(datet, TIMEFMT).lstrip('0'), float(tide['v'])), end='')
        else:
            if prevTide: print()  # end previous day
            print('\t{}: '.format(dt.strftime(datet, DATEFMT)), end='')  # start new day
            print('{} ({:.1f} ft)'.format(dt.strftime(datet, TIMEFMT).lstrip('0'), float(tide['v'])), end='')
        prevTide = tide
    print()

def getAndPrintTides(tideStationConfig, args):
    url = getDayUrl(tideStationConfig['url_noaa'], args.START, args.DAYS_IN_FUTURE)
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception('NOAA API is down')

    jsonArray = response.json()['predictions']
    # printTides(jsonArray)
    printTideDiveFmt(jsonArray)

def main():
    data = json.loads(open(data_collect.absName('dive_sites.json')).read())

    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--start-date", dest="START", default=dt.now(),
                        type=lambda d: dt.strptime(d, '%Y-%m-%d').date(),
                        help="Start date to begin considering diveable conditions in the format yyyy-mm-dd")
    args = parser.parse_args()

    # ---------------------------------- MANUALLY CONFIGURABLE PARAMETERS ---------------------------------------------
    STATIONS = []
    # STATIONS.append('Bowman Bay')
    # STATIONS.append('Hanbury Point, North San Juan Island')
    # STATIONS.append('Kanaka Bay, South San Juan Island')
    # STATIONS.append('Sekiu')
    # STATIONS.append('Crescent Bay')
    # STATIONS.append('Ayock Point')
    # STATIONS.append('La Push')
    STATIONS.append('Des Moines')
    # args.START = dt(2023, 7, 29)
    args.START = dt.now()
    args.DAYS_IN_FUTURE = 0
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
