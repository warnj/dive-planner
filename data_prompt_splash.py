'''
This program is used to identify the time offset from the current station slack predictions specified for the dive site
by prompting the user to enter the splash times for past Marker Buoy club dives as current-sensitive locations.
'''

from dive_plan import *
from data_collect import absName
from data_query_old import *
from datetime import datetime as dt
import json, webbrowser, csv
import numpy as np


def promptForActualSplash(dive):
    webbrowser.open(dive.url)
    while True:
        time = input('Enter dive splash time (example 11:30AM or 02:05pm) or "s" to skip this dive or "x" to end now: ').strip().upper()
        if time == 'S':
            return None
        if time == 'X':
            raise RuntimeError
        dayStr = dt.strftime(dive.date, DATEFMT)
        try:
            splash = dt.strptime(dayStr + ' ' + time, TIMEPARSEFMT)
            return splash
        except ValueError:
            print('Entered time format did not match expected format (example 11:30AM or 02:05pm):')

def printSplashMetrics(dives, siteData):
    beforeFloodActualToPredictedDif, beforeFloodActualToSlackDif = [], []
    beforeEbbActualToPredictedDif, beforeEbbActualToSlackDif = [], []
    for dive in dives:
        if not dive.splash:
            continue

        minCurrentTime, markerBuoyEntryTime, entryTime = getEntryTimes(dive.slack, siteData)

        print(dive)
        print('\t', dive.slack)
        print('\tPredicted: MarkerBuoyEntryTime = {}   MyEntryTime = {}   MinCurrentTime = {}'.format(
            dt.strftime(markerBuoyEntryTime, TIMEPRINTFMT),
            dt.strftime(entryTime, TIMEPRINTFMT),
            dt.strftime(minCurrentTime, TIMEPRINTFMT))
        )
        print('\tActual MarkerBuoyEntryTime = {}'.format(dt.strftime(dive.splash, TIMEPRINTFMT)))

        predictedDif = dive.splash - markerBuoyEntryTime
        print("\tDifference from actual to predicted (minutes): {}".format(predictedDif.total_seconds()/60))

        slackDif = dive.splash - dive.slack.time
        print("\tDifference from actual to slack (minutes): {}".format(slackDif.total_seconds()/60))

        if dive.slack.slackBeforeEbb:
            beforeEbbActualToPredictedDif.append(predictedDif.total_seconds()/60)
            beforeEbbActualToSlackDif.append(slackDif.total_seconds()/60)
        else:
            beforeFloodActualToPredictedDif.append(predictedDif.total_seconds()/60)
            beforeFloodActualToSlackDif.append(slackDif.total_seconds()/60)

    beforeFloodActualToPredictedDif = np.array(beforeFloodActualToPredictedDif)
    beforeFloodActualToSlackDif = np.array(beforeFloodActualToSlackDif)
    beforeEbbActualToPredictedDif = np.array(beforeEbbActualToPredictedDif)
    beforeEbbActualToSlackDif = np.array(beforeEbbActualToSlackDif)

    print("{} dives before Ebb".format(len(beforeEbbActualToPredictedDif)))
    if len(beforeEbbActualToPredictedDif) > 0:
        print("\t{:.0f} avg, {:.0f} median prediction error (minutes)".format(np.average(beforeEbbActualToPredictedDif), np.median(beforeEbbActualToPredictedDif)))
        print("\t{:.0f} avg, {:.0f} median slack offset (minutes)".format(np.average(beforeEbbActualToSlackDif), np.median(beforeEbbActualToSlackDif)))
        print(beforeEbbActualToSlackDif)
    print("{} dives before Flood".format(len(beforeFloodActualToPredictedDif)))
    if len(beforeFloodActualToPredictedDif) > 0:
        print("\t{:.0f} avg, {:.0f} median prediction error (minutes)".format(np.average(beforeFloodActualToPredictedDif), np.median(beforeFloodActualToPredictedDif)))
        print("\t{:.0f} avg, {:.0f} median slack offset (minutes)".format(np.average(beforeFloodActualToSlackDif), np.median(beforeFloodActualToSlackDif)))
        print(beforeFloodActualToSlackDif)


def main():
    WRITE_SPLASH_TO_FILE = True

    inputFile = 'dive_meetup_data_old_format_with_slacks_with_splash.csv'
    outputFile = 'dive_meetup_data_old_format_with_slacks_with_splash.csv'
    sites = ["Day Island Wall"]


    print('Extracting dives from data file', inputFile)
    dives, slacks = getDives(inputFile)

    if not slacks:
        print('No slacks in {}, make sure to run data_add_slacks.py first. Exiting.'.format(inputFile))
        exit(0)

    print('Classifying dive sites')
    results = refineDives(dives)

    print('Prompting for splash time at each dive')
    data = json.loads(open(absName('dive_sites.json')).read())
    for site, sitedives in results.items():
        siteData = getSiteData(sites, site, data)
        if siteData == None:
            continue
        station = getStation(data['stations'], siteData['data'])
        print('{} - {}\n{} - {}'.format(siteData['name'], siteData['data'], station['url'], station['coords']))

        # Print each dive, its corresponding slack, and predicted entry time
        for dive in sitedives:
            # ask for input on the dives that don't have splash times
            if not dive.splash:
                print('\t', dive)
                print('\t\t', dive.slack)
                try:
                    dive.splash = promptForActualSplash(dive)
                except RuntimeError:
                    break
        print()
        printSplashMetrics(sitedives, siteData)

    if WRITE_SPLASH_TO_FILE:
        print('Writing slacks to file', outputFile)
        with open(absName(outputFile), 'w', encoding='utf-8', newline='\n') as f:
            w = csv.writer(f, delimiter=',')
            for dive in dives:
                if dive.splash:
                    w.writerow([dt.strftime(dive.date, MEETUP_TIME_FORMAT), dive.title, dive.location, dive.address, dive.descr, dive.url, dive.slack, dt.strftime(dive.splash, MEETUP_TIME_FORMAT)])
                else:
                    w.writerow([dt.strftime(dive.date, MEETUP_TIME_FORMAT), dive.title, dive.location, dive.address, dive.descr, dive.url, dive.slack, ""])
        print('Done writing to file', absName(outputFile))


if __name__ == "__main__":
    main()
