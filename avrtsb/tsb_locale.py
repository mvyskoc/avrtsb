__all__ = ['_']

import gettext
import locale
import os

locale_dir = os.path.join( os.path.dirname(__file__), "locale" )
lang_code, lang_encoding=locale.getdefaultlocale()
translation = gettext.translation('pytsb', locale_dir, languages=[lang_code], fallback=True)
_ = translation.ugettext
