'''
This program is used to rank the longest and shortest slack times for a current
station over a given time interval. Longer slacks are present when the max
current speed on the exchange before and after slack is smaller.
'''

import dive_plan
import data_collect
import interpreter as intp
import json
from must_do_dives import getSite
from datetime import datetime as dt


def getDiveableSlacks(slacks, site):
    """Returns list of slacks that are dive-able for the given site."""
    diveableSlacks = []
    for s in slacks:
        if s.ebbSpeed > 0.0:
            print('WARNING - EBB SPEED IS POSITIVE')
        if s.floodSpeed < 0.0:
            print('WARNING - FLOOD SPEED IS NEGATIVE')

        diveable, info = dive_plan.isDiveable(s, site, False)
        if diveable:
            diveableSlacks.append(s)
    return diveableSlacks



def getInterpreter(station, use_xtide_docker, use_noaa):
    """Returns the appropriate interpreter for the given station and settings."""
    if use_xtide_docker:
        return intp.XTideDockerInterpreter(station['name'], station)
    elif use_noaa:
        if 'british columbia' in station['name'].lower():
            print('using Canadian Currents API')
            return intp.CanadaAPIInterpreter("", station)
        else:
            return intp.NoaaAPIInterpreter(station['url_noaa_api'], station)
    else:
        return intp.TBoneSCInterpreter(station['url_xtide_a'], station['name'])


def main():
    # ---------------------------------- CONFIGURABLE PARAMETERS ------------------------------------------------------
    # SITE = 'Whiskey Point'
    # SITE = 'Boat Pass'
    # SITE = 'Gabriola Pass'
    # SITE = 'Dodd Narrows'
    # SITE = 'Skyline Wall'
    # SITE = 'Deception Pass'
    # SITE = 'Goose Island'
    # SITE = 'Peavine Pass'
    # SITE = 'Deadman Island'
    # SITE = 'Lime Kiln Haro'
    # SITE = 'Salt Creek NOAA'
    SITE = 'Keystone Jetty'
    # SITE = 'Day Island Wall'
    # SITE = 'Sechelt Rapids'
    # SITE = 'Nakwakto'
    USE_XTIDE_DOCKER = False
    USE_NOAA = True
    TIME_FILTER = intp.TIME_FILTER_EARLY_NIGHT
    DAYS_IN_FUTURE = 365
    START_DATE = dt(2026, 3, 1)
    INCLUDE_WORKDAYS = False
    INCLUDE_FRIDAYS = True
    # -----------------------------------------------------------------------------------------------------------------

    data = json.loads(open(data_collect.absName('dive_sites.json')).read())
    siteJson = getSite(data['sites'], SITE)
    station = dive_plan.getStation(data['stations'], siteJson['data'])

    m = getInterpreter(station, USE_XTIDE_DOCKER, USE_NOAA)

    days = dive_plan.getDiveDays(DAYS_IN_FUTURE, START_DATE, INCLUDE_WORKDAYS, INCLUDE_FRIDAYS)

    # Preload full range once for XTide Docker to avoid per-day container runs
    if USE_XTIDE_DOCKER and isinstance(m, intp.XTideDockerInterpreter) and days:
        m.preload_range(days[0], days[-1])

    slacks = []
    for day in days:
        slacks.extend(m.getSlacks(day, TIME_FILTER))

    # Filter out the non-diveable slacks
    diveableSlacks = getDiveableSlacks(slacks, siteJson)

    # Calculate and print stats
    if len(slacks) > 0:
        percentSlacksDiveable = float(len(diveableSlacks)) / len(slacks) * 100
        print('{:0.2f}% of all slacks are diveable ({}/{})'.format(
            percentSlacksDiveable, len(diveableSlacks), len(slacks)))

    diveableDays = 0
    prevDay = ''
    for s in diveableSlacks:
        curDay = dt.strftime(s.time, intp.DATEFMT)
        if prevDay != curDay:
            prevDay = curDay
            diveableDays += 1

    percentDaysDiveable = float(diveableDays) / len(days) * 100
    print('{:0.2f}% of all days are diveable ({}/{})'.format(
        percentDaysDiveable, diveableDays, len(days)))

    # Sort by the sum of the max current speeds from weakest to strongest
    diveableSlacks.sort(key=lambda x: abs(x.ebbSpeed) + abs(x.floodSpeed))

    # Print results
    for s in diveableSlacks:
        afterSunrise = (s.time - s.sunriseTime).total_seconds() / 60.0
        beforeSunset = (s.sunsetTime - s.time).total_seconds() / 60.0
        print('{}\tSpeed sum = {:0.1f}\tTime before/after dark = {:0.0f}min'.format(
            s, abs(s.ebbSpeed) + abs(s.floodSpeed), min(beforeSunset, afterSunrise)))

    if USE_NOAA and 'british columbia' in station['name'].lower():
        print('number of api calls: {}'.format(m.numAPICalls))
if __name__ == '__main__':
    main()
