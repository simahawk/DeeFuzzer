#!/usr/bin/env python
# -*- coding: utf-8 -*-

import liblo
import sys

# send all messages to port 1234 on the local machine
try:
    target = liblo.Address(sys.argv[1])
except liblo.AddressError, err:
    sys.exit(err)

# send message "/foo/message1" with int, float and string arguments
liblo.send(target, "/media/next", 1)
