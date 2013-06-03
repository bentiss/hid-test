#!/bin/env python
# -*- coding: utf-8 -*-
#
# Hid test suite / compare evemu files
#
# Copyright (c) 2012 Benjamin Tissoires <benjamin.tissoires@gmail.com>
# Copyright (c) 2012 Red Hat, Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import os
import sys

# Sometimes, the events within a frame (between two EV_SYN events) may not be
# ordered in the same way.
# This comparison is not sensitive to this problem.

def parse_evemu(file):
	descr = []
	frames = []
	frame = []
	slot = 0
	last_slot = 0
	n = 1
	slots_values = {0:{}}
	slots_values_updated = []
	extras = []
	values = {}
	values_updated = []
	time = "0"

	def terminate_slot(slot):
		if slots_values[slot].has_key('0039') and slots_values[slot]['0039'].endswith('-1'):
			return
		if len(slots_values_updated) == 0:
			return
		for k, v in slots_values[slot].items():
			if k not in slots_values_updated:
				extras.append(len(frame))
				frame.append(v)

	def terminate_frame(n, trigger):
		if len(frame) == 0 and trigger == "0000 0000 0":
			# old kernels can not set HID_QUIRK_NO_INPUT_SYNC, giving from times
			# to times empty frames
			return []
		for k, v in values.items():
			if k not in values_updated:
				extras.append(len(frame))
				frame.append(v)
		if len(frame) > 0:
			if trigger:
				frame.append(trigger)
			# EV_SYN(1) are a pain: adding them, no matter the device says
			if "0000 0000 1" not in frame:
				extras.append(len(frame))
				frame.append("0000 0000 1")
			frames.append((float(time), n, frame, extras))
		return []

	for line in file.readlines():
		if line.startswith('#'):
			continue
		if line.startswith('E:'):
			# remove end of lines comments
			stripped_line = line[:line.find('#')].rstrip('\t ')
			e, time, type, code, value = stripped_line.split(' ')

			# newer evemu send the value with leading 0.
			# transforming back and forth to str allows a common format
			v = int(value)
			value = str(v)
			if int(type, 16) == 0 and int(code, 16) == 0:
				if v == 0 :
					# EV_SYN
					if len(slots_values_updated) > 0:
						terminate_slot(slot)
					frame = terminate_frame(n, ' '.join([type, code, value]))
				elif v == 1:
					if "0000 0000 1" not in frame:
						frame.append(' '.join([type, code, value]))
				else:
					frame.append(' '.join([type, code, value]))
				slots_values_updated = []
				values_updated = []
				extras = []
			else:
				c = int(code, 16)
				if int(type, 16) == 1:
					# BTN event
					if v == 2:
						# key repeat event, drop it
						continue
				elif int(type, 16) == 3:
					# absolute event
					if c >=  0x2f and c <= 0x3d:
						# MT event
						if c == 0x2f:
							if len(slots_values_updated) > 0:
								terminate_slot(slot)
							# slot value
							slot = value
							if slot not in slots_values.keys():
								slots_values[slot] = {}
							slots_values_updated = []
						elif len(slots_values_updated) == 0:
							# if the slot was not given, then add it to avoid
							# missmatches if slots are not given in the very same order
							str_slot = '0003 002f ' + str(slot)
							extras.append(len(frame))
							frame.append(str_slot)
							slots_values_updated.append('002f')
						slots_values_updated.append(code)
						slots_values[slot][code] = ' '.join([type, code, value])
					else:
						values_updated.append(code)
						values[code] = ' '.join([type, code, value])
				frame.append(' '.join([type, code, value]))
		else:
			descr.append(line)
		n += 1
	if len(slots_values_updated) > 0:
		terminate_slot(slot)
	terminate_frame(n, None)

	if len(frames) == 1:
		time, n, frame, extras = frames[0]
		if len(frame) == 1 and frame[0] == '0000 0000 1':
			# all keys up event sent on disconnect
			# that means that no events were sent, we can drop the
			# results
			frames = []
	return descr, frames

def print_(str_result, line):
	if str_result:
		str_result.append(line)
	else:
		print line

def cleanup_properties(expected, result):
	if abs(len(expected) - len(result)) == 1:
		exp_prop = False
		res_prop = False
		for d in expected:
			if d.startswith("P:"):
				exp_prop = True
				break
		for d in result:
			if d.startswith("P:"):
				res_prop = True
				break
		if exp_prop != res_prop:
			if exp_prop:
				expected = [d for d in expected if not d.startswith("P:")]
			if res_prop:
				result = [d for d in result if not d.startswith("P:")]
	return expected, result

def compare_desc(expected, result):
	expected, result = cleanup_properties(expected, result)
	if len(expected) != len(result):
		return False

	for i in xrange(len(expected)):
		if expected[i] != result[i]:
			if not expected[i].startswith('A: 2f 0'):
				return False

	return True

