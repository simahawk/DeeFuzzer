#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2006-2011 Guillaume Pellerin

# <yomguy@parisson.com>

# This software is a computer program whose purpose is to stream audio
# and video data through icecast2 servers.

# This software is governed by the CeCILL license under French law and
# abiding by the rules of distribution of free software. You can use,
# modify and/ or redistribute the software under the terms of the CeCILL
# license as circulated by CEA, CNRS and INRIA at the following URL
# "http://www.cecill.info".

# As a counterpart to the access to the source code and  rights to copy,
# modify and redistribute granted by the license, users are provided only
# with a limited warranty and the software's author, the holder of the
# economic rights, and the successive licensors have only limited
# liability.

# In this respect, the user's attention is drawn to the risks associated
# with loading, using,  modifying and/or developing or reproducing the
# software by the user in light of its specific status of free software,
# that may mean that it is complicated to manipulate, and that also
# therefore means that it is reserved for developers and  experienced
# professionals having in-depth computer knowledge. Users are therefore
# encouraged to load and test the software's suitability as regards their
# requirements in conditions enabling the security of their systems and/or
# data to be ensured and, more generally, to use and operate it in the
# same conditions as regards security.

# The fact that you are presently reading this means that you have had
# knowledge of the CeCILL license and that you accept its terms.

# Author: Guillaume Pellerin <yomguy@parisson.com>

import os
import shout
import Queue
import time
import mimetypes
import hashlib
from threading import Thread
from deefuzzer.station import (
    Station,
)
from deefuzzer.tools.utils import (
    get_conf_dict,
    folder_contains_music,
    replace_all,
    merge_defaults,
)
from deefuzzer.tools.logger import QueueLogger

mimetypes.add_type('application/x-yaml', '.yaml')


