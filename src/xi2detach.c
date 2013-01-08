/*
 * Hid test suite / xi2 dettach slave
 *
 * Copyright (c) 2012 Benjamin Tissoires <benjamin.tissoires@gmail.com>
 * Copyright (c) 2012 Red Hat, Inc.
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

#if HAVE_CONFIG_H
#include <config.h>
#endif

/* X11 */
#include <X11/Xlib.h>
#include <X11/extensions/XInput.h>
#include <X11/extensions/XInput2.h>

/* Unix */
#include <getopt.h>

/* C */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <errno.h>

#define _GNU_SOURCE
#include <errno.h>
extern char *program_invocation_name;
extern char *program_invocation_short_name;

static int xi_opcode;

/**
 * Print usage information.
 */
static int usage(void)
{
	printf("USAGE:\n");
	printf("   %s [OPTION]\n", program_invocation_short_name);

	printf("\n");
	printf("where OPTION is either:\n");
	printf("   -h or --help: print this message\n");

	return EXIT_FAILURE;
}

static const struct option long_options[] = {
	{ "help", no_argument, NULL, 'h' },
	{ 0, },
};

static int
xinput_version(Display	*display)
{
	XExtensionVersion	*version;
	static int vers = -1;

	if (vers != -1)
		return vers;

	version = XGetExtensionVersion(display, INAME);

	if (version && (version != (XExtensionVersion*) NoSuchExtension)) {
		vers = version->major_version;
		XFree(version);
	}

	/* Announce our supported version so the server treats us correctly. */
	if (vers >= XI_2_Major) {
		int maj = 2, min = 3;

		XIQueryVersion(display, &maj, &min);
	}

	return vers;
}

static int init(Display *dpy)
{
	XIEventMask evmask;
	unsigned char mask[2] = { 0, 0 };
	int event, error;

	if (dpy == NULL) {
		fprintf(stderr, "Unable to connect to X server\n");
		return -1;
	}

	if (!XQueryExtension(dpy, "XInputExtension", &xi_opcode, &event, &error)) {
		fprintf(stderr, "X Input extension not available.\n");
		return -1;
	}

	if (!xinput_version(dpy)) {
		fprintf(stderr, "extension not available.\n");
		return -1;
	}

	XISetMask(mask, XI_DeviceChanged);
	XISetMask(mask, XI_HierarchyChanged);

	evmask.deviceid = XIAllDevices;
	evmask.mask_len = sizeof(mask);
	evmask.mask = mask;

	XISelectEvents(dpy, DefaultRootWindow(dpy), &evmask, 1);
	XSync(dpy, False);
	return 0;
}

static void detachSlave(Display *dpy, int deviceID) {
	XIDetachSlaveInfo c;
	int ret;

	c.type = XIDetachSlave;
	c.deviceid = deviceID;

	ret = XIChangeHierarchy(dpy, (XIAnyHierarchyChangeInfo*)&c, 1);
	XSync(dpy, 0);
}

static void process_hierarchy_event(Display *dpy, XIHierarchyEvent *ev){
	int i;

	for (i = 0; i < ev->num_info; i++) {
		char *action = NULL;
		int id = ev->info[i].deviceid;

		if (ev->info[i].flags & XIMasterAdded)
			action = " master added";
		if (ev->info[i].flags & XIMasterRemoved)
			action = " master removed";
		if (ev->info[i].flags & XISlaveAdded)
			action = " slave added";
		if (ev->info[i].flags & XISlaveRemoved)
			action = " slave removed";
		if (ev->info[i].flags & XISlaveAttached)
			action = " slave attached";
		if (ev->info[i].flags & XISlaveDetached)
			action = " slave detached";

		if (action) {
			if (!(ev->info[i].flags & (XIMasterRemoved | XISlaveRemoved))) {
				int n;
				XIDeviceInfo *infos = XIQueryDevice(dpy, id, &n);
				fprintf(stderr, "%s (%d) %s.\n", infos->name, infos->deviceid, action);
				XIFreeDeviceInfo(infos);
			} else
				fprintf(stderr, "%d %s.\n", id, action);
		}

		if (ev->info[i].flags & XISlaveAdded)
			detachSlave(dpy, id);
	}
}

static void event (Display *dpy)
{
	XEvent ev;

	XNextEvent(dpy, &ev);
	if (ev.xcookie.type == GenericEvent && ev.xcookie.extension == xi_opcode &&
	    XGetEventData(dpy, &ev.xcookie)) {
		//printf("Received event %d\n",ev.xcookie.evtype);
		switch(ev.xcookie.evtype) {
		case XI_HierarchyChanged:
			process_hierarchy_event(dpy, (XIHierarchyEvent *)ev.xcookie.data);
			break;
		default:
			fprintf(stderr, "other event.\n");
		}
		XFreeEventData(dpy, (XGenericEventCookie*)&ev);
	}
}


int main(int argc, char **argv)
{
	Display* dpy = XOpenDisplay(NULL);
	int ret;

	while (1) {
		int option_index = 0;
		int c = getopt_long(argc, argv, "h", long_options, &option_index);
		if (c == -1)
			break;
		switch (c) {
		default:
			return usage();
		}
	}

	ret = init(dpy);
	if (ret)
		return ret;

	while (1) {
		event(dpy);
	}

	return 0;
}