def compare_files(exp, res, str_result = None, prefix = '', delta_timestamp = 0):
	''' returns ok, warning '''
	last_expected = None
	last_result = None
	warning = False

	exp_desc, res_desc = cleanup_properties(exp[0], res[0])

	if len(exp_desc) != len(res_desc):
		print_(str_result, prefix + 'description differs, got ' + str(len(res_desc)) + ' lines, instead of ' + str(len(exp_desc)))
		return False, warning

	for i in xrange(len(exp_desc)):
		if exp_desc[i] != res_desc[i]:
			print_(str_result, prefix + 'line ' + str(i + 1) + ': error, got ' + str(res_desc[i]) + ' instead of ' + str(exp_desc[i]))
			if res_desc[i].startswith('A: 2f 0'):
				print_(str_result, prefix + 'This error is related to slot definition, it may be harmless, continuing...')
				warning = True
			else:
				return False, warning

	if len(exp[1]) != len(res[1]):
		if len(exp[1]) < len(res[1]):
			print_(str_result, prefix + 'too many events, should get only ' + str(len(exp[1])) + ' events instead of ' + str(len(res[1])))
		else:
			print_(str_result, prefix + 'too few events, should get ' + str(len(exp[1])) + ' events instead of ' + str(len(res[1])))
		return False, warning

	for i in xrange(len(exp[1])):
		exp_time, exp_line, exp_events, extras = exp[1][i]
		res_time, res_line, res_events, extras = res[1][i]
		if len(exp_events) != len(res_events):
			print_(str_result, prefix + 'line ' + str(res_line) + ', frame ' + str(i + 1) + ': got ' + str(len(res_events)) + ' events instead of ' + str(len(exp_events)))
			return False, warning

		for j in xrange(len(exp_events)):
			r = res_events[j]
			if r.startswith('0003 002f '):
				# ignore slots, as they may be changed at each run
				continue
			if r not in exp_events:
				print_(str_result, prefix + 'line ' + str(res_line) + ', frame ' + str(i) + ": '"  + str(r) + "' not in " + str(exp_events))
				return False, warning
			index = exp_events.index(r)
			del(exp_events[index])

		# all the events are the same, now compare the sync timestamp
		if not last_expected:
			last_expected = exp_time
		if not last_result:
			last_result = res_time
		exp_delta = exp_time - last_expected
		res_delta = res_time - last_result
		last_expected = exp_time
		last_result = res_time

		if delta_timestamp > 0 and abs(exp_delta - res_delta) > delta_timestamp:
			print_(str_result, prefix + 'line ' + str(res_line) + ', frame ' + str(i) + ': timestamps differs too much -> ' + str(res_delta - exp_delta) + ' at ' + str(res_time))
			warning = True

	return True, warning

def compare_sets(expected_list, result_list, str_result = None, delta_timestamp = 0):
	warning = False
	matches = True
	if expected_list == None:
		return False, warning

	# parse both sets
	res_list = [ parse_evemu(res) for res in result_list]
	files_exp_list = [ open(exp, 'r') for exp in expected_list]
	exp_list = [ parse_evemu(exp) for exp in files_exp_list]
	for f in files_exp_list:
		f.close()

	i = 0
	found = False
	for res in res_list:
		prefix = 'output #' + str(i) + ': '
		if len(res_list) == 1:
			prefix = ''
		desc, data = res
		exp = None
		for exp_item in exp_list:
			exp_desc, d = exp_item
			if compare_desc(desc, exp_desc):
				exp = exp_item
				break

		if not exp:
			print_(str_result, prefix + 'no matching device')
			warning = True
			if len(data) > 0:
				matches = False
				print_(str_result, prefix + str(len(data)) + ' events received -> test failed')
			else:
				print_(str_result, prefix + 'no events received -> ignoring')
		else:
			found = True
			r, w = compare_files(exp, res, str_result, prefix, delta_timestamp)
			warning = warning or w
			matches = matches and r

		i += 1

	if not found:
		return False, warning

	return matches, warning

def dump_diff(name, events_file):
	import evdev
	events_file.seek(0)
	descr, frames = parse_evemu(events_file)
	output = open(name, 'w')
	f_number = 0
	for d in descr:
		output.write(d)
	for time, n, frame, extras in frames:
		f_number += 1
		output.write('frame '+str(f_number) + ':\n')
		for i in xrange(len(frame)):
			type, code, value = frame[i].split(' ')
			type = int(type, 16)
			code = int(code, 16)
			stype, scode = evdev.match(type, code)
			end = '\n'
			if i in extras:
				end = '*\n'
			output.write('    '+ frame[i] + ' '*(30 - len(frame[i])) + '# ' + stype + ' / ' + scode + end)
	output.close()

if __name__ == '__main__':
	if len(sys.argv) == 2:
		f0 = open(sys.argv[1])
		parsed = parse_evemu(f0)
		name = os.path.basename(sys.argv[1]) + ".evd"
		print "dumping output in:", name
		dump_diff(name, f0)
		f0.close()
		sys.exit(0)
	f0 = open(sys.argv[1])
	f1 = open(sys.argv[2])
	success, warning = compare_files(parse_evemu(f0), parse_evemu(f1))
	if not success:
		print "test failed, dumping outputs in:"
		name = os.path.basename(sys.argv[1]) + ".evd"
		dump_diff(name, f0)
		print name
		name = os.path.basename(sys.argv[2]) + ".evd"
		dump_diff(name, f1)
		print name
	else:
		print "the too files are equivalent"
	f0.close()
	f1.close()
