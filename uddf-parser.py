# convert shearwater export to my excel dive log csv format
import xml.etree.ElementTree as ET
from datetime import timedelta, datetime
import os
import csv


def meters_to_feet(meters: float) -> float:
    """Converts meters to feet."""
    return meters * 3.28084


def kelvin_to_fahrenheit(kelvin: float) -> float:
    """Converts Kelvin to Fahrenheit."""
    return (kelvin - 273.15) * 9 / 5 + 32


def format_seconds_to_dhms(seconds: int) -> str:
    """Formats a duration in seconds to a string (e.g., >24hrs or H:MM)."""
    td = timedelta(seconds=seconds)
    days = td.days
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days > 0:
        return ""
        # return ">24hrs"
    else:
        if seconds >= 30:
            minutes += 1
            if minutes == 60:
                minutes = 0
                hours += 1
                if hours == 24:
                    return ">24hrs"
        return f"{hours}:{minutes:02}"


def get_total_minutes(seconds: int) -> int:
    """Returns total minutes for a duration, rounded to the nearest minute."""
    minutes, rem_seconds = divmod(seconds, 60)
    if rem_seconds >= 30:
        minutes += 1
    return minutes


def parse_uddf(file_path: str) -> dict:
    """
    Parses a UDDF file and extracts key dive statistics.

    Args:
        file_path: The path to the .uddf file.

    Returns:
        A dictionary containing the extracted dive statistics, or None on failure.
    """
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        ns = {'uddf': 'http://www.streit.cc/uddf/3.2/'}

        dive_data = {}
        dive_element = root.find('.//uddf:dive', ns)
        if dive_element is None:
            return None

        # --- Extract Information Before Dive ---
        info_before = dive_element.find('uddf:informationbeforedive', ns)
        if info_before:
            dt_elem = info_before.find('uddf:datetime', ns)
            if dt_elem is not None:
                datetime_str = dt_elem.text.replace('Z', '')
                dt_obj = datetime.fromisoformat(datetime_str)

                if dt_obj.second >= 30:
                    dt_obj += timedelta(minutes=1)

                dive_data['Date'] = dt_obj.strftime('%Y-%m-%d')
                dive_data['Start Time'] = f"{dt_obj.hour}:{dt_obj.strftime('%M')}"
            else:
                dive_data['Date'] = 'N/A'
                dive_data['Start Time'] = 'N/A'

            si_elem = info_before.find('.//uddf:passedtime', ns)
            if si_elem is not None:
                si_seconds = int(si_elem.text)
                dive_data['Surface Interval'] = format_seconds_to_dhms(si_seconds)

        # --- Extract Information After Dive ---
        info_after = dive_element.find('uddf:informationafterdive', ns)
        if info_after:
            depth_elem = info_after.find('uddf:greatestdepth', ns)
            if depth_elem is not None:
                max_depth_m = float(depth_elem.text)
                dive_data['Max Depth (ft)'] = round(meters_to_feet(max_depth_m), 1)

            avg_depth_elem = info_after.find('uddf:averagedepth', ns)
            if avg_depth_elem is not None:
                avg_depth_m = float(avg_depth_elem.text)
                dive_data['Average Depth (ft)'] = round(meters_to_feet(avg_depth_m), 1)

            duration_elem = info_after.find('uddf:diveduration', ns)
            if duration_elem is not None:
                duration_seconds = int(duration_elem.text)
                dive_data['Dive Time (min)'] = get_total_minutes(duration_seconds)

        # --- Extract General Dive Information ---
        location_elem = root.find('.//uddf:divesite//uddf:location', ns)
        dive_data['Location'] = location_elem.text if location_elem is not None else 'N/A'

        # --- Extract Water Temperature ---
        temp_elements = dive_element.findall('.//uddf:waypoint/uddf:temperature', ns)
        # Ensure there are enough readings to get an in-water temp
        if temp_elements and len(temp_elements) > 1:
            # We skip the first reading (at time 0) as it is often a surface temperature
            temps_k = [float(temp.text) for temp in temp_elements[1:]]
            if temps_k:
                min_temp_k = min(temps_k)
                # Round to the nearest whole number for Fahrenheit
                dive_data['Water Temp (F)'] = round(kelvin_to_fahrenheit(min_temp_k))

        return dive_data

    except (FileNotFoundError, ET.ParseError, Exception):
        return None


