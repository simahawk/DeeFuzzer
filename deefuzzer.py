#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2006-2009 Guillaume Pellerin

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
import sys
import time
import datetime
import string
import random
import Queue
import collections
import shout
import subprocess
import platform
import urllib
from threading import Thread
from tools import *

version = '0.3.6'
year = datetime.datetime.now().strftime("%Y")
platform_system = platform.system()


def prog_info():
    desc = """ deefuzzer : easy and instant media streaming tool
 version : %s
 running on system : %s

 Copyright (c) 2007-%s Guillaume Pellerin <yomguy@parisson.com>
 All rights reserved.

 This software is licensed as described in the file COPYING, which
 you should have received as part of this distribution. The terms
 are also available at http://svn.parisson.org/deefuzzer/DeeFuzzerLicense

 depends :  python, python-xml, python-shout, libshout3, icecast2,
            python-mutagen, python-twitter, python-tinyurl,
            python-liblo (pyliblo)
 provides : python-shout

 Usage : deefuzzer $1
  where $1 is the path for a XML config file
  ex: deefuzzer example/myfuzz.xml

 see http://svn.parisson.org/deefuzzer/ for more details
        """

    return desc % (version, platform_system, year)


class DeeFuzzerError:
    """The DeeFuzzer main error class"""
    def __init__(self, message):
        self.message = message
    def __str__(self):
        return 'DeeFuzzer Error : ' + self.message


class DeeFuzzerStreamError:
    """The DeeFuzzer stream error class"""
    def __init__(self, message, command, subprocess):
        self.message = message
        self.command = str(command)
        self.subprocess = subprocess

    def __str__(self):
        if self.subprocess.stderr != None:
            error = self.subprocess.stderr.read()
        else:
            error = ''
        return "%s ; command: %s; error: %s" % (self.message,
                                                self.command,
                                                error)


class DeeFuzzer(Thread):
    """a DeeFuzzer diffuser"""

    def __init__(self, conf_file):
        Thread.__init__(self)
        self.conf_file = conf_file
        self.conf = self.get_conf_dict()
        if 'log' in self.conf['deefuzzer'].keys():
            self.logger = Logger(self.conf['deefuzzer']['log'])
        else:
            self.logger = Logger('.' + os.sep + 'deefuzzer.log')
        if 'm3u' in self.conf['deefuzzer'].keys():
            self.m3u = self.conf['deefuzzer']['m3u']
        else:
            self.m3u = '.' + os.sep + 'deefuzzer.m3u'

        if isinstance(self.conf['deefuzzer']['station'], dict):
            # Fix wrong type data from xmltodict when one station (*)
            self.nb_stations = 1
        else:
            self.nb_stations = len(self.conf['deefuzzer']['station'])

        # Set the deefuzzer logger
        self.logger.write('Starting DeeFuzzer v' + version)
        self.logger.write('Using libshout version %s' % shout.version())

        # Init all Stations
        self.stations = []
        self.logger.write('Number of stations : ' + str(self.nb_stations))

    def get_conf_dict(self):
        confile = open(self.conf_file,'r')
        conf_xml = confile.read()
        confile.close()
        return xmltodict(conf_xml,'utf-8')

    def set_m3u_playlist(self):
        m3u_dir = os.sep.join(self.m3u.split(os.sep)[:-1])
        if not os.path.exists(m3u_dir):
            os.makedirs(m3u_dir)
        m3u = open(self.m3u, 'w')
        i = 1
        m3u.write('#EXTM3U\n')
        for s in self.stations:
            info = '#EXTINF:%s,%s' % (str(i), s.channel.name + ' (' + s.short_name + ')\n')
            url =  s.channel.protocol + '://' + s.channel.host + ':' + str(s.channel.port) + s.channel.mount + '\n'
            m3u.write(info)
            m3u.write(url)
            i += 1
        m3u.close()
        self.logger.write('Writing M3U file to : ' + self.m3u)


    def run(self):
        # Create a Queue
        q = Queue.Queue(1)

        for i in range(0,self.nb_stations):
            if isinstance(self.conf['deefuzzer']['station'], dict):
                station = self.conf['deefuzzer']['station']
            else:
                station = self.conf['deefuzzer']['station'][i]
            # Create a Station
            self.stations.append(Station(station, q, self.logger, self.m3u))

        self.set_m3u_playlist()

        # Create a Producer
        p = Producer(q)
        p.start()

        # Start the Stations
        for i in range(0,self.nb_stations):
            self.stations[i].start()


