#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2007-2009 Guillaume Pellerin <yomguy@parisson.com>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://svn.parisson.org/deefuzz/wiki/DefuzzLicense.
#
# Author: Guillaume Pellerin <yomguy@parisson.com>

import os
import re
import string
import json
import yaml
import mimetypes
from itertools import chain
from deefuzzer.tools.xmltodict import xmltodict

mimetypes.add_type('application/x-yaml', '.yaml')


def clean_word(word):
    """ Return the word without excessive blank spaces, underscores and
    characters causing problem to exporters"""
    word = re.sub("^[^\w]+", "", word)  # trim the beginning
    word = re.sub("[^\w]+$", "", word)  # trim the end
    word = re.sub("_+", "_", word)  # squeeze continuous _ to one _
    word = re.sub("^[^\w]+", "", word)  # trim the beginning _
    # word = string.replace(word,' ','_')
    # word = string.capitalize(word)
    dict = '&[];"*:,'
    for letter in dict:
        word = string.replace(word, letter, '_')
    return word


def get_file_info(media):
    file_name = media.split(os.sep)[-1]
    file_title = file_name.split('.')[:-1]
    file_title = '.'.join(file_title)
    file_ext = file_name.split('.')[-1]
    return file_name, file_title, file_ext


def is_absolute_path(path):
    return os.sep == path[0]


def merge_defaults(setting, default):
    combined = {}
    for key in set(chain(setting, default)):
        if key in setting:
            if key in default:
                if isinstance(setting[key], dict) \
                        and isinstance(default[key], dict):
                    combined[key] = merge_defaults(setting[key], default[key])
                else:
                    combined[key] = setting[key]
            else:
                combined[key] = setting[key]
        else:
            combined[key] = default[key]
    return combined


def replace_all(option, repl):
    if isinstance(option, list):
        r = []
        for i in option:
            r.append(replace_all(i, repl))
        return r
    elif isinstance(option, dict):
        r = {}
        for key in option.iterkeys():
            r[key] = replace_all(option[key], repl)
        return r
    elif isinstance(option, str):
        return option.format(**repl)
    return option


def read_yaml(data):

    def custom_str_constructor(loader, node):
        return loader.construct_scalar(node).encode('utf-8')

    yaml.add_constructor(u'tag:yaml.org,2002:str', custom_str_constructor)
    return yaml.load(data)


def read_xml(data):
    return xmltodict(data, 'utf-8')


def deunicodify_hook(pairs):
    new_pairs = []
    for key, value in pairs:
        if isinstance(value, unicode):
            value = value.encode('utf-8')
        if isinstance(key, unicode):
            key = key.encode('utf-8')
        new_pairs.append((key, value))
    return dict(new_pairs)


def read_json(data):
    return json.loads(data, object_pairs_hook=deunicodify_hook)

EXT_READERS = (
    ('xml', read_xml),
    ('json', read_json),
    ('yaml', read_yaml),
    ('yml', read_yaml),
)


def get_conf_dict(afile):
    mime_type = mimetypes.guess_type(afile)[0]

    for ext, reader in EXT_READERS:
        if ext in mime_type:
            with open(afile, 'r') as confile:
                return reader(confile.read())
    return False


def folder_contains_music(folder):
    files = os.listdir(folder)
    for filename in files:
        filepath = os.path.join(folder, filename)
        if os.path.isfile(filepath):
            mime_type = mimetypes.guess_type(filepath)[0]
            if 'audio/mpeg' in mime_type or 'audio/ogg' in mime_type:
                return True
    return False
