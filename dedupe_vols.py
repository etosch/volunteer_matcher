import argparse
import csv
import datetime

def load_assigned_vols(input_file):
	vols_list = []
	with open(input_file, newline='') as vols:
		reader = csv.DictReader(vols, delimiter=',')
		for row in reader:
			if not row['assigned'].strip():
				continue
			vols_list.append((row['id'], row['assigned']))
	
	return vols_list


def load_input_vols(input_file):
	vols_list = []
	with open(input_file, newline='') as vols:
		reader = csv.DictReader(vols, delimiter=',')
		for row in reader:
			vols_list.append(' '.join([row['first_name'].strip(), row['last_name'].strip()]))
	
	return vols_list


def find_duplicates(assigned_vols, input_vols):
	dupes = set()
	num_dupes = 0
	for input_vol in input_vols:
		for vol_id, assigned_vol in assigned_vols:
			if input_vol in assigned_vol:
				num_dupes += 1
				dupes.add(input_vol)
	print(f'Total duplicates: {num_dupes}')
	return dupes

def write_deduped_file(input_file, dupes):
	filename = f'deduped_vols_{int(datetime.datetime.now().timestamp())}.csv'
	with open(filename, 'w') as write:
		with open(input_file, newline='') as vols:
			reader = csv.DictReader(vols, delimiter=',')
			writer = csv.DictWriter(write, fieldnames=reader.fieldnames, delimiter=',')

			writer.writeheader()
			for row in reader:
				if f'{row["first_name"].strip()} {row["last_name"].strip()}' in dupes:
					continue
				writer.writerow(row)
	print(filename)



parser = argparse.ArgumentParser()
parser.add_argument('--assigned_vols_file', nargs=1)
parser.add_argument('--input_vols_file', nargs=1)

args = parser.parse_args()

assigned_vols = load_assigned_vols(args.assigned_vols_file[0])
input_vols = load_input_vols(args.input_vols_file[0])

dupes = find_duplicates(assigned_vols, input_vols)
write_deduped_file(args.input_vols_file[0], dupes)