class Producer(Thread):
    """a DeeFuzzer Producer master thread"""

    def __init__(self, q):
        Thread.__init__(self)
        self.q = q

    def run(self):
        i=0
        q = self.q
        while 1:
            q.put(i,1)
            i+=1


class Station(Thread):
    """a DeeFuzzer shouting station thread"""

    def __init__(self, station, q, logger, m3u):
        Thread.__init__(self)
        self.station = station
        self.q = q
        self.logger = logger
        self.channel = shout.Shout()
        self.id = 999999
        self.counter = 0
        self.command = 'cat '
        self.delay = 0

       # Media
        self.media_dir = self.station['media']['dir']
        self.channel.format = self.station['media']['format']
        self.mode_shuffle = int(self.station['media']['shuffle'])
        self.bitrate = self.station['media']['bitrate']
        self.ogg_quality = self.station['media']['ogg_quality']
        self.samplerate = self.station['media']['samplerate']
        self.voices = self.station['media']['voices']

        # RSS
        self.rss_dir = self.station['rss']['dir']
        self.rss_enclosure = self.station['rss']['enclosure']

        # Infos
        self.channel.url = self.station['infos']['url']
        self.short_name = self.station['infos']['short_name']
        self.channel.name = self.station['infos']['name'] + ' ' + self.channel.url
        self.channel.genre = self.station['infos']['genre']
        self.channel.description = self.station['infos']['description']
        self.base_name = self.rss_dir + os.sep + self.short_name + '_' + self.channel.format
        self.rss_current_file = self.base_name + '_current.xml'
        self.rss_playlist_file = self.base_name + '_playlist.xml'
        self.m3u = m3u

        # Server
        self.channel.protocol = 'http'     # | 'xaudiocast' | 'icy'
        self.channel.host = self.station['server']['host']
        self.channel.port = int(self.station['server']['port'])
        self.channel.user = 'source'
        self.channel.password = self.station['server']['sourcepassword']
        self.channel.mount = '/' + self.short_name + '.' + self.channel.format
        self.channel.public = int(self.station['server']['public'])
        self.channel.audio_info = { 'bitrate': self.bitrate,
                                    'samplerate': self.samplerate,
                                    'quality': self.ogg_quality,
                                    'channels': self.voices,}
        self.playlist = self.get_playlist()
        self.lp = len(self.playlist)
        self.channel.open()

        # Logging
        self.logger.write('Opening ' + self.short_name + ' - ' + self.channel.name + \
                ' (' + str(self.lp) + ' tracks)...')

        self.metadata_relative_dir = 'metadata'
        self.metadata_url = self.channel.url + '/rss/' + self.metadata_relative_dir
        self.metadata_dir = self.rss_dir + os.sep + self.metadata_relative_dir
        if not os.path.exists(self.metadata_dir):
            os.makedirs(self.metadata_dir)

        # Twitter
        self.twitter_mode = '0'
        if 'twitter' in self.station:
            self.twitter_mode = self.station['twitter']['mode']
            self.twitter_user = self.station['twitter']['user']
            self.twitter_pass = self.station['twitter']['pass']
            if self.twitter_mode == '1':
                self.twitter = Twitter(self.twitter_user, self.twitter_pass)
                self.twitter_tags = self.station['twitter']['tags'].split(' ')
                import tinyurl
                self.tinyurl = tinyurl.create_one(self.channel.url + '/m3u/' + self.m3u.split(os.sep)[-1])

        self.jingles_mode = '0'
        if 'jingles' in self.station:
            self.jingles_mode =  self.station['jingles']['mode']
            self.jingles_shuffle = self.station['jingles']['shuffle']
            self.jingles_dir = self.station['jingles']['dir']
            if self.jingles_mode =='1':
                self.jingles_list = self.get_jingles()
                self.jingles_length = len(self.jingles_list)
                self.jingle_id = 0

        self.osc_control_mode = '0'
        if 'control' in self.station:
            self.osc_control_mode = self.station['control']['mode']
            self.osc_port = self.station['control']['port']
            if self.osc_control_mode =='1':
                self.osc_controller = OSCController(self.osc_port)
                self.osc_controller.add_method('/media/next', 'i', self.media_next_callback)
                self.osc_controller.start()

        self.osc_relay = 0
        if 'relay' in self.station:
            self.relay_url = self.station['relay']['url']
            self.osc_controller.add_method('/media/relay', 'i', self.relay_callback)

    def media_next_callback(self, path, value):
        value = value[0]
        self.osc_next_media = value
        message = "Received OSC message '%s' with arguments '%d'" % (path, value)
        self.logger.write(message)

    def relay_callback(self, path, value):
        value = value[0]
        self.osc_relay = value
        message = "Received OSC message '%s' with arguments '%d'" % (path, value)
        self.logger.write(message)

    def get_playlist(self):
        file_list = []
        for root, dirs, files in os.walk(self.media_dir):
            for file in files:
                s = file.split('.')
                ext = s[len(s)-1]
                if ext.lower() == self.channel.format and not os.sep+'.' in file:
                    file_list.append(root + os.sep + file)
        file_list.sort()
        return file_list

    def get_jingles(self):
        file_list = []
        for root, dirs, files in os.walk(self.jingles_dir):
            for file in files:
                s = file.split('.')
                ext = s[len(s)-1]
                if ext.lower() == self.channel.format and not os.sep+'.' in file:
                    file_list.append(root + os.sep + file)
        file_list.sort()
        return file_list

    def get_next_media(self):
        # Init playlist
        if self.lp != 0:
            old_playlist = self.playlist
            new_playlist = self.get_playlist()
            lp_new = len(new_playlist)

            if lp_new != self.lp or self.counter == 0:
                # Init playlists
                self.playlist = new_playlist
                self.id = 0
                self.lp = lp_new

                # Twitting new tracks
                new_playlist_set = set(self.playlist)
                old_playlist_set = set(old_playlist)
                new_tracks = new_playlist_set - old_playlist_set
                if len(new_tracks) != 0:
                    self.new_tracks = list(new_tracks.copy())
                    new_tracks_objs = self.media_to_objs(self.new_tracks)

                    for media_obj in new_tracks_objs:
                        title = media_obj.metadata['title']
                        artist = media_obj.metadata['artist']
                        if not (title or artist):
                            song = str(media_obj.file_name)
                        else:
                            song = artist + ' : ' + title
                        song = song.encode('utf-8')
                        artist = artist.encode('utf-8')
                        message = 'New track ! %s #%s #%s' % (song.replace('_', ' '), artist.replace(' ', ''), self.short_name)
                        self.update_twitter(message)

                if self.mode_shuffle == 1:
                    # Shake it, Fuzz it !
                    random.shuffle(self.playlist)

                self.logger.write('Station ' + self.short_name + \
                                 ' : generating new playlist (' + str(self.lp) + ' tracks)')
                self.update_rss(self.media_to_objs(self.playlist), self.rss_playlist_file, '(playlist)')

            if self.jingles_mode == '1' and (self.counter % 2) == 0 and not self.jingles_length == 0:
                media = self.jingles_list[self.jingle_id]
                self.jingle_id = (self.jingle_id + 1) % self.jingles_length
            else:
                media = self.playlist[self.id]
                self.id = (self.id + 1) % self.lp

            return media

        else:
            mess = 'No media in media_dir !'
            self.logger.write(mess)
            sys.exit(mess)

    def media_to_objs(self, media_list):
        media_objs = []
        for media in media_list:
            file_name, file_title, file_ext = get_file_info(media)
            if file_ext.lower() == 'mp3':
                media_objs.append(Mp3(media))
            elif file_ext.lower() == 'ogg':
                media_objs.append(Ogg(media))
        return media_objs

    def update_rss(self, media_list, rss_file, sub_title):
        rss_item_list = []
        if not os.path.exists(self.rss_dir):
            os.makedirs(self.rss_dir)

        channel_subtitle = self.channel.name + ' ' + sub_title
        _date_now = datetime.datetime.now()
        date_now = str(_date_now)
        media_absolute_playtime = _date_now

        for media in media_list:
            media_stats = os.stat(media.media)
            media_date = time.localtime(media_stats[8])
            media_date = time.strftime("%a, %d %b %Y %H:%M:%S +0200", media_date)
            media.metadata['Duration'] = str(media.length).split('.')[0]
            media.metadata['Bitrate'] = str(media.bitrate) + ' kbps'
            media.metadata['Next play'] = str(media_absolute_playtime).split('.')[0]

            media_description = '<table>'
            media_description_item = '<tr><td>%s:   </td><td><b>%s</b></td></tr>'
            for key in media.metadata.keys():
                if media.metadata[key] != '':
                    media_description += media_description_item % (key.capitalize(), media.metadata[key])
            media_description += '</table>'

            title = media.metadata['title']
            artist = media.metadata['artist']
            if not (title or artist):
                song = str(media.file_title)
            else:
                song = artist + ' : ' + title

            media_absolute_playtime += media.length

            if self.rss_enclosure == '1':
                media_link = self.channel.url + '/media/' + media.file_name
                media_link = media_link.decode('utf-8')
                rss_item_list.append(PyRSS2Gen.RSSItem(
                    title = song,
                    link = media_link,
                    description = media_description,
                    enclosure = PyRSS2Gen.Enclosure(media_link, str(media.size), 'audio/mpeg'),
                    guid = PyRSS2Gen.Guid(media_link),
                    pubDate = media_date,)
                    )
            else:
                media_link = self.metadata_url + '/' + media.file_name + '.xml'
                media_link = media_link.decode('utf-8')
                rss_item_list.append(PyRSS2Gen.RSSItem(
                    title = song,
                    link = media_link,
                    description = media_description,
                    guid = PyRSS2Gen.Guid(media_link),
                    pubDate = media_date,)
                    )

        rss = PyRSS2Gen.RSS2(title = channel_subtitle,
                            link = self.channel.url,
                            description = self.channel.description.decode('utf-8'),
                            lastBuildDate = date_now,
                            items = rss_item_list,)

        f = open(rss_file, 'w')
        rss.write_xml(f, 'utf-8')
        f.close()

    def update_twitter(self, message):
        if self.twitter_mode == '1':
            tags = '#' + ' #'.join(self.twitter_tags)
            message = message + ' ' + tags
            message = message[:113] + ' ' + self.tinyurl
            message = message.decode('utf8')
            self.logger.write('Twitting : "' + message + '"')
            self.twitter.post(message)

    def run(self):
        q = self.q
        p = Player()
        p.start()
        while True:
            it = q.get(1)
            if self.lp == 0:
                self.logger.write('Error : Station ' + self.short_name + ' have no media to stream !')
                break
            self.osc_next_media = 0
            media = self.get_next_media()
            self.counter += 1
            q.task_done()

            if os.path.exists(media) and not os.sep+'.' in media:
                it = q.get(1)
                self.current_media_obj = self.media_to_objs([media])
                self.title = self.current_media_obj[0].metadata['title']
                self.artist = self.current_media_obj[0].metadata['artist']
                self.title = self.title.replace('_', ' ')
                self.artist = self.artist('_', ' ')
                if not (self.title or self.artist):
                    song = str(self.current_media_obj[0].file_name)
                else:
                    song = self.artist + ' : ' + self.title
                self.song = song.encode('utf-8')
                self.artist = self.artist.encode('utf-8')

                self.metadata_file = self.metadata_dir + os.sep + self.current_media_obj[0].file_name + '.xml'
                self.update_rss(self.current_media_obj, self.metadata_file, '')
                self.channel.set_metadata({'song': self.song, 'charset': 'utf8',})
                self.update_rss(self.current_media_obj, self.rss_current_file, '(currently playing)')
                self.logger.write('DeeFuzzing this file on %s :  id = %s, name = %s' \
                    % (self.short_name, self.id, self.current_media_obj[0].file_name))

                if not (self.jingles_mode == '1' and (self.counter % 2) == 1):
                    message = 'Now playing: %s #%s #%s' % (self.song.replace('_', ' '), self.artist.replace(' ', ''), self.short_name)
                    self.update_twitter(message)

                if self.osc_relay != 0:
                    stream = p.relay(self.relay_url)
                else:
                    p.set_media(media)
                    stream = p.read_slow()
                q.task_done()

                for __chunk in stream:
                    it = q.get(1)
                    try:
                        self.channel.send(__chunk)
                        self.channel.sync()
                        if self.osc_next_media != 0 or self.osc_relay != 0:
                            break
                        # self.logger.write('Station delay (ms) ' + self.short_name + ' : '  + str(self.channel.delay()))
                    except:
                        self.logger.write('ERROR : Station ' + self.short_name + ' : could not send the buffer... ')
                        self.channel.close()
                        self.channel.open()
                        continue
                    q.task_done()
            else:
                self.logger.write('Error : Station ' + self.short_name + ' : ' + media + 'not found !')

        self.channel.close()


