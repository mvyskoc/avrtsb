__all__ = ['_', '_l', 'STDOUT_ENCODING', 'SYS_ENCODING', 'LANG_CODE']

import gettext
import locale
import os
import sys

LOCALE_DOMAIN = 'pytsb'
LOCALE_DIRECTORY = os.path.join( os.path.dirname(__file__), "locale" )
LOCALE_TEMPLATE = os.path.join(LOCALE_DIRECTORY, LOCALE_DOMAIN + '.pot')

STDOUT_ENCODING=sys.stdout.encoding

LANG_CODE, SYS_ENCODING = locale.getdefaultlocale()

if LANG_CODE == None:
    LANG_CODE = "en_US"
 
translation = gettext.translation('pytsb', LOCALE_DIRECTORY,
                                  languages=[LANG_CODE],
                                  codeset=STDOUT_ENCODING,
                                  fallback=True)

_ = translation.ugettext
_l = translation.lgettext

