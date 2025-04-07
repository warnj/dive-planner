# dive-planner

## Disclaimer
Diving is dangerous and can cause injury or death. The data sources and this software may be incorrect. The makers of this software will, in no event, be liable for any personal harm or damage to goods caused by use of this tool. You are responsible for your own safety. Using this tool indicates your acceptance of these terms. 

## How to run Planner
* Install Python3
* `pip install -r requirements.txt`
* `python3 dive_plan.py`

## Basic command line examples
```$xslt
python3 dive_plan.py --sites "day island wall"
python3 dive_plan.py --sites "day island wall, sunrise beach"
python3 dive_plan.py --includeworkdays --sites "day island wall"
python3 dive_plan.py --futuredays 14 --sites "day island wall"
python3 dive_plan.py --start-date 2020-10-01 --sites "day island wall"
```

## Complex command line examples
```$xslt
python3 dive_plan.py --night --includeworkdays --futuredays 1 -d 2020-10-09 --sites "day island wall"
python3 dive_plan.py -w -f 0 -d 2020-10-09 --sites "deception pass"
python3 dive_plan.py -w -f 30 -d 2021-04-01 --sort --sites "deception pass"
```

## Run in IDE
Choose desired options under MANUALLY CONFIGURABLE PARAMETERS in dive_plan.py.
Ensure the other lines are commented out.
```$xslt
python3 dive_plan.py
```

## Background
Current-sensitive dive sites have a limited number of times where the site can safely be dived.
These programs automate the process of planning dives at sites with strong currents.

## Data
* Stored in `dive_sites.json` file broken into current stations and dive sites.
* Current station properties
    * Name
    * Base URL for Xtide current data from `tbone.biol.sc.edu`
    * Base URL for NOAA current data from `tidesandcurrents.noaa.gov`
* Dive site properties
    * Linked to current station name
    * Time offsets in minutes for adjusted slack at the site. If slack at dive site is 30min before slack
    at the current station, offset is `-30`.
    * Max allowable current speed on either side of exchange. Longer slack time when max speed is smaller.
    * Estimated dive duration for the site.

## Picking best dive day for a site
* **Option 1:** Run rank_year_slacks.py over the desired time window
* **Option 2:** Run dive_plan.py for site over desired time period, set args.SORT = True
  * Copy output to notepad++
  * Delete lines containing "Not diveable" or "Current too strong"
    * Go to the search menu, Ctrl + F, and open the Mark tab.
    * Check Bookmark line (if there is no Mark tab update to the current version). 
    * Enter your search term and click Mark All
    * All lines containing the search term are bookmarked. 
    * Now go to the menu Search → Bookmark → Remove Bookmarked lines

## Picking the best dive day for multiple dives or sites
Example would be to find rare days where you can dive both Deception Pass and Skyline. Or do two dives at Day Island.
* Add desired site pair(s) under `must_do_dives` in `dive_sites.json`
* Run `must_do_dives.py` over desired time window
