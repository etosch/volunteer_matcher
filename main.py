import googlemaps
from collections import defaultdict
import re
import csv
import datetime
import pprint
import random
import os


# Max distance in seconds that's acceptable for a volunteer to drive
MAX_DURATION_SEC = 40 * 60

# Number of volunteers to match per voting location
PER_LOCATION_QUOTA = 3

# Number of volunteers per voting location to fetch from google maps at a time.
# NOTE: Google maps charges for number of elements -- len(origins) x len(destinations)
BATCH_SIZE = 1

# Whether to actually call google maps
DRY_RUN = True

# The dates to match on
DATES = ['10/19', '10/20', '10/21', '10/22', '10/23', '10/24', '10/25']


SEND_ME_ANYWHERE = 'Send me anywhere!'
COUNTY_REGEX = r"\([^)]*\)"
DATE_REGEX = r"\(([^\)]*)\)"

# Cache for directions already fetched: {(voting_loc.id, volunteer.id): {'value': seconds, 'text': '15 min'}}
duration_cache = {}

# Number of elements fetched from Google Maps. Distance Matrix API charges by elements. 
num_google_maps_elements = 0

# Distance Matrix API must be enabled in GCP and this is the API key
GOOGLE_MAPS_KEY = os.environ.get("GOOGLE_MAPS_KEY")
assert GOOGLE_MAPS_KEY, "Must set Google Maps API key in env variable"

gmaps = googlemaps.Client(key=GOOGLE_MAPS_KEY)

log_file = open(f'logs/directions_log_{int(datetime.datetime.now().timestamp())}.txt', 'w')

class Volunteer:
	"""
	Properties:
		volunteer.id
		volunteer.addr_str
		volunteer[]:
			- first_name
			- last_name
			- address_street
			- address_city
			- address_zip
			- date_preference
			- county_preference
	"""

	def __init__(self, row, row_id):
		self._row = row
		self.addr_str = self.addr_str()
		self.id = row_id

	def addr_str(self):
		street = self._row['address_street'] or ''
		city = self._row['address_city'] or ''
		zip_code = self._row['address_zip'] or ''

		return ' '.join([street, city, zip_code]).strip()

	def __getitem__(self, attr):
		return self._row[attr]


class VotingLoc:
	"""
	Properties:
		voting_loc.id
		voting_loc[]
			- rank
			- county
			- precinct_name
			- voting_location
			- voting_addr
			- dates
	"""
	def __init__(self, row, row_id):
		self._row = row
		self.id = row_id

	def __getitem__(self, attr):
		return self._row[attr]


def load_volunteers():
	ret = []
	i = 0
	with open('volunteers.csv', newline='') as volunteers:
		reader = csv.DictReader(volunteers, delimiter=',')
		for row in reader:
			ret.append(Volunteer(row, i))
			i += 1
	return ret


def load_voting_locs():
	ret = []
	i = 0
	with open('voting_locs.csv', newline='') as voting_locs:
		reader = csv.DictReader(voting_locs, delimiter=',')
		for row in reader:
			ret.append(VotingLoc(row, i))
			i += 1

	return ret


def log_directions(directions_resp):
	global log_file
	pprint.pprint(directions_resp, log_file)


def get_directions(volunteers, voting_loc):
	if DRY_RUN:
		return {(voting_loc.id, v.id): {'value': random.randint(1, 2000), 'text': '15 min'} for v in volunteers}

	durations_map = {}
	for v in volunteers:
		durations_map[(voting_loc.id, v.id)] = duration_cache.get((voting_loc.id, v.id))


	need_directions = list(filter(lambda v: (voting_loc.id, v.id) not in duration_cache, volunteers))
	origins = [v.addr_str for v in need_directions]


	if not origins:
		return durations_map

	global num_google_maps_elements
	num_google_maps_elements += len(origins)

	# Rows are origins, columns are destinations
	res = googlemaps.distance_matrix.distance_matrix(gmaps, origins, [voting_loc['voting_addr']])

	log_directions(res)

	for i in range(len(res['rows'])):
		cell = res['rows'][i]['elements'][0]
		if cell['status'] == 'OK':
			key = (voting_loc.id, need_directions[i].id)
			duration_cache[key] = cell['duration']
			durations_map[key] = cell['duration']		

	return durations_map


