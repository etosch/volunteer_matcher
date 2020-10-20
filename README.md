# volunteer_matcher

This is a script to match volunteers to polling locations on different dates.

## How to run

One time setup: Install python 3, create a virtual env, and install requirements, set up Google maps API key (see section below for info).

```
python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

To run: tune constants in the script and then run the script.

```
env GOOGLE_MAPS_KEY="YOUR_API_KEY" python main.py
```

Command line args:
--input_vl_file: path to voting location / open spots file
--use_open_spots: uses "open spots mode" for the voting location input. See **Input files** section under **voting_locs.csv** for more info.
--do_it: Actually call out to google maps.

## Algorithm
- Matches up to `PER_LOCATION_QUOTA` volunteers per voting location in a round-robin manner by rank. For all voting locations with the same rank, attempt to assign one volunteer to each, then assign another to all locations until we reach the quota.
- If volunteers only have county preference "Send me anywhere!", they will be slotted wherever volunteers are needed.
- If a volunteer chooses "Send me anywhere!" and another county preference, we will only consider county preferences. 
- If the volunteer doesn't provide an address, they can be assigned to any location in a county they preference.
- If a volunteer provides an address and county preference, they won't be matched more than distance of `MAX_DURATION_SEC` seconds.
- If a volunteer doesn't preference a county, but a voting location in that county is within our distance threshold, the volunteer won't be matched.
- When running multiple dates at a time, we will preference matching volunteers at the same location as they have been before.
- In open spots mode, we use (van_precinct_id, county, voting_location) as a voting location's unique key. Because voting location names aren't unique, we have a few duplicates (LDS churches). Before processing, any voting locations that end up with more than 2 open spots are printed out. Should stop the script and make the voting location names be unique before running again. 

## Input files
### voting_locs.csv
These are all of the voting locations to match volunteers to.

Columns:
- rank: Integer representing how to prioritize the voting location. Lower number is higher priority. Doesn't have to be unique.
- county: County name, must correspond to counties in **volunteers.csv**
- precinct_name: Name of the precinct, used for logging in output
- voting_location: Name of the voting location
- voting_addr: Address of voting location. Must be searchable in Google maps. Can use custom maps import functionality to check these locations.
- dates: Comma-separated list of dates that the location is open. Dates should be formatted like "MM/DD"

### Open Spots Mode
For input sheets with one open spot per row, instead of one voting location per row. We use this for subsequent runs for election day. This is the same output as the **open_spots.csv** output file.

NOTE: From election day schedule, must remove rows that already have volunteers matched. 

Columns:
- rank: Integer representing how to prioritize the voting location. Lower number is higher priority. Doesn't have to be unique.
- id: The ID of the open spot
- county: County name, must correspond to counties in **volunteers.csv**
- precinct_name: Name of the precinct, used for logging in output
- voting_location: Name of the voting location
- voting_addr: Address of voting location. Must be searchable in Google maps. Can use custom maps import functionality to check these locations.
- dates: Comma-separated list of dates that the location is open. Dates should be formatted like "MM/DD"


### volunteers.csv
These are all the volunteers willing to be matched:

Columns:
- first_name: Volunteer's first name (used for logging)
- last_name: Volunteer's last name (used for logging)
- address_street: Volunteers address containing the street number and street
- address_city: Volunteer's city
- address_zip: Volunteer's zip code
- date_preference: Comma-separated list of dates. Each date must be in format like "Tuesday (MM/DD)"
- county_preference: Comma-separated list of county preferences. Must match counties in **voting_locs.csv** but may have parentheses appended. Like "Maricopa (e.g. Phoenix)", for example. Value can also be "Send me anywhere!"


## Output files
For each date, the following output files are generated.

### output/{date}_matched.csv
One row per volunteer slot per location. If the volunteer position is not filled, will be marked as "Unfilled".

Columns: 
- Date: Date that the volunteer is matched
- Rank: Rank of the voting location
- County: County of the voting location
- Precinct Name: Precinct name of the voting location
- Voting Location: Name of the voting location
- Volunteer: Volunteer's first and last name
- Vol Addr: Volunteer's street address (from **input.csv** this is address_street, address_city, and address_zip concatenated)
- Vol Duration: Driving distance for the volunteer

### output/{date}_unmatched.csv
All volunteers who aren't matched per date.

Columns:
- Date: Date that the volunteer is unmatched
- Name: First and last name of the volunteer
- Address: Volunteer's address, if provided
- County Preference: Same county preference as row input in **volunteers.csv**

### output/{date}_open_spots.csv
All spots still needing to be filled. Can be run with a new batch of volunteers using the flag `--use_open_spots`.

Columns:
- rank: Integer representing how to prioritize the voting location. Lower number is higher priority. Doesn't have to be unique.
- id: The ID of the open spot
- county: County name, must correspond to counties in **volunteers.csv**
- precinct_name: Name of the precinct, used for logging in output
- voting_location: Name of the voting location
- voting_addr: Address of voting location. Must be searchable in Google maps. Can use custom maps import functionality to check these locations.
- dates: Comma-separated list of dates that the location is open. Dates should be formatted like "MM/DD"

### logs/directions_log_{timestamp}.txt
Records all responses from the Distance Matrix API. Useful for debugging if addresses can't be found by Google Maps. 

## Setting up Google Maps API Key
Create a new GCP project (should generate $300 in credits if you don't already use GCP) in the GCP console.

On the home page, search "Distance Matrix API" in the searchbar. Enable the integration. (This comes with $200 in credits per month for this API).

Note that 1000 elements queried costs $5. 

To get API Key:
- Click "Manage" on the Distance Matrix API page.
- Click on "Credentials"
- Create a new API key
- Use this API key when calling the script.


# dedupe_vols.py Script

This script takes in csvs of assigned volunteers and volunteers we will try to assign and filters out any assigned volunteers from the new list. It then dumps this filtered data into a new output file.

## How to run
```
python dedupe_vols.py --assigned_vols_file={path/to/filename.csv} --input_vols_file={path/to/filename.csv}
```


## Algorithm
Does string matching to see if a first name/last name pair appears anywhere in the `assigned` column of the assigned volunteers. This way if there are multiple people assigned, any name in the list will match.

## Input file: assigned volunteers

Columns:
- id: The ID of the assigment
- assigned: The names of people assigned to the spot

## Input file: input volunteers

Columns:
- first_name: First name of the volunteer
- last_name: Last name of the volunteer

## Output:

Output will be put in a file called `deduped_vols_{timestamp}.csv`.

This will contain all of the data in the input volunteers file but with any rows filtered out where the volunteer's name is in the assigned file.



