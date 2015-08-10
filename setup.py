#!/usr/bin/python
# -*- coding: UTF-8 -*-
from ez_setup import use_setuptools
use_setuptools()

import os
from setuptools import setup
from setuptools.command.build_py import build_py as _build_py
from babel.messages import frontend as babel

LOCALE_DOMAIN = 'pytsb'
LOCALE_DIRECTORY = 'avrtsb/locale'
LOCALE_TEMPLATE = os.path.join(LOCALE_DIRECTORY, LOCALE_DOMAIN + '.pot')

def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

class compile_catalog(babel.compile_catalog):
    def initialize_options(self):
        babel.compile_catalog.initialize_options(self)
        self.domain = LOCALE_DOMAIN
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
        self.domain = 'pytsb'
        self.no_wrap = False
        self.width = None
        

class build_py(_build_py):
    def run(self):
        self.run_command('compile_catalog')
        _build_py.run(self)

setup(
    name = "avrtsb",
    version = "0.2.5a2",
    author = "Martin Vyskočil",
    author_email = "m.vyskoc@seznam.cz",
    description = ("Python version of TinySafeBoot"
                   "A tiny and safe Bootloader for AVR-ATtinys and ATmegas"),
    license = "GPLv3",
    keywords = "TinySafeBoot, AVR, bootloader",
    url = "http://github.com/mvyskoc/avrtsb",
    download_url="https://github.com/mvyskoc/avrtsb/tarball/v0.2.5a2",
    packages=['avrtsb'],
    package_data={'avrtsb': ['tsb_db.pklz', 'locale/*/LC_MESSAGES/*.mo']},
    long_description=read('README.md'),
    zip_safe=False, 
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "Programming Language :: Python",
        "Programming Language :: Python :: 2",
        "Topic :: Software Development :: Embedded Systems",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
    ],

    cmdclass = {'compile_catalog': compile_catalog,
                'extract_messages': extract_messages,
                'init_catalog': init_catalog,
                'update_catalog': update_catalog,
                'build_py': build_py},

    message_extractors = {
        'avrtsb': [
            ('**.py',                'python', None)
        ],
    },

    dependency_links=['https://launchpad.net/intelhex/+download'],

    install_requires=[
          'pyserial', 'intelhex', 'babel'
    ],

    entry_points = {
        'console_scripts': ['pytsb=avrtsb.pytsb:main'],
    }
)
