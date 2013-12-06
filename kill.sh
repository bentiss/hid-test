#!/bin/sh

sudo kill $(ps -aef | grep python | grep testsuite.py | awk '{ print $2 ; }' )
