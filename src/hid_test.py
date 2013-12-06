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
import os
import subprocess
import shlex
import threading
import compare_evemu

hid_replay_path = "/usr/bin"
hid_replay_cmd = "hid-replay"
hid_replay = hid_replay_path + '/' + hid_replay_cmd


global_lock = threading.Lock()

raw_length = 78

class HIDBase(object):
	def dump_outs(self):
		return []
	def close(self):
		pass

class HIDTest(HIDBase):
	running = True

	instances = []
	current = None
	uhid_mappings = {}
	event_mappings = {}

	def __init__(self, path):
		self.path = path
		self.condition = threading.Condition()

		self.reset()

	def reset(self):
		self.hid_replay = None
		self.nodes = {}
		self.nodes_ready = []
		self.cv = threading.Condition()
		self.outs = []
		self.condition_op = False
		self.hid_name = None

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

	def terminate(self):
		if self.hid_replay :
			self.hid_replay.terminate()

	@classmethod
	def hid_udev_event(cls, action, device):
		for instance in cls.instances:
			instance.__hid_udev_event(action, device)

	@classmethod
	def event_udev_event(cls, action, device):
		# we maintain an association event node / uhid node
		if not cls.event_mappings.has_key(device.sys_path):
			cls.event_mappings[device.sys_path] = cls.current

		cls.event_mappings[device.sys_path].__event_udev_event(action, device)

		if action == "remove":
			del(cls.event_mappings[device.sys_path])

	def __hid_udev_event(self, action, device):
		if not action == "add":
			return

		if self.hid_name:
			# not our business
			return

		# the uhid node has been created
		self.hid_name = device.sys_name

		HIDTest.uhid_mappings[self.hid_name] = self

	def __event_udev_event(self, action, device):
#		print action, device, device.sys_name
		if action == 'add':
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
			self.nodes[device.sys_name] = tmp, p

			# notify the current hid test that one device has been added
			self.condition.acquire()
			self.condition_op = True
			self.condition.notify()
			self.condition.release()

		elif action == 'remove':
			# get corresponding capturing process in background
			try:
				result, p = self.nodes[device.sys_name]
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
			self.cv.acquire()
			self.nodes_ready.append((device.sys_name, name, result))
			del self.nodes[device.sys_name]
			self.cv.notify()
			self.cv.release()

	def print_launch(self):
		print "launching test", self.path

	def run_test(self):
		self.reset()
		# acquire the lock so that only this test will get the udev 'add' notifications
		global_lock.acquire()

		if not HIDTest.running:
			global_lock.release()
			return -1

		HIDTest.instances.append(self)
		# we accept adding new event nodes
		HIDTest.current = self

		self.print_launch()
		self.hid_replay = subprocess.Popen(shlex.split(hid_replay + " -s 1 -1 " + self.path))

		# wait for one input node to be created
		self.condition.acquire()
		if not self.condition_op:
			self.condition.wait()
		self.condition_op = False
		self.condition.release()

		# wait 1 more second before releasing the lock, in case others
		# devices appear
		time.sleep(1)

		# now other tests can be launched
		global_lock.release()

		if self.hid_replay.wait():
			return -1

		self.hid_replay = None

		# wait for all the captures to finish
		self.cv.acquire()
		while len(self.nodes.keys()) > 0:
			self.cv.wait()
		self.cv.release()

		global_lock.acquire()
		HIDTest.instances.remove(self)
		global_lock.release()

		# retrieve the different captures
		for sys_name, name, out in self.nodes_ready:
			self.outs.append(out)

	def close(self):
		for out in self.outs:
			out.close()
		self.outs = []

	def run(self):
		self.run_test()

		self.dump_outs()

		# close the captures so that the tmpfiles are destroyed
		self.close()
		return 0

class Compare(object):
	def __init__(self, path, expected, results, result_database, delta_timestamp, hid_base):
		self.delta_timestamp = delta_timestamp
		self.result_database = result_database
		self.expected = expected
		self.outs = results
		self.path = path
		self.hid_base = hid_base

	def dump_outs(self):
		return self.hid_base.dump_outs()

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

	def append_result(self, str_result, result, warning):
		global_lock.acquire()
		# append the result of the test to the list,
		self.result_database.append_result(self.path, result, warning)

		str_result.append(self.result_database.get_results_count())
		str_result.append("-" * raw_length)

		print '\n'.join(str_result)
		global_lock.release()

	def run(self):
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
		self.hid_base.close()

		# append the result of the test to the list,
		# we only count the warning if the test passed
		self.append_result(str_result, r, w and r)

		return 0

class HIDTestAndCompare(HIDTest):
	def __init__(self, path, result_database, delta_timestamp):
		super(HIDTestAndCompare, self).__init__(path)
		self.delta_timestamp = delta_timestamp
		self.result_database = result_database
		self.expected = result_database.get_expected(path)
		self.compare = None

	def print_launch(self):
		print "launching test", self.path, "against", self.expected

	def run(self):
		self.run_test()
		return Compare(self.path, self.expected, self.outs, self.result_database, self.delta_timestamp, self).run()

class HIDThread(threading.Thread):
	count = 1
	sema = None
	ok = True
	lock = threading.Lock()

	def __init__(self, file, result_database, delta_timestamp, simple_evemu_mode):
		threading.Thread.__init__(self)
		HIDThread.lock.acquire()
		if not HIDThread.sema:
			HIDThread.sema = threading.Semaphore(HIDThread.count)
		HIDThread.lock.release()
		self.daemon = True

		if simple_evemu_mode:
			self.hid = HIDTest(file)
		else:
			self.hid = HIDTestAndCompare(file, result_database, delta_timestamp)

	def run(self):
		HIDThread.sema.acquire()
		if HIDThread.ok and self.hid.run() < 0:
			HIDThread.ok = False
		HIDThread.sema.release()

	def terminate(self):
		self.hid.terminate()