def try_to_fill_from_cache(voting_loc, potential_volunteers, num_to_match=PER_LOCATION_QUOTA):
	filled_volunteers = []
	for v_id in potential_volunteers:
		if (voting_loc.id, v_id) in duration_cache:
			duration = duration_cache[(voting_loc.id, v_id)]
			if duration['value'] < MAX_DURATION_SEC:
				filled_volunteers.append((v_id, duration))

		if len(filled_volunteers) == num_to_match:
			break

	return filled_volunteers


def get_all_volunteers_from_cache(vl_id):
	all_volunteers = set()
	for key in duration_cache:
		if key[0] == vl_id:
			all_volunteers.add(key[1])
	return all_volunteers


def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def match_vol_to_voting_loc(date, vl, potential_vids, vols_by_id, send_to_county_by_date, send_me_anywhere_by_date):
	# First, try to fill spot with volunteers whose directions have been fetched. If their distance is in 
	# bounds, they have already been matched to the location on another date.
	cached_volunteers = try_to_fill_from_cache(vl, potential_vids, num_to_match=1)

	if cached_volunteers:
		return cached_volunteers[0]

	# Remove all cached volunteers from the list of potential volunteers since they've already been 
	# considered above.
	potential_vids = list(potential_vids.difference(get_all_volunteers_from_cache(vl.id)))

	for c in chunks(potential_vids, BATCH_SIZE):
		directions = get_directions([vols_by_id[v_id] for v_id in c], vl)

		for key in directions:
			if not directions[key]:
				continue

			if directions[key]['value'] < MAX_DURATION_SEC:
				_, v_id = key
				return (v_id, directions[key])

	# If no volunteer could be matched, then check volunteers who can go anywhere in the county
	county = vl['county'].strip()
	if len(send_to_county_by_date[date][county]) > 0:
		return (send_to_county_by_date[date][county].pop(), {'text': 'Send me to county', 'value': 0})

	# If still no one was matched, then fill with a "Send me anywhere!" volunteer
	if len(send_me_anywhere_by_date[date]) > 0:
		return (send_me_anywhere_by_date[date].pop(), {'text': 'Send me anywhere', 'value': 0})

	return None, None


