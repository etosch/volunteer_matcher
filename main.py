import googlemaps
from collections import defaultdict
import re
import csv
import datetime
import pprint
import random
import os
import argparse


# Max distance in seconds that's acceptable for a volunteer to drive
MAX_DURATION_SEC = 40 * 60

# Number of volunteers to match per voting location
PER_LOCATION_QUOTA = 2

# Number of volunteers per voting location to fetch from google maps at a time.
# NOTE: Google maps charges for number of elements -- len(origins) x len(destinations)
BATCH_SIZE = 1

# The dates to match on
DATES = ['11/3']


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

ids = ['A', 'B', 'C']

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
			- van_precinct_id
		open_spots: Number of spots to fill
		ids: The ids of the open spots
	"""
	def __init__(self, row, row_id, open_ids=None):
		self._row = row
		self.id = row_id
		self.open_spots = len(open_ids) if open_ids else PER_LOCATION_QUOTA
		self.ids = open_ids or [self._row['rank'].strip() + ids[i] for i in range(self.open_spots)]

	def __getitem__(self, attr):
		return self._row[attr]

	def add_open_spot(self, open_spot_id):
		self.open_spots += 1
		self.ids.append(open_spot_id)

	def key():
		return get_vl_key(self._row)

	def __str__(self):
		return f'id: {self.id}, open spots: {self.open_spots}, county: {self._row["county"]}, location: {self._row["voting_location"]}'


def get_vl_key(row_dict):
	return f'{row_dict["van_precinct_id"].strip()}:{row_dict["county"].strip()}:{row_dict["voting_location"].strip()}'


def load_volunteers():
	ret = []
	i = 0
	with open('volunteers.csv', newline='') as volunteers:
		reader = csv.DictReader(volunteers, delimiter=',')
		for row in reader:
			ret.append(Volunteer(row, i))
			i += 1
	return ret


def load_voting_locs(input_vl_file, use_open_spots):
	ret = []
	i = 0

	if not use_open_spots:
		with open(input_vl_file, newline='') as voting_locs:
			reader = csv.DictReader(voting_locs, delimiter=',')
			for row in reader:
				ret.append(VotingLoc(row, i))
				i += 1

		return ret

	voting_loc_by_key = {}
	with open(input_vl_file, newline='') as voting_locs:
		reader = csv.DictReader(voting_locs, delimiter=',')
		for row in reader:
			vl_key = get_vl_key(row)
			if vl_key not in voting_loc_by_key:
				voting_loc_by_key[vl_key] = VotingLoc(row, i, open_ids=[row['id']])
				i += 1
			else:
				voting_loc_by_key[vl_key].add_open_spot(row['id'])
	return list(voting_loc_by_key.values())


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
	try:
		res = googlemaps.distance_matrix.distance_matrix(gmaps, origins, [voting_loc['voting_addr']])
	except:
		print("Origins: ", origins, "Polling location: ", voting_loc['voting_addr'])
		raise

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


def match_vol_to_voting_loc(date, vl, potential_vids, vols_by_id, send_to_county_by_date, send_me_anywhere_by_date, already_matched):
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
	while len(send_to_county_by_date[date][county]) > 0:
		potential_vol = send_to_county_by_date[date][county].pop()
		if potential_vol not in already_matched:
			return (potential_vol, {'text': 'Send me to county', 'value': 0})

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
				if len(matched_volunteers_by_loc[vl.id]) == vl.open_spots:
					continue

				county = vl['county'].strip()
				potential_vids = set(filter(lambda v: v not in matched, volunteers_by_county[county]))

				v_id, duration = match_vol_to_voting_loc(
					date,
					vl, 
					potential_vids,
					vols_by_id, 
					send_to_county_by_date, 
					send_me_anywhere_by_date,
					matched,
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
		if num_matched < vl.open_spots:
			open_spots_by_voting_loc[vl.id] = vl.open_spots - num_matched
			print(f"Unmatched: {vl['voting_location'].strip()}, {vl.open_spots - num_matched}")

	filename_date = date.replace('/', '-')

	with open(f'output/{filename_date}_unmatched.csv', 'w', newline='') as unmatched:
		csv_writer = csv.writer(unmatched, delimiter=',')
		csv_writer.writerow(['Date', 'Name', 'Address', 'County Preference'])
		for v in raw_volunteers:
			if v.id not in matched and date in v['date_preference']:
				csv_writer.writerow([date, f"{v['first_name'].strip()} {v['last_name'].strip()}", v.addr_str, v['county_preference']])

	with open(f'output/{filename_date}_matched.csv', 'w', newline='') as matched:
		csv_writer = csv.writer(matched, delimiter=',')
		csv_writer.writerow(['Date', 'ID', 'Rank', 'County', 'Precinct Name', 'Voting Location', 'Volunteer', 'Vol Addr', 'Vol Duration'])
		for vl in voting_locs:
			ids = set(vl.ids)
			matched = matched_volunteers_by_loc[vl.id]
			for v, duration in matched:
				csv_writer.writerow([date, ids.pop(), vl['rank'], vl['county'], vl['precinct_name'].strip(), vl['voting_location'].strip(), f"{vols_by_id[v]['first_name'].strip()} {vols_by_id[v]['last_name'].strip()}", vols_by_id[v].addr_str, duration['text']])
		
			if open_spots_by_voting_loc.get(vl.id):
				for i in range(open_spots_by_voting_loc[vl.id]):
					csv_writer.writerow([date, ids.pop(), vl['rank'], vl['county'], vl['precinct_name'].strip(), vl['voting_location'].strip(), 'Unfilled', '', ''])


	with open(f'output/{filename_date}_open_spots.csv', 'w', newline='') as open_spots:
		csv_writer = csv.writer(open_spots, delimiter=',')
		csv_writer.writerow(['dates', 'id', 'rank', 'van_precinct_id', 'county', 'precinct_name', 'voting_location', 'voting_addr'])
		for vl_id, num_spots in open_spots_by_voting_loc.items():
			vl = vls_by_id[vl_id]
			for i in range(num_spots):
				csv_writer.writerow([date, vl.ids[len(vl.ids) - 1 - i], vl['rank'], vl['van_precinct_id'], vl['county'], vl['precinct_name'].strip(), vl['voting_location'].strip(), vl['voting_addr'].strip()])


def voting_loc_has_date(d, vl):
	dates = map(lambda d: d.strip(), vl['dates'].split(','))
	return d in dates


def run(input_vl_file, use_open_spots):
	voting_locs = load_voting_locs(input_vl_file, use_open_spots)
	
	print("MORE THAN 2")
	for vl in voting_locs:
		if vl.open_spots > PER_LOCATION_QUOTA:
			print(str(vl))

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


parser = argparse.ArgumentParser()
parser.add_argument('--input_vl_file', nargs='?')
parser.add_argument('--use_open_spots', type=bool, nargs='?', const=True)
parser.add_argument('--do_it', type=bool, nargs='?', const=True)

args = parser.parse_args()

# Whether to call google maps or not
DRY_RUN = not args.do_it

print(f"Start time: {str(datetime.datetime.now())}")
run(input_vl_file=args.input_vl_file, use_open_spots=args.use_open_spots)
print(f"Num google maps API elements: {num_google_maps_elements}")
print(f"End time: {str(datetime.datetime.now())}")
