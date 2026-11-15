"""Filename categories for icons and program marks, independent of HTTP safety."""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from boosty_downloader.viewer.api_models import FileType

_SUFFIXES: Final[dict[FileType, str]] = {
    'pdf': 'pdf',
    'document': 'doc docx docm dot dotx odt rtf pages txt md markdown log tex srt ass ssa vtt xps',
    'book': 'epub fb2 mobi azw azw3 djvu cbz cbr cb7',
    'sheet': 'xls xlsx xlsm ods csv tsv numbers',
    'slides': 'ppt pptx pptm odp key',
    'image': (
        'jpg jpeg png gif webp avif heic heif bmp tif tiff jxl svg ico psd psb kra xcf clip '
        'sai sai2 procreate ai eps exr tga cr2 cr3 nef arw dng raf orf rw2'
    ),
    'audio': 'mp3 m4a aac flac wav ogg oga opus aiff aif wma mid midi ape wv mka',
    'video': 'mp4 m4v mov mkv webm avi wmv flv mpg mpeg m2ts mts 3gp ogv vob',
    'archive': 'zip rar 7z tar gz tgz bz2 tbz2 xz txz zst lz lzma cab iso img dmg vhd vhdx',
    'model': (
        'fbx obj stl glb gltf 3mf ply blend ma mb max c4d usd usda usdc usdz dae 3ds abc ztl '
        'unitypackage'
    ),
    'code': (
        'html htm xhtml css json xml yaml yml toml ini cfg lua c cpp h cs java go rs swift sql '
        'glsl hlsl gd'
    ),
    'font': 'ttf otf woff woff2 ttc',
    'program': (
        'exe com scr pif cpl msi msp msc msix msixbundle appx appxbundle application appref-ms '
        'appinstaller ppkg vsto xll xlam ppam gadget diagcab settingcontent-ms library-ms '
        'search-ms searchconnector-ms rdp pkg mpkg app apk xapk ipa deb rpm appimage run snap '
        'flatpakref jar jnlp mobileconfig prefpane workflow lnk url website webloc inetloc '
        'fileloc desktop'
    ),
    'script': (
        'bat cmd btm ps1 psm1 vbs vbe vb js jse ws wsf wsc wsh sct hta chm sh bash zsh ksh csh '
        'fish command tool terminal applescript scpt scptd py pyw pyz pl rb reg scf inf'
    ),
}
_TYPE_BY_SUFFIX: Final[dict[str, FileType]] = {
    f'.{name}': kind for kind, names in _SUFFIXES.items() for name in names.split()
}


def suffix(name: str) -> str:
    """Return the last-dot suffix after NFC and Windows trailing-dot/space rules."""
    name = unicodedata.normalize('NFC', name).replace('\\', '/').rsplit('/', 1)[-1]
    name = name.rstrip(' .')
    dot = name.rfind('.')
    return name[dot:].lower() if dot >= 0 else ''


def file_type(name: str) -> FileType:
    """Classify the stored filename without reading or opening its file."""
    return _TYPE_BY_SUFFIX.get(suffix(name), 'other')
