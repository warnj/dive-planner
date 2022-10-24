'''
This program is used to rank the longest and shortest slack times for a current
station over a given time interval. Longer slacks are present when the max
current speed on the exchange before and after slack is smaller.
'''

import dive_plan, data_collect
import interpreter as intp
import json
from must_do_dives import getSite
from datetime import datetime as dt

# returns list of slacks in given list that are divable for the given site, mostly taken from must_do_dives.py
def getDiveableSlacks(slacks, site):
    diveableSlacks = []
    for s in slacks:
        if s.ebbSpeed > 0.0:
            print('WARNING - EBB SPEED IS POSITIVE')
        if s.floodSpeed < 0.0:
            print('WARNING - FLOOD SPEED IS NEGATIVE')

        # Check if diveable or not
        diveable, info = dive_plan.isDiveable(s, site, False)
        if diveable:
            diveableSlacks.append(s)
    return diveableSlacks

def main():
    SITE = 'Whiskey Point'
    # SITE = 'Deception Pass'

    # NOAA = True
    NOAA = False

    # NIGHT = True
    NIGHT = False

    data = json.loads(open(data_collect.absName('dive_sites.json')).read())
    siteJson = getSite(data['sites'], SITE)

    station = dive_plan.getStation(data['stations'], siteJson['data'])
    if NOAA:
        m = intp.NoaaInterpreter(station['url_noaa'])
    else:
        m = intp.TBoneSCInterpreter(station['url_xtide'])

    slacks = []
    days = dive_plan.getAllDays(300, dt(2023, 2, 1))
    # days = dive_plan.getAllDays(230)
    for day in days:
        slacks.extend(m.getSlacks(day, night=NIGHT))

    # filter out the non-diveable slacks
    diveableSlacks = getDiveableSlacks(slacks, siteJson)

    # sort by the sum of the max current speeds from weakest to strongest
    diveableSlacks.sort(key=lambda x: abs(x.ebbSpeed)+abs(x.floodSpeed))

    for s in diveableSlacks:
        print('{}\tSpeed sum = {:0.1f}'.format(s, abs(s.ebbSpeed)+abs(s.floodSpeed)))


if __name__ == '__main__':
    main()