class Player(Thread):
    """A file streaming iterator"""

    def __init__(self):
        Thread.__init__(self)
        self.main_buffer_size = 0x100000
        self.sub_buffer_size = 0x10000
        self.q = collections.deque(4*self.sub_buffer_size)

    def set_media(self, media):
        self.media = media

    def stream(self, media):
        """Read media and stream data through a generator.
        Taken from Telemeta (see http://telemeta.org)"""

        command = self.command + '"' + media + '"'

        proc = subprocess.Popen(command,
                    shell = True,
                    bufsize = self.sub_buffer_size,
                    stdin = subprocess.PIPE,
                    stdout = subprocess.PIPE,
                    close_fds = True)

        # Core processing
        while True:
            __chunk = proc.stdout.read(self.sub_buffer_size)
            status = proc.poll()
            if status != None and status != 0:
                raise DeeFuzzerStreamError('Command failure:', command, proc)
            if not __chunk:
                break
            yield __chunk

    def read_fast(self):
        """Read media and stream data through a generator."""
        media = self.media
        m = open(media, 'r')
        while True:
            __main_chunk = m.read(self.sub_buffer_size)
            if not __main_chunk:
                break
            yield __main_chunk
        m.close()

    def read_slow(self):
        """Read a bigger part of the media and stream the little parts
         of the data through a generator"""
        media = self.media
        m = open(media, 'r')
        while True:
            __main_chunk = m.read(self.main_buffer_size)
            if not __main_chunk:
                break
            i = 0
            while True:
                start = i * self.sub_buffer_size
                end = self.sub_buffer_size + (i * self.sub_buffer_size)
                __sub_chunk = __main_chunk[start:end]
                if not __sub_chunk:
                    break
                yield __sub_chunk
                i += 1
        m.close()

    def relay(self, url):
        """Read a distant media through its URL"""
        q = self.q
        r = Relay(q, url)
        r.start()
        while True:
            __chunk = q.popleft(self.sub_buffer_size)
            if not __chunk:
                break
            yield __chunk

    def run(self):
        pass


class Relay(Thread):

    def __init__(self, q, url):
        Thread.__init__(self)
        self.main_buffer_size = 0x100000
        self.sub_buffer_size = 0x10000
        self.url = url
        self.u = urllib.urlopen(self.url)
        self.q = q

    def run(self):
        q = self.q
        while True:
            data = self.u.read(self.main_buffer_size)
            q.put(data)
        self.u.close()


class Twitter:

    def __init__(self, username, password):
        import twitter
        self.username = username
        self.password = password
        self.api = twitter.Api(username=self.username, password=self.password)

    def post(self, message):
        try:
            self.api.PostUpdate(message)
        except:
            pass


class OSCController(Thread):

    def __init__(self, port):
        Thread.__init__(self)
        import liblo
        self.port = port
        try:
            self.server = liblo.Server(self.port)
        except liblo.ServerError, err:
            self.logger.write(str(err))

    def add_method(self, path, type, method):
        self.server.add_method(path, type, method)

    def server(self):
        return self.server

    def run(self):
        while True:
            self.server.recv(1000)


def main():
    if len(sys.argv) == 2:
        d = DeeFuzzer(sys.argv[-1])
        d.start()
    else:
        text = prog_info()
        sys.exit(text)

if __name__ == '__main__':
    main()
