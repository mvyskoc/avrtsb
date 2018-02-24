#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
from tsb_locale import LOCALE_TEMPLATE 
from tsb_locale import LOCALE_DOMAIN 
from tsb_locale import LOCALE_DIRECTORY
from babel.messages import frontend as babel


class compile_catalog(babel.compile_catalog):
    def initialize_options(self):
        babel.compile_catalog.initialize_options(self)
        self.domain = [LOCALE_DOMAIN]
        self.directory = LOCALE_DIRECTORY
        self.locale = None
        self.use_fuzzy = True
        self.statistics = True

class update_catalog(babel.update_catalog):
    def initialize_options(self):
        babel.update_catalog.initialize_options(self)
        self.domain = LOCALE_DOMAIN
        self.input_file = LOCALE_TEMPLATE
        self.output_dir = LOCALE_DIRECTORY
        self.no_wrap = False
        self.ignore_obsolete = True
        self.no_fuzzy_matching = False
        self.previous = False

    def run(self):
        self.run_command('extract_messages')
        babel.update_catalog.run(self)

class extract_messages(babel.extract_messages):
    def initialize_options(self):
        babel.extract_messages.initialize_options(self)
        self.charset = 'utf-8'
        self.no_default_keywords = False
        self.keywords = '_ l'
        self.mapping_file = None
        self.no_location = False
        self.omit_header = False
        self.output_file = LOCALE_TEMPLATE
        self.input_dirs = 'avrtsb'
        self.width = None
        self.no_wrap = False
        self.sort_output = False
        self.sort_by_file = True        
        self.msgid_bugs_address = 'm.vyskoc@seznam.cz'
        self.copyright_holder = None
        self.add_comments = None
        self.strip_comments = False

class init_catalog(babel.init_catalog):
    def initialize_options(self):
        babel.init_catalog.initialize_options(self)
        self.output_dir = LOCALE_DIRECTORY
        self.output_file = None
        self.input_file = LOCALE_TEMPLATE
        self.locale = None
        self.domain = LOCALE_DOMAIN
        self.no_wrap = False
        self.width = None

# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4

