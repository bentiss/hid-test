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
import getopt

context = pyudev.Context()

hid_replay_path = "/home/btissoir/Src/Kernel/hid-replay/src"
hid_replay_cmd = "hid-replay"
hid_replay = hid_replay_path + '/' + hid_replay_cmd

monitor = pyudev.Monitor.from_netlink(context)
monitor.filter_by('input')

global currentRunningHidTest
currentRunningHidTest = None
nodes = {}

global_lock = threading.Lock()
global_condition = threading.Condition()
global_condition_op = False


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
			p = subprocess.Popen(shlex.split("evemu-record " + dev_path), stderr=subprocess.PIPE, stdout=tmp)

			# store it for later
			nodes[device.sys_name] = tmp, p, currentRunningHidTest
			currentRunningHidTest.nodes[device.sys_name] = tmp, p, currentRunningHidTest

			# notify the current hid test that one device has been added
			global_condition.acquire()
			global global_condition_op
			global_condition_op = True
			global_condition.notify()
			global_condition.release()

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
	running = True
	def __init__(self, path, delta_timestamp):
		self.path = path
		self.reset()
		self.hid_replay = None
		self.delta_timestamp = delta_timestamp

	def reset(self):
		self.nodes = {}
		self.nodes_ready = []
		self.cv = threading.Condition()
		self.outs = []
		self.expected = []

	def dump_outs(self):
		hid_name = os.path.splitext(os.path.basename(self.path))[0]
		outfiles = []
		for i in xrange(len(self.outs)):
			out = self.outs[i]
			out.seek(0)
			ev_name = hid_name + '_' + str(i) + ".ev"
			outfiles.append(ev_name)
			expected = open(ev_name, 'w')
			for l in out.readlines():
				expected.write(l)
		return outfiles

	def dump_diffs(self):
		hid_name = os.path.splitext(os.path.basename(self.path))[0]
		outfiles = []
		for i in xrange(len(self.outs)):
			ev_name = hid_name + '_res_' + str(i) + ".evd"
			outfiles.append(ev_name)
			compare_evemu.dump_diff(ev_name, self.outs[i])
		if not self.expected:
			return outfiles
		for i in xrange(len(self.expected)):
			ev_name = hid_name + '_exp_' + str(i) + ".evd"
			outfiles.append(ev_name)
			expect = open(self.expected[i], 'r')
			compare_evemu.dump_diff(ev_name, expect)
			expect.close()
		return outfiles

	def compare_result(self, str_result):
		return compare_evemu.compare_sets(self.expected, self.outs, str_result, self.delta_timestamp)

	def terminate(self):
		if self.hid_replay :
			self.hid_replay.terminate()

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

		# acquire the lock so that only this test will get the udev 'add' notifications
		global_lock.acquire()

		if not HIDTest.running:
			global_lock.release()
			return -1

		global currentRunningHidTest
		currentRunningHidTest = self

		print "launching test", self.path, "against", results
		self.hid_replay = subprocess.Popen(shlex.split(hid_replay + " -s 1 -1 " + self.path))

		# wait for one device to be added
		global_condition.acquire()
		global global_condition_op
		if not global_condition_op:
			global_condition.wait()
		global_condition_op = False
		global_condition.release()

		# wait 1 more second before releasing the lock, in case others
		# devices appear
		time.sleep(1)

		# now other tests can be notified by udev
		global_lock.release()

		if self.hid_replay.wait():
			return -1

		self.hid_replay = None

		# wait for all the captures to finish
		self.cv.acquire()
		while len(self.nodes.keys()) > 0:
			self.cv.wait()
		self.cv.release()

		# retrieve the different captures
		for sys_name, name, out in self.nodes_ready:
			self.outs.append(out)

		raw_length = 78
		basename = os.path.basename(self.path)
		name_length = len(basename) + 2
		prev = (raw_length - name_length) / 2
		after = raw_length - name_length - prev
		str_result = [("-"*prev) + " " + basename + " " + ("-"*after)]

		# compare them
		r, w = self.compare_result(str_result)

		if not r:
			# if there is a change, then dump the captures in the current directory
			str_result.append("test failed, dumping outputs in:")
			str_result.extend(self.dump_outs())
			str_result.extend(self.dump_diffs())
		elif w:
			# if there is a warning, still dump the captures in the current directory
			str_result.append("success but warning raised, dumping outputs in:")
			str_result.extend(self.dump_outs())
		else:
#			self.dump_outs()
			str_result.append("success")

		# close the captures so that the tmpfiles are destroyed
		for out in self.outs:
			out.close()

		global_lock.acquire()
		# append the result of the test to the list,
		# we only count the warning if the test passed
		tests.append((self.path, (r, w and r)))

		str_result.append("-" * raw_length)

		print '\n'.join(str_result)
		global_lock.release()

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
class HIDThread(threading.Thread):
	count = 1
	sema = None
	ok = True
	lock = threading.Lock()

	def __init__(self, file, delta_timestamp):
		threading.Thread.__init__(self)
		HIDThread.lock.acquire()
		if not HIDThread.sema:
			HIDThread.sema = threading.Semaphore(HIDThread.count)
		HIDThread.lock.release()
		self.daemon = True

		self.hid = HIDTest(file, delta_timestamp)

	def run(self):
		HIDThread.sema.acquire()
		if HIDThread.ok and self.hid.run():
			HIDThread.ok = False
		HIDThread.sema.release()

	def terminate(self):
		self.hid.terminate()


# disable stdout buffering
sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)

optlist, args = getopt.gnu_getopt(sys.argv[1:], 'hj:t:')

delta_timestamp = 0

for opt, arg in optlist:
	if opt == '-h':
		print \
""" -h	print the help message.
 -jN	Launch N threads in parallel. This reduce the global time of the tests,
	but corrupts the timestamps between frames.
 -tS	Print a warning if the timestamps between two frames is greater than S.
	Example: "-t0.01".
	If S is 0, then timestamps are ignored (default behavior)."""
		sys.exit(0)
	elif opt == '-t':
		delta_timestamp = float(arg)
	elif opt == '-j':
		HIDThread.count = int(arg)
		if HIDThread.count < 1:
			print "the number of threads can not be less than one. Disabling threading launches."
			HIDThread.count = 1

if not os.path.exists("/dev/uhid"):
	print "It is required to load the uhid kernel module."
	sys.exit(1)

rootdir = '.'
if len(args) > 0:
	rootdir = args[0]
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
	hid_files.sort()
	list_of_hid_files = hid_files
	if len(args) > 1:
		list_of_hid_files = args[1:]

	threads = []
	for file in list_of_hid_files:
		if HIDThread.count > 1:
			thread = HIDThread(file, delta_timestamp)
			threads.append(thread)
			thread.start()
		elif HIDTest(file, delta_timestamp).run():
			break
	while len(threads) > 0:
		try:
			# Join all threads using a timeout so it doesn't block
			t = threads.pop(0)
			t.join(1)
			if t.isAlive():
				threads.append(t)
		except KeyboardInterrupt:
			print "Ctrl-c received! Sending kill to threads..."
			HIDTest.running = False
			HIDThread.ok = False
			for t in threads:
				t.terminate()
finally:
	report_results(tests)
	xi2detach.terminate()