class DeeFuzzer(Thread):
    """a DeeFuzzer diffuser"""

    logger = None
    m3u = None
    rss = None
    stations_available = {}
    stations_enabled = {}
    watch_folder = {}
    log_queue = Queue.Queue()
    main_loop = False
    ignore_errors = False
    max_retry = 0

    def __init__(self, conf_file):
        Thread.__init__(self)
        self.conf_file = conf_file
        self.conf = get_conf_dict(self.conf_file)

        if 'deefuzzer' not in self.conf:
            return

        self.conf = self.conf['deefuzzer']

        # Get the log setting first (if possible)
        log_file = str(self.conf.pop('log', ''))
        self.log_dir = os.sep.join(log_file.split(os.sep)[:-1])
        if not os.path.exists(self.log_dir) and self.log_dir:
            os.makedirs(self.log_dir)
        self.logger = QueueLogger(log_file, self.log_queue)
        self.logger.start()
        self._load_settings()
        # Set the deefuzzer logger
        self._info('Starting DeeFuzzer')
        self._info('Using libshout version %s' % shout.version())
        self._info('Number of stations: %d' % len(self.stations_available))

    def _load_settings(self):
        self.m3u = str(self.conf['m3u'])
        self.ignore_errors = bool(self.conf['ignore_errors'])
        self.max_retry = int(self.conf['max_retry'])

        # get stations
        stations = self.conf.get('station', [])
        # Load station definitions from the main config file
        if not isinstance(stations, list):
            stations = [stations, ]
        for item in stations:
            self.add_station(item)

        if 'stationconfig' in self.conf:
            # Load additional station definitions from the requested folder
            self.load_stations_fromconfig(self.conf['stationconfig'])

        if 'stationfolder' in self.conf:
            # Create stations automagically from a folder structure
            if isinstance(self.conf['stationfolder'], dict):
                self.watch_folder = self.conf['stationfolder']

        skip_keys = (
            # TODO: would be better to have explicit remaining keys
            'm3u', 'ignore_errors', 'max_retry',
            'stationconfig', 'stationfolder'
        )
        for k, v in self.conf.iteritems():
            if k not in skip_keys:
                setattr(self, k, v)

    def _log(self, level, msg):
        print level, msg
        try:
            obj = {'msg': 'Core: ' + str(msg), 'level': level}
            self.log_queue.put(obj)
        except:
            pass

    def _info(self, msg):
        self._log('info', msg)

    def _err(self, msg):
        self._log('err', msg)

    def _write_m3u(self, m3u):
        m3u.write('#EXTM3U\n')
        for station in self.stations_available.itervalues():
            m3u.write('#EXTINF:{},{}\n'.format('-1', station['info']['name']))
            channel_url = u'http://{}:{}/{}\n'.format(
                station['server']['host'],
                station['server']['port'],
                station['server']['mountpoint'])
            m3u.write(channel_url)

    def set_m3u_playlist(self):
        m3u_dir = os.sep.join(self.m3u.split(os.sep)[:-1])
        if not os.path.exists(m3u_dir) and m3u_dir:
            os.makedirs(m3u_dir)
        with open(self.m3u, 'w') as m3u:
            self._write_m3u(m3u)
        self._info('Writing M3U file to : ' + self.m3u)

    def _station_creates_fromfolder(self):
        """Scan a folder for subfolders containing media
        and make stations from them all."""

        options = self.watch_folder
        if 'folder' not in options:
            # We have no folder specified.  Bail.
            return

        if self.main_loop:
            if 'livecreation' not in options:
                # We have no folder specified.  Bail.
                return

            if int(options['livecreation']) == 0:
                # Livecreation not specified.  Bail.
                return

        folder = str(options['folder'])
        if not os.path.isdir(folder):
            # The specified path is not a folder.  Bail.
            return

        files = os.listdir(folder)
        for file in files:
            filepath = os.path.join(folder, file)
            if os.path.isdir(filepath):
                if folder_contains_music(filepath):
                    self._station_create(filepath, options)

    def _station_exists(self, name):
        return name in self.stations_available
        # try:
        #     for s in self.stations_available:
        #         if 'info' not in s:
        #             continue
        #         if 'short_name' not in s['info']:
        #             continue
        #         if s['info']['short_name'] == name:
        #             return True
        #     return False
        # except:
        #     pass
        # return True

    def _station_create(self, folder, options):
        """Create a station definition for a folder given the options."""

        path, name = os.path.split(folder)
        if self._station_exists(name):
            return
        self._info('Creating station for folder ' + folder)

        station = {
            'station_name': name,
            'path': folder,
        }
        self._station_apply_defaults(station)

        def skip_key(key):
            return 'folder' in key or key in ('path', 'control')

        for key in station.iterkeys():
            if not skip_key(key):
                station[key] = replace_all(station[key], station)

        if 'media' not in station:
            station['media'] = {}

        station['media']['source'] = folder
        self.add_station(station, name)

    def _station_apply_defaults(self, station):
        # Apply station defaults if they exist
        if 'stationdefaults' in self.conf:
            if isinstance(self.conf['stationdefaults'], dict):
                station.update(merge_defaults(
                    station,
                    self.conf['stationdefaults']
                ))

    def load_stations_fromconfig(self, folder):
        """Load one or more configuration files looking for stations."""

        if isinstance(folder, dict) or isinstance(folder, list):
            # We were given a list or dictionary.
            # Loop though it and load em all
            for f in folder:
                self.load_station_configs(f)
            return

        if os.path.isfile(folder):
            # We have a file specified.  Load just that file.
            self.load_station_config(folder)
            return

        if not os.path.isdir(folder):
            # Whatever we have, it's not either a file or folder.  Bail.
            return

        self._info('Loading station config files in ' + folder)
        files = os.listdir(folder)
        for file in files:
            filepath = os.path.join(folder, file)
            if os.path.isfile(filepath):
                self.load_station_config(filepath)

    # TODO
    def load_station_config(self, file):
        """Load station configuration(s) from a config file."""

        self._info('Loading station config file ' + file)
        stationdef = get_conf_dict(file)
        if isinstance(stationdef, dict):
            if 'station' in stationdef:
                if isinstance(stationdef['station'], dict):
                    self.add_station(stationdef['station'], name)
                elif isinstance(stationdef['station'], list):
                    for s in stationdef['station']:
                        self.add_station(s)

    def add_station(self, this_station, name):
        """Adds a station configuration to the list of stations."""
        if name in self.stations_available:
            raise ValueError("At least 2 stations w/ same name ``%s`" % name)
        self.stations_available[name] = this_station

    def run(self):
        q = Queue.Queue(1)
        stations_count = 0
        p = Producer(q)
        p.start()
        # Keep the Stations running
        while True:
            self._station_creates_fromfolder()
            available_count = len(self.stations_available)
            if available_count > stations_count:
                self._info('Loading new stations')

            for i, (name, station) in enumerate(
                    self.stations_available.iteritems()):
                station.setdefault('retries', 0)
                try:
                    status = self._station_check_status(station, name)
                    if status is True:
                        # already existing
                        continue

                    self._station_prepare(station, name)

                    new_station = Station(station, q, self.log_queue, self.m3u)
                    if new_station.valid:
                        station['station_instance'] = new_station
                        station['station_instance'].start()
                        self.stations_enabled[name] = new_station
                        self._info('Started station ' + name)
                    else:
                        self._err('Error validating station ' + name)
                except Exception as err:
                    print 'ERR', err
                    raise
                    self._err('Error initializing station ' + name)
                    if not self.ignore_errors:
                        raise
                    continue

                if self.m3u:
                    self.set_m3u_playlist()

            stations_count = available_count
            self.main_loop = True

            time.sleep(5)
            # end main loop

    def _station_maxretry_over(self, station):
        return self.max_retry >= 0 and station['retries'] <= self.max_retry

    def _station_check_status(self, station, name):
        try:
            if 'station_instance' in station:
                # Check for station running here
                if station['station_instance'].isAlive():
                    # Station exists and is alive.  Don't recreate.
                    station['retries'] = 0
                    return True

                if self._station_maxretry_over(station):
                    # Station passed max retries count: will not be reloaded
                    if 'station_stop_logged' not in station:
                        msg = (
                            'Station {} is stopped and will not be restarted.'
                        ).format(name)
                        self._err(msg)
                        station['station_stop_logged'] = True
                    return True

                station['retries'] += 1
                trynum = str(station['retries'])
                msg = 'Restarting station {} (try {})'.format(name, trynum)
                self._info(msg)
        except Exception as e:
            self._err('Error checking status for ' + name)
            self._err(str(e))
            if not self.ignore_errors:
                raise

    def _station_autoname(self, station):
        name = ''
        if 'info' in station and 'short_name' in station['info']:
            prefix = name = station['info']['short_name']
            y = 1
            while name in self.stations_enabled.keys():
                y += 1
                name = prefix + " " + str(y)
        return name

    def _station_prepare(self, station, name=''):
        if not name:
            name = self._station_autoname(station)
        namehash = hashlib.md5(name).hexdigest()
        station['station_statusfile'] = os.sep.join([self.log_dir, namehash])


class Producer(Thread):
    """a DeeFuzzer Producer master thread.  Used for locking/blocking"""

    def __init__(self, q):
        Thread.__init__(self)
        self.q = q

    def run(self):
        while True:
            try:
                self.q.put(True, True)
            except:
                pass
