'''
This program is used to
'''

import dive_plan, data_collect
import interpreter as intp

from datetime import datetime as dt
import json


def main():
    START = dt(2019, 1, 1)

    # STATION = "Strait of Juan de Fuca Entrance, Washington Current"
    # STATION = "Juan De Fuca Strait (East), British Columbia Current"
    # STATION = "Rosario Strait, Washington Current"
    # STATION = "Deception Pass (narrows), Washington Current"
    # STATION = "Admiralty Inlet (off Bush Point), Washington Current"
    # STATION = "Alki Point, 0.3 mile west of, Puget Sound, Washington Current"
    # STATION = "West end, Rich Passage, Puget Sound, Washington Current"
    # STATION = "Agate Passage, north end, Puget Sound, Washington Current"
    # STATION = "The Narrows, north end (midstream), Washington Current"
    STATION = "South end (midstream), The Narrows, Puget Sound, Washington Current"
    # STATION = "Hale Passage, west end, Puget Sound, Washington Current"

    # NOAA = True
    NOAA = False

    data = json.loads(open(data_collect.absName('dive_sites.json')).read())

    station = dive_plan.getStation(data['stations'], STATION)
    if NOAA:
        m = intp.NoaaInterpreter(station['url_noaa'])
    else:
        m = intp.MobilegeographicsInterpreter(station['url'])

    slacks = []
    days = dive_plan.getAllDays(365, START)
    for day in days:
        slacks.extend(m.getSlacks(day, False))

    # sort by the sum of the max current speeds from weakest to strongest
    slacks.sort(key=lambda x: abs(x.ebbSpeed)+abs(x.floodSpeed))

    for s in slacks:
        print('{}\tSpeed sum = {:0.1f}'.format(s, abs(s.ebbSpeed)+abs(s.floodSpeed)))


if __name__ == '__main__':
    main()