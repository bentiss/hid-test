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
import compare_evemu

context = pyudev.Context()

hid_replay_path = "/home/btissoir/Src/Kernel/hid-replay/src"
hid_replay_cmd = "hid-replay"
hid_replay = hid_replay_path + '/' + hid_replay_cmd

monitor = pyudev.Monitor.from_netlink(context)
monitor.filter_by('input')

global currentRunningHidTest
currentRunningHidTest = None
nodes = {}

def log_event(action, device):
	if 'event' in device.sys_name:
#		print action, device, device.sys_name
		if action == 'add':
			if not currentRunningHidTest:
				return

			tmp = os.tmpfile()

			# get node attributes
			dev_path = "/dev/input/" + device.sys_name
			subprocess.call(shlex.split("evemu-describe " + dev_path), stdout=tmp)

			# start capturing events
			p = subprocess.Popen(shlex.split("evemu-record " + dev_path), stderr=None, stdout=tmp)

			# store it for later
			nodes[device.sys_name] = tmp, p, currentRunningHidTest
			currentRunningHidTest.nodes[device.sys_name] = tmp, p, currentRunningHidTest

		elif action == 'remove':
			# get corresponding capturing process in background
			result, p, hid = nodes[device.sys_name]

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
			hid.cv.acquire()
			hid.nodes_ready.append((device.sys_name, name, result))
			del nodes[device.sys_name]
			del hid.nodes[device.sys_name]
			hid.cv.notify()
			hid.cv.release()


observer = pyudev.MonitorObserver(monitor, log_event)
observer.start()

tests = []

class HIDTest(object):
	def __init__(self, path):
		self.path = path
		self.reset()

	def reset(self):
		self.nodes = {}
		self.nodes_ready = []
		self.cv = threading.Condition()
		self.outs = []
		self.expected = []

	def dump_outs(self):
		hid_name = os.path.splitext(os.path.basename(self.path))[0]
		for i in xrange(len(self.outs)):
			out = self.outs[i]
			out.seek(0)
			ev_name = hid_name + '_' + str(i) + ".ev"
			print ev_name
			expected = open(ev_name, 'w')
			for l in out.readlines():
				expected.write(l)

	def dump_diff(self, name, events_file):
		events_file.seek(0)
		descr, frames = compare_evemu.parse_evemu(events_file)
		output = open(name, 'w')
		f_number = 0
		for d in descr:
			output.write(d)
		for time, n, frame, extras in frames:
			f_number += 1
			output.write('frame '+str(f_number) + ':\n')
			for i in xrange(len(frame)):
				end = '\n'
				if i in extras:
					end = '*\n'
				output.write('    '+ frame[i] + end)
		output.close()

	def dump_diffs(self):
		hid_name = os.path.splitext(os.path.basename(self.path))[0]
		for i in xrange(len(self.outs)):
			ev_name = hid_name + '_res_' + str(i) + ".evd"
			print ev_name
			self.dump_diff(ev_name, self.outs[i])
		if not self.expected:
			return
		for i in xrange(len(self.expected)):
			ev_name = hid_name + '_exp_' + str(i) + ".evd"
			print ev_name
			expect = open(self.expected[i], 'r')
			self.dump_diff(ev_name, expect)
			expect.close()

	def compare_result(self):
		warning = False
		if self.expected == None:
			return False, warning

		if len(self.outs) != len(self.expected):
			return False, warning

		for i in xrange(len(self.outs)):
			out = self.outs[i]
			expect = open(self.expected[i], 'r')
			r, w = compare_evemu.compare_files(expect, out)
			expect.close()
			if w:
				warning = True
			if not r:
				return r, warning

		return True, warning

	def run(self):
		self.reset()
		results = None
		rname = os.path.splitext(os.path.basename(self.path))[0]
		for ev_file in ev_files:
			if rname in ev_file:
				if not results:
					results = []
				results.append(ev_file)

		# In case there are several files, keep the right one
		if results:
			kernel_release = os.uname()[2]
			_results = {}
			for r in results:
				basename = os.path.basename(r)
				rkernel_release = os.path.basename(os.path.dirname(r)).rstrip('.x')
				if not rkernel_release.startswith('3.'):
					rkernel_release = kernel_release
				if kernel_release < rkernel_release:
					# ignore dumps from earlier kernels
					continue
				if basename not in _results.keys():
					_results[basename] = r
				else:
					current_kernel_release = os.path.basename(os.path.dirname(_results[basename])).rstrip('.x')
					if current_kernel_release < rkernel_release:
						# overwrite the file only if the kernel release is earlier
						_results[basename] = r
			results = _results.values()
			results.sort()

		self.expected = results

		print "testing", self.path, "against", results
		if subprocess.call(shlex.split(hid_replay + " -s 1 -1 " + self.path)):
			return -1

		# wait for all the captures to finish
		self.cv.acquire()
		while len(self.nodes.keys()) > 0:
			self.cv.wait()
		self.cv.release()

		# retrieve the different captures
		for sys_name, name, out in self.nodes_ready:
			self.outs.append(out)

		# compare them
		r, w = self.compare_result()

		if not r:
			# if there is a change, then dump the captures in the current directory
			print "test failed, dumping outputs in:"
			self.dump_outs()
			self.dump_diffs()
		elif w:
			# if there is a warning, still dump the captures in the current directory
			print "success but warning raised, dumping outputs in:"
			self.dump_outs()
		else:
#			self.dump_outs()
			print "success"

		# close the captures so that the tmpfiles are destroyed
		for out in self.outs:
			out.close()

		# append the result of the test to the list,
		# we only count the warning if the test passed
		tests.append((self.path, (r, w and r)))

		print "----------------------------------------------------------------"

		return None

def report_results(tests):
	good = 0
	warn = 0
	for file, (r, w) in tests:
		print file, "->", r,
		if w:
			print '(warning raised)'
		else:
			print ''
		if r: good += 1
		if w: warn += 1
	print good,'/', len(tests), 'tests passed (', warn, 'warnings )'

# disable stdout buffering
sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)

rootdir = '.'
if len(sys.argv) > 1:
	rootdir = sys.argv[1]
hid_files = []
ev_files = []

# starts xi2dettach
xi2detach = subprocess.Popen(shlex.split(os.path.join(os.path.dirname(sys.argv[0]), 'xi2detach')), stderr= subprocess.PIPE, stdout= subprocess.PIPE)

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
			currentRunningHidTest = HIDTest(file)
			currentRunningHidTest.run()
	else:
		hid_files.sort()
		for file in hid_files:
			currentRunningHidTest = HIDTest(file)
			if currentRunningHidTest.run():
				break
finally:
	report_results(tests)
	xi2detach.terminate()

