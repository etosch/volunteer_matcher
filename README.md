# volunteer_matcher

This is a script to match volunteers to polling locations on different dates.

## How to run

One time setup: Install python 3, create a virtual env, and install requirements

```
python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

To run: tune constants in the script and then run the script.

```
env GOOGLE_MAPS_KEY="YOUR_API_KEY" python main.py
```

## Algorithm
- Matches up to `PER_LOCATION_QUOTA` volunteers per voting location in a round-robin manner by rank. For all voting locations with the same rank, attempt to assign one volunteer to each, then assign another to all locations until we reach the quota.
- If volunteers only have county preference "Send me anywhere!", they will be slotted wherever volunteers are needed.
- If a volunteer chooses "Send me anywhere!" and another county preference, we will only consider county preferences. 
- If the volunteer doesn't provide an address, they can be assigned to any location in a county they preference.
- If a volunteer provides an address and county preference, they won't be matched more than distance of `MAX_DURATION_SEC` seconds.
- If a volunteer doesn't preference a county, but a voting location in that county is within our distance threshold, the volunteer won't be matched.
- When running multiple dates at a time, we will preference matching volunteers at the same location as they have been before.

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
All voting locations with open spots for the date.
Can import into google custom maps with **output/{date}_unmatched.csv** to match extra volunteers.

Columns:
- Date: Date that the location has open spots
- Rank: Rank of voting location
- County: County of voting location
- Name: Precinct name
- Voting location: Name of voting location
- Address: Street address of voting location
- Num Open Spots: Number of spots still available

### logs/directions_log_{timestamp}.txt
Records all responses from the Distance Matrix API. Useful for debugging if addresses can't be found by Google Maps. 
