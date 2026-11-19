#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The first start of a ready-made machine sets up the system it runs on.
# localecfg, rayesetupchoices and the users job read rootMountPoint, which
# the mount job sets in a real install; here it is /.

import libcalamares


def pretty_name():
    return "Getting ready"


def run():
    libcalamares.globalstorage.insert("rootMountPoint", "/")
    libcalamares.globalstorage.insert("firmwareType", "efi")
    return None