if __name__ == "__main__":
    log_directory = '/Users/juwarner/Downloads/april2025'
    output_csv_file = 'dive_log_summary.csv'

    print(f"--- Scanning for dive logs in: '{os.path.abspath(log_directory)}' ---")

    uddf_files_to_process = []
    try:
        for filename in sorted(os.listdir(log_directory)):
            if filename.lower().endswith('.uddf'):
                uddf_files_to_process.append(os.path.join(log_directory, filename))
    except FileNotFoundError:
        print(f"Error: Directory not found at '{log_directory}'")

    if not uddf_files_to_process:
        print("\nNo .uddf files found in the directory.")
    else:
        print(f"Found {len(uddf_files_to_process)} dive log(s).")
        choice = input(
            "\nSelect an output format:\n"
            "  1. Print Summaries to Console\n"
            "  2. Generate a single CSV file\n"
            "Enter your choice (1 or 2): "
        )

        if choice == '1':
            print("\n--- Generating Per-Dive Summaries ---")
            for full_path in uddf_files_to_process:
                filename = os.path.basename(full_path)
                print(f"\n--- Dive Log Summary for: {filename} ---")
                dive_stats = parse_uddf(full_path)
                if dive_stats:
                    print(f"{'Date':<18}: {dive_stats.get('Date', 'N/A')}")
                    print(f"{'Start Time':<18}: {dive_stats.get('Start Time', 'N/A')}")
                    print(f"{'Location':<18}: {dive_stats.get('Location', 'N/A')}")
                    print(f"{'Surface Interval':<18}: {dive_stats.get('Surface Interval', 'N/A')}")
                    print(f"{'Max Depth':<18}: {dive_stats.get('Max Depth (ft)', 'N/A')} ft")
                    print(f"{'Average Depth':<18}: {dive_stats.get('Average Depth (ft)', 'N/A')} ft")
                    print(f"{'Dive Time':<18}: {dive_stats.get('Dive Time (min)', 'N/A')} minutes")
                    print(f"{'Min Temp':<18}: {dive_stats.get('Water Temp (F)', 'N/A')}°F")
                else:
                    print("    -> Failed to parse this file.")
                print("-" * (len(filename) + 24))

        elif choice == '2':
            print(f"\n--- Generating CSV file: {output_csv_file} ---")
            headers = [
                'date', 'start time', 'location', 'surface interval',
                'max depth (ft)', 'avg depth (ft)', 'dive time (min)', 'min temp (F)'
            ]
            with open(output_csv_file, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(headers)

                for full_path in uddf_files_to_process:
                    dive_stats = parse_uddf(full_path)
                    if dive_stats:
                        row = [
                            dive_stats.get('Date', ''),
                            dive_stats.get('Start Time', ''),
                            dive_stats.get('Location', ''),
                            dive_stats.get('Surface Interval', ''),
                            dive_stats.get('Max Depth (ft)', ''),
                            dive_stats.get('Average Depth (ft)', ''),
                            dive_stats.get('Dive Time (min)', ''),
                            dive_stats.get('Water Temp (F)', '')
                        ]
                        writer.writerow(row)
                    else:
                        print(f"    -> Warning: Could not parse, skipping file: {os.path.basename(full_path)}")

            print(f"\nSuccessfully created '{output_csv_file}' with data from {len(uddf_files_to_process)} dive logs.")

        else:
            print("\nInvalid choice. Please run the script again and enter 1 or 2.")
