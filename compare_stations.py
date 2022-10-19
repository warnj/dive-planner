'''
This program is used to compare slack at two current stations.

Current stations will have a constant offset (one for slack before ebb and
another before flood) from each other if based on the same underlying data
source. Otherwise the time differences between the stations will vary for each
slack.
'''

import dive_plan, data_collect
import interpreter as intp

from datetime import datetime as dt
import numpy as np
import json


def main():
    START = dt.now()
    TRIM_NOAA = True

    # STATION1 = "Strait of Juan de Fuca Entrance, Washington Current"
    # STATION1 = "Juan De Fuca Strait (East), British Columbia Current"
    # STATION1 = "Rosario Strait, Washington Current"
    # STATION1 = "Deception Pass (narrows), Washington Current"
    # STATION1 = "Admiralty Inlet (off Bush Point), Washington Current"
    # STATION1 = "Alki Point, 0.3 mile west of, Puget Sound, Washington Current"
    # STATION1 = "West end, Rich Passage, Puget Sound, Washington Current"
    # STATION1 = "Agate Passage, north end, Puget Sound, Washington Current"
    # STATION1 = "The Narrows, north end (midstream), Washington Current"
    # STATION1 = "South end (midstream), The Narrows, Puget Sound, Washington Current"
    # STATION1 = "Hale Passage, west end, Puget Sound, Washington Current"
    STATION1 = "Burrows I. Allan I. Passage between, Washington Current"

    NOAA1 = True
    # NOAA1 = False

    # STATION2 = "Strait of Juan de Fuca Entrance, Washington Current"
    # STATION2 = "Juan De Fuca Strait (East), British Columbia Current"
    # STATION2 = "Rosario Strait, Washington Current"
    # STATION2 = "Deception Pass (narrows), Washington Current"
    # STATION2 = "Admiralty Inlet (off Bush Point), Washington Current"
    # STATION2 = "Alki Point, 0.3 mile west of, Puget Sound, Washington Current"
    # STATION2 = "West end, Rich Passage, Puget Sound, Washington Current"
    # STATION2 = "Agate Passage, north end, Puget Sound, Washington Current"
    # STATION2 = "The Narrows, north end (midstream), Washington Current"
    # STATION2 = "South end (midstream), The Narrows, Puget Sound, Washington Current"
    # STATION2 = "Hale Passage, west end, Puget Sound, Washington Current"
    # STATION2 = "Gibson Point, 0.8 mile east of, Puget Sound, Washington Current"
    STATION2 = "Burrows Pass, Washington Current"

    NOAA2 = True
    # NOAA2 = False


    data = json.loads(open(data_collect.absName('dive_sites.json')).read())

    station1 = dive_plan.getStation(data['stations'], STATION1)
    if NOAA1:
        m1 = intp.NoaaInterpreter(station1['url_noaa'])
    else:
        m1 = intp.TBoneSCInterpreter(station1['url_xtide'])

    station2 = dive_plan.getStation(data['stations'], STATION2)
    if NOAA2:
        m2 = intp.NoaaInterpreter(station2['url_noaa'])
    else:
        m2 = intp.TBoneSCInterpreter(station2['url_xtide'])

    slacks1 = m1.allSlacks(START)
    slacks2 = m2.allSlacks(START)

    if len(slacks1) != len(slacks2) and (NOAA1 or NOAA2) and TRIM_NOAA:  # one source is NOAA and one is MobileGeographics
        print("Trimming excess NOAA slacks")
        if NOAA1:
            slacks1 = slacks1[:len(slacks2)]
        elif NOAA2:
            slacks2 = slacks2[:len(slacks1)]

    if len(slacks1) != len(slacks2):
        print("Pick a different day or add some fancy comparison - number of slacks don't match")
        source = "NOAA" if NOAA1 else "XTide"
        print('{} slacks from {} station for location {}'.format(len(slacks1), source, STATION1))
        source = "NOAA" if NOAA2 else "XTide"
        print('{} slacks from {} station for location {}'.format(len(slacks2), source, STATION2))
        exit(0)

    beforeEbbDiffs = []
    beforeFloodDiffs = []
    for i, s1 in enumerate(slacks1):
        s2 = slacks2[i]
        assert s2.slackBeforeEbb == s1.slackBeforeEbb

        diff = (s1.time - s2.time).total_seconds() / 60

        if s1.slackBeforeEbb:
            beforeEbbDiffs.append(diff)
        else:
            beforeFloodDiffs.append(diff)

    print("Before ebb diffs: ", beforeEbbDiffs)
    print("Before flood diffs: ", beforeFloodDiffs)

    beforeEbbDiffs = np.array(beforeEbbDiffs)
    beforeFloodDiffs = np.array(beforeFloodDiffs)

    print("{} slacks before Ebb".format(len(beforeEbbDiffs)))
    if len(beforeEbbDiffs) > 0:
        print("\t{:.2f} avg slack difference from station1 to station2 in minutes".format(np.average(beforeEbbDiffs)))
        print("\t{:.2f} median slack difference from station1 to station2 in minutes".format(np.median(beforeEbbDiffs)))
        print("\t{:.2f} min slack difference from station1 to station2 in minutes".format(np.min(beforeEbbDiffs)))
        print("\t{:.2f} max slack difference from station1 to station2 in minutes".format(np.max(beforeEbbDiffs)))
        print("\t{:.2f} std deviation in slack difference from station1 to station2 in minutes".format(np.std(beforeEbbDiffs)))

    print("{} slacks before Flood".format(len(beforeFloodDiffs)))
    if len(beforeFloodDiffs) > 0:
        print("\t{:.2f} avg slack difference from station1 to station2 in minutes".format(np.average(beforeFloodDiffs)))
        print("\t{:.2f} median slack difference from station1 to station2 in minutes".format(np.median(beforeFloodDiffs)))
        print("\t{:.2f} min slack difference from station1 to station2 in minutes".format(np.min(beforeFloodDiffs)))
        print("\t{:.2f} max slack difference from station1 to station2 in minutes".format(np.max(beforeFloodDiffs)))
        print("\t{:.2f} std deviation in slack difference from station1 to station2 in minutes".format(np.std(beforeFloodDiffs)))


if __name__ == '__main__':
    main()
