#!/usr/bin/python
# -*- coding: UTF-8 -*-
from ez_setup import use_setuptools
use_setuptools()
import os
from setuptools import setup
def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

setup(
    name = "avrtsb",
    version = "0.2.1",
    author = "Martin Vyskočil",
    author_email = "m.vyskoc@seznam.cz",
    description = ("Python version of TinySafeBoot"
                   "A tiny and safe Bootloader for AVR-ATtinys and ATmegas"),
    license = "GPLv3",
    keywords = "TinySafeBoot, AVR, bootloader",
    #url = "http://packages.python.org/an_example_pypi_project",
    packages=['avrtsb'],
    package_data={'avrtsb': ['tsb_db.pklz', 'locale/*/LC_MESSAGES/*.mo']},
    long_description=read('README.TXT'),
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

    dependency_links=['https://launchpad.net/intelhex/+download'],

    install_requires=[
          'pyserial', 'intelhex'
    ],

    entry_points = {
        'console_scripts': ['pytsb=avrtsb.pytsb:main'],
    }
)
