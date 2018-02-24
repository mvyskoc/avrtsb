#!/usr/bin/python
# -*- coding: UTF-8 -*-
from ez_setup import use_setuptools
use_setuptools()

import os
from setuptools import setup
from setuptools.command.install import _install
from setuptools.command.build_py import build_py as _build_py

babel_cmdclass = {}
try:
    from avrtsb import setup_locale
    babel_cmdclass = {'compile_catalog'  : setup_locale.compile_catalog,
                      'extract_messages' : setup_locale.extract_messages,
                      'init_catalog'     : setup_locale.init_catalog,
                      'update_catalog'   : setup_locale.update_catalog}
except ImportError:
    print("Warning: babel package is not installed. It is required for")
    print("compilation a prepare new localisation.")
    print()
    print("Install it with the following command:")
    prin( "  pip2 install babel")

def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

def compile_catalog(distribution):
    from avrtsb import setup_locale
    compiler = setup_locale.compile_catalog(distribution)
    compiler.initialize_options()
    compiler.run()


class build_py(_build_py, object):
    def run(self):
        compile_catalog(self.distribution) 
        super(build_py, self).run()

setup_cmdclass = {
    'build_py'   : build_py,
}
setup_cmdclass.update(babel_cmdclass)



setup(
    name = "avrtsb",
    version = "0.2.6",
    author = "Martin Vyskočil",
    author_email = "m.vyskoc@seznam.cz",
    description = ("Python version of TinySafeBoot"
                   "A tiny and safe Bootloader for AVR-ATtinys and ATmegas"),
    license = "GPLv3",
    keywords = "TinySafeBoot, AVR, bootloader",
    url = "http://github.com/mvyskoc/avrtsb",
    download_url="https://github.com/mvyskoc/avrtsb/tarball/v0.2.6",
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

    cmdclass=setup_cmdclass,
    message_extractors = {
        'avrtsb': [
            ('**.py','python', None)
        ],
    },

    dependency_links=['https://launchpad.net/intelhex/+download'],
    python_requires="~=2.5",

    install_requires=[
          'pyserial', 'intelhex', 'babel'
    ],

    entry_points = {
        'console_scripts': ['pytsb=avrtsb.pytsb:main']
    }
)
