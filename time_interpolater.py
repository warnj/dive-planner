# for sites like Deception Pass the real slack is typically about halfway between Xtide and NOAA predictions, this
# takes the clock math away and returns the exact midpoint given a multiline string output from dive_plan.py

from datetime import datetime as dt
import re

str = """
    Deception Pass - Deception Pass (narrows), Washington Current - 48.4062 N, 122.6430 W
http://tide.arthroinfo.org/tideshow.cgi?site=Deception+Pass+%28narrows%29%2C+Washington+Current&glen=14&year=2024&month=05&day=13
https://tidesandcurrents.noaa.gov/noaacurrents/DownloadPredictions?fmt=csv&i=&r=2&tz=LST%2fLDT&u=1&id=PUG1701_24&t=am%2fpm&i=&threshold=&thresholdvalue=&d=2024-05-13
	XTide
		Diveable: 3.23 -> Mon 2024-05-13 06:54AM -> -6.16
			MinCurrentTime = Mon 2024-05-13 06:54AM, Duration = 70, SurfaceSwim = 0
			Entry Time: Mon 2024-05-13 06:19AM	(Exit time: 07:29AM)
			3.23 > 6:54AM > -6.16
			3.23(4:49AM) > 6:54AM > -6.16(10:37AM)
			Speed sum = 9.4
		Not diveable before flood:	-6.16 -> Mon 2024-05-13 01:37PM -> 5.69
	NOAA / CA
		Diveable: 2.2 -> Mon 2024-05-13 07:42AM -> -5.32
			MinCurrentTime = Mon 2024-05-13 07:42AM, Duration = 70, SurfaceSwim = 0
			Entry Time: Mon 2024-05-13 07:07AM	(Exit time: 08:17AM)
			2.2 > 7:42AM > -5.32
			2.2(5:12AM) > 7:42AM > -5.32(10:30AM)
			Speed sum = 7.5
		Not diveable before flood:	-5.32 -> Mon 2024-05-13 02:30PM -> 4.7
	XTide
		Diveable: 2.77 -> Tue 2024-05-14 08:11AM -> -5.47
			MinCurrentTime = Tue 2024-05-14 08:11AM, Duration = 70, SurfaceSwim = 0
			Entry Time: Tue 2024-05-14 07:36AM	(Exit time: 08:46AM)
			2.77 > 8:11AM > -5.47
			2.77(5:56AM) > 8:11AM > -5.47(11:40AM)
			Speed sum = 8.2
		Not diveable before flood:	-5.47 -> Tue 2024-05-14 02:43PM -> 5.22
	NOAA / CA
		Diveable: 1.71 -> Tue 2024-05-14 08:48AM -> -4.12
			MinCurrentTime = Tue 2024-05-14 08:48AM, Duration = 70, SurfaceSwim = 0
			Entry Time: Tue 2024-05-14 08:13AM	(Exit time: 09:23AM)
			1.71 > 8:48AM > -4.12
			1.71(6:24AM) > 8:48AM > -4.12(11:18AM)
			Speed sum = 5.8
		Not diveable before flood:	-4.12 -> Tue 2024-05-14 03:18PM -> 3.84
    """


def extract_entry_time(entry_string):
    pattern = r'Entry Time:(.+?)\s*\(Exit'
    match = re.search(pattern, entry_string)
    if match:
        entry_time = match.group(1)
        return entry_time.strip()
    return None  # Return None if no match is found

def main():
    def calculate_time_difference(data):
        entry_times = []

        lines = data.split('\n')

        for line in lines:
            if 'Entry Time:' in line:
                entry_time_str = line.split(':')[-1].strip()
                # entry_time = dt.strptime(entry_time_str, '%a %Y-%m-%d %I:%M%p')
                entry_time = extract_entry_time(entry_time_str)
                entry_times.append(entry_time)

        time_differences = []
        print(entry_times)
        for i in range(1, len(entry_times)):
            time_diff = entry_times[i - 1] + (entry_times[i] - entry_times[i - 1]) / 2
            time_differences.append(time_diff)

        return time_differences

    time_differences = calculate_time_difference(str)
    print("Time differences between Entry Times:")
    for time_diff in time_differences:
        print(time_diff)


if __name__ == "__main__":
    main()

