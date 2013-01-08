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

	def terminate_slot(slot):
		if slots_values[slot].has_key('0039') and slots_values[slot]['0039'].endswith('-1'):
			return
		if len(slots_values_updated) == 0:
			return
		for k, v in slots_values[slot].items():
			if k not in slots_values_updated:
				frame.append(v)

	def terminate_frame(n):
		if len(frame) > 0:
			frames.append((float(time), n, frame))
		return []

	for line in file.readlines():
		if line.startswith('E:'):
			e, time, type, code, value = line.split(' ')
			value = value.rstrip('\n')
			if int(type, 16) == 0 and int(code, 16) == 0 and int(value, 16) == 0 :
				if len(slots_values_updated) > 0:
					terminate_slot(slot)
				slots_values_updated = []
				frame = terminate_frame(n)
			else:
				c = int(code, 16)
				if int(type, 16) == 3 and c == 0x2f:
					if len(slots_values_updated) > 0:
						terminate_slot(slot)
					# slot value
					slot = value
					if slot not in slots_values.keys():
						slots_values[slot] = {}
					slots_values_updated = []
				if c >=  0x2f and c <= 0x3d:
					if len(slots_values_updated) == 0 and int(type, 16) == 3 and c != 0x2f:
						# if the slot was not given, then add it to avoid
						# missmatches if slots are not given in the very same order
						str_slot = '0003 002f ' + str(slot)
						frame.append(str_slot)
						slots_values_updated.append('002f')
					slots_values_updated.append(code)
					slots_values[slot][code] = ' '.join([type, code, value])
				frame.append(' '.join([type, code, value]))
		else:
			descr.append(line)
		n += 1
	terminate_frame(n)
	return descr, frames

def compare_files(expected, result):
	''' returns ok, warning '''
	last_expected = None
	last_result = None
	exp = parse_evemu(expected)
	res = parse_evemu(result)
	warning = False

	if len(exp[0]) != len(res[0]):
		print 'description differs, got', len(res[0]), 'lines, instead of', len(exp[0])
		return False, warning

	for i in xrange(len(exp[0])):
		if exp[0][i] != res[0][i]:
			print 'line', i + 1, ': error, got'
			print res[0][i],
			print 'instead of'
			print exp[0][i],
			if res[0][i].startswith('A: 2f 0'):
				print 'This error is related to slot definition, it may be harmless, continuing...'
				warning = True
			else:
				return False, warning

	if len(exp[1]) != len(res[1]):
		if len(exp[1]) < len(res[1]):
			print 'too many events, should get only', len(exp[1]), 'instead of', len(res[1])
		else:
			print 'too few events, should get ', len(exp[1]), 'instead of', len(res[1])
		return False, warning

	for i in xrange(len(exp[1])):
		exp_time, exp_line, exp_events = exp[1][i]
		res_time, res_line, res_events = res[1][i]
		if len(exp_events) != len(res_events):
			print 'line', res_line, ', frame', i, ': got', len(res_events), 'events instead of', len(exp_events)
			return False, warning

		for j in xrange(len(exp_events)):
			r = res_events[j]
			if r.startswith('0003 002f '):
				# ignore slots, as they may be changed at each run
				continue
			if r not in exp_events:
				print 'line', res_line, ', frame', i, ':', "'" + r + "'", 'not in', exp_events
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

		if abs(exp_delta - res_delta) > 0.01:
			print 'line', res_line, ', frame', i, ': timestamps differs too much ->', res_delta - exp_delta, 'at', res_time
			warning = True

	return True, warning

if __name__ == '__main__':
	print compare_files(open(sys.argv[1]), open(sys.argv[2]))
