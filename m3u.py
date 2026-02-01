import requests
import os
import re
import json
import sys
import time
import urllib.parse
import urllib3
import concurrent.futures
from datetime import datetime, timedelta
from base64 import b64decode, b64encode
from binascii import a2b_hex

try:
    from bs4 import BeautifulSoup
    from dateutil import parser
    from playwright.sync_api import sync_playwright
except ImportError:
    print("ERROR: Missing required libraries. Please run: pip install requests beautifulsoup4 python-dateutil playwright", file=sys.stderr)

 # Disable security warnings for requests without SSL verification
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def headers_to_extvlcopt(headers):
    """Function kept for compatibility, but no longer actively used."""
    return []

def search_m3u8_in_sites(channel_id, is_tennis=False, session=None):
    """Directly generates the dlhd.dad URL for the provided channel_id."""
    return f"https://dlhd.dad/watch.php?id={channel_id}"

def dlhd():
    """
    Extracts 24/7 channels and live events from DaddyLive and saves them in a single M3U file.
    Automatically removes duplicate channels.
    """
    print("Running dlhd...")

    JSON_FILE = "daddyliveSchedule.json"
    OUTPUT_FILE = "dlhd.m3u"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
    }

    # ========== SUPPORT FUNCTIONS ==========
    def clean_category_name(name):
        return re.sub(r'<[^>]+>', '', name).strip()

    def clean_tvg_id(tvg_id):
        cleaned = re.sub(r'[^a-zA-Z0-9À-ÿ]', '', tvg_id)
        return cleaned.lower()

    # ========== EXTRACTION OF 24/7 CHANNELS ==========
    print("Extracting 24/7 channels from HTML page...")
    html_url = "https://dlhd.dad/24-7-channels.php"
    session = requests.Session()

    try:
        response = requests.get(html_url, headers=HEADERS, timeout=15, verify=False)
        response.raise_for_status()
        
        # Parse HTML with BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        cards = soup.find_all('a', class_='card')
        
        print(f"Found {len(cards)} channels in HTML page")
 
        channels_247 = []
 
        for card in cards:
            # Extract channel name
            title_div = card.find('div', class_='card__title')
            if not title_div:
                continue
            
            name = title_div.text.strip()
            
            # Extract channel ID from href
            href = card.get('href', '')
            if not ('id=' in href):
                continue
            
            channel_id = href.split('id=')[1].split('&')[0]
            
            if not name or not channel_id:
                continue

            # Apply corrections as before
            if name == "Sky Calcio 7 (257) Italy":
                name = "DAZN"
            if channel_id == "853":
                name = "Canale 5 Italy"
            
            # Search for .m3u8 stream
            stream_url = search_m3u8_in_sites(channel_id, is_tennis="tennis" in name.lower(), session=session)
            
            if stream_url: # The function now always returns a URL
                channels_247.append((name, stream_url))

        # Count occurrences of each channel name
        name_counts = {}
        for name, _ in channels_247:
            name_counts[name] = name_counts.get(name, 0) + 1
 
        # Add a counter to duplicate names
        final_channels = []
        name_counter = {}
 
        for name, stream_url in channels_247:
            if name_counts[name] > 1:
                if name not in name_counter:
                    # First occurrence of a duplicate, keep the original name
                    name_counter[name] = 1
                    final_channels.append((name, stream_url))
                else:
                    # Subsequent occurrences, add counter
                    name_counter[name] += 1
                    new_name = f"{name} ({name_counter[name]})"
                    final_channels.append((new_name, stream_url))
            else:
                final_channels.append((name, stream_url))

        print(f"Found {len(channels_247)} 24/7 channels")
        channels_247 = final_channels
    except Exception as e:
        print(f"Error extracting 24/7 channels: {e}")
        channels_247 = []

    # ========== EXTRACTION OF LIVE EVENTS ==========
    print("Extracting live events...")
    live_events = []

    if os.path.exists(JSON_FILE):
        try:
            now = datetime.now()
            yesterday_date = (now - timedelta(days=1)).date()

            with open(JSON_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            categorized_channels = {}

            for date_key, sections in data.items():
                date_part = date_key.split(" - ")[0]
                try:
                    date_obj = parser.parse(date_part, fuzzy=True).date()
                except Exception as e:
                    print(f"Error parsing date '{date_part}': {e}")
                    continue

                process_this_date = False
                is_yesterday_early_morning_event_check = False

                if date_obj == now.date():
                    process_this_date = True
                elif date_obj == yesterday_date:
                    process_this_date = True
                    is_yesterday_early_morning_event_check = True
                else:
                    continue

                if not process_this_date:
                    continue

                for category_raw, event_items in sections.items():
                    category = clean_category_name(category_raw)
                    if category.lower() == "tv shows":
                        continue
                    if category not in categorized_channels:
                        categorized_channels[category] = []

                    for item in event_items:
                        time_str = item.get("time", "00:00")
                        event_title = item.get("event", "Evento")

                        try:
                            original_event_time_obj = datetime.strptime(time_str, "%H:%M").time()
                            event_datetime_adjusted_for_display_and_filter = datetime.combine(date_obj, original_event_time_obj)

                            if is_yesterday_early_morning_event_check:
                                start_filter_time = datetime.strptime("00:00", "%H:%M").time()
                                end_filter_time = datetime.strptime("04:00", "%H:%M").time()
                                if not (start_filter_time <= original_event_time_obj <= end_filter_time):
                                    continue
                            else:
                                if now - event_datetime_adjusted_for_display_and_filter > timedelta(hours=2):
                                    continue

                            time_formatted = event_datetime_adjusted_for_display_and_filter.strftime("%H:%M")
                        except Exception as e_time:
                            print(f"Errore parsing orario '{time_str}' per evento '{event_title}' in data '{date_key}': {e_time}")
                            time_formatted = time_str

                        for ch in item.get("channels", []):
                            channel_name = ch.get("channel_name", "")
                            channel_id = ch.get("channel_id", "")

                            tvg_name = f"{event_title} ({time_formatted})"
                            categorized_channels[category].append({
                                "tvg_name": tvg_name,
                                "channel_name": channel_name,
                                "channel_id": channel_id,
                                "event_title": event_title,
                                "category": category
                            })

            # Converti in lista per il file M3U
            for category, channels in categorized_channels.items():
                for ch in channels:
                    try: 
                        # Search first for .m3u8 stream
                        stream = search_m3u8_in_sites(ch["channel_id"], is_tennis="tennis" in ch["channel_name"].lower(), session=session)                        
                        if stream:
                            live_events.append((f"{category} | {ch['tvg_name']}", stream))
                    except Exception as e:
                        print(f"Error on {ch['tvg_name']}: {e}")

            print(f"Found {len(live_events)} live events")

        except Exception as e:
            print(f"Error extracting live events: {e}")
            live_events = []
    else:
        print(f"File {JSON_FILE} not found, live events skipped")

    # ========== GENERATION OF UNIFIED M3U FILE ==========
    print("Generating unified M3U file...")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n\n")

        # Add live events if present
        if live_events:
            f.write(f'#EXTINF:-1 group-title="Live Events",DADDYLIVE\n')
            f.write("https://example.com.m3u8\n\n")

            for name, url in live_events:
                f.write(f'#EXTINF:-1 group-title="Live Events",{name}\n')
                f.write(f'{url}\n\n')

        # Add 24/7 channels
        if channels_247:
            for name, url in channels_247:
                f.write(f'#EXTINF:-1 group-title="DLHD 24/7",{name}\n')
                f.write(f'{url}\n\n')

    total_channels = len(channels_247) + len(live_events)
    print(f"Created file {OUTPUT_FILE} with {total_channels} total channels:")
    print(f"  - {len(channels_247)} 24/7 channels")
    print(f"  - {len(live_events)} live events")

 # Function for the fourth script (schedule_extractor.py)
def schedule_extractor():
    # Code for the fourth script here
    # Add the code of your "schedule_extractor.py" script in this function.
    print("Running schedule_extractor.py...")

    def html_to_json(html_content):
        soup = BeautifulSoup(html_content, 'html.parser')
        result = {}

        schedule_days = soup.find_all('div', class_='schedule__day')
        if not schedule_days:
            print("WARNING: No 'schedule__day' found in HTML content!")
            return {}

        for day_div in schedule_days:
            day_title_div = day_div.find('div', class_='schedule__dayTitle')
            if not day_title_div:
                continue
            current_date = day_title_div.get_text(strip=True)
            result[current_date] = {}

            for category_div in day_div.find_all('div', class_='schedule__category'):
                cat_header = category_div.find('div', class_='schedule__catHeader')
                if not cat_header:
                    continue
                
                # We use the inner HTML to keep any tags, as before
                current_category_html = cat_header.find('div', class_='card__meta').decode_contents()
                current_category = current_category_html.strip() + "</span>" # Maintains compatibility with previous format
                result[current_date][current_category] = []

                for event_div in category_div.find_all('div', class_='schedule__event'):
                    event_header = event_div.find('div', class_='schedule__eventHeader')
                    if not event_header:
                        continue

                    time_span = event_header.find('span', class_='schedule__time')
                    event_title_span = event_header.find('span', class_='schedule__eventTitle')

                    event_time = time_span.get_text(strip=True) if time_span else ""
                    event_info = event_title_span.get_text(strip=True) if event_title_span else ""

                    event_data = {
                        "time": event_time,
                        "event": event_info,
                        "channels": []
                    }

                    channels_div = event_div.find('div', class_='schedule__channels')
                    if channels_div:
                        for link in channels_div.find_all('a'):
                            href = link.get('href', '')
                            channel_id_match = re.search(r'(?:watch|stream)-(\d+)\.php', href) or re.search(r'id=(\d+)', href)
                            if channel_id_match:
                                channel_id = channel_id_match.group(1)
                                channel_name = link.get_text(strip=True)
                                event_data["channels"].append({
                                    "channel_name": channel_name,
                                    "channel_id": channel_id
                                })
                    result[current_date][current_category].append(event_data)
        return result
    
    def modify_json_file(json_file_path):
        with open(json_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        current_month = datetime.now().strftime("%B")
    
        for date in list(data.keys()):
            match = re.match(r"(\w+\s\d+)(st|nd|rd|th)\s(\d{4})", date)
            if match:
                day_part = match.group(1)
                suffix = match.group(2)
                year_part = match.group(3)
                new_date = f"{day_part}{suffix} {current_month} {year_part}"
                data[new_date] = data.pop(date)
    
        with open(json_file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        
        print(f"JSON file modified and saved in {json_file_path}")
    
    def extract_schedule_container():
        url = f"https://dlhd.dad/"

        script_dir = os.path.dirname(os.path.abspath(__file__))
        json_output = os.path.join(script_dir, "daddyliveSchedule.json")

        print(f"Accessing page {url} to extract the schedule container...")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
    
            max_attempts = 3
            for attempt in range(1, max_attempts + 1):
                try:
                    print(f"Attempt {attempt} of {max_attempts}...")
                    page.goto(url)
                    print("Waiting for full page load...")
                    page.wait_for_timeout(10000)  # 10 seconds

                    schedule_content = page.evaluate("""() => {
                        const container = document.querySelector('body');
                        return container ? container.outerHTML : '';
                    }""")

                    if not schedule_content:
                        print("WARNING: Page content not found or empty!")
                        if attempt == max_attempts:
                            browser.close()
                            return False
                        else:
                            continue
    
                    print("Converting main schedule HTML to JSON format...")
                    json_data = html_to_json(schedule_content)
    
                    with open(json_output, "w", encoding="utf-8") as f:
                        json.dump(json_data, f, indent=4)
    
                    print(f"JSON data saved in {json_output}")
    
                    modify_json_file(json_output)
                    browser.close()
                    return True
    
                except Exception as e:
                    print(f"ERROR in attempt {attempt}: {str(e)}")
                    if attempt == max_attempts:
                        print("All attempts failed!")
                        browser.close()
                        return False
                    else:
                        print(f"Retrying... (attempt {attempt + 1} of {max_attempts})")
    
            browser.close()
            return False
    
    if __name__ == "__main__":
        success = extract_schedule_container()
        if not success:
            exit(1)

def vavoo_channels():
    # Code for the seventh script here
    # Add the code of your "world_channels_generator.py" script in this function.
    print("Running vavoo_channels...")
    
    def getAuthSignature():
        headers = {
            "user-agent": "okhttp/4.11.0",
            "accept": "application/json",
            "content-type": "application/json; charset=utf-8",
            "content-length": "1106",
            "accept-encoding": "gzip"
        }
        data = {
            "token": "tosFwQCJMS8qrW_AjLoHPQ41646J5dRNha6ZWHnijoYQQQoADQoXYSo7ki7O5-CsgN4CH0uRk6EEoJ0728ar9scCRQW3ZkbfrPfeCXW2VgopSW2FWDqPOoVYIuVPAOnXCZ5g",
            "reason": "app-blur",
            "locale": "de",
            "theme": "dark",
            "metadata": {
                "device": {
                    "type": "Handset",
                    "os": "Android",
                    "osVersion": "10",
                    "model": "Pixel 4",
                    "brand": "Google"
                }
            }
        }
        resp = requests.post("https://vavoo.to/mediahubmx-signature.json", json=data, headers=headers, timeout=10)
        return resp.json().get("signature")
    
    def vavoo_groups():
        # You can add more groups for more channels
        return [""]
    
    def clean_channel_name(name):
        """Removes .a, .b, .c suffixes from the channel name"""
        # Removes .a, .b, .c at the end of the name (with or without spaces before)
        cleaned_name = re.sub(r'\s*\.(a|b|c|s|d|e|f|g|h|i|j|k|l|m|n|o|p|q|r|t|u|v|w|x|y|z)\s*$', '', name, flags=re.IGNORECASE)
        return cleaned_name.strip()
    
    def get_channels():
        signature = getAuthSignature()
        headers = {
            "user-agent": "okhttp/4.11.0",
            "accept": "application/json",
            "content-type": "application/json; charset=utf-8",
            "accept-encoding": "gzip",
            "mediahubmx-signature": signature
        }
        all_channels = []
        for group in vavoo_groups():
            cursor = 0
            while True:
                data = {
                    "language": "de",
                    "region": "AT",
                    "catalogId": "iptv",
                    "id": "iptv",
                    "adult": False,
                    "search": "",
                    "sort": "name",
                    "filter": {"group": group},
                    "cursor": cursor,
                    "clientVersion": "3.0.2"
                }
                resp = requests.post("https://vavoo.to/mediahubmx-catalog.json", json=data, headers=headers, timeout=10)
                r = resp.json()
                items = r.get("items", [])
                all_channels.extend(items)
                cursor = r.get("nextCursor")
                if not cursor:
                    break
        return all_channels
    
    def save_as_m3u(channels, filename="vavoo.m3u"):
        # 1. Collect all channels into a flat list
        all_channels_flat = []
        for ch in channels:
            original_name = ch.get("name", "NoName")
            name = clean_channel_name(original_name)
            url = ch.get("url", "")
            category = ch.get("group", "General")
            if url:
                all_channels_flat.append({'name': name, 'url': url, 'category': category})

        # 2. Count occurrences of each name
        name_counts = {}
        for ch_data in all_channels_flat:
            name_counts[ch_data['name']] = name_counts.get(ch_data['name'], 0) + 1

        # 3. Rename duplicates
        final_channels_data = []
        name_counter = {}
        for ch_data in all_channels_flat:
            name = ch_data['name']
            if name_counts[name] > 1:
                if name not in name_counter:
                    name_counter[name] = 1
                    new_name = name  # Keep the original name for the first occurrence
                else:
                    name_counter[name] += 1
                    new_name = f"{name} ({name_counter[name]})"
            else:
                new_name = name
            final_channels_data.append({'name': new_name, 'url': ch_data['url'], 'category': ch_data['category']})

        # 4. Group channels by category for file writing
        channels_by_category = {}
        for ch_data in final_channels_data:
            category = ch_data['category']
            if category not in channels_by_category:
                channels_by_category[category] = []
            channels_by_category[category].append((ch_data['name'], ch_data['url']))

        # 5. Write the M3U file
        with open(filename, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for category in sorted(channels_by_category.keys()):
                channel_list = sorted(channels_by_category[category], key=lambda x: x[0].lower())
                f.write(f"\n# {category.upper()}\n")
                for name, url in channel_list:
                    f.write(f'#EXTINF:-1 group-title="{category} VAVOO",{name}\n{url}\n')

        print(f"M3U playlist saved in: {filename}")
        print(f"Channels organized in {len(channels_by_category)} categories:")
        for category, channel_list in channels_by_category.items():
            print(f"  - {category}: {len(channel_list)} channels")
    
    if __name__ == "__main__":
        channels = get_channels()
        print(f"Found {len(channels)} channels. Creating M3U playlist with proxy links...")
        save_as_m3u(channels) 
        
def sportsonline():
    import requests
    import re
    from bs4 import BeautifulSoup
    import datetime
    
    # URL of the schedule file
    PROG_URL = "https://sportsonline.st/prog.txt"
    OUTPUT_FILE = "sportsonline.m3u"  # Defined as a constant
    
    def get_channel_languages(lines):
        """
        Analyzes the lines of the schedule file to map channels with their languages.
        Returns a dictionary with key=channel_id and value=language (e.g. {'hd7': 'ITALIAN'}).
        """
        channel_language_map = {}
        for line in lines:
            line_stripped = line.strip()
            # Look for lines that define the language of a channel (format: "HD7 ITALIAN")
            if line_stripped and not line_stripped.startswith(('http', '|', '#')) and ' ' in line_stripped:
                parts = line_stripped.split(maxsplit=1)
                if len(parts) == 2:
                    channel_id_raw = parts[0].strip()
                    language = parts[1].strip()
                    # Check that the first element is a channel ID (e.g. HD7, BR1, etc.)
                    if channel_id_raw and not any(day in channel_id_raw.upper() for day in 
                        ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]):
                        channel_id = channel_id_raw.lower()
                        channel_language_map[channel_id] = language
                        print(f"[INFO] Found channel: {channel_id.upper()} - Language: {language}")
        return channel_language_map
    
    def extract_channel_from_url(url):
        """
        Extracts the channel identifier from the URL.
        Ex: https://sportzonline.st/channels/hd/hd5.php -> hd5
        """
        match = re.search(r'/([a-z0-9]+)\.php$', url, re.IGNORECASE)
        if match:
            return match.group(1).lower()
        return None
    
    print("Running sportsonline...")
    
    # --- Check the day of the week ---
    today_weekday = datetime.date.today().weekday()
    weekdays_english = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
    day_to_filter = weekdays_english[today_weekday]
    print(f"Today is {day_to_filter}, only today's events will be searched.")

    print(f"1. Downloading schedule from: {PROG_URL}")
    try:
        response = requests.get(PROG_URL, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"[FATAL ERROR] Unable to download the schedule file: {e}")
        return

    lines = response.text.splitlines()

    print("\n2. Mapping channels with their respective languages...")
    channel_language_map = get_channel_languages(lines)

    if not channel_language_map:
        print("[WARNING] No channel with language found in the schedule.")
        return

    playlist_entries = []

    print("\n3. Searching for broadcasted Events...")

    processing_today_events = False

    for line in lines:
        line_upper = line.upper().strip()

        # Check if the line is a weekday header
        if line_upper in weekdays_english:
            if line_upper == day_to_filter:
                processing_today_events = True
            else:
                processing_today_events = False
            continue

        # Process the line only if we are in the correct day's section
        if not processing_today_events:
            continue

        if '|' not in line:
            continue

        parts = line.split('|')
        if len(parts) != 2:
            continue

        event_info = parts[0].strip()
        page_url = parts[1].strip()

        # Extract the channel from the URL
        channel_id = extract_channel_from_url(page_url)
        
        if channel_id and channel_id in channel_language_map:
            language = channel_language_map[channel_id]
            print(f"\n[EVENT] Found event: '{event_info}' - Channel: {channel_id.upper()} - Language: {language}")
            
            # Reformat the event name: Event Name Time [LANGUAGE]
            event_parts = event_info.split(maxsplit=1)
            if len(event_parts) == 2:
                time_str_original, name_only = event_parts
                
                # Add 1 hour to the time
                try:
                    original_time = datetime.datetime.strptime(time_str_original.strip(), '%H:%M')
                    new_time = original_time + datetime.timedelta(hours=1)
                    time_str = new_time.strftime('%H:%M')
                except ValueError:
                    time_str = time_str_original.strip()
                
                event_name = f"{name_only.strip()} {time_str} [{language}]"
            else:
                event_name = f"{event_info} [{language}]"

            playlist_entries.append({
                "name": event_name,
                "url": page_url,
                "referrer": "https://sportsonline.st/",
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
    
    # Create fallback channel if there are no events
    if not playlist_entries:
        print("\n[INFO] No events found today.")
        print("[INFO] Creating fallback channel 'NO EVENT'...")
        playlist_entries.append({
            "name": "NO EVENT", 
            "url": "https://cph-p2p-msl.akamaized.net/hls/live/2000341/test/master.m3u8",
            "referrer": "https://sportsonline.st/",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

    # 4. Create the M3U file
    print(f"\n4. Writing playlist to file: {OUTPUT_FILE}")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for entry in playlist_entries:
            f.write(f'#EXTINF:-1 group-title="Live Events SPORTSONLINE",{entry["name"]}\n')
            f.write(f'{entry["url"]}\n')

    print(f"\n[COMPLETED] Playlist created successfully! Open the file '{OUTPUT_FILE}' with a player like VLC.")

def main():
    try:
        try:
            schedule_extractor()
        except Exception as e:
            print(f"Error during execution of schedule_extractor: {e}")
            return
        try:
            vavoo_channels()
        except Exception as e:
            print(f"Error during execution of vavoo_channels: {e}")
            return
        try:
            dlhd()
        except Exception as e:
            print(f"Error during execution of dlhd: {e}")
            return
        try:
            sportsonline()
        except Exception as e:
            print(f"Error during execution of sportsonline: {e}")
            return
        print("All scripts executed successfully!")
    finally:
        pass

if __name__ == "__main__":
    main()
