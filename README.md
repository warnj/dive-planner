# dive-planner

## How to run Planner
* Install Python3
* `pip install -r requirements.txt`
* `python3 dive_plan.py`

## Basic examples
```$xslt
python3 dive_plan.py --sites "day island wall"
python3 dive_plan.py --sites "day island wall, sunrise beach"
python3 dive_plan.py --includeworkdays --sites "day island wall"
python3 dive_plan.py --futuredays 14 --sites "day island wall"
python3 dive_plan.py --start-date 2020-10-01 --sites "day island wall"
```

## Complex examples
```$xslt
python3 dive_plan.py --night --includeworkdays --futuredays 1 -d 2020-10-09 --sites "day island wall"
python3 dive_plan.py -w -f 0 -d 2020-10-09 --sites "deception pass"
python3 dive_plan.py -w -f 30 -d 2021-04-01 --sort --sites "deception pass"
```

## Background
Current-sensitive dive sites have a limited number of times where the site can safely be dived.
These programs automate the process of planning dives at sites with strong currents.

## Data
* Stored in `dive_sites.json` file broken into current stations and dive sites.
* Current station properties
    * Name
    * Base URL for current data from `tides.mobilegeographics.com`. This is based on XTides predictions.
    * Base URL for current data from `tidesandcurrents.noaa.gov`. This is based on current NOAA predictions.
    * XTide station may not have a similarly located NOAA station, in which case NOAA URL can be left blank
    and vice versa.
* Dive site properties
    * Linked to a current station
    * Time offsets in minutes for adjusted slack at the site. If slack at dive site is 30min before slack
    at the current station, offset is `-30`.
    * Max allowable current speed on either side of exchange. Longer slack time when max speed is smaller.
    * Estimated dive duration for the site.

## Historical Dive Data Collection and Analysis
`data_collect.py` used to scan Meetup.com website for Marker Buoy dive club and save dive site, date, and time in .csv.
Other `data_*.py` programs used to add expected splash time to current sensitive sites to generate
current correction factors and max allowable speeds.

## Picking Best Dive Day
* Run dive_plan.py for site over desired time period, set args.SORT = True
* Copy output to notepad++
* Delete lines containing "Not diveable" or "Current too strong"
  ** Go to the search menu, Ctrl + F, and open the Mark tab.
  ** Check Bookmark line (if there is no Mark tab update to the current version). 
  ** Enter your search term and click Mark All
  ** All lines containing the search term are bookmarked. 
  ** Now go to the menu Search → Bookmark → Remove Bookmarked lines
