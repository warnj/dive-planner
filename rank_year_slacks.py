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

# returns list of slacks in given list that are dive-able for the given site, mostly taken from must_do_dives.py
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
    # SITE = 'Whiskey Point'
    # SITE = 'Boat Pass'
    # SITE = 'Gabriola Pass'
    # SITE = 'Dodd Narrows'
    # SITE = 'Skyline Wall'
    SITE = 'Deception Pass'
    # SITE = 'Goose Island'
    # SITE = 'Peavine Pass'
    # SITE = 'Deadman Island'
    # SITE = 'Lime Kiln Haro'
    # SITE = 'Salt Creek NOAA'
    # SITE = 'Day Island Wall'
    # SITE = 'Sechelt Rapids'
    # SITE = 'Nakwakto'

    USE_XTIDE_DOCKER = True
    # USE_XTIDE_DOCKER = False

    # NOAA = True
    NOAA = False

    # NIGHT = True
    NIGHT = False

    data = json.loads(open(data_collect.absName('dive_sites.json')).read())
    siteJson = getSite(data['sites'], SITE)

    station = dive_plan.getStation(data['stations'], siteJson['data'])
    if USE_XTIDE_DOCKER:
        m = intp.XTideDockerInterpreter(station['name'], station)
    elif NOAA:
        if 'british columbia' in station['name'].lower():
            print('using Canadian Currents API')
            m = intp.CanadaAPIInterpreter("", station)
        else:
            m = intp.NoaaAPIInterpreter(station['url_noaa_api'], station)
    else:
        m = intp.TBoneSCInterpreter(station['url_xtide_a'], station['name'])

    slacks = []
    days = dive_plan.getAllDays(365, dt(2026, 1, 1))
    # Preload full range once for XTide Docker to avoid per-day container runs
    if USE_XTIDE_DOCKER and isinstance(m, intp.XTideDockerInterpreter) and days:
        m.preload_range(days[0], days[-1])
    # days = dive_plan.getAllDays(290)
    # days = dive_plan.getNonWorkDays(365, dt(2026, 1, 1))
    for day in days:
        slacks.extend(m.getSlacks(day, night=NIGHT))

    # filter out the non-diveable slacks
    diveableSlacks = getDiveableSlacks(slacks, siteJson)

    # calc stats
    if len(slacks) > 0:
        percentSlacksDiveable = float(len(diveableSlacks)) / len(slacks) * 100
        print('{:0.2f}% of all slacks are diveable ({}/{})'.format(percentSlacksDiveable, len(diveableSlacks), len(slacks)))
    diveableDays = 0
    prevDay = ''
    for s in diveableSlacks:
        curDay = dt.strftime(s.time, intp.DATEFMT)
        if prevDay != curDay:
            prevDay = curDay
            diveableDays += 1
    percentDaysDiveable = float(diveableDays) / len(days) * 100
    print('{:0.2f}% of all days are diveable ({}/{})'.format(percentDaysDiveable, diveableDays, len(days)))

    # sort by the sum of the max current speeds from weakest to strongest
    diveableSlacks.sort(key=lambda x: abs(x.ebbSpeed)+abs(x.floodSpeed))
    # sort by the min flood speed
    # diveableSlacks.sort(key=lambda x: abs(x.floodSpeed))

    for s in diveableSlacks:
        # print('{}\tSpeed sum = {:0.1f}'.format(s, abs(s.ebbSpeed) + abs(s.floodSpeed)))
        afterSunrise = (s.time - s.sunriseTime).total_seconds() / 60.0
        beforeSunset = (s.sunsetTime - s.time).total_seconds() / 60.0
        print('{}\tSpeed sum = {:0.1f}\tTime before/after dark = {:0.0f}min'.format(s, abs(s.ebbSpeed)+abs(s.floodSpeed), min(beforeSunset, afterSunrise)))

    if NOAA and 'british columbia' in station['name'].lower():
        print('number of api calls: {}'.format(m.numAPICalls))
if __name__ == '__main__':
    main()
