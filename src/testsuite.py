#!/bin/env python
# -*- coding: utf-8 -*-
#
# Hid test suite / main program
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

import time
import pyudev
import os
import sys
import subprocess
import shlex
import threading

context = pyudev.Context()

hid_replay_path = "/home/btissoir/Src/Kernel/hid-replay/src"
hid_replay_cmd = "hid-replay"
hid_replay = hid_replay_path + '/' + hid_replay_cmd

monitor = pyudev.Monitor.from_netlink(context)
monitor.filter_by('input')

nodes = {}
nodes_ready = []
tests = []
cv = threading.Condition()


def reset():
	global nodes, nodes_ready
	nodes = {}
	nodes_ready = []

def log_event(action, device):
	if 'event' in device.sys_name:
#		print action, device, device.sys_name
		if action == 'add':
			tmp = os.tmpfile()

			# get node attributes
			dev_path = "/dev/input/" + device.sys_name
			subprocess.call(shlex.split("evemu-describe " + dev_path), stdout=tmp)

			# start capturing events
			p = subprocess.Popen(shlex.split("evemu-record " + dev_path), stderr=None, stdout=tmp)

			# store it for later
			nodes[device.sys_name] = tmp, p

		elif action == 'remove':
			# get corresponding capturing process in background
			result, p = nodes[device.sys_name]

			# wait for it to terminate
			p.wait()

			# get the name of the node
			result.seek(0)
			name = None
			for l in result.readlines():
				if "Input device name" in l:
					name = l.replace("Input device name: \"", '')[:-2]
					break

			# reset the output so that it can be re-read later
			result.seek(0)

			# notify test_hid that we are done with the capture of this node
			cv.acquire()
			nodes_ready.append((device.sys_name, name, result))
			del nodes[device.sys_name]
			cv.notify()
			cv.release()


observer = pyudev.MonitorObserver(monitor, log_event)
observer.start()

def compare_files(expected, result):
	last_expected = None
	last_result = None
	for l_expected in expected.readlines():
		l_result = result.readline()
		l_expected = l_expected.rstrip('\n')
		l_result = l_result.rstrip('\n')
		if l_result != l_expected:
			if l_expected.startswith('E:'):
				# slightly complicate because the times may not
				# be exactly the same
				e, exp_time, exp_data = l_expected.split(' ', 2)
				e, res_time, res_data = l_result.split(' ', 2)
				if not last_expected:
					last_expected = float(exp_time)
				if not last_result:
					last_result = float(res_time)
				exp_delta = float(exp_time) - last_expected
				res_delta = float(res_time) - last_result

				if exp_data != res_data or abs(exp_delta - res_delta) > 0.05:
					print abs(exp_delta - res_delta), exp_data, res_data
					return False
			else:
				print l_result, l_expected
				return False
	return True

def dump_outs(file, outs):
	hid_name = os.path.splitext(os.path.basename(file))[0]
	for i in xrange(len(outs)):
		out = outs[i]
		ev_name = hid_name + '_' + str(i) + ".ev"
		print ev_name
		expected = open(ev_name, 'w')
		for l in out.readlines():
			expected.write(l)

def compare_result(file, name, expected, outs):
	if expected == None:
		return False

	if len(outs) != len(expected):
		return False

	for i in xrange(len(outs)):
		out = outs[i]
		expect = open(expected[i], 'r')
		r = compare_files(expect, out)
		expect.close()
		if not r:
			return False

	return True

def test_hid(file):
	reset()
	results = None
	rname = os.path.splitext(os.path.basename(file))[0]
	for ev_file in ev_files:
		if rname in ev_file:
			if not results:
				results = []
			results.append(ev_file)

	print "testing", file, "against", results
	if subprocess.call(shlex.split(hid_replay + " -s 1 -1 " + file)):
		return -1

	# wait for all the captures to finish
	cv.acquire()
	while len(nodes.keys()) > 0:
		cv.wait()
	cv.release()

	# retrieve the different captures
	outs = []
	for sys_name, name, out in nodes_ready:
		outs.append(out)

	# compare them
	r = compare_result(file, name, results, outs)

	if not r:
		# if there is a change, then dump the catptures in the current directory
		dump_outs(file, outs)

	# close the captures so that the tmpfiles are destroyed
	for out in outs:
		out.close()

	# append the result of the test to the list
	tests.append((file, r))
	return None

rootdir = '.'
if len(sys.argv) > 1:
	rootdir = sys.argv[1]
hid_files = []
ev_files = []

# first, retrieve all the .hid and .ev files in rootdir (first arg if given, otherwise, cwd)
for root, dirs, files in os.walk(rootdir):
	for f in files:
		path = os.path.join(root, f)
		if f.endswith(".hid"):
			hid_files.append(path)
		elif f.endswith(".ev"):
			ev_files.append(path)

try:
	# if specific devices are given, treat them, otherwise, run the test on all .hid
	if len(sys.argv) > 2:
		for file in sys.argv[2:]:
			test_hid(file)
	else:
		for file in hid_files:
			if test_hid(file):
				break
finally:
	for file, r in tests:
		print file, "->", r

