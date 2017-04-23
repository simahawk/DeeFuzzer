#!/usr/bin/env python
# -*- coding: utf-8 -*-

import liblo
import sys

# send all messages to port sys.argv[1] on the local machine
try:
    target = liblo.Address(sys.argv[1])
except liblo.AddressError, err:
    print str(err)
    sys.exit()

# send message "/foo/message1" with int, float and string arguments
liblo.send(target, "/record", 0)
