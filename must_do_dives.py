'''
This program is used to identify if days in the future (or past) are considered diveable for a subset of dive sites
specified by dive_sites.json
'''

import data_collect
import interpreter as intp
import dive_plan

from datetime import datetime as dt
import json


def getDiveable(slacks, site):
    diveableSlacks = []
    for s in slacks:
        if s.ebbSpeed > 0.0:
            print('WARNING - EBB SPEED IS POSITIVE')
        if s.floodSpeed < 0.0:
            print('WARNING - FLOOD SPEED IS NEGATIVE')

        # Check if diveable or not
        diveable, info = dive_plan.isDiveable(s, site, False)
        if diveable:
            diveableSlacks.append((s, info))
    return diveableSlacks

# given site name and json data returns current station
def getSite(sites, name):
    for i in range(len(sites)):
        siteData = sites[i]
        if siteData['name'] == name:
            return siteData

def main():

    # ---------------------------------- CONFIGURABLE PARAMETERS -----------------------------------------------------------
    START = dt.now()
    START = dt(2020, 3, 1)  # date to begin considering diveable conditions
    DAYS_IN_FUTURE = 100  # number of days after START to consider

    FILTER_NON_WORKDAYS = False  # only consider diving on weekends and holidays
    FILTER_DAYLIGHT = True  # only consider slacks that occur during daylight hours

    possibleDiveDays = [  # Specify dates
        # dt(2019, 3, 31),
        # dt(2019, 3, 16),
        # dt(2019, 3, 3)
    ]

    NOAA = False
    # ----------------------------------------------------------------------------------------------------------------------


    if not possibleDiveDays:
        if FILTER_NON_WORKDAYS:
            possibleDiveDays = dive_plan.getNonWorkDays(DAYS_IN_FUTURE, START)
        else:
            possibleDiveDays = dive_plan.getAllDays(DAYS_IN_FUTURE, START)

    data = json.loads(open(data_collect.absName('dive_sites.json')).read())

    for i in range(len(data['must_do_dives'])):
        site1 = getSite(data['sites'], data['must_do_dives'][i]['name1'])
        site2 = getSite(data['sites'], data['must_do_dives'][i]['name2'])

        station1 = dive_plan.getStation(data['stations'], site1['data'])
        station2 = dive_plan.getStation(data['stations'], site2['data'])

        if NOAA:
            m1 = intp.NoaaInterpreter(station1['url_noaa'])
            m2 = intp.NoaaInterpreter(station2['url_noaa'])
        else:
            m1 = intp.MobilegeographicsInterpreter(station1['url'])
            m2 = intp.MobilegeographicsInterpreter(station2['url'])


        print('{} - {}'.format(site1['name'], site2['name']))

        for day in possibleDiveDays:
            if site1 == site2:
                slacks = m1.getSlacks(day, not FILTER_DAYLIGHT)
                diveableSlacks = getDiveable(slacks, site1)
                if len(diveableSlacks) >= 2:
                    for s, info in diveableSlacks:
                        dive_plan.printDive(s, site1, info)
            else:
                slacks1 = m1.getSlacks(day, not FILTER_DAYLIGHT)
                diveableSlacks1 = getDiveable(slacks1, site1)

                slacks2 = m2.getSlacks(day, not FILTER_DAYLIGHT)
                diveableSlacks2 = getDiveable(slacks2, site2)

                if len(diveableSlacks2) >= 2 or len(diveableSlacks1) >= 2:
                    if len(diveableSlacks1) >= 2:
                        print('WOW: {} is diveable twice today!'.format(site1['name']))
                    else:
                        print('WOW: {} is diveable twice today!'.format(site2['name']))
                    for s, info in diveableSlacks1:
                        dive_plan.printDive(s, site1, info)
                    for s, info in diveableSlacks2:
                        dive_plan.printDive(s, site2, info)

                if len(diveableSlacks1) == 0:
                    continue
                if len(diveableSlacks2) == 0:
                    continue

                # each site is diveable once this day, print them if they don't overlap with each other
                _, _, entryTime1, exitTime1 = dive_plan.getEntryTimes(diveableSlacks1[0][0], site1)
                _, _, entryTime2, exitTime2 = dive_plan.getEntryTimes(diveableSlacks2[0][0], site2)

                latest_start = max(entryTime1, entryTime2)
                earliest_end = min(exitTime1, exitTime2)

                if latest_start > earliest_end:
                    print("BOTH SITES DIVEABLE: transfer time = {0:0.2f} minutes".format((latest_start-earliest_end).total_seconds() / 60))
                    print("{} Diveable".format(site1['name']))
                    dive_plan.printDive(diveableSlacks1[0][0], site1, diveableSlacks1[0][1])
                    print("{} Diveable".format(site2['name']))
                    dive_plan.printDive(diveableSlacks2[0][0], site2, diveableSlacks2[0][1])
                else:
                    print("{0}: Both sites diveable but times overlap by {1:0.2f} minutes".format(
                        dt.strftime(day, intp.DATEFMT), (earliest_end-latest_start).total_seconds() / 60))



if __name__ == '__main__':
    main()
