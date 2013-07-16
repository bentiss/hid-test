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
import re

context = pyudev.Context()

hid_replay_path = "/usr/bin"
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

raw_length = 78

global total_tests_count
total_tests_count = 0

global skipped
skipped = []

def log_event(action, device):
	if 'event' in device.sys_name:
#		print action, device, device.sys_name
		if action == 'add':
			if not currentRunningHidTest:
				return

			tmp = os.tmpfile()

			# get node attributes
			dev_path = "/dev/input/" + device.sys_name.encode('ascii')
			if subprocess.call(shlex.split("evemu-describe " + dev_path), stdout=tmp):
				# the device has already been unplugged
				return

			prev_pos = tmp.tell()
			tmp.seek(0)
			first_line = tmp.readline()
			if first_line.startswith("# EVEMU"):
				# FIXME: check evemu > 1.1, but as there is no release with 1.0...
				# earlier evemu drop the description in evemu-record too
				tmp.close()
				tmp = os.tmpfile()
			else:
				tmp.seek(prev_pos)

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
			try:
				result, p, hid = nodes[device.sys_name]
			except KeyError:
				# not a registered device => we don't care
				return

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

def get_major_minor(string = os.uname()[2]):
	kernel_release_regexp = re.compile(r"(\d+)\.(\d+)[^\d]*")
	m = kernel_release_regexp.match(string)
	if not m:
		return 0
	major_r, minor_r = m.groups()
	major_r, minor_r = int(major_r), int(minor_r)
	return major_r << 16 | minor_r


class HIDTest(object):
	running = True
	def __init__(self, path, delta_timestamp, expected):
		self.path = path
		self.reset()
		self.hid_replay = None
		self.delta_timestamp = delta_timestamp
		self.expected = expected

	def reset(self):
		self.nodes = {}
		self.nodes_ready = []
		self.cv = threading.Condition()
		self.outs = []

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

	def append_result(self, str_result, result, warning):
		global_lock.acquire()
		# append the result of the test to the list,
		tests.append((self.path, (result, warning)))

		str_result.append(get_results_count(tests, None))
		str_result.append("-" * raw_length)

		print '\n'.join(str_result)
		global_lock.release()

	def run(self):
		self.reset()
		# acquire the lock so that only this test will get the udev 'add' notifications
		global_lock.acquire()

		if not HIDTest.running:
			global_lock.release()
			return -1

		global currentRunningHidTest
		currentRunningHidTest = self

		print "launching test", self.path, "against", self.expected
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

		# append the result of the test to the list,
		# we only count the warning if the test passed
		self.append_result(str_result, r, w and r)

		return 0

def get_results_count(tests, skipped_hid_files):
	global total_tests_count
	good = 0
	err = 0
	warn = 0
	skipped = 0
	if skipped_hid_files:
		skipped = len(skipped_hid_files)
	for file, (r, w) in tests:
		if r: good += 1
		else: err += 1
		if w: warn += 1
	run_count = good + err + skipped
	str_result = "%d / %d tests run, %d / %d passed"%(run_count, total_tests_count, good, good + err)
	if err or warn or skipped:
		n = 0
		for c in (err, warn, skipped):
			if c: n += 1
		splits = ('', ' and ', ', ')
		s = ""
		if warn:
			s += "%d warnings"%(warn)
			n -= 1
			if n:
				s += splits[n]
		if err:
			s += "%d errors"%(err)
			n -= 1
			if n:
				s += splits[n]
		if skipped:
			s += "%d skipped"%(skipped)
		str_result += " (%s)"%(s)
	return str_result

def report_results(tests):
	passed_without_warns = [file for file, (r, w) in tests if r and not w]
	passed_with_warns = [file for file, (r, w) in tests if r and w]
	errors = [file for file, (r, w) in tests if not r]

	if len(skipped) > 0:
		print "tests skipped ( - ):"
		for file in skipped:
			print " - ", file, "-> skipped"

	if len(passed_without_warns) > 0:
		print "tests passed (   ):"
		for file in passed_without_warns:
			print "   ", file, "-> OK"

	if len(passed_with_warns) > 0:
		print "tests passed with warnings (WW):"
		for file in passed_with_warns:
			print "WW:", file, "-> OK"

	if len(errors) > 0:
		print "tests failed (EE):"
		for file in errors:
			print "EE:", file, "-> ERROR"

	print get_results_count(tests, skipped)

class HIDThread(threading.Thread):
	count = 1
	sema = None
	ok = True
	lock = threading.Lock()

	def __init__(self, file, delta_timestamp, expected):
		threading.Thread.__init__(self)
		HIDThread.lock.acquire()
		if not HIDThread.sema:
			HIDThread.sema = threading.Semaphore(HIDThread.count)
		HIDThread.lock.release()
		self.daemon = True

		self.hid = HIDTest(file, delta_timestamp, expected)

	def run(self):
		HIDThread.sema.acquire()
		if HIDThread.ok and self.hid.run() < 0:
			HIDThread.ok = False
		HIDThread.sema.release()

	def terminate(self):
		self.hid.terminate()

def help(argv):
	print argv[0], "[OPTION] [DATABASE [HID_DEVICES]]\n"\
