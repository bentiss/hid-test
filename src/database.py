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

import os
import sys
import re

def get_major_minor(string = os.uname()[2]):
	kernel_release_regexp = re.compile(r"(\d+)\.(\d+)[^\d]*")
	m = kernel_release_regexp.match(string)
	if not m:
		return 0
	major_r, minor_r = m.groups()
	major_r, minor_r = int(major_r), int(minor_r)
	return major_r << 16 | minor_r

class HIDTestDatabase(object):
	def __init__(self, rootdir, kernel_release, fast_mode = False):
		self.rootdir = rootdir
		self.total_tests_count = 0
		self.skipping_db = []
		self.skipped = []
		self.tests = []
		self.fast_mode = fast_mode
		self.kernel_release = get_major_minor(kernel_release)
		self.database = {}
		self.construct_db()

	def skip_test(self, hid_file):
		rname = os.path.splitext(os.path.basename(hid_file))[0]
		for skip_file in self.skipping_db:
			if rname in skip_file:
				if hid_file not in self.skipped:
					self.skipped.append(hid_file)
				return True
		return False

	def get_results_count(self):
		good = 0
		err = 0
		warn = 0
		skipped = len(self.skipped)
		for file, (r, w) in self.tests:
			if r: good += 1
			else: err += 1
			if w: warn += 1
		run_count = good + err + skipped
		str_result = "%d / %d tests run, %d / %d passed"%(run_count, self.total_tests_count, good, good + err)
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

	def report_results(self):
		passed_without_warns = [file for file, (r, w) in self.tests if r and not w]
		passed_with_warns = [file for file, (r, w) in self.tests if r and w]
		errors = [file for file, (r, w) in self.tests if not r]

		if len(self.skipped) > 0:
			print "tests skipped (SK):"
			for file in self.skipped:
				print "SK:", file

		if len(passed_without_warns) > 0:
			print "tests passed (OK):"
			for file in passed_without_warns:
				print "OK:", file

		if len(passed_with_warns) > 0:
			print "tests passed with warnings (WW):"
			for file in passed_with_warns:
				print "WW:", file

		if len(errors) > 0:
			print "tests failed (EE):"
			for file in errors:
				print "EE:", file

		print self.get_results_count()

	def construct_db(self):
		hid_files = []
		ev_files = []
		skip_files = []
		ev_dumps = {}
		# first, retrieve all the .hid, .ev and .skip files in rootdir (first arg if given, otherwise, cwd)
		for root, dirs, files in os.walk(self.rootdir):
			for f in files:
				path = os.path.join(root, f)
				if f.endswith(".hid"):
					hid_files.append(path)
				elif f.endswith(".ev"):
					ev_files.append(path)
				elif f.endswith(".skip"):
					skip_files.append(path)

		# now that we have all the data, organize them:

		# - the skipped files are the one matching the kernel:
		for skip_file in skip_files:
			kernel_skip = os.path.basename(os.path.dirname(skip_file))
			rkernel_release = get_major_minor(kernel_skip)
			if rkernel_release == self.kernel_release:
				self.skipping_db.append(skip_file)

		# - organize the evemu traces:
		#   * if a dump is from an earlier kernel than the tested one -> skip it
		#   * keep only the latest dump (from the more recent allowed kernel)
		for ev_file in ev_files:
			basename = os.path.basename(ev_file)
			ev_kernel_release = get_major_minor(os.path.basename(os.path.dirname(ev_file)))
			if not ev_kernel_release:
				ev_kernel_release = self.kernel_release - 1
			ev_dump = {
				"path": ev_file,
				"kernel_release": ev_kernel_release,
			}
			# discard dumps from earlier kernels
			if ev_kernel_release > self.kernel_release:
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
			self.database[hid_file] = [ ev_dumps[ev_file] for ev_file in results]

		# - fast mode: skip the matching kernels evemu
		if self.fast_mode:
			for hid_file in hid_files:
				results = self.database[hid_file]
				skip = len(results) > 0
				for r in results:
					if r["kernel_release"] != kernel_release:
						skip = False
				if skip:
					self.skipping_db.append(hid_file)

	def append_hid_file(self, filename):
		if not self.has_key(filename):
			self.database[filename] = []

	def get_hid_files(self):
		keys = self.database.keys()
		keys.sort()
		return keys

	def get_skipped_hid_files(self):
		self.skipped.sort()
		return self.skipped

	def incr_total_tests_count(self, n):
		self.total_tests_count += n

	def __getitem__(self, item):
		return self.database[item]

	def has_key(self, item):
		return self.database.has_key(item)

	def get_expected(self, file):
		return [ ev_file["path"] for ev_file in self.database[file]]

	def append_result(self, path, result, warning):
		self.tests.append((path, (result, warning)))

def main():
	rootdir = '.'
	if len(sys.argv) > 1:
		rootdir = sys.argv[1]

	kernel_release = os.uname()[2]

	database = HIDTestDatabase(rootdir, kernel_release)

	print "tested:"
	print database.get_hid_files()
	print "skipped files:"
	print database.get_skipped_hid_files()
	database.report_results()

if __name__ == "__main__":
	main()
