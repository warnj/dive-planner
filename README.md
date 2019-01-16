# dive-planner

## Background
For current-sensitive dive sites, there is often a limited number of days where the site
can be dove safely and enjoyably. These programs automate the process of planning dives
at sites with strong currents.

## Data
A dive site is specified in dive_sites.json. A current station url is required (currently only
mobilegeographic links are supported).  Other data needed include correction times for 
slack current, the maximum current speed on each side of slack where the site is diveable, and
approximate dive duration.

## Dive Planning
* Configure the following settings in dive_plan.py
    * START - set to start date
    * DAYS_IN_FUTURE - set to number of days to consider beyond start
    * SITES - uncomment the "createOrAppend" lines of dive sites to consider diving at
    * filterNonWorkDays - True 
    * filterDaylight - 
    * PRINTINFO
    * possibleDiveDays
     
* Run `python dive_plan.py`

## Historical Dive Data Collection



## Historical Dive Data Analysis


## Notes
* Build for Python 3
* Dependencies: bs4, Firefox, geckodriver, Selenium, pandas
