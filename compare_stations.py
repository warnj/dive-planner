'''
This program is used to
'''

from dive_plan import *
from datetime import datetime as dt
import numpy as np



def allSlackIndexes(lines):
    slacks = []
    for i, line in enumerate(lines):
        if 'slack' in line:
            slacks.append(i)
    return slacks


def allSlacks(webData):
    slackIndexes = allSlackIndexes(webData)
    return getSlackData(webData, slackIndexes, None, None)  # populate Slack objects


def main():
    START = dt.now()

    STATION1 = "http://tides.mobilegeographics.com/locations/67.html"  # Admiralty Head
    # STATION1 = "http://tides.mobilegeographics.com/locations/8176.html"  # Narrows North
    # STATION1 = "http://tides.mobilegeographics.com/locations/153.html"  # Alki Point

    STATION2 = "http://tides.mobilegeographics.com/locations/69.html"  # Admiralty Inlet
    # STATION2 = "https://tides.mobilegeographics.com/locations/3053.html"  # Hale Passage
    # STATION2 = "http://tides.mobilegeographics.com/locations/7626.html"  # Narrows South

    m1 = MobilegeographicsInterpreter(STATION1)
    slacks1 = m.getSlacks(day, )

    m2 = MobilegeographicsInterpreter(STATION2)

    webLines = getWebLines(MobilegeographicsInterpreter.getDayUrl(STATION1, day))
    slacks1 = allSlacks(webLines)

    webLines = getWebLines(MobilegeographicsInterpreter.getDayUrl(STATION2, day))
    slacks2 = allSlacks(webLines)

    if len(slacks1) != len(slacks2):
        print("Pick a different day or add some fancy comparison - number of slacks don't match")
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
