#!/bin/env python
# -*- coding: utf-8 -*-
#
# Hid test suite / main program
#
# Copyright (c) 2012-2013 Benjamin Tissoires <benjamin.tissoires@gmail.com>
# Copyright (c) 2012-2013 Red Hat, Inc.
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
import getopt
import re
from hid_test import HIDTest, HIDTestAndCompare, HIDThread
from database import HIDTestDatabase

context = pyudev.Context()

def udev_event(action, device):
	if ":" in device.sys_name:
		HIDTest.hid_udev_event(action, device)
	elif 'event' in device.sys_name:
		HIDTest.event_udev_event(action, device)

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
	-kKVER	overwritte the current kernel version
	-tS	Print a warning if the timestamps between two frames is greater than S.
		Example: "-t0.01".
		If S is 0, then timestamps are ignored (default behavior).
	-E	"Evemu mode": Do not compare, just output the evemu outputs in
		the current directory.
	-f	"fast mode": if a device already has an expected output from the same
		kernel series, then skip the test."""

def start_xi2detach():
	# starts xi2detach
	xi2detach = subprocess.Popen(shlex.split(os.path.join(os.path.dirname(sys.argv[0]), 'xi2detach')), stderr= subprocess.PIPE, stdout= subprocess.PIPE)

	import time
	time.sleep(1)
	return xi2detach

def run_tests(list_of_hid_files, database, simple_evemu_mode, delta_timestamp):
	threads = []
	database.set_actual_hid_list(list_of_hid_files)
	# create udev notification system
	monitor = pyudev.Monitor.from_netlink(pyudev.Context())
	monitor.filter_by('input')
	monitor.filter_by('hid')
	observer = pyudev.MonitorObserver(monitor, udev_event)
	# start monitoring udev events
	observer.start()

	for file in list_of_hid_files:
		if database.skip_test(file):
			continue
		if not database.has_key(file):
			# TODO: failure
			continue
		if HIDThread.count > 1:
			thread = HIDThread(file, database, delta_timestamp, simple_evemu_mode)
			threads.append(thread)
			thread.start()
		else:
			if simple_evemu_mode:
				if HIDTest(file).run() < 0:
					break
			else:
				if HIDTestAndCompare(file, database, delta_timestamp).run() < 0:
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

def main():
	fast_mode = False
	simple_evemu_mode = False
	delta_timestamp = 0
	kernel_release = os.uname()[2]
	# disable stdout buffering
	sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)

	optlist, args = getopt.gnu_getopt(sys.argv[1:], 'hj:k:t:fdE')
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
		elif opt == '-k':
			kernel_release = arg
		elif opt == '-E':
			simple_evemu_mode = True
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

	database = HIDTestDatabase(rootdir, kernel_release, fast_mode)
	hid_files = database.get_hid_files()

	# if specific devices are given, treat them, otherwise, run the test on all .hid
	list_of_hid_files = hid_files
	if len(args) > 1:
		list_of_hid_files = args[1:]
	if len(list_of_hid_files) == 0:
		help(sys.argv)
		sys.exit(1)

	xi2detach = start_xi2detach()

	try:
		run_tests(list_of_hid_files, database, simple_evemu_mode, delta_timestamp)
	finally:
		if not simple_evemu_mode:
			database.report_results()
		xi2detach.terminate()

if __name__ == "__main__":
	main()
