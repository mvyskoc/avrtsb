__all__ = ['_', '_l', 'STDOUT_ENCODING', 'SYS_ENCODING', 'LANG_CODE']

import gettext
import locale
import os
import sys

STDOUT_ENCODING=sys.stdout.encoding

locale_dir = os.path.join( os.path.dirname(__file__), "locale" )
LANG_CODE, SYS_ENCODING = locale.getdefaultlocale()

if LANG_CODE == None:
    LANG_CODE = "en_US"
 
translation = gettext.translation('pytsb', locale_dir,
                                  languages=[LANG_CODE],
                                  codeset=STDOUT_ENCODING,
                                  fallback=True)

_ = translation.ugettext
_l = translation.lgettext