def match_by_date(date, volunteers_by_county, voting_locs, vols_by_id, raw_volunteers, vls_by_id, send_me_anywhere_by_date, send_to_county_by_date):
	matched = set()
	matched_volunteers_by_loc = defaultdict(list)
	vls_by_rank = defaultdict(list)

	for vl in voting_locs:
		vls_by_rank[int(vl['rank'])].append(vl)
	sorted_vl_ranks = sorted(list(vls_by_rank.keys()))

	open_spots_by_voting_loc = {}

	# Assign volunteers round-robin. In order of rank, assign 1 volunteer to each location, then assign another
	# until we reach the quota. 
	for rank in sorted_vl_ranks:
		for i in range(PER_LOCATION_QUOTA):
			for vl in vls_by_rank[rank]:
				county = vl['county'].strip()
				potential_vids = set(filter(lambda v: v not in matched, volunteers_by_county[county]))

				v_id, duration = match_vol_to_voting_loc(
					date,
					vl, 
					potential_vids,
					vols_by_id, 
					send_to_county_by_date, 
					send_me_anywhere_by_date,
				)

				if v_id is None:
					continue
				
				for existing_vol in matched_volunteers_by_loc[vl.id]:
					if v_id == existing_vol[0]:
						assert False, f"Already matched v_id {v_id} to vl_id {vl.id}"

				matched_volunteers_by_loc[vl.id].append((v_id, duration))
				matched.add(v_id)
				print(f"Matched: {vl['county']}, {vl['voting_location'].strip()}, {v_id}, {duration['text']}")

	for vl in voting_locs:
		num_matched = len(matched_volunteers_by_loc[vl.id])
		if num_matched < PER_LOCATION_QUOTA:
			open_spots_by_voting_loc[vl.id] = PER_LOCATION_QUOTA - num_matched
			print(f"Unmatched: {vl['voting_location'].strip()}, {PER_LOCATION_QUOTA - num_matched}")

	filename_date = date.replace('/', '-')

	with open(f'output/{filename_date}_unmatched.csv', 'w', newline='') as unmatched:
		csv_writer = csv.writer(unmatched, delimiter=',')
		csv_writer.writerow(['Date', 'Name', 'Address', 'County Preference'])
		for v in raw_volunteers:
			if v.id not in matched and date in v['date_preference']:
				csv_writer.writerow([date, f"{v['first_name']} {v['last_name']}", v.addr_str, v['county_preference']])

	with open(f'output/{filename_date}_matched.csv', 'w', newline='') as matched:
		csv_writer = csv.writer(matched, delimiter=',')
		csv_writer.writerow(['Date', 'Rank', 'County', 'Precinct Name', 'Voting Location', 'Volunteer', 'Vol Addr', 'Vol Duration'])
		for vl in voting_locs:
			matched = matched_volunteers_by_loc[vl.id]
			for v, duration in matched:
				csv_writer.writerow([date, vl['rank'], vl['county'], vl['precinct_name'], vl['voting_location'], f"{vols_by_id[v]['first_name']} {vols_by_id[v]['last_name']}", vols_by_id[v].addr_str, duration['text']])
		
			if open_spots_by_voting_loc.get(vl.id):
				for i in range(open_spots_by_voting_loc[vl.id]):
					csv_writer.writerow([date, vl['rank'], vl['county'], vl['precinct_name'], vl['voting_location'], 'Unfilled', '', ''])


	with open(f'output/{filename_date}_open_spots.csv', 'w', newline='') as open_spots:
		csv_writer = csv.writer(open_spots, delimiter=',')
		csv_writer.writerow(['Date', 'Rank', 'County', 'Name', 'Voting location', 'Address', 'Num Open Spots'])
		for vl_id, num_spots in open_spots_by_voting_loc.items():
			vl = vls_by_id[vl_id]
			csv_writer.writerow([date, vl['rank'], vl['county'], vl['precinct_name'], vl['voting_location'], vl['voting_addr'], num_spots])


def voting_loc_has_date(d, vl):
	dates = map(lambda d: d.strip(), vl['dates'].split(','))
	return d in dates


def run():
	voting_locs = load_voting_locs()
	raw_volunteers = load_volunteers()
	vols_by_id = {v.id: v for v in raw_volunteers}
	vls_by_id = {vl.id: vl for vl in voting_locs}

	volunteers_by_county_by_date = defaultdict(lambda: defaultdict(set))
	send_me_anywhere_by_date = defaultdict(set)
	send_to_county_by_date = defaultdict(lambda: defaultdict(set))
	for v in raw_volunteers:
		if not v['date_preference']:
			continue

		date_iter = re.finditer(DATE_REGEX, v['date_preference'])
		raw_counties = re.sub(COUNTY_REGEX, '', v['county_preference'])
		for d in date_iter:
			date = d.groups()[0].strip()
			county_list = list(map(lambda s: s.strip(), raw_counties.split(',')))

			if SEND_ME_ANYWHERE in county_list and len(county_list) == 1:
				send_me_anywhere_by_date[date].add(v.id)
				continue

			for county in county_list:
				if v.addr_str:
					volunteers_by_county_by_date[date][county].add(v.id)
				else:
					send_to_county_by_date[date][county].add(v.id)

	for date in DATES:
		volunteers_by_county = volunteers_by_county_by_date[date]
		print(f"\n\n\n\nMatching date {date}")
		filtered_voting_locs = list(filter(lambda vl: voting_loc_has_date(date, vl), voting_locs))
		match_by_date(date, volunteers_by_county, filtered_voting_locs, vols_by_id, raw_volunteers, vls_by_id, send_me_anywhere_by_date, send_to_county_by_date)


print(f"Start time: {str(datetime.datetime.now())}")
run()
print(f"Num google maps API elements: {num_google_maps_elements}")
print(f"End time: {str(datetime.datetime.now())}")