"""Where:
 * DATABASE is a path containing .hid files and their corresponding .ev (evemu traces).
	If omitted, using '.' as a database.
 * HID_DEVICES is one or more .hid files.
 * OPTION is:
	-h	print the help message.
	-jN	Launch N threads in parallel. This reduce the global time of the tests,
		but corrupts the timestamps between frames.
	-tS	Print a warning if the timestamps between two frames is greater than S.
		Example: "-t0.01".
		If S is 0, then timestamps are ignored (default behavior).
	-f	"fast mode": if a device already has an expected output from the same
		kernel series, then skip the test."""

delta_timestamp = 0

def start_xi2detach():
	# starts xi2detach
	xi2detach = subprocess.Popen(shlex.split(os.path.join(os.path.dirname(sys.argv[0]), 'xi2detach')), stderr= subprocess.PIPE, stdout= subprocess.PIPE)

	import time
	time.sleep(1)
	return xi2detach

def skip_test(hid_file, skipping_db):
	rname = os.path.splitext(os.path.basename(hid_file))[0]
	for skip_file in skipping_db:
		if rname in skip_file:
			return True
	return False

def construct_db(rootdir, fast_mode):
	hid_files = []
	skipping_hid_files = []
	ev_files = []
	skip_files = []
	database = {}
	ev_dumps = {}
	# first, retrieve all the .hid, .ev and .skip files in rootdir (first arg if given, otherwise, cwd)
	for root, dirs, files in os.walk(rootdir):
		for f in files:
			path = os.path.join(root, f)
			if f.endswith(".hid"):
				hid_files.append(path)
			elif f.endswith(".ev"):
				ev_files.append(path)
			elif f.endswith(".skip"):
				skip_files.append(path)

	# now that we have all the data, organize them:
	kernel_release = get_major_minor()

	# - the skipped files are the one matching the kernel:
	skipping_hid_files = []
	for skip_file in skip_files:
		kernel_skip = os.path.basename(os.path.dirname(skip_file))
		rkernel_release = get_major_minor(kernel_skip)
		if rkernel_release == kernel_release:
			skipping_hid_files.append(skip_file)

	# - organize the evemu traces:
	#   * if a dump is from an earlier kernel than the tested one -> skip it
	#   * keep only the latest dump (from the more recent allowed kernel)
	for ev_file in ev_files:
		basename = os.path.basename(ev_file)
		ev_kernel_release = get_major_minor(os.path.basename(os.path.dirname(ev_file)))
		if not ev_kernel_release:
			ev_kernel_release = kernel_release - 1
		ev_dump = {
			"path": ev_file,
			"kernel_release": ev_kernel_release,
		}
		# discard dumps from earlier kernels
		if ev_kernel_release > kernel_release:
			continue
		# keep the latest evemu dump
		if not ev_dumps.has_key(basename) or \
		   ev_dumps[basename]["kernel_release"] < ev_kernel_release:
			ev_dumps[basename] = ev_dump

	# - now retrieve the expected evemu traces per hid test
	for hid_file in hid_files:
		results = []
		basename = os.path.splitext(os.path.basename(hid_file))[0]
		# get all matching evemu dumps
		for ev_file in ev_dumps.keys():
			if basename in ev_file:
				results.append(ev_file)
		results.sort()
		database[hid_file] = [ ev_dumps[ev_file] for ev_file in results]

	# - fast mode: skip the matching kernels evemu
	if fast_mode:
		for hid_file in hid_files:
			results = database[hid_file]
			skip = len(results) > 0
			for r in results:
				if r["kernel_release"] != kernel_release:
					skip = False
			if skip:
				skipping_hid_files.append(hid_file)

	return database, skipping_hid_files

def run_tests(list_of_hid_files, database, skipping_db):
	global total_tests_count, skipped
	threads = []
	total_tests_count = len(list_of_hid_files)
	for file in list_of_hid_files:
		if skip_test(file, skipping_db):
			skipped.append(file)
			continue
		if not database.has_key(file):
			# TODO: failure
			continue
		expected = [ ev_file["path"] for ev_file in database[file]]
		if HIDThread.count > 1:
			thread = HIDThread(file, delta_timestamp, expected)
			threads.append(thread)
			thread.start()
		elif HIDTest(file, delta_timestamp, expected).run() < 0:
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
	return skipped

def main():
	fast_mode = False
	# disable stdout buffering
	sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)

	optlist, args = getopt.gnu_getopt(sys.argv[1:], 'hj:t:fd')
	for opt, arg in optlist:
		if opt == '-h':
			help(sys.argv)
			sys.exit(0)
		elif opt == '-t':
			delta_timestamp = float(arg)
		elif opt == '-j':
			HIDThread.count = int(arg)
			if HIDThread.count < 1:
				print "the number of threads can not be less than one. Disabling threading launches."
				HIDThread.count = 1
		elif opt == '-f':
			fast_mode = True
		elif opt == '-m':
			pass

	if not os.path.exists("/dev/uhid"):
		print "It is required to load the uhid kernel module."
		sys.exit(1)

	rootdir = '.'
	if len(args) > 0:
		rootdir = args[0]

	database, skipping_db = construct_db(rootdir, fast_mode)
	hid_files = database.keys()
	hid_files.sort()

	xi2detach = start_xi2detach()

	# if specific devices are given, treat them, otherwise, run the test on all .hid
	list_of_hid_files = hid_files
	if len(args) > 1:
		list_of_hid_files = args[1:]

	try:
		run_tests(list_of_hid_files, database, skipping_db)
	finally:
		report_results(tests)
		xi2detach.terminate()

if __name__ == "__main__":
	main()
