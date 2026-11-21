#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File    : book_translator.py
Author  : Hadi Sarhangi Fard
Date    : 2026-11-19   (version 3.4)
Project : DeepTome Translator - layout-preserving neural machine translation of PDF documents

What this file is
-----------------
The whole application in one module: the desktop window (Tkinter), the command line interface and the
translation pipeline.

  1. PDF layout analysis      text spans -> lines -> paragraphs, headings, formulas, figures, tables, margin notes
  2. Text protection          technical terms, names, acronyms, inline maths are masked as placeholders (ZX1XZ)
  3. Machine translation      local MADLAD-400 / NLLB-200 (CTranslate2, int8), Ollama or any OpenAI-compatible API,
                              with hallucination checks and automatic re-translation of damaged sentences
  4. Typesetting              the translation is written back at the place of the original paragraph, with the
                              original size / weight / colour / alignment; right-to-left scripts and two-column
                              pages are mirrored
  5. Tools around it          parts of 2 pages with a cache (resume after a crash), review / layout editor, quick
                              text translation with speech, glossary and user instructions, history, setup data

Languages: English, Persian, German, French, Spanish - in both directions.

Copyright (c) 2026 Hadi Sarhangi Fard.   All rights reserved.
GitHub : https://github.com/Hadifard

Run the GUI :  python book_translator.py
Run the CLI :  python book_translator.py --cli book.pdf -l fa -o out --formats pdf,txt
"""
from __future__ import annotations

import argparse
import base64
import collections
import hashlib
import html
import json
import math
import os
import queue
import re
import shutil
import socket
import statistics
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24.3
except ImportError:  # pragma: no cover
    import fitz  # type: ignore

APP_TITLE = "DeepTome Translator"
APP_SUBTITLE = ("Translate books and documents between languages  ·  same layout, fonts and styles  ·  "
                "technical terms stay original  ·  open-source offline AI")
APP_VERSION = "3.5"
APP_YEAR = "2026"
APP_AUTHOR = "Hadi Sarhangi Fard"                     # owner of the copyright
APP_COPYRIGHT = f"© {APP_YEAR} {APP_AUTHOR}. All rights reserved."
APP_BUILD = "2026-11-21d"          # shown in the log: proves which version produced a file
GITHUB = "https://github.com/Hadifard"
LINKEDIN = "https://www.linkedin.com/in/hadi-sarhangi-fard-mech-eng/"
EMAIL = ""                       # your e-mail address for "Contact me" in Help: type it between the quotes
try:
    LOGO_FILE = Path(__file__).resolve().parent / "assets" / "logo.png"     # logo of the window header
except NameError:  # pragma: no cover
    LOGO_FILE = Path.cwd() / "assets" / "logo.png"

_ACTIVITY: List[Callable[[str, str], None]] = [lambda text, tag="w": None]


def act(text: str, tag: str = "w") -> None:
    """Live-activity line for the window ('h' = green headings, 'b' = blue actions, 'w' = white body text)."""
    try:
        _ACTIVITY[0](text, tag)
    except Exception:
        pass


def set_activity(fn: Callable[[str, str], None]) -> None:
    _ACTIVITY[0] = fn

APP_DIR = Path.home() / ".pdf_book_translator"
FONT_DIR = APP_DIR / "fonts"
CACHE_DIR = APP_DIR / "cache"
MODEL_DIR = APP_DIR / "models"
GLOSSARY_FILE = APP_DIR / "glossary.txt"
try:
    SCRIPT_FONT_DIR = Path(__file__).resolve().parent / "fonts"      # put .ttf files here to work fully offline
except NameError:  # pragma: no cover
    SCRIPT_FONT_DIR = Path.cwd() / "fonts"


class Cancelled(Exception):
    pass


# ════════════════════════════════════════════════════════════════════════════
#  Fonts  (local files first – the internet is only a convenience, never required)
# ════════════════════════════════════════════════════════════════════════════
RAST = "https://github.com/rastikerdar"
NOTO = "https://raw.githubusercontent.com/notofonts/notofonts.github.io/main/fonts"
GF = "https://raw.githubusercontent.com/google/fonts/main/ofl"


def _rk(repo: str, name: str, bold: bool = True) -> dict:
    spec = {"regular": (f"{name}.ttf", f"{RAST}/{repo}/raw/master/dist/{name}.ttf")}
    if bold:
        spec["bold"] = (f"{name}-Bold.ttf", f"{RAST}/{repo}/raw/master/dist/{name}-Bold.ttf")
    return spec


def _noto(folder: str) -> dict:
    base = f"{NOTO}/{folder}/hinted/ttf/{folder}"
    return {"regular": (f"{folder}-Regular.ttf", f"{base}-Regular.ttf"),
            "bold": (f"{folder}-Bold.ttf", f"{base}-Bold.ttf")}


def _gf(folder: str, name: str, bold: bool = True) -> dict:
    spec = {"regular": (f"{name}-Regular.ttf", f"{GF}/{folder}/{name}-Regular.ttf")}
    if bold:
        spec["bold"] = (f"{name}-Bold.ttf", f"{GF}/{folder}/{name}-Bold.ttf")
    return spec


FONT_SPECS: Dict[str, dict] = {
    # ---- free Persian fonts (found locally first, downloaded only if missing) ----
    "Vazirmatn": {
        "regular": ("Vazirmatn-Regular.ttf", f"{RAST}/vazirmatn/raw/master/fonts/ttf/Vazirmatn-Regular.ttf"),
        "bold": ("Vazirmatn-Bold.ttf", f"{RAST}/vazirmatn/raw/master/fonts/ttf/Vazirmatn-Bold.ttf")},
    "Sahel": _rk("sahel-font", "Sahel"),
    "Shabnam": _rk("shabnam-font", "Shabnam"),
    "Samim": _rk("samim-font", "Samim"),
    "Parastoo": _rk("parastoo-font", "Parastoo"),
    "Tanha": _rk("tanha-font", "Tanha", bold=False),
    "Gandom": _rk("gandom-font", "Gandom", bold=False),
    "Nahid": _rk("nahid-font", "Nahid", bold=False),
    "Estedad": {
        "regular": ("Estedad-Regular.ttf", "https://github.com/aminabedi68/Estedad/raw/master/fonts/ttf/Estedad-Regular.ttf"),
        "bold": ("Estedad-Bold.ttf", "https://github.com/aminabedi68/Estedad/raw/master/fonts/ttf/Estedad-Bold.ttf")},
    "Lalezar": _gf("lalezar", "Lalezar", bold=False),
    "Noto Naskh Arabic": _noto("NotoNaskhArabic"),
    "Noto Sans Arabic": _noto("NotoSansArabic"),
    "Amiri": _gf("amiri", "Amiri"),
    "Harmattan": _gf("harmattan", "Harmattan"),
    "Scheherazade New": _gf("scheherazadenew", "ScheherazadeNew"),
    "Lateef": _gf("lateef", "Lateef", bold=False),
    # ---- commercial Persian fonts: must be installed on the computer (or copied into the "fonts" folder) ----
    "B Yaghout": {"system": ["byaghout", "byaghut", "byagut", "yaghout", "yaghut", "yagut"]},
    "B Yagut": {"system": ["byagut", "byaghut", "byaghout", "yagut", "yaghut", "yaghout"]},
    "Yaghout": {"system": ["yaghout", "yaghut", "yagut", "byaghout", "byaghut", "byagut"]},
    "B Lotus": {"system": ["blotus", "lotus"]},
    "B Titr": {"system": ["btitr", "titr"]},
    "B Jadid": {"system": ["bjadid", "jadid"]},
    "Jadid": {"system": ["jadid", "bjadid"]},
    "B Mitra": {"system": ["bmitra", "mitra"]},
    "Mitra": {"system": ["mitra", "bmitra"]},
    "IranSans": {"system": ["iransans", "iransansweb", "iransansfanum"]},
    "B Nazanin": {"system": ["bnazanin"]},
    "B Yekan": {"system": ["byekan"]},
    # ---- fonts that ship with the operating system (offline fallbacks, all contain Persian letters) ----
    "Times New Roman": {"system": ["times", "timesnewroman", "liberationserif"]},
    "Calibri": {"system": ["calibri", "carlito"]},
    "Cambria": {"system": ["cambria", "caladea"]},
    "Georgia": {"system": ["georgia"]},
    "Verdana": {"system": ["verdana"]},
    "Noto Serif": _noto("NotoSerif"),
    "Tahoma": {"system": ["tahoma"]},
    "Segoe UI": {"system": ["segoeui"]},
    "Arial": {"system": ["arial"]},
    "DejaVu Sans": {"system": ["dejavusans"]},
    # ---- fonts used automatically for the other languages / Latin text ----
    "Noto Sans": _noto("NotoSans"),
    "Noto Sans Devanagari": _noto("NotoSansDevanagari"),
    "Noto Sans Bengali": _noto("NotoSansBengali"),
    "Noto Nastaliq Urdu": _noto("NotoNastaliqUrdu"),
}

PERSIAN_FONTS: List[str] = [
    "B Yaghout", "B Yagut", "Yaghout", "B Lotus", "B Titr", "B Jadid", "Jadid", "B Mitra", "Mitra",
    "IranSans", "B Nazanin", "B Yekan",
    "Vazirmatn", "Sahel", "Shabnam", "Samim", "Parastoo", "Tanha", "Gandom",
    "Nahid", "Estedad", "Lalezar", "Noto Naskh Arabic", "Noto Sans Arabic",
    "Amiri", "Harmattan", "Scheherazade New", "Lateef",
    "Tahoma", "Segoe UI", "Arial", "DejaVu Sans",
]
DEFAULT_FA_FONT = "B Yaghout"            # default heading + body font whenever the target language is Persian
CUSTOM_FONT_LABEL = "Custom font file…"
SAME_FONT = "(same as original document)"
LATIN_FONTS: List[str] = [SAME_FONT, "Times New Roman", "Arial", "Calibri", "Cambria", "Georgia", "Verdana", "Tahoma",
                          "Segoe UI", "Noto Sans", "Noto Serif", "DejaVu Sans"]
FALLBACK_FONTS = ["Vazirmatn", "Tahoma", "Segoe UI", "Arial", "DejaVu Sans", "Noto Sans"]

# ---------------------------------------------------------------- font lookup
_SYSTEM_INDEX: Optional[Dict[str, Path]] = None


def _norm(s: str) -> str:
    return re.sub(r"[\s_\-]+", "", s.lower())


def _system_font_dirs() -> List[Path]:
    dirs: List[Path] = [FONT_DIR, SCRIPT_FONT_DIR]
    if sys.platform.startswith("win"):
        dirs += [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
                 Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"]
    elif sys.platform == "darwin":
        dirs += [Path("/Library/Fonts"), Path("/System/Library/Fonts"), Path.home() / "Library/Fonts"]
    else:
        dirs += [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
                 Path.home() / ".fonts", Path.home() / ".local/share/fonts"]
    return [d for d in dirs if d.exists()]


def system_font_index(refresh: bool = False) -> Dict[str, Path]:
    global _SYSTEM_INDEX
    if _SYSTEM_INDEX is None or refresh:
        idx: Dict[str, Path] = {}
        for d in _system_font_dirs():
            try:
                for p in d.rglob("*"):
                    if p.suffix.lower() in (".ttf", ".otf"):
                        idx.setdefault(_norm(p.stem), p)
            except OSError:
                continue
        _SYSTEM_INDEX = idx
    return _SYSTEM_INDEX


def _is_bold_stem(stem: str) -> bool:
    return "bold" in stem or stem.endswith("bd")


def find_system_font(prefixes: List[str]) -> Dict[str, Optional[Path]]:
    idx = system_font_index()
    bad = ("light", "thin", "medium", "italic", "oblique", "heavy", "black", "semi", "extra", "condensed", "mono",
           "serif")
    regular = bold = None
    for stem, path in sorted(idx.items(), key=lambda kv: len(kv[0])):
        if not any(stem.startswith(pfx) for pfx in prefixes):
            continue
        if any(b in stem for b in bad):
            continue
        if _is_bold_stem(stem):
            bold = bold or path
        elif "bold" not in stem:
            regular = regular or path
    return {"regular": regular, "bold": bold}


def find_local_font(key: str) -> Dict[str, Optional[Path]]:
    """Exact-name lookup (e.g. 'Vazirmatn' -> Vazirmatn-Regular.ttf / Vazirmatn-Bold.ttf) in the font folders."""
    idx = system_font_index()
    base = _norm(key)
    reg = idx.get(base) or idx.get(base + "regular")
    bold = idx.get(base + "bold") or idx.get(base + "bd")
    return {"regular": reg, "bold": bold}


_NET_STATE: Dict[str, bool] = {}


def internet_available() -> bool:
    """Quick one-off check, so that offline users never wait for font downloads to time out."""
    if "ok" not in _NET_STATE:
        try:
            socket.create_connection(("cdn.jsdelivr.net", 443), timeout=4).close()
            _NET_STATE["ok"] = True
        except OSError:
            _NET_STATE["ok"] = False
    return _NET_STATE["ok"]


def _mirrors(url: str) -> List[str]:
    """GitHub URL -> [original, jsDelivr mirror] (the mirror often works when GitHub is slow / blocked)."""
    m = (re.match(r"https://github\.com/([^/]+)/([^/]+)/raw/([^/]+)/(.+)", url)
         or re.match(r"https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)", url))
    if not m:
        return [url]
    u, r, b, p = m.groups()
    return [url, f"https://cdn.jsdelivr.net/gh/{u}/{r}@{b}/{p}"]


def _download(url: str, dest: Path, log: Callable[[str], None]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last: Optional[Exception] = None
    for u in _mirrors(url):
        try:
            log(f"Downloading font {dest.name} …")
            req = urllib.request.Request(u, headers={"User-Agent": f"{APP_TITLE}/{APP_VERSION}"})
            with urllib.request.urlopen(req, timeout=25) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            if tmp.stat().st_size < 10_000:
                raise RuntimeError("downloaded file is too small")
            tmp.replace(dest)
            return
        except Exception as exc:
            last = exc
            tmp.unlink(missing_ok=True)
            log(f"  could not download from {u.split('/')[2]} ({type(exc).__name__})")
    raise RuntimeError(f"Font download failed ({dest.name}): {last}")


def resolve_font(key: str, log: Callable[[str], None] = print, custom: Optional[str] = None,
                 download: bool = True) -> Dict[str, Optional[Path]]:
    """Return {'regular': Path, 'bold': Path|None} for a font key or a custom file (local files first)."""
    if custom:
        reg = Path(custom)
        if not reg.is_file():
            raise FileNotFoundError(f"Custom font not found: {custom}")
        bold = None
        for cand in (f"{reg.stem}-Bold", f"{reg.stem}Bold", f"{reg.stem}_Bold", f"{reg.stem} Bold",
                     reg.stem.replace("Regular", "Bold")):
            for ext in (reg.suffix, ".ttf", ".otf"):
                p = reg.with_name(cand + ext)
                if p.is_file() and p != reg:
                    bold = p
                    break
            if bold:
                break
        return {"regular": reg, "bold": bold}

    spec = FONT_SPECS[key]
    if "system" in spec:
        found = find_system_font(spec["system"])
        if not found["regular"]:
            raise FileNotFoundError(f"Font '{key}' was not found on this computer.")
        return found

    out = find_local_font(key)
    for weight in ("regular", "bold"):
        if out[weight] or weight not in spec:
            continue
        if not (download and internet_available()):
            continue
        fname, url = spec[weight]
        path = FONT_DIR / fname
        try:
            _download(url, path, log)
            out[weight] = path
        except Exception as exc:
            if weight == "regular":
                raise RuntimeError(str(exc))
            log(f"Bold weight skipped: {exc}")
    if not out["regular"]:
        raise FileNotFoundError(
            f"Font '{key}' is not installed and could not be downloaded. Copy its .ttf files into\n"
            f"  {FONT_DIR}\nor into a 'fonts' folder next to this script (works fully offline), "
            f"or choose another font / 'Custom font file…'.")
    return out


def resolve_font_safe(key: str, log: Callable[[str], None], custom: Optional[str] = None,
                      download: bool = True) -> Dict[str, Optional[Path]]:
    """Like resolve_font, but falls back to a font that ships with the OS so a job never dies because of a font."""
    try:
        return resolve_font(key, log, custom, download)
    except Exception as exc:
        log(f"Warning: {exc}")
        for alt in FALLBACK_FONTS:
            if alt == key:
                continue
            try:
                got = resolve_font(alt, log, None, download)
                log(f"Using fallback font: {alt}")
                return got
            except Exception:
                continue
        raise RuntimeError("No usable font found. Put a Persian .ttf (e.g. Vazirmatn-Regular.ttf) into "
                           f"{FONT_DIR} and try again.")


def font_has_latin(path: Path) -> bool:
    try:
        from fontTools.ttLib import TTFont
        f = TTFont(str(path), lazy=True, fontNumber=0)
        cmap = f.getBestCmap() or {}
        f.close()
        return all(ord(c) in cmap for c in "AaEeRrtT")
    except Exception:
        return True


def render_font_sample(font_path: Path, text: str, rtl: bool = True, min_width: int = 380, height: int = 40,
                       size: float = 15.0) -> bytes:
    """PNG with a sentence typeset in the given font (the sample shown next to the font choice, like Word).
    The picture is as wide as the sentence needs; the window scrolls it sideways."""
    tmp = Path(tempfile.mkdtemp(prefix="pbt_sample_"))
    doc = None
    try:
        ext = font_path.suffix.lower() or ".ttf"
        shutil.copy(font_path, tmp / f"sample{ext}")
        try:
            need = fitz.Font(fontfile=str(tmp / f"sample{ext}")).text_length(text, fontsize=size) * 1.12
        except Exception:
            need = len(text) * size * 0.65
        width = int(max(min_width, need + 24))
        doc = fitz.open()
        page = doc.new_page(width=width, height=height)
        css = f"@font-face{{font-family:sample;src:url(sample{ext});}}"
        markup = (f'<p dir="{"rtl" if rtl else "ltr"}" style="margin:0;font-family:sample;font-size:{size}pt;'
                  f'text-align:{"right" if rtl else "left"};color:#1E293B;">{html.escape(text)}</p>')
        page.insert_htmlbox(fitz.Rect(8, min(4, height / 20), width - 8, height - min(4, height / 20)), markup, css=css,
                            archive=fitz.Archive(str(tmp)))
        return page.get_pixmap(dpi=96, alpha=False).tobytes("png")
    finally:
        if doc is not None:
            doc.close()
        shutil.rmtree(tmp, ignore_errors=True)


def font_family_name(path: Path, fallback: str = "") -> str:
    """Family name stored inside a font file (used to name the font in Word documents)."""
    try:
        from fontTools.ttLib import TTFont
        f = TTFont(str(path), lazy=True, fontNumber=0)
        try:
            for nid in (16, 1):
                for rec in f["name"].names:
                    if rec.nameID == nid:
                        txt = rec.toUnicode().strip()
                        if txt:
                            return txt
        finally:
            f.close()
    except Exception:
        pass
    return fallback or path.stem


# ---------------------------------------------------------------- fonts of the ORIGINAL document
_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")
_STYLE_TAIL = re.compile(r"(bolditalic|boldoblique|bold|italic|oblique|regular|book|light|medium|demi|"
                         r"semibold|black|heavy|psmt|mt|ps)$")
_FONT_SYNONYMS = {"timesnewroman": ["times", "timesnewroman"], "timesnewromanps": ["times", "timesnewroman"],
                  "arialmt": ["arial"], "couriernew": ["cour", "couriernew"], "couriernewps": ["cour", "couriernew"],
                  "calibri": ["calibri", "carlito"], "cambria": ["cambria", "caladea"],
                  "helvetica": ["helvetica", "arial", "liberationsans"], "palatino": ["pala", "palatino"],
                  "georgia": ["georgia"], "verdana": ["verdana"], "tahoma": ["tahoma"]}


def clean_font_name(name: str) -> str:
    """'ABCDEF+TimesNewRomanPS-BoldMT' -> 'timesnewromanps' (family part, lower case, no spaces)."""
    n = _SUBSET_PREFIX.sub("", name or "")
    n = _norm(n)
    for _ in range(4):
        m = _STYLE_TAIL.search(n)
        if not m or m.start() < 3:
            break
        n = n[:m.start()]
    return n


def generic_family(name: str, mono: bool = False) -> str:
    """CSS generic family that matches an original font name (used when the font file is not on this computer)."""
    if mono or MONO_RE.search(name or ""):
        return "monospace"
    if SANS_RE.search(name or ""):
        return "sans-serif"
    if SERIF_RE.search(name or ""):
        return "serif"
    return "sans-serif"


def find_original_font(name: str) -> Optional[Dict[str, Optional[Path]]]:
    """Look for the font that the source document used for a span (so untranslated terms keep their own face)."""
    base = clean_font_name(name)
    if len(base) < 3:
        return None
    prefixes = _FONT_SYNONYMS.get(base, [base])
    try:
        got = find_system_font(prefixes)
    except Exception:
        return None
    return got if got.get("regular") else None


def find_math_font() -> Optional[Dict[str, Optional[Path]]]:
    """A serif font with Greek letters, the common maths symbols and the direction marks (Times New Roman on
    Windows, Liberation Serif / DejaVu Serif on Linux …): regular, bold, italic, bold italic."""
    idx = system_font_index()
    sets = [("times", "timesbd", "timesi", "timesbi"),
            ("timesnewroman", "timesnewromanbold", "timesnewromanitalic", "timesnewromanbolditalic"),
            ("liberationserifregular", "liberationserifbold", "liberationserifitalic", "liberationserifbolditalic"),
            ("dejavuserif", "dejavuserifbold", "dejavuserifitalic", "dejavuserifbolditalic"),
            ("notoserifregular", "notoserifbold", "notoserifitalic", "notoserifbolditalic"),
            ("stixtwotextregular", "stixtwotextbold", "stixtwotextitalic", "stixtwotextbolditalic")]
    for r, b, i, bi in sets:
        if r in idx:
            return {"regular": idx[r], "bold": idx.get(b), "italic": idx.get(i), "bolditalic": idx.get(bi)}
    return None


# ---------------------------------------------------------------- font processing
EXTRA_CHARS = (
    "".join(chr(c) for c in range(0x20, 0x7F)) + "".join(chr(c) for c in range(0xA0, 0x100)) +
    "".join(chr(c) for c in range(0x2010, 0x2030)) + "".join(chr(c) for c in range(0x0660, 0x066A)) +
    "".join(chr(c) for c in range(0x06F0, 0x06FA)) + "\u200c\u200d\u200e\u200f\u060c\u061b\u061f\u066b\u066c\u00ab\u00bb\u2026"
    "\u0391\u0392\u0393\u0394\u03b1\u03b2\u03b3\u03b4\u03bc\u03a9\u03c9\u00b0\u00b1\u00d7\u2212\u2264\u2265\u2248"
)


def make_oblique(src: Path, dst: Path, angle: float = 11.0) -> bool:
    """Synthesise an italic face by shearing every glyph (TrueType outlines). Returns False if not possible."""
    try:
        from fontTools.ttLib import TTFont
        font = TTFont(str(src))
        if "glyf" not in font:           # CFF-based OpenType: cannot be sheared here
            font.close()
            return False
        t = math.tan(math.radians(angle))
        glyf = font["glyf"]
        for name in font.getGlyphOrder():
            g = glyf[name]
            if g.isComposite():
                for c in g.components:
                    if getattr(c, "flags", 0) & 0x0002 and hasattr(c, "x"):     # ARGS_ARE_XY_VALUES
                        c.x = int(round(c.x + c.y * t))
            elif g.numberOfContours > 0:
                coords = g.coordinates
                for i in range(len(coords)):
                    x, y = coords[i]
                    coords[i] = (int(round(x + y * t)), y)
        if "post" in font:
            font["post"].italicAngle = -angle
        if "head" in font:
            font["head"].macStyle = font["head"].macStyle | 2
        if "OS/2" in font:
            os2 = font["OS/2"]
            os2.fsSelection = (os2.fsSelection | 0x01) & ~0x40
        font.save(str(dst))
        font.close()
        return True
    except Exception:
        return False


def subset_font(src: Path, dst: Path, text: str, log: Callable[[str], None]) -> Path:
    """Keep only the glyphs needed for this book (keeps the PDF small).
    Falls back to the complete font if fontTools is not installed."""
    with open(src, "rb") as fh:
        is_cff = fh.read(4) == b"OTTO"
    if is_cff:  # CFF-based OpenType: MuPDF cannot draw re-subsetted CFF, embed it whole
        shutil.copy(src, dst)
        return dst
    try:
        import logging
        logging.getLogger("fontTools").setLevel(logging.ERROR)
        from fontTools import subset as ftsubset
        opts = ftsubset.Options()
        opts.layout_features = ["*"]
        opts.name_IDs = ["*"]
        opts.notdef_outline = True
        opts.hinting = False
        opts.drop_tables = list(set(opts.drop_tables) | {"DSIG"})
        font = ftsubset.load_font(str(src), opts)
        sub = ftsubset.Subsetter(opts)
        extra = ""
        if re.search("[\u0600-\u06ff]", text):
            # Arabic-script text is drawn with the contextual letter forms of the font.  Their code points
            # (Arabic Presentation Forms) must stay in the character table, or the text of the PDF can not be
            # copied, searched or read again (it came out as '\x9e¤8د \x99¦ د£Z').
            extra = "".join(chr(c) for c in list(range(0xFB50, 0xFDFF)) + list(range(0xFE70, 0xFEFF)))
        sub.populate(text=text + EXTRA_CHARS + extra)
        sub.subset(font)
        ftsubset.save_font(font, str(dst), opts)
        font.close()
        return dst
    except Exception as exc:  # pragma: no cover
        log(f"Font subsetting skipped ({type(exc).__name__}: {exc}); embedding the full font.")
        shutil.copy(src, dst)
        return dst


# ════════════════════════════════════════════════════════════════════════════
#  Languages and translation models
# ════════════════════════════════════════════════════════════════════════════
LANGS: Dict[str, dict] = {
    "fa": dict(name="Persian", rtl=True, nllb="pes_Arab", font=None, min_lh=1.0),
    "zh": dict(name="Chinese (Simplified)", rtl=False, nllb="zho_Hans", font=None, min_lh=1.0),  # built-in CJK font
    "hi": dict(name="Hindi", rtl=False, nllb="hin_Deva", font="Noto Sans Devanagari", min_lh=1.4),
    "es": dict(name="Spanish", rtl=False, nllb="spa_Latn", font="Noto Sans", min_lh=1.0),
    "fr": dict(name="French", rtl=False, nllb="fra_Latn", font="Noto Sans", min_lh=1.0),
    "ar": dict(name="Arabic", rtl=True, nllb="arb_Arab", font="Noto Naskh Arabic", min_lh=1.0),
    "bn": dict(name="Bengali", rtl=False, nllb="ben_Beng", font="Noto Sans Bengali", min_lh=1.4),
    "pt": dict(name="Portuguese", rtl=False, nllb="por_Latn", font="Noto Sans", min_lh=1.0),
    "ru": dict(name="Russian", rtl=False, nllb="rus_Cyrl", font="Noto Sans", min_lh=1.0),
    "ur": dict(name="Urdu", rtl=True, nllb="urd_Arab", font="Noto Nastaliq Urdu", min_lh=1.9),
    "id": dict(name="Indonesian", rtl=False, nllb="ind_Latn", font="Noto Sans", min_lh=1.0),
    "de": dict(name="German", rtl=False, nllb="deu_Latn", font="Noto Sans", min_lh=1.0),
    "en": dict(name="English", rtl=False, nllb="eng_Latn", font="Noto Sans", min_lh=1.0),
}
LATIN_LANGS = {"de", "fr", "es", "en", "pt", "id"}       # typeset with the fonts of the original / a Latin font
LANG_SHRINK = {"de": 0.94, "fr": 0.95, "es": 0.95}         # these translations are longer than the English text
HYPHEN_DICT = {"de": "de_DE", "fr": "fr_FR", "es": "es_ES", "en": "en_US"}

# Languages offered in the window.  Only the ticked ones work today; the others are shown (greyed out) because
# they will be added in future versions.
ORIGIN_LANGS: List[Tuple[str, str, bool]] = [("en", "English", True), ("fa", "Persian", True),
                                             ("de", "German", True), ("fr", "French", True),
                                             ("es", "Spanish", True)]
TARGET_LANGS: List[Tuple[str, str, bool]] = [("fa", "Persian", True), ("de", "German", True),
                                             ("fr", "French", True), ("es", "Spanish", True),
                                             ("en", "English", True)]

# label shown in the GUI -> model id (Hugging Face id, or a folder on your disk)
MODELS: Dict[str, str] = {
    "MADLAD-400 3B · Apache-2.0 · best quality (≈12 GB download, once)": "google/madlad400-3b-mt",
    "NLLB-200 1.3B · CC-BY-NC · good (≈5.5 GB, once)": "facebook/nllb-200-distilled-1.3B",
    "NLLB-200 600M · CC-BY-NC · fast / low memory (≈2.5 GB, once)": "facebook/nllb-200-distilled-600M",
}
DEFAULT_MODEL = "google/madlad400-3b-mt"


# ════════════════════════════════════════════════════════════════════════════
#  Options / data classes
# ════════════════════════════════════════════════════════════════════════════
@dataclass
class Options:
    skip_tables: bool = True
    skip_figures: bool = True
    skip_code: bool = True
    skip_backmatter: bool = True
    backmatter_keywords: str = "References, Bibliography, Works Cited, Appendix, Appendices, Glossary, Index"
    translate_captions: bool = True
    translate_bookmarks: bool = True
    keep_terms: bool = True         # technical terms stay as they are (built-in + user glossary)
    justify_body: bool = True       # Justify body text (not headings / captions)
    chunk_pages: int = 20           # layout analysis window (pages that are read together)
    part_pages: int = 2             # pages translated + typeset per part; finished parts are cached and merged at the end
    swap_columns: bool = True       # Persian: two-column pages are mirrored (the first column is the right one)
    split_pages: int = 0            # > 0: a PDF file of its own for every <split_pages> pages (long jobs, slow PCs)
    src_lang: str = "en"            # language of the input document
    engine: str = "local"           # local = built-in MADLAD / NLLB · ollama = local LLM · api = OpenAI-compatible
    llm_model: str = ""             # e.g. gemma3:12b (Ollama) or gpt-4o-mini (online)
    llm_url: str = ""               # server address; empty = the default of the engine
    llm_key: str = ""               # API key of the online service (never written to the log)
    best_quality: bool = False      # beam search (2 candidates per sentence): a little better, about 2x slower
    backmatter_at: Optional[Tuple[int, float]] = None   # found once, used by all parts
    keep_names: bool = True         # proper names and Capitalized (compound) terms stay as they are
    specialties: List[str] = field(default_factory=list)    # up to 4 fields typed by the user (Chemistry, AI …)
    auto_specialty: bool = True     # the app also works out the subject of the book itself
    auto_terms: bool = True         # also keep acronyms, units, identifiers, formulas … as they are
    persian_digits: bool = True
    rtl_direction: bool = True      # Right-To-Left direction for right-to-left target languages (Persian …)
    align_right: bool = True        # Align Right for right-to-left target languages (mirror of Align Left)
    heading_font: str = DEFAULT_FA_FONT     # headings, titles, subtitles
    body_font: str = DEFAULT_FA_FONT        # body text, captions, lists …
    heading_font_file: Optional[str] = None  # custom .ttf / .otf for headings (when heading_font is CUSTOM_FONT_LABEL)
    body_font_file: Optional[str] = None     # custom .ttf / .otf for the body text
    font_scale: float = 1.0         # 1.0 = every size exactly as in the source; 0.8 = 80 % …; 1.2 = 120 %
    out_pdf: bool = True            # output formats (at least one)
    out_docx: bool = False
    out_txt: bool = False
    min_scale: float = 0.5          # smallest allowed font shrink factor when a translation does not fit
    pages: str = ""                 # "" = all, or "1-20, 25"
    model: str = DEFAULT_MODEL
    allow_download: bool = True     # fonts / models may be downloaded once if they are not on the disk
    bilingual_headings: bool = True # sub-headings: Persian heading + English original in brackets
    speed: str = "accurate"         # "accurate" (full layout, default) | "fast" (text only, no typesetting)


# ── the app's own data folder: everything it remembers between two runs ──
HISTORY_FILE = APP_DIR / "history.json"                  # input files that were translated (newest first)
SETTINGS_FILE = APP_DIR / "settings.json"                # the settings of the window
PENDING_FILE = APP_DIR / "pending_job.json"              # a job that was started and has not finished yet
JOBS_DIR = APP_DIR / "jobs"                              # finished parts (2 pages each) of running / interrupted jobs
INSTRUCTIONS_FILE = APP_DIR / "user_instructions.txt"    # "My instructions": how the user wants terms translated


_LP = "\\\\?\\"                 # Windows long-path prefix
_LPU = "\\\\?\\UNC\\"


def long_path(path: str) -> str:
    """Windows may hand over a short 8.3 path (D:\\MYFOLD~1\\DOCUME~1 …): give back the real, readable one."""
    try:
        path = os.path.abspath(str(path))
        if path.startswith(_LPU):
            path = "\\\\" + path[8:]
        elif path.startswith(_LP):
            path = path[4:]
        if os.name == "nt" and "~" in path:
            import ctypes
            buf = ctypes.create_unicode_buffer(32768)
            target = path if os.path.exists(xl(path)) else os.path.dirname(path)
            n = ctypes.windll.kernel32.GetLongPathNameW(target, buf, 32768)
            if 0 < n < 32768:
                path = buf.value if target == path else os.path.join(buf.value, os.path.basename(path))
    except Exception:
        pass
    return str(path)


def output_name(pdf_path: str, lang: str, ext: str, pages_spec: str = "") -> str:
    """Translated_to_fa__<original name>.pdf  (a page selection adds  _pages_3-6)."""
    tail = ""
    if pages_spec.strip():
        tail = "_pages_" + re.sub(r"[^0-9,\-]+", "", pages_spec.replace(" ", "")).strip(",")[:40]
    return f"Translated_to_{lang}__{Path(pdf_path).stem}{tail}{ext}"


def xl(path) -> str:
    """Windows refuses paths of 260 characters or more unless they carry the long-path prefix.  The output folder of a
    deeply nested file plus the long output name easily gets there."""
    path = os.path.abspath(str(path))
    if os.name == "nt" and len(path) >= 240 and not path.startswith("\\\\?\\"):
        return ("\\\\?\\UNC\\" + path[2:]) if path.startswith("\\\\") else ("\\\\?\\" + path)
    return path


def shell_path(path) -> str:
    """Path for other programs (Explorer, the PDF viewer): they can not take 260 characters or more, so a very long
    path is handed over in its short 8.3 form."""
    path = long_path(path)
    if os.name == "nt" and len(path) >= 255:
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(32768)
            n = ctypes.windll.kernel32.GetShortPathNameW(xl(path), buf, 32768)
            if 0 < n < 32768:
                v = buf.value
                return ("\\\\" + v[8:]) if v.startswith(_LPU) else v[4:] if v.startswith(_LP) else v
        except Exception:
            pass
    return path


def is_file(path) -> bool:
    return bool(path) and os.path.isfile(xl(path))


def exists(path) -> bool:
    return bool(path) and os.path.exists(xl(path))


MAX_OUT_PATH = 250          # longer paths can be written by this app, but PDF viewers / Word can not open them


def fit_output_path(out_dir: str, name: str, log: Optional[Callable[[str], None]] = None) -> str:
    """Full path of an output file.  If it would be too long for Windows programs, the original file name inside
    it is shortened (the folder and 'Translated_to_xx__' stay)."""
    full = os.path.join(str(out_dir), name)
    over = len(full) - MAX_OUT_PATH
    if over <= 0:
        return full
    stem, ext = os.path.splitext(name)
    m = re.match(r"(Translated_to_[a-z]+__)(.*?)(_pages_[0-9,\-]+)?$", stem)
    head, core, tail = (m.group(1), m.group(2), m.group(3) or "") if m else ("", stem, "")
    core = core[:max(8, len(core) - over)].rstrip(" ._-")
    short = os.path.join(str(out_dir), head + core + tail + ext)
    if log and short != full:
        log(f"Note: the folder path is very long, so the output file name was shortened to “{Path(short).name}” "
            f"(Windows programs can not open paths longer than 260 characters).")
    return short


def is_locked(path) -> bool:
    """True if the file exists and can not be overwritten now (it is open in a PDF viewer / Word …)."""
    path = xl(path)
    if not os.path.exists(path):
        return False
    try:
        with open(path, "ab"):
            pass
        return False
    except OSError:
        return True


def free_name(path) -> Path:
    """book.pdf -> book_01.pdf, book_02.pdf …: the first name that does not exist yet."""
    path = Path(path)
    for k in range(1, 1000):
        cand = path.with_name(f"{path.stem}_{k:02d}{path.suffix}")
        if not os.path.exists(xl(cand)):
            return cand
    return path.with_name(f"{path.stem}_{int(time.time())}{path.suffix}")


def save_with_fallback(dst: str, write: Callable[[str], None], log: Callable[[str], None],
                       quiet: bool = False) -> Optional[str]:
    """Writes an output file.  The file is first written to a short temporary path (the PDF library can not write
    to very long paths) and then copied to its place.  If a file with this name is open in another program, the
    result is saved next to it with an index (_01, _02 …) – a finished translation is never lost.
    quiet=True (intermediate update of the growing file): a locked file is simply skipped -> None."""
    import shutil
    dst = str(dst)
    tmp_dir = JOBS_DIR / "_out"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / f"{os.getpid()}_{int(time.time() * 1000)}{Path(dst).suffix}"
    try:
        write(str(tmp))
        os.makedirs(xl(Path(dst).parent), exist_ok=True)
        try:
            shutil.copyfile(str(tmp), xl(dst))
            return dst
        except PermissionError:
            if quiet:
                return None
        alt = str(free_name(dst))
        log(f"Warning: “{Path(dst).name}” is open in another program and can not be overwritten – "
            f"saved as “{Path(alt).name}” instead.")
        shutil.copyfile(str(tmp), xl(alt))
        return alt
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def load_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text("utf-8"))
    except Exception:
        return default


def save_json(path: Path, data) -> None:
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        tmp = Path(path).with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(path)
    except Exception:
        pass


def add_history(pdf_path: str, outputs: List[str], langs: List[str]) -> None:
    """Called when a job starts (no outputs yet) and again when it has finished."""
    hist = [h for h in load_json(HISTORY_FILE, []) if isinstance(h, dict)]
    hist = [h for h in hist if not (h.get("input") == long_path(pdf_path) and not h.get("outputs")
                                    and h.get("langs") == langs)]
    hist.insert(0, {"input": long_path(pdf_path), "outputs": [long_path(o) for o in outputs], "langs": langs,
                    "time": time.strftime("%Y-%m-%d %H:%M")})
    save_json(HISTORY_FILE, hist[:300])


def job_cache_dir(pdf_path: str, lang: str, opts: "Options") -> Path:
    """Folder of the finished parts of ONE job (same file, language and settings).  Starting the same job again
    continues after the last finished part."""
    import dataclasses
    d = dataclasses.asdict(opts)
    for k in ("pages", "out_pdf", "out_docx", "out_txt", "allow_download", "chunk_pages", "backmatter_at"):
        d.pop(k, None)
    try:
        st = os.stat(xl(pdf_path))
        sig = f"{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        sig = ""
    extra = ""
    for f in (GLOSSARY_FILE, INSTRUCTIONS_FILE):
        try:
            extra += f.read_text("utf-8")
        except Exception:
            pass
    key = json.dumps([long_path(pdf_path), sig, lang, d, APP_BUILD, hashlib.sha1(extra.encode("utf-8")).hexdigest()],
                     sort_keys=True, default=str)
    return JOBS_DIR / hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]


def purge_old_jobs(days: int = 30) -> None:
    try:
        limit = time.time() - days * 86400
        for d in JOBS_DIR.iterdir():
            if d.is_dir() and d.stat().st_mtime < limit:
                import shutil
                shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass


# ── "My instructions": the user teaches the app how to translate (or not translate) words and phrases ──
_FA_CH = re.compile(r"[\u0600-\u06FF]")
_QUOTES = "\"'“”‘’«»`"


def _unq(t: str) -> str:
    return t.strip().strip(_QUOTES).strip().rstrip(".،,;").strip().strip(_QUOTES).strip()


GLOSS_KINDS = ("fa", "de", "fr", "es", "en")   # "<language> | term = translation": a fixed translation


def parse_instruction(text: str) -> Optional[Tuple[str, str, str]]:
    """One sentence of the user -> (kind, english, translation).
        kind 'fa' / 'de' : always translate <english> as <translation> in this target language
        kind 'keep'      : never translate <english> (it stays in English)
        kind 'translate' : always translate <english> (even if a term list says it should stay English)
    Understood forms (English or Persian):
        X = Y        X -> Y        translate X as Y        X means Y        X را Y ترجمه کن        X یعنی Y
        keep X       don't translate X        X را ترجمه نکن
        translate X  X را ترجمه کن"""
    t = text.strip()
    if not t or t.startswith("#"):
        return None
    m = re.fullmatch(r"(fa|de|fr|es|en|keep|translate)\s*\|\s*(.+)", t, re.I)            # the stored form
    if m:
        kind, rest = m.group(1).lower(), m.group(2)
        if kind in GLOSS_KINDS:
            if "=" not in rest:
                return None
            en, tr = (_unq(x) for x in rest.split("=", 1))
            return (kind, en, tr) if en and tr else None
        return (kind, _unq(rest), "") if _unq(rest) else None
    pair = None
    for rx in (r"(?:please\s+)?translate\s+(.+?)\s+(?:as|to|into)\s+(.+)",
               r"(.+?)\s+(?:should be translated as|must be translated as|is translated as|means)\s+(.+)",
               r"(?:معنی|ترجمه)\s*[‌ ]?(?:ی)?\s+(.+?)\s+(?:می\s*شود|میشه|هست|است|یعنی|:)\s*(.+)",
               r"(?:به\s*جای)\s+(.+?)\s+(?:بنویس|بگذار|بذار)\s+(.+)",
               r"(.+?)\s+را\s+(?:به\s*صورت\s+|به\s+)?(.+?)\s+ترجمه\s+کن(?:ید)?\.?",
               r"(.+?)\s+(?:یعنی|=>|->|→|==|=)\s+(.+)", r"(.+?)\s*(?:=>|->|→|=)\s*(.+)"):
        m = re.fullmatch(rx, t, re.I)
        if m:
            pair = (_unq(m.group(1)), _unq(m.group(2)))
            break
    if pair and pair[0] and pair[1]:
        a, b = pair
        if _FA_CH.search(a) and not _FA_CH.search(b):       # the translation was written first
            a, b = b, a
        if not _FA_CH.search(a):
            return ("fa" if _FA_CH.search(b) else "de", a, b)
    for rx in (r"(?:please\s+)?(?:do\s*n[o']?t|don’t|never)\s+translate\s+(.+)", r"keep\s+(.+?)(?:\s+(?:as it is|in english|unchanged|original))?",
               r"(.+?)\s+را\s+ترجمه\s+نکن(?:ید)?\.?", r"(.+?)\s+(?:ترجمه\s+نشود|ترجمه\s+نشه|انگلیسی\s+بماند|انگلیسی\s+بمونه)\.?"):
        m = re.fullmatch(rx, t, re.I)
        if m and _unq(m.group(1)) and not _FA_CH.search(_unq(m.group(1))):
            return ("keep", _unq(m.group(1)), "")
    for rx in (r"(?:please\s+)?(?:always\s+)?translate\s+(.+)", r"(.+?)\s+را\s+ترجمه\s+کن(?:ید)?\.?"):
        m = re.fullmatch(rx, t, re.I)
        if m and _unq(m.group(1)) and not _FA_CH.search(_unq(m.group(1))):
            return ("translate", _unq(m.group(1)), "")
    return None


def format_instruction(ins: Tuple[str, str, str]) -> str:
    kind, en, tr = ins
    return f"{kind} | {en} = {tr}" if kind in GLOSS_KINDS else f"{kind} | {en}"


def load_instructions_text() -> str:
    try:
        return INSTRUCTIONS_FILE.read_text("utf-8")
    except Exception:
        return ""


def save_instructions_text(text: str) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    INSTRUCTIONS_FILE.write_text(text.strip() + "\n", "utf-8")


def load_instructions() -> List[Tuple[str, str, str]]:
    out = []
    for line in load_instructions_text().splitlines():
        ins = parse_instruction(line)
        if ins:
            out.append(ins)
    return out


def add_instructions(new: List[Tuple[str, str, str]]) -> None:
    """Adds / replaces instructions (the newest instruction about a term wins)."""
    if not new:
        return
    keys = {i[1].lower() for i in new}
    lines = []
    for line in load_instructions_text().splitlines():
        ins = parse_instruction(line)
        if ins and ins[1].lower() in keys and (ins[0] not in ("fa", "de") or
                                                  any(n[0] == ins[0] or n[0] in ("keep", "translate")
                                                      for n in new if n[1].lower() == ins[1].lower())):
            continue
        lines.append(line)
    lines += [format_instruction(i) for i in new]
    save_instructions_text("\n".join(lines))


# ── learned timing: every finished part teaches the app how long a page takes on THIS computer ──
TIMING_FILE = APP_DIR / "timing_history.json"


def _timing_key(opts: "Options", lang: str) -> str:
    fmt = "txt" if opts.speed == "fast" else ("pdf" if opts.out_pdf else "") + ("docx" if opts.out_docx else "")
    return f"{engine_tag(opts)}|{opts.src_lang}>{lang}|{opts.speed}|{fmt or 'txt'}" + \
        ("|bq" if opts.best_quality and opts.engine == "local" else "|g")


def load_timing() -> List[dict]:
    try:
        return json.loads(TIMING_FILE.read_text("utf-8"))
    except Exception:
        return []


def record_timing(opts: "Options", lang: str, pages: int, seconds: float) -> None:
    if pages <= 0 or seconds <= 0:
        return
    try:
        hist = load_timing()
        hist.append({"key": _timing_key(opts, lang), "pages": pages, "sec": round(seconds, 1)})
        hist = hist[-2000:]
        APP_DIR.mkdir(parents=True, exist_ok=True)
        tmp = TIMING_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(hist), "utf-8")
        tmp.replace(TIMING_FILE)
    except Exception:
        pass


def predicted_sec_per_page(opts: "Options", lang: str) -> Tuple[Optional[float], int]:
    """(seconds per page, number of earlier parts it is based on): the average of ALL earlier translations done
    on this computer with the same settings."""
    rec = [r for r in load_timing() if r.get("key") == _timing_key(opts, lang)]
    pg = sum(r["pages"] for r in rec)
    if not rec or pg <= 0:
        return None, 0
    return sum(r["sec"] for r in rec) / pg, len(rec)


def fmt_dur(sec: float) -> str:
    sec = int(max(0, sec))
    if sec < 60:
        return f"{sec} s"
    if sec < 3600:
        return f"{sec // 60} min"
    return f"{sec // 3600} h {sec % 3600 // 60:02d} min"


@dataclass
class Run:
    """A stretch of text with one uniform style (one or more PDF spans)."""
    text: str
    size: float
    bold: bool
    italic: bool
    color: str
    mono: bool = False
    va: str = ""                    # "", "sup", "sub"
    font: str = ""                  # name of the original PDF font (kept terms are typeset with it)
    bbox: Optional[Tuple[float, float, float, float]] = None   # place on the page (one-line runs only)
    img: Optional[Tuple[int, float, float, float, float]] = None   # (page, x0, y0, x1, y1): paste as a picture
    parts: Optional[List["Run"]] = None   # inline maths: the original runs (θ, x + sub i …) kept and re-typed as they are

    def key(self) -> tuple:
        return (self.size, self.bold, self.italic, self.color, self.mono, self.va)


@dataclass
class Para:
    page: int
    bbox: Tuple[float, float, float, float]
    text: str
    size: float
    bold: bool
    italic: bool
    color: str
    align: str          # left | right | center | justify
    lh: float           # line height / font size
    n_lines: int
    mono: bool = False
    serif: bool = False
    runs: List[Run] = field(default_factory=list)
    skip: Optional[str] = None   # reason, or None if it will be translated
    font: str = ""               # dominant original font name
    indent: float = 0.0          # first-line indent (pt) of the original paragraph ("Tab")
    heading: bool = False        # heading / title / subtitle (False = body text, captions, lists …)
    bars: List[Tuple[float, float, float, float]] = field(default_factory=list)   # fraction bars (drawn lines)
    moved: bool = False          # put at another place by hand in the review window
    dh: float = 0.0              # review window: extra height of the block (the content below was pushed down)
    lh_mult: float = 1.0         # review window: line spacing factor of the block
    title: bool = False          # THE title of the article / book: its original is written under the translation
    members: List[Tuple[float, float, float, float]] = field(default_factory=list)   # boxes of one whole equation
    erase: List[Tuple[float, float, float, float]] = field(default_factory=list)     # box of every original span


# ════════════════════════════════════════════════════════════════════════════
#  PDF analysis (text extraction + classification)
# ════════════════════════════════════════════════════════════════════════════
LIGATURES = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl",
             "\ufb05": "st", "\ufb06": "st", "\u00a0": " ", "\u200b": ""}
MONO_RE = re.compile(r"(mono|courier|consolas|typewriter|menlo|inconsolata|code|lucida\s*console|cmtt)", re.I)
ITALIC_RE = re.compile(r"(italic|oblique|slanted|kursiv|cmti|cmsl|cmbxti|-it$|-ital|,it$)", re.I)
BOLD_RE = re.compile(r"(bold|black|heavy|semibold|demi|cmbx|-bd$)", re.I)
SERIF_RE = re.compile(r"(times|serif|roman|minion|garamond|palatino|georgia|cambria|cmr|cmbx|cmti|charter|"
                      r"baskerville|bookman|century|utopia|nimbus\s*rom|libertine|computer\s*modern|lmroman|stix)", re.I)
SANS_RE = re.compile(r"(sans|arial|helvet|calibri|verdana|tahoma|segoe|roboto|open\s*sans|lato|gothic|cmss|"
                     r"myriad|futura|frutiger|univers|optima|lmsans)", re.I)
CAPTION_RE = re.compile(r"^(?:figure|fig\.|table|chart|graph|plate|scheme|listing|exhibit)\s+[\dA-Z][\d.\-A-Za-z]*"
                        r"\s*[:.\-–—]", re.I)


def _clean(text: str) -> str:
    for k, v in LIGATURES.items():
        text = text.replace(k, v)
    return re.sub(r"\s+", " ", text).strip()


_CTRL_RE = re.compile("[\u0000-\u0008\u000b-\u001f\u007f-\u009f\ufffd\u200b\u2060\ufeff]")
_SPACE_RE = re.compile("[\u00a0\u2000-\u200a\u202f\u205f\u3000]")


_BAD_MATH_RE = re.compile("[\ud400-\ud7cb]")
_PRES_RE = re.compile("[\ufb50-\ufdff\ufe70-\ufefe]+")
_AR2FA_READ = {ord("ي"): "ی", ord("ك"): "ک", ord("ى"): "ی"}


def _fix_lig(text: str) -> str:
    """Ligatures expanded; control characters removed (Springer puts a BEL between a heading number and its title:
    it was typeset as a '�' box); special spaces and the non-breaking hyphen become normal characters."""
    for k, v in LIGATURES.items():
        text = text.replace(k, v)
    if _PRES_RE.search(text):
        # Arabic Presentation Forms (one code point per contextual form, many Persian PDFs use them): back to the
        # ordinary letters, which the translation models know
        text = _PRES_RE.sub(lambda m: unicodedata.normalize("NFKC", m.group()), text).translate(_AR2FA_READ)
    if _BAD_MATH_RE.search(text):
        # a PDF whose character table lost the high part of U+1D400…U+1D7FF (maths italic θ, β …): the letters
        # arrive as U+D4xx…U+D7xx (Korean syllables) and were printed as wrong glyphs.  Put the real letter back.
        text = _BAD_MATH_RE.sub(lambda m: unicodedata.normalize("NFKC", chr(0x10000 + ord(m.group()))), text)
    return _CTRL_RE.sub("", _SPACE_RE.sub(" ", text)).replace("\u2011", "-")


def parse_pages(spec: str, n: int) -> Set[int]:
    if not spec.strip():
        return set(range(n))
    spec = re.sub(r"\s*(?:[–—_]|\bto\b|\buntil\b)\s*", "-", spec.strip(), flags=re.I)      # 41–44, 41_44, 41 to 44
    spec = re.sub(r"\s*-\s*", "-", spec)
    pages: Set[int] = set()
    for part in re.split(r"[,\s;]+", spec.strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise ValueError(f"Invalid page range: {part!r}")
        a, b = int(m[1]), int(m[2] or m[1])
        if a > b:
            a, b = b, a
        pages.update(range(max(a, 1) - 1, min(b, n)))
    if not pages:
        raise ValueError("The page range selects no pages.")
    return pages


def _is_bold(span: dict) -> bool:
    return bool(span["flags"] & 16) or bool(BOLD_RE.search(span["font"]))


def _is_italic(span: dict) -> bool:
    return bool(span["flags"] & 2) or bool(ITALIC_RE.search(span["font"]))


def _is_mono(span: dict) -> bool:
    return bool(span["flags"] & 8) or bool(MONO_RE.search(span["font"]))


def _is_serif(span: dict) -> bool:
    name = span["font"]
    if SANS_RE.search(name):
        return False
    return bool(span["flags"] & 4) or bool(SERIF_RE.search(name))


SRC_RTL = [False]          # the document that is being read is written from right to left (Persian, Arabic)


def _ltr_view(lines: List[dict]) -> List[dict]:
    """Right-to-left originals: the same lines seen in a mirror, so that 'left' means 'where a line starts' and
    the rules for paragraphs and alignment (written for left-to-right text) hold unchanged."""
    if not SRC_RTL[0]:
        return lines
    return [dict(l, bbox=(-l["bbox"][2], l["bbox"][1], -l["bbox"][0], l["bbox"][3]), _orig=l) for l in lines]


def _ltr_view_force(lines: List[dict]) -> List[dict]:
    return [dict(l, bbox=(-l["bbox"][2], l["bbox"][1], -l["bbox"][0], l["bbox"][3]), _orig=l) for l in lines]


def _split_block(lines: List[dict]) -> List[List[dict]]:
    """Split a MuPDF block into real paragraphs."""
    if len(lines) == 1:
        return [lines]
    if SRC_RTL[0]:
        SRC_RTL[0] = False
        try:
            return [[l["_orig"] for l in g] for g in _split_block(_ltr_view_force(lines))]
        finally:
            SRC_RTL[0] = True
    size = statistics.median(l["size"] for l in lines) or 10
    left = min(l["bbox"][0] for l in lines)
    right = max(l["bbox"][2] for l in lines)
    body = lines[:-1]
    justified = sum(1 for l in body if right - l["bbox"][2] < 3) >= 0.6 * len(body)
    groups = [[lines[0]]]
    for prev, cur in zip(lines, lines[1:]):
        gap = cur["bbox"][1] - prev["bbox"][3]
        new = gap > 0.55 * size or cur["bbox"][1] < prev["bbox"][1] + 0.3 * size  # new row, or same row
        if not new and justified and prev["bbox"][2] < right - 1.5 * size:
            new = True
        if not new and cur["bbox"][0] - left > 0.8 * size and abs(prev["bbox"][0] - left) < 0.5 * size:
            new = True
        if new:
            groups.append([cur])
        else:
            groups[-1].append(cur)
    return groups


def _alignment(lines: List[dict], page_rect) -> str:
    if SRC_RTL[0] and len(lines) > 1:
        # mirrored: the result 'left' then means "starts at the reading side" – which is the left side again in
        # the left-to-right translation
        SRC_RTL[0] = False
        try:
            return _alignment(_ltr_view_force(lines), page_rect)
        finally:
            SRC_RTL[0] = True
    if len(lines) == 1:
        x0, _, x1, _ = lines[0]["bbox"]
        c = (x0 + x1) / 2
        pc = (page_rect.x0 + page_rect.x1) / 2
        if abs(c - pc) < 0.02 * page_rect.width and x0 > page_rect.x0 + 0.12 * page_rect.width:
            return "center"
        return "left"
    rest = lines[1:]  # ignore first-line indent
    lefts = [l["bbox"][0] for l in rest]
    rights = [l["bbox"][2] for l in lines[:-1]]
    centers = [(l["bbox"][0] + l["bbox"][2]) / 2 for l in lines]
    tol = 2.5
    left_ok = max(lefts) - min(lefts) < tol
    right_ok = max(rights) - min(rights) < tol
    if left_ok and right_ok and len(lines) > 2:
        return "justify"                # also a justified paragraph that goes on in the next column (all lines full)
    if left_ok and right_ok and abs(lines[0]["bbox"][0] - lines[-1]["bbox"][0]) < tol:
        return "left"
    if max(centers) - min(centers) < tol:
        return "center"
    if right_ok and not left_ok:
        return "right"
    return "left"


def _append_run(runs: List[Run], r: Run) -> None:
    if not r.text:
        return
    if runs and runs[-1].key() == r.key():
        runs[-1].text += r.text
        a, b = runs[-1].bbox, r.bbox
        same_line = a and b and min(a[3], b[3]) - max(a[1], b[1]) > 0.3 * min(a[3] - a[1], b[3] - b[1])
        runs[-1].bbox = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])) if same_line else None
    else:
        runs.append(r)


_CMEX_MAP = str.maketrans({"P": "∑", "X": "∑", "Q": "∏", "Y": "∏", "R": "∫", "Z": "∫", "S": "∮", "H": "∮",
                           "q": "√", "r": "√", "s": "√", "t": "√"})


def build_runs(grp: List[dict]) -> List[Run]:
    """Turn the spans of a paragraph (several lines) into style runs, joining lines like a typesetter would."""
    runs: List[Run] = []
    for li, ln in enumerate(grp):
        spans = [s for s in ln["all"] if s["text"]]
        real = [s for s in spans if s["text"].strip()]
        if not real:
            continue
        big = max(real, key=lambda s: s["size"])
        base_y, big_size = big["origin"][1], big["size"]
        if li > 0 and runs:
            first = real[0]["text"].lstrip()[:1]
            last = runs[-1].text
            if last.endswith("\u00ad"):
                runs[-1].text = last[:-1]
            elif last.endswith("-") and len(last) > 1 and last[-2].isalpha() and first.islower():
                runs[-1].text = last[:-1]
            elif not last.endswith(" "):
                runs[-1].text += " "
        # the baseline of the line = the baseline that carries most of its characters
        bw: collections.Counter = collections.Counter()
        for s in real:
            bw[round(s["origin"][1], 1)] += len(s["text"].strip())
        base_y = bw.most_common(1)[0][0] if bw else base_y
        for s in spans:
            va = ""
            t_ = s["text"].strip()
            if t_:
                dy = base_y - s["origin"][1]
                small = s["size"] < 0.9 * big_size
                if dy > (0.15 if small else 0.28) * s["size"] and (small or len(t_) <= 12):
                    va = "sup"
                elif dy < -(0.15 if small else 0.28) * s["size"] and (small or len(t_) <= 12):
                    va = "sub"
            if "CMEX" in s.get("font", "").upper():           # TeX big operators without a Unicode map: P -> ∑ …
                s = dict(s, text=s["text"].translate(_CMEX_MAP))
            _append_run(runs, Run(_fix_lig(s["text"]), round(s["size"], 1), _is_bold(s), _is_italic(s),
                                  f"#{s['color'] & 0xFFFFFF:06x}", _is_mono(s), va, s.get("font", ""),
                                  tuple(s["bbox"]) if s.get("bbox") and s["text"].strip() else None))
    # normalise white space (also across run borders)
    prev_space = True
    for r in runs:
        t = re.sub(r"\s+", " ", r.text)
        if prev_space and t.startswith(" "):
            t = t[1:]
        r.text = t
        if t:
            prev_space = t.endswith(" ")
    while runs and not runs[-1].text.strip():
        runs.pop()
    if runs:
        runs[-1].text = runs[-1].text.rstrip()
    merged: List[Run] = []
    for r in runs:
        _append_run(merged, r)
    return merged


def dominant_style(runs: List[Run]) -> Run:
    w: collections.Counter = collections.Counter()
    for r in runs:
        w[r.key()[:5]] += sum(c.isalpha() for c in r.text) or 0.01
    (size, bold, italic, color, mono), _ = w.most_common(1)[0]
    return Run("", size, bold, italic, color, mono)


def dominant_font(runs: List[Run]) -> str:
    w: collections.Counter = collections.Counter()
    for r in runs:
        if r.font:
            w[r.font] += sum(c.isalpha() for c in r.text) or 0.01
    return w.most_common(1)[0][0] if w else ""


def first_line_indent(grp: List[dict]) -> float:
    """Indent of the first line compared with the other lines of the paragraph (a "Tab"), in points."""
    if len(grp) < 2:
        return 0.0
    left = min(l["bbox"][0] for l in grp[1:])
    ind = grp[0]["bbox"][0] - left
    size = grp[0]["size"] or 10
    return round(ind, 1) if 0.6 * size <= ind <= 6 * size else 0.0


def is_heading_para(p: Para, body: float) -> bool:
    """Heading / title / subtitle (they get the 'Heading font'); everything else is body text."""
    if p.mono or CAPTION_RE.match(p.text):
        return False
    words = len(p.text.split())
    if p.size >= body * 1.12 and p.n_lines <= 4:
        return True
    if p.bold and p.n_lines <= 2 and words <= 14 and p.size >= body * 0.97:
        return True
    letters = [c for c in p.text if c.isalpha()]
    return bool(letters) and p.n_lines == 1 and words <= 10 and p.size >= body * 0.97 and is_allcaps(p.text)


def mark_text_grid_tables(paras: List[Para], obstacles: list) -> None:
    """Fallback table detector for tables without ruling lines: >=3 consecutive rows of >=2 short,
    single-line cells whose left edges line up in columns."""
    cells = [p for p in paras if not p.skip and p.n_lines == 1 and len(p.text.split()) <= 10]
    cells.sort(key=lambda p: (p.bbox[1] + p.bbox[3]) / 2)
    rows: List[List[Para]] = []
    for p in cells:
        yc = (p.bbox[1] + p.bbox[3]) / 2
        if rows and abs(yc - statistics.mean((q.bbox[1] + q.bbox[3]) / 2 for q in rows[-1])) <= 2.5:
            rows[-1].append(p)
        else:
            rows.append([p])
    rows = [sorted(r, key=lambda q: q.bbox[0]) for r in rows]
    multi = [r for r in rows if len(r) >= 2]
    run: List[List[Para]] = []

    def flush() -> None:
        if len(run) >= 3:
            x0 = min(q.bbox[0] for r in run for q in r); x1 = max(q.bbox[2] for r in run for q in r)
            y0 = min(q.bbox[1] for r in run for q in r); y1 = max(q.bbox[3] for r in run for q in r)
            box = fitz.Rect(x0 - 1, y0 - 1, x1 + 1, y1 + 1)
            for q in paras:
                c = fitz.Rect(q.bbox)
                if not q.skip and q.n_lines == 1 and box.contains(c):
                    q.skip = "table"
            obstacles.append(box)

    for r in multi:
        if run:
            prev = run[-1]
            gap = min(q.bbox[1] for q in r) - max(q.bbox[3] for q in prev)
            common = sum(1 for a in r for b in prev if abs(a.bbox[0] - b.bbox[0]) <= 3)
            if gap <= 3.5 * r[0].size and common >= 2:
                run.append(r)
                continue
            flush()
            run.clear()
        run.append(r)
    flush()


# Regions of the page that must be copied as pictures into Word files: tables, figures / graphs, formulas
REGIONS: Dict[int, List[Tuple[str, tuple]]] = {}


MATHFONT_RE = re.compile(r"CMMI|CMSY|CMEX|CMMIB|MSBM|MSAM|MTMI|MTSY|MTEX|MT-?Extra|STIXMath|STIXSize|STIXVar|"
                         r"STIXIntegral|STIXNonUni|Mathematica|LMMath|Cambria ?Math|XITSMath|EuclidMath|EuclidSymbol",
                         re.I)       # NOT STIXGeneral / STIX-Regular / Times: those are the text fonts of many journals
MATHITALIC_RE = re.compile(r"Italic|Oblique|Math|CMMI|CMSY|CMEX", re.I)
_MATH_SIGNS = re.compile(r"[=≈≠≤≥∑∫√∂∇∞∈∀∃±∝←→⇒⟨⟩|‖]")
_MATHFUNCS = frozenset("exp log sin cos tan max min lim arg det sup inf sinh cosh tanh ln mod".split())
_LONG_WORD = re.compile(r"\b[a-z]{4,}\b")
_STOPWORDS = frozenset("a an the is are was were be been of in on at to for by with as and or that this these those from "
                       "where which when if then than it its we our can may let given such not no each both into over "
                       "under between using used has have had do does thus hence so but also only".split())


def _stopwords(t: str) -> int:
    return sum(1 for w in re.findall(r"[A-Za-z]+", t) if w.lower() in _STOPWORDS)


# two real words next to each other at the END of the line (the line then ends with a letter, a hyphenated word or
# sentence punctuation – not with an equation number or a bracket): running text that only starts with maths
_PROSE_TAIL = re.compile(r"\b[a-z]{5,}\s+(?:[a-z]{1,3}\s+)*[a-z]{3,}(?:\s+[a-z]+)*[-.,;:]?\s*$")


def looks_like_formula(text: str, math_chars: int = 0) -> bool:
    """A displayed equation: set in a maths font, or built from '=', sums, integrals … with hardly any real words
    (and often a number in brackets at its end).  Such a block is never translated."""
    t = text.strip()
    if not t:
        return False
    if len(re.findall(r"[\u0600-\u06ff]{3,}", t)) >= 3:
        return False                                  # Persian / Arabic running text
    words = _LONG_WORD.findall(t)
    if len(words) >= 7:
        return False                                  # real sentences (inline maths inside them is fine)
    if _PROSE_TAIL.search(t):
        return False                                  # '… ∈ R4 represents the corresponding dis-': a line of a sentence
    sw = _stopwords(t)
    if sw == 0 and len(t) <= 220 and not [w for w in re.findall(r"[A-Za-z]{3,}", t) if w.lower() not in _MATHFUNCS] \
            and (re.search(r"[=<>≈≠≤≥∈∑∫∏∂∇±+−]", t) or re.search(r"\(\d+\)\s*$", t)) and re.search(r"[A-Za-z0-9]", t):
        return True                                   # no real word at all, only symbols / letters / numbers
    if sw >= 3 or (sw >= 2 and math_chars < 0.5 * len(t)):
        return False                                  # "… is the Two-norm formula": a sentence, not an equation
    if math_chars >= 0.3 * len(t) and len(words) <= 5:
        return True
    if _MATH_SIGNS.search(t) and len(words) <= 2 and len(t.split()) <= 40:
        return True
    return bool(re.search(r"\(\d{1,3}\)\s*$", t) and "=" in t and len(words) <= 3 and len(t) < 160)


def _formula_line(l: dict) -> bool:
    t = l["text"].strip()
    if not t or l["rotated"]:
        return False
    mc = sum(len(s["text"]) for s in l["spans"] if MATHFONT_RE.search(s.get("font", "")))
    sw = _stopwords(t)
    if sw >= 3 or (sw >= 2 and mc < 0.5 * len(t)):
        return False                                  # a line of a sentence (it only contains maths)
    if looks_like_formula(t, mc):
        return True
    chars = sum(len(s["text"].strip()) for s in l["spans"]) or 1
    mi = sum(len(s["text"].strip()) for s in l["spans"] if MATHITALIC_RE.search(s.get("font", "")))
    if mi >= 0.6 * chars and len(t) <= 70 and len(_LONG_WORD.findall(t)) <= 3 and re.search(r"[=+−∑∫(]", t):
        return True                                   # a line that is almost only math-italic letters
    return len(t) <= 16 and sum(c.isalpha() for c in t) <= 0.5 * len(t) and bool(re.search(r"[A-Za-z]", t)) \
        and bool(re.search(r"[()=+∈∑∫\-−×/^|]", t))


_NEUTRAL_RUN = re.compile(r"[\s(),;=+\-−×·/|:.]*")
# Greek letters, letter-like symbols (ℝ ℕ ℓ), arrows, maths operators, maths alphanumerics, private-use maths glyphs
_GREEK_RUN = re.compile("[Ͱ-Ͽ℀-⅏←-⇿∀-⋿⟀-⟿⨀-⫿"
                        "\U0001d400-\U0001d7ff-]+")


def _mathy(r: Run) -> bool:
    """A run that is maths: set in a maths font, a Greek letter / maths symbol, a sub- or superscript, a single
    italic letter (x, y, n …) or a single bold letter (a vector: x, r)."""
    t = r.text.strip()
    if not t or r.mono:
        return False
    if r.va and len(t) <= 12 and not re.search(r"[A-Za-z]{4,}", t):
        return True                                       # x², w_ij, 10⁻⁴ (not a long superscripted word)
    if MATHFONT_RE.search(r.font or "") and not re.search(r"[A-Za-z]{4,}", t):
        return True
    if r.bold and len(t) == 1 and t.isalpha():
        return True                                       # a vector
    return bool(_GREEK_RUN.fullmatch(t.replace(" ", ""))
                or (r.italic and len(t) <= 3 and re.fullmatch("[A-Za-zͰ-Ͽ\U0001d400-\U0001d7ff][\\w′']?", t)))


# what may stand BETWEEN two maths runs of one expression: operators, brackets, digits, Greek letters, exp / log …
_MATH_GLUE = re.compile("[\\s\\d()=+\\-−×·/|.\\[\\]{}<>≤≥≈≠∈∉⊂⊆∪∩±∓∗∘′'^_!‖:"
                        "Ͱ-Ͽ℀-⅏←-⇿∀-⋿⟀-⟿⨀-⫿"
                        "\U0001d400-\U0001d7ff]*")


def _glue(t: str, depth: int = 0) -> bool:
    """Text between two maths runs that belongs to the expression.  Inside brackets commas / semicolons are part
    of it (c(x; d, n, h), [0, 1]); outside, ', ' and '. ' end the expression ('α, β' stay two units)."""
    if not t:
        return False
    if depth <= 0 and (re.fullmatch(r"\s*[,.;]\s*", t) or re.search(r"[,.;]\s+\S", t.strip())):
        return False
    # function names (exp, log …) and single letters between maths runs (': R' of 'o(x) : R³') are maths too
    rest = re.sub(r"[A-Za-z]+", lambda m: "" if m.group().lower() in _MATHFUNCS
                  or (len(m.group()) == 1 and m.group() not in "aAI") else m.group(), t)
    if depth > 0:
        rest = rest.replace(",", "").replace(";", "")
    return bool(_MATH_GLUE.fullmatch(rest))


_HARD_MATH = re.compile("[\U0001d400-\U0001d7ff\ue000-\uf8ff\u0370-\u03ff\u2200-\u22ff\u2a00-\u2aff\u2140-\u214f∫∑∏∂∇√∞‖∮≈≠≤≥→←↔⇒⇔′″°]")


def _balance(grp: List[Run]) -> int:
    t = "".join(g.text for g in grp)
    return t.count("(") + t.count("[") - t.count(")") - t.count("]")


def _hard_math(grp: List[Run]) -> bool:
    """Only maths that is hard to type is photographed: integrals, sums, partial derivatives, Greek letters and other
    symbols, a sub- AND a superscript together, long / stacked indices.  x, p, R_pq, z_p stay ordinary typed text."""
    t = "".join(g.text for g in grp)
    if _HARD_MATH.search(t):
        return True
    vas = [g for g in grp if g.va]
    if {g.va for g in vas} == {"sub", "sup"}:
        return True
    if any(len(g.text.strip()) > 3 for g in vas):
        return True
    if grp[0].bbox and grp[-1].bbox:
        top = min(g.bbox[1] for g in grp if g.bbox)
        bot = max(g.bbox[3] for g in grp if g.bbox)
        if bot - top > 1.65 * max(g.size for g in grp):
            return True                                   # stacked (fraction, limits)
    return len(t.replace(" ", "")) > 14 and len(vas) >= 1


_LIST_LABEL = re.compile(r"\s*(?:\(?\d{1,3}[.)]?|\(?[A-Za-z][.)]|\(?[a-h]|\(?[ivxIVX]{1,4}[.)]|[•\-–▪●■◦*])\s*")
def _same_row(a, b) -> bool:
    """Two line boxes on one text row (a sub- / superscript piece counts: it overlaps most of its own height)."""
    ov = min(a[3], b[3]) - max(a[1], b[1])
    return ov > 0.5 * min(a[3] - a[1], b[3] - b[1]) and abs((a[1] + a[3]) - (b[1] + b[3])) / 2 < 0.6 * max(
        a[3] - a[1], b[3] - b[1])


_LATEX_RE = re.compile(r"\\\s*[A-Za-z]{2,}|[_^]\s*\{|&\s*=")
_PUA_RE = re.compile(r"[\ue000-\uf8ff\ufffd]")


_SYMBOL_CHARS = re.compile("[Ͱ-Ͽ℀-⋿⨀-⫿\U0001d400-\U0001d7ff]")
_INLINE_MATH_CH = re.compile("[=<>±Ͱ-Ͽ∀-⋿\U0001d400-\U0001d7ff]")


def math_text(t: str) -> str:
    """𝑥, 𝜃, 𝐀 (Mathematical Alphanumeric Symbols) -> x, θ, A: every font has those letters; the maths style (italic,
    bold) is kept by the run itself."""
    return "".join(unicodedata.normalize("NFKC", c) if 0x1D400 <= ord(c) <= 0x1D7FF else c for c in t)


_OPEN, _CLOSE = "([{", ")]}"
_GLUE_CH = set("0123456789=+-−×·/|<>≤≥≈≠∈∉⊂⊆∪∩±∓∗∘′'^!‖∑∏∫∂∇√∞→←↔⇒⇔ ") | set(_OPEN) | set(_CLOSE)


def _is_sym(c: str) -> bool:
    return c in _GLUE_CH or bool(_GREEK_RUN.fullmatch(c))


def _glue_prefix(t: str, depth: int) -> int:
    """Length of the maths that continues at the START of an ordinary run (' ∈ [0, 1] balances' -> ' ∈ [0, 1]',
    '), where' -> ')').  depth = brackets still open in the maths before it."""
    best, d, i = 0, depth, 0
    while i < len(t):
        c = t[i]
        if c in _OPEN:
            d += 1
        elif c in _CLOSE:
            if d == 0:
                break
            d -= 1
        elif c in ",." and (d > 0 or (0 < i < len(t) - 1 and t[i - 1].isdigit() and t[i + 1].isdigit())):
            pass                                          # [0, 1]   3.5
        elif not _is_sym(c):
            break
        i += 1
        if d == 0 and t[:i].strip():
            best = i
    seg = t[:best]
    while seg.rstrip() and seg.rstrip()[-1] in "-−/'′" and t[len(seg):len(seg) + 1].isalpha():
        seg = seg.rstrip()[:-1]                           # 'x-axis': the hyphen belongs to the word
    if not seg.strip() or not any(c not in " " for c in seg):
        return 0
    return len(seg.rstrip())


def _glue_inside(t: str) -> bool:
    """A short ordinary run that lies completely INSIDE an open maths bracket: '0, 1' of 'σ ∈ [0, 1]', 'a, b'."""
    t = t.strip()
    if not t or len(t) > 24 or any(c in _OPEN + _CLOSE for c in t):
        return False
    return all(_is_sym(c) or c in ",.;" or (c.isalpha() and not (t[k - 1:k].isalpha() or t[k + 1:k + 2].isalpha()))
               for k, c in enumerate(t))


def _glue_suffix(t: str) -> int:
    """Length of the maths at the END of an ordinary run that belongs to the maths after it ('gradient ∇' -> '∇',
    'the value (' -> '(').  Plain spaces / digits alone are not taken."""
    i = len(t)
    while i > 0 and _is_sym(t[i - 1]) and t[i - 1] not in _CLOSE:
        i -= 1
    seg = t[i:]
    core = seg.strip()
    if not core or core.isdigit() or not any(not c.isdigit() for c in core):
        return 0
    if i > 0 and t[i - 1].isalnum() and not seg[:1].isspace():
        return 0                                          # 'f(' glued to a word: part of the word
    return len(seg) - (len(seg) - len(seg.lstrip()))


def cluster_math(runs: List[Run], pno: int) -> List[Run]:
    """Maths inside the text (θ, w_ij = exp(−d²/2σ²), x_i, λ ∈ [0, 1] …) is neither translated nor photographed: the
    maths runs of one expression and the operators / brackets around and between them are joined into ONE unit that
    keeps every original run (with its sub- / superscript, italic, font).  The translated sentence carries this unit
    along as one left-to-right block, so in Persian it moves with the words around it and is never torn apart."""
    import dataclasses as dc
    out: List[Run] = []
    i, n = 0, len(runs)
    runs = list(runs)
    while i < n:
        r = runs[i]
        if not _mathy(r):
            out.append(r)
            i += 1
            continue
        j, k = i, i + 1
        while k < n:
            if _mathy(runs[k]):
                j = k
                k += 1
            elif _glue(runs[k].text, _balance(runs[i:k])) and k + 1 < n and _mathy(runs[k + 1]):
                k += 1
            else:
                break
        grp = list(runs[i:j + 1])
        lone = len(grp) == 1 and not grp[0].va and not MATHFONT_RE.search(grp[0].font or "") \
            and not _GREEK_RUN.search(grp[0].text)
        # operators in front of the maths, at the end of the previous ordinary run ('gradient ∇' + f)
        if out and not out[-1].parts and not _mathy(out[-1]):
            cut = _glue_suffix(out[-1].text)
            if cut:
                prev = out[-1]
                head, tail = prev.text[:len(prev.text) - cut], prev.text[len(prev.text) - cut:]
                if head.strip():
                    out[-1] = dc.replace(prev, text=head, bbox=None)
                else:
                    out.pop()
                grp.insert(0, dc.replace(prev, text=tail, bbox=None))
                lone = False
        # the maths continues at the start of the next ordinary run (' ∈ [0, 1] balances', '), where')
        # … also over several runs while a bracket is open: 'σ ∈ [' + '0, 1' (text font) + ']' (another font)
        undo: Optional[Tuple[int, int]] = None
        while j + 1 < n:
            nxt = runs[j + 1]
            depth = max(0, _balance(grp))
            if _mathy(nxt):
                if depth <= 0:
                    break
                grp.append(nxt)
                j += 1
                continue
            cut = _glue_prefix(nxt.text, depth)
            if not cut and depth > 0 and _glue_inside(nxt.text):
                if undo is None:
                    undo = (len(grp), j)                  # taken on trust: given back if the bracket never closes
                grp.append(nxt)
                j += 1
                continue
            if not cut:
                break
            grp.append(dc.replace(nxt, text=nxt.text[:cut], bbox=None))
            rest = nxt.text[cut:]
            lone = False
            if rest:
                runs[j + 1] = dc.replace(nxt, text=rest, bbox=None)
                break
            j += 1
        if undo is not None:
            if _balance(grp) > 0:
                grp, j = grp[:undo[0]], undo[1]
            else:
                lone = False
        while len(grp) > 1 and _balance(grp) > 0 and not grp[-1].text.strip(_OPEN + " "):
            grp = grp[:-1]
        if lone or not "".join(g.text for g in grp).strip():
            out.extend(grp)                               # a lone italic letter: the normal term guard handles it
            i = j + 1
            continue
        first = grp[0]
        text = "".join(g.text for g in grp)
        bb = [g.bbox for g in grp if g.bbox]
        box = (min(b[0] for b in bb), min(b[1] for b in bb), max(b[2] for b in bb), max(b[3] for b in bb)) \
            if bb and len(bb) == len(grp) else None
        kept = []
        for g in grp:                                       # glyphs without a Unicode meaning (private-use codes of
            g2 = dc.replace(g)                              # old maths fonts) can only be copied as a tiny picture
            if g2.bbox and _PUA_RE.search(g2.text):
                g2.img = (pno,) + tuple(g2.bbox)
            kept.append(g2)
        out.append(Run(text, first.size, first.bold, first.italic, first.color, first.mono, "", first.font, box,
                       None, kept))
        i = j + 1
    return out


def find_gutter(paras: List[Para], pr) -> Optional[Tuple[float, float]]:
    """(x0, x1) of the empty strip between the two text columns of a page, or None for a one-column page."""
    body = [p for p in paras if p.n_lines >= 2 and not p.skip and 0.18 * pr.width <= p.bbox[2] - p.bbox[0] < 0.62 * pr.width]
    if len(body) < 3:
        return None
    lo, hi = min(p.bbox[0] for p in body), max(p.bbox[2] for p in body)
    w = hi - lo
    if w < 0.5 * pr.width:
        return None
    best = None
    start = None
    x = lo + 0.3 * w
    end = lo + 0.7 * w
    while x <= end + 1:
        free = not any(p.bbox[0] < x < p.bbox[2] for p in body)
        if free and start is None:
            start = x
        if (not free or x > end) and start is not None:
            if best is None or x - start > best[1] - best[0]:
                best = (start, x)
            start = None
        x += 1.0
    if best is None or best[1] - best[0] < 5:
        return None
    left = [p for p in body if p.bbox[2] <= best[0] + 1]
    right = [p for p in body if p.bbox[0] >= best[1] - 1]
    if len(left) < 2 or len(right) < 2:
        return None
    return best


def column_of(b, gut: Optional[Tuple[float, float]]) -> int:
    """0 = left column, 1 = right column, 2 = spans the whole page (or the page has one column)."""
    if gut is None:
        return 2
    if b[2] <= gut[1] + 3:
        return 0
    if b[0] >= gut[0] - 3:
        return 1
    return 2


def group_equations(paras: List[Para], pr, pno: int) -> List[Para]:
    """One displayed equation = ONE picture.  The main row, its fraction / limit / bracket fragments and the
    number '(n)' are joined (inside their own column) into a single block; several rows stacked under one another
    belong together as well."""
    gut = find_gutter(paras, pr)
    for p in paras:                                    # a line of a sentence is text, however much maths it contains
        if p.skip == "formula-like" and len(_LATEX_RE.findall(p.text)) < 2 \
                and (_stopwords(p.text) >= 3 or (_stopwords(p.text) >= 2 and len(_LONG_WORD.findall(p.text)) >= 2)):
            p.skip = None
    seeds = sorted((p for p in paras if p.skip == "formula-like" and not p.heading), key=lambda q: q.bbox[1])
    used: Set[int] = set()
    out_groups: List[Tuple[Para, List[Para]]] = []
    for sd in seeds:
        if id(sd) in used:
            continue
        col = column_of(sd.bbox, gut)
        members = [sd]
        used.add(id(sd))
        box = list(sd.bbox)
        grow = True
        while grow:
            grow = False
            pad = max(4.0, 1.0 * max(sd.size, 8.0))
            for q in paras:
                if id(q) in used or q.heading or q.skip not in (None, "formula-like", "no words (number / symbol)"):
                    continue
                if column_of(q.bbox, gut) != col:
                    continue
                if q.bbox[3] < box[1] - pad or q.bbox[1] > box[3] + pad:
                    continue                                   # not on the rows of the equation
                if q.skip is None and re.findall(r"[A-Za-z]{3,}", q.text) and (
                        q.bbox[3] < box[1] - 0.5 * pad or q.bbox[1] > box[3] + 0.5 * pad):
                    continue                                   # text only when it is really on the same row
                wordless = not re.findall(r"[A-Za-z]{3,}", q.text) and len(q.text) <= 30
                if q.skip is None and wordless and q.n_lines <= 2 and q.bbox[2] > box[0] - 30 and q.bbox[0] < box[2] + 30:
                    pass                                       # a stray fragment of the equation (exponent, index …)
                elif q.skip is None and (q.n_lines > 2 or len(_LONG_WORD.findall(q.text)) > 1 or _stopwords(q.text) >= 2
                                         or q.text.rstrip().endswith("?")):
                    continue                                   # ordinary text stays text
                if q.skip is None and q.bbox[2] - q.bbox[0] > 0.45 * (pr.width):
                    continue
                if box[3] - box[1] > 0.45 * pr.height:
                    continue
                members.append(q)
                used.add(id(q))
                box = [min(box[0], q.bbox[0]), min(box[1], q.bbox[1]), max(box[2], q.bbox[2]), max(box[3], q.bbox[3])]
                grow = True
        members.sort(key=lambda q: (round(q.bbox[1] / 4), q.bbox[0]))
        text = " ".join(m.text.strip() for m in members)
        g = Para(pno, tuple(box), text, sd.size, False, False, sd.color, "center", 1.2, 1, False, sd.serif, [],
                 skip="formula-like", font=sd.font, members=[tuple(m.bbox) for m in members])
        out_groups.append((g, members))
    if not out_groups:
        return paras
    drop = {id(m) for _g, ms in out_groups for m in ms}
    first_at = {id(ms[0]): g for g, ms in out_groups}
    result: List[Para] = []
    firsts = {}
    for g, ms in out_groups:
        idx = min(paras.index(m) for m in ms)
        firsts[idx] = g
    for i, p in enumerate(paras):
        if i in firsts:
            result.append(firsts[i])
        if id(p) not in drop:
            result.append(p)
    return result


_BR_SWAP = str.maketrans("()[]{}", ")(][}{")


def _merge_rtl_rows(data: dict) -> None:
    """Persian / Arabic originals: MuPDF cuts every text row into pieces (at each change of direction, at each
    zero-width joiner) and gives them in reading order.  The pieces of one row are joined into ONE line again, so
    the paragraph builder sees whole lines; brackets, which come out mirrored, are turned back."""
    for block in data.get("blocks", []):
        if block.get("type") != 0 or not block.get("lines"):
            continue
        rows: List[dict] = []
        for ln in block["lines"]:
            spans = [dict(sp) for sp in ln.get("spans", [])]
            if not any(sp["text"].strip() for sp in spans):
                continue
            prev = rows[-1] if rows else None
            if prev is not None and _same_row(prev["bbox"], ln["bbox"]) and prev.get("dir") == ln.get("dir"):
                size = max([sp["size"] for sp in spans] + [1.0])
                # reading goes to the left: the new piece ends where the row so far begins
                gap = min(abs(prev["bbox"][0] - ln["bbox"][2]), abs(ln["bbox"][0] - prev["bbox"][2]))
                a, b = prev["spans"][-1]["text"], spans[0]["text"]
                if not (a.endswith(" ") or b.startswith(" ")):
                    sep = "‌" if gap < 0.12 * size and a[-1:].isalpha() and b[:1].isalpha() else " "
                    prev["spans"].append(dict(prev["spans"][-1], text=sep))
                prev["spans"] += spans
                prev["bbox"] = (min(prev["bbox"][0], ln["bbox"][0]), min(prev["bbox"][1], ln["bbox"][1]),
                                max(prev["bbox"][2], ln["bbox"][2]), max(prev["bbox"][3], ln["bbox"][3]))
            else:
                rows.append(dict(ln, spans=spans))
        for row in rows:
            text = "".join(sp["text"] for sp in row["spans"])
            if len(re.findall(r"[؀-ۿ]", text)) < 0.3 * max(1, sum(c.isalpha() for c in text)):
                continue                                   # a Latin row inside the Persian document
            depth = 0
            for ch in text:                                # ')…(' : the brackets of this row are mirrored
                depth += (ch in "([{") - (ch in ")]}")
                if depth < 0:
                    for sp in row["spans"]:
                        sp["text"] = sp["text"].translate(_BR_SWAP)
                    break
        block["lines"] = rows
    # MuPDF often makes one block of every row of right-to-left text: rows that follow each other closely, in the
    # same size and above each other, are one block again (the paragraph rules cut it where a paragraph ends)
    merged: List[dict] = []
    for block in data.get("blocks", []):
        prev = merged[-1] if merged else None
        if (prev is not None and block.get("type") == 0 and prev.get("type") == 0 and block.get("lines")
                and prev.get("lines")):
            a_, c_ = prev["lines"][-1], block["lines"][0]
            sa = max((sp["size"] for sp in a_["spans"]), default=0)
            sc = max((sp["size"] for sp in c_["spans"]), default=0)
            gap = c_["bbox"][1] - a_["bbox"][3]
            ov = min(a_["bbox"][2], c_["bbox"][2]) - max(a_["bbox"][0], c_["bbox"][0])
            if abs(sa - sc) < 0.6 and -0.3 * sa < gap < 0.7 * sa and a_.get("dir") == c_.get("dir")                     and ov > 0.3 * min(a_["bbox"][2] - a_["bbox"][0], c_["bbox"][2] - c_["bbox"][0]):
                prev["lines"] = prev["lines"] + block["lines"]
                pb, bb = prev["bbox"], block["bbox"]
                prev["bbox"] = (min(pb[0], bb[0]), min(pb[1], bb[1]), max(pb[2], bb[2]), max(pb[3], bb[3]))
                continue
        merged.append(block)
    data["blocks"] = merged


def extract_page(page, pno: int, opts: Options) -> Tuple[List[Para], List]:
    """Return (paragraphs, obstacle rectangles) for one page."""
    flags = fitz.TEXTFLAGS_DICT & ~(fitz.TEXT_PRESERVE_IMAGES | fitz.TEXT_PRESERVE_LIGATURES)
    data = page.get_text("dict", flags=flags)
    SRC_RTL[0] = bool(LANGS.get(opts.src_lang, {}).get("rtl"))
    if SRC_RTL[0]:
        _merge_rtl_rows(data)
    pr = page.rect
    paras: List[Para] = []
    REGIONS[pno] = []

    # a line that MuPDF cut into two BLOCKS ('where L' | 'ᵢc(r) is the photometric loss …', a run-in heading and its
    # text): the second block is appended to the first, the two halves of the line are joined below
    tblocks: List[dict] = []
    for block in data["blocks"]:
        if block.get("type") != 0 or not block.get("lines"):
            continue
        block = dict(block, lines=list(block["lines"]))
        for m in reversed(tblocks[-3:]):
            a, c = m["lines"][-1], block["lines"][0]
            sa = [s for s in a["spans"] if s["text"].strip()]
            sc = [s for s in c["spans"] if s["text"].strip()]
            if not sa or not sc or a["dir"] != c["dir"]:
                continue
            sz = max(s["size"] for s in sa + sc)
            gap = c["bbox"][0] - a["bbox"][2]
            row = list(a["bbox"])                       # the whole row so far (Ns under '1/', ∑ above …)
            for prev_l in reversed(m["lines"][:-1]):
                if not _same_row(prev_l["bbox"], row):
                    break
                row = [min(row[0], prev_l["bbox"][0]), min(row[1], prev_l["bbox"][1]),
                       max(row[2], prev_l["bbox"][2]), max(row[3], prev_l["bbox"][3])]
            same_row = _same_row(row, c["bbox"])
            gap = c["bbox"][0] - row[2]
            runin = all(_is_bold(s) for s in sa) or "".join(s["text"] for s in sa).rstrip()[-1:] in ".:"
            # not for a numbered / lettered list ('20  a  How many moles …'): there the following lines are indented
            flush = not _LIST_LABEL.fullmatch("".join(s["text"] for s in sa))   # never a list label: 20 | a | How …
            if same_row and flush and -max(3.0, 1.5 * sz) < gap < (2.5 if runin else 1.2) * sz:
                m["lines"] = m["lines"] + block["lines"]
                m["bbox"] = tuple(fitz.Rect(m["bbox"]) | fitz.Rect(block["bbox"]))
                block = None
                break
        if block is not None:
            tblocks.append(block)

    for block in tblocks:
        lines = []
        for ln in block["lines"]:
            spans = [s for s in ln["spans"] if s["text"].strip()]
            if not spans:
                continue
            dx, dy = ln["dir"]
            rotated = abs(dx - 1) > 0.05 or abs(dy) > 0.05
            lines.append({
                "text": "".join(s["text"] for s in ln["spans"]),
                "bbox": ln["bbox"], "spans": spans, "all": ln["spans"], "rotated": rotated,
                "size": max(s["size"] for s in spans),
            })
        # a run-in heading ('Input and Output.  Our input is …') often comes as a line of its own on the SAME row as
        # the text after it: both were typeset at the same place and printed over each other.  Join them.
        joined: List[dict] = []
        for li_, l in enumerate(lines):
            if joined and not l["rotated"] and not joined[-1]["rotated"] and \
                    not _LIST_LABEL.fullmatch(joined[-1]["text"]):
                a = joined[-1]
                sz = max(a["size"], l["size"]) or 10
                same_row = _same_row(a["bbox"], l["bbox"])
                gap = l["bbox"][0] - a["bbox"][2]
                runin = all(_is_bold(s) or _is_italic(s) for s in a["spans"]) or a["text"].rstrip()[-1:] in ".:"
                # (a line that MuPDF cut in two at a sub- / superscript – 'where L' + 'ᵢc(r) is …' – is joined too)
                if same_row and -max(3.0, 1.5 * sz) < gap < (2.5 if runin else 1.2) * sz:
                    sep = [] if a["text"].endswith(" ") else [dict(a["all"][-1], text=" ")]
                    a["all"] = a["all"] + sep + l["all"]
                    a["spans"] = a["spans"] + l["spans"]
                    a["text"] = a["text"] + ("" if a["text"].endswith(" ") else " ") + l["text"]
                    a["bbox"] = (a["bbox"][0], min(a["bbox"][1], l["bbox"][1]), l["bbox"][2], max(a["bbox"][3], l["bbox"][3]))
                    a["size"] = sz
                    continue
            joined.append(dict(l))
        lines = joined
        if not lines:
            continue
        groups: List[Tuple[List[dict], bool]] = []
        seg: List[dict] = []
        seg_f = False
        for l in lines + [None]:                    # lines of displayed equations form blocks of their own
            f = _formula_line(l) if l is not None else None
            if seg and f != seg_f:
                groups += [(g, seg_f) for g in ([seg] if seg_f else _split_block(seg))]
                seg = []
            if l is not None:
                seg.append(l)
                seg_f = f
        for grp, forced_formula in groups:
            runs = build_runs(grp)
            if not runs:
                continue
            dom = dominant_style(runs)
            serif_w: collections.Counter = collections.Counter()
            for l in grp:
                for s in l["spans"]:
                    serif_w[_is_serif(s)] += len(s["text"].strip())
            x0 = min(l["bbox"][0] for l in grp); y0 = min(l["bbox"][1] for l in grp)
            x1 = max(l["bbox"][2] for l in grp); y1 = max(l["bbox"][3] for l in grp)
            if len(grp) > 1:
                pitch = statistics.median(b["bbox"][1] - a["bbox"][1] for a, b in zip(grp, grp[1:]))
                lh = min(max(pitch / dom.size, 1.0), 2.2)
            else:
                lh = 1.2
            text = "".join(r.text for r in runs)
            p = Para(pno, (x0, y0, x1, y1), text, dom.size, dom.bold, dom.italic, dom.color,
                     _alignment(grp, pr), lh, len(grp), dom.mono, serif_w.most_common(1)[0][0], runs,
                     font=dominant_font(runs), indent=first_line_indent(grp))
            # every span of every line: these are the glyphs that must be erased before the translation is typeset
            # (run boxes are not enough – a run that continues on the next line has no box)
            p.erase = [tuple(s["bbox"]) for l in grp for s in l["spans"] if s["text"].strip()]
            p.runs = cluster_math(p.runs, pno)
            alpha = sum(c.isalpha() for c in p.text)
            math_chars = sum(len(s["text"]) for l in grp for s in l["spans"] if MATHFONT_RE.search(s.get("font", "")))
            if forced_formula and not any(l["rotated"] for l in grp):
                p.skip = "formula-like"
            elif any(l["rotated"] for l in grp):
                p.skip = "rotated text"
            elif alpha < 2:
                p.skip = "no words (number / symbol)"
            elif alpha < 0.4 * len(p.text) or looks_like_formula(p.text, math_chars):
                p.skip = "formula-like"
            elif len(_LATEX_RE.findall(p.text)) >= 2 and _stopwords(p.text) < 3:
                p.skip = "formula-like"                     # an equation whose glyphs carry its LaTeX source as text
            elif re.fullmatch(r"(https?://|www\.)\S+|\S+@\S+\.\S+", p.text):
                p.skip = "URL / e-mail"
            elif re.search(r"(?:\.\s?){5,}", p.text):
                p.skip = "contents line"
            elif opts.skip_code and dom.mono:
                p.skip = "code"
            elif not opts.translate_captions and CAPTION_RE.match(p.text):
                p.skip = "caption"
            paras.append(p)

    obstacles = [fitz.Rect(p.bbox) for p in paras]

    # ---- tables
    if opts.skip_tables:
        try:
            for t in page.find_tables().tables:
                if t.row_count >= 2 and t.col_count >= 2:
                    tr = fitz.Rect(t.bbox)
                    obstacles.append(tr)
                    REGIONS[pno].append(("table", tuple(tr)))
                    for p in paras:
                        c = fitz.Rect(p.bbox)
                        if not p.skip and tr.contains(fitz.Point((c.x0 + c.x1) / 2, (c.y0 + c.y1) / 2)):
                            p.skip = "table"
        except Exception:
            pass
        n_before = len(obstacles)
        mark_text_grid_tables(paras, obstacles)
        REGIONS[pno] += [("table", tuple(o)) for o in obstacles[n_before:]]

    # ---- raster figures
    page_area = pr.get_area()
    try:
        for info in page.get_image_info():
            ir = fitz.Rect(info["bbox"])
            if ir.get_area() > 0.7 * page_area or ir.is_empty:
                continue
            obstacles.append(ir)
            REGIONS[pno].append(("figure", tuple(ir)))
            if opts.skip_figures:
                for p in paras:
                    pb = fitz.Rect(p.bbox)
                    if not p.skip and pb.get_area() > 0 and (pb & ir).get_area() > 0.6 * pb.get_area():
                        p.skip = "text inside image"
    except Exception:
        pass

    # ---- vector figures: short labels inside drawing clusters
    if opts.skip_figures:
        try:
            drawings = page.get_drawings()
            if drawings:
                for cl in page.cluster_drawings(drawings=drawings):
                    if cl.get_area() > 0.85 * page_area:
                        continue
                    n = sum(1 for d in drawings if cl.contains(d["rect"]))
                    if n < 4:
                        continue
                    REGIONS[pno].append(("figure", tuple(cl)))
                    for p in paras:
                        c = fitz.Rect(p.bbox)
                        if (not p.skip and len(p.text.split()) <= 8
                                and cl.contains(fitz.Point((c.x0 + c.x1) / 2, (c.y0 + c.y1) / 2))):
                            p.skip = "figure label"
        except Exception:
            pass

    # fragments of a displayed equation (a sum sign with its limits, '(5)', 'exp(…)dy') that were cut into blocks of
    # their own must not be translated either: otherwise a piece of the equation is erased and replaced by words
    zones = [fitz.Rect(p.bbox) + (-6, -5, 6, 5) for p in paras if p.skip == "formula-like"]
    for q in paras:
        if q.skip or not zones:
            continue
        qr = fitz.Rect(q.bbox)
        if qr.get_area() <= 0:
            continue
        for z in zones:
            # (a line of words right above an equation – '0.02 mol HCl react with excess Sb2S3?' – is text)
            if (qr & z).get_area() > 0.3 * qr.get_area() and _stopwords(q.text) < 2 \
                    and len(_LONG_WORD.findall(q.text)) <= 1 and not q.text.rstrip().endswith("?"):
                q.skip = "formula-like"
                break
    paras = group_equations(paras, pr, pno)
    for p in paras:
        if p.skip == "formula-like":
            REGIONS[pno].append(("formula", (p.bbox[0] - 2, p.bbox[1] - 2, p.bbox[2] + 2, p.bbox[3] + 2)))
            if p.members:
                obstacles.append(fitz.Rect(p.bbox))
    return paras, obstacles


def estimate_body_size(doc, pages: List[int], opts: Options) -> float:
    sample = pages[:: max(1, len(pages) // 25)][:25]
    cnt: collections.Counter = collections.Counter()
    for i in sample:
        for b in doc[i].get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                for s in ln["spans"]:
                    cnt[round(s["size"], 1)] += len(s["text"].strip())
    return cnt.most_common(1)[0][0] if cnt else 10.0


def find_back_matter(analysis: Dict[int, List[Para]], pages_sorted: List[int], n_pages: int,
                     body: float, keywords: str) -> Optional[Tuple[int, float, str]]:
    kws = [re.escape(k.strip()) for k in re.split(r"[,;\n]", keywords) if k.strip()]
    if not kws:
        return None
    rx = re.compile(r"^(?:(?:chapter|part|section)?\s*[\dIVXivx]+[\.\):]?\s+)?(?:" + "|".join(kws) +
                    r")(?:\s+[A-Z0-9][\w\-:,&' ]{0,40})?\s*[:.]?$", re.I)
    for pno in pages_sorted:
        if pno < 0.4 * n_pages:
            continue
        for p in sorted(analysis[pno], key=lambda q: q.bbox[1]):
            t = p.text.strip()
            if len(t) > 70 or p.n_lines > 2 or re.search(r"\.{3,}", t):
                continue
            heading = p.bold or p.size >= body * 1.08 or t.isupper()
            if heading and rx.match(t):
                return pno, p.bbox[1], t
    return None


FRONT_META_RE = re.compile(r"(isbn|©|copyright|all rights reserved|published by|printed in|library of congress|"
                           r"first (?:published|edition|printing)|\bedition\b|www\.|https?://|\S+@\S+\.\S+|orcid|"
                           r"received:|accepted:|doi:|corresponding author|e-mail)", re.I)
AFFIL_RE = re.compile(r"\b(universit\w*|institute|department|dept\.|faculty|laborator\w*|college|school of|"
                      r"hospital|academy|centre|center for)\b", re.I)
CONTENTS_RE = re.compile(r"^(table of contents|contents|list of (figures|tables)|inhaltsverzeichnis)$", re.I)
ABSTRACT_RE = re.compile(r"^\s*(abstract|summary)\b", re.I)


def mark_front_matter(analysis: Dict[int, List[Para]], selected: List[int], n_pages: int, body: float,
                      log: Callable[[str], None]) -> None:
    """Article / book templates: authors, affiliations, e-mails, publisher / copyright data and cover pages are
    names and data, not text to translate."""
    cnt = 0
    for i in selected:
        if i >= 8:
            break
        for p in analysis[i]:
            if p.skip or p.n_lines > 6:
                continue
            if FRONT_META_RE.search(p.text) or (i <= 1 and not p.heading and AFFIL_RE.search(p.text)
                                                 and p.size <= body * 1.3):
                p.skip = "front matter (author / publisher)"
                cnt += 1
    if 0 in analysis:
        ps = sorted(analysis[0], key=lambda q: q.bbox[1])
        ab = next((q for q in ps if ABSTRACT_RE.match(q.text) and q.bbox[1] > 0), None)
        if ab is not None:                                       # scientific article: title, authors, …, Abstract
            above = [q for q in ps if q.bbox[1] < ab.bbox[1]]
            top = max([q for q in above if len(q.text.split()) >= 3] or above, key=lambda q: q.size, default=None)
            for q in ps:
                if top is not None and q is not top and q.bbox[3] <= ab.bbox[1] + 1 and q.bbox[1] >= top.bbox[3] - 1 \
                        and not q.skip and q.bbox[0] < top.bbox[2] and q.bbox[2] > top.bbox[0]:
                    q.skip = "front matter (author / affiliation)"
                    cnt += 1
        elif n_pages >= 40 and sum(len(q.text.split()) for q in ps) < 80:   # cover / title page of a book
            for q in ps:
                if not q.skip:
                    q.skip = "front matter (cover page)"
                    cnt += 1
    if cnt:
        log(f"Front matter: {cnt} blocks (authors, affiliations, book data) are kept as they are.")


_NAME_TOK = re.compile(r"[A-ZÀ-ÖØ-ÞĀ-Ž][\w'’\-]*\.?")
_NAME_PART = {"van", "von", "de", "der", "den", "del", "di", "da", "dos", "al", "el", "bin", "ibn", "le", "la", "ten"}
_NAME_LEAD = re.compile(r"^(?:edited by|academic editors?|guest editors?|editors?|authors?|reviewed by|"
                        r"written by|translated by|supervisors?|advisors?|reviewers?)\s*:?\s+", re.I)
_NAME_VETO = set("""learning deep computer vision image images processing detection estimation analysis system systems
network networks model models method methods data using based towards toward approach survey review study introduction
theory design control engineering science sciences applied modern fast object objects distance issue special journal
university institute department international conference proceedings advanced new novel efficient robust neural machine
intelligence artificial digital signal information technology research applications application related work works
background results discussion conclusion conclusions experiments evaluation future open issues materials summary
abstract keywords article letter paper chapter part section volume edition the a an of for in on with to""".split())


def names_line(text: str, loose: bool = False) -> bool:
    """A line that only lists persons: 'Marek Vajgl 1,*, Petr Hurtik 1 and Tomáš Nejezchleba 2', 'Edited by Dr. Deokwoo
    Lee and Dr. YoHan Park'.  Names are never sent to the translation model (it replaces unknown names by famous
    ones).  loose = the line is in the author area of the first pages, so plain 'First Last, First Last' is enough."""
    t = " ".join(text.split())
    if not t or len(t) > 400:
        return False
    strong = False
    m = _NAME_LEAD.match(t)
    if m:
        strong, t = True, t[m.end():]
    if re.search(r"\b(?:Dr|Prof|Mr|Mrs|Ms)\.\s", t):
        strong = True
    t = re.sub(r"\b(?:Dr|Prof|Mr|Mrs|Ms|PhD|Ph\.D|Jr|Sr)\b\.?", " ", t)
    marks = bool(re.search(r"[a-zà-ž]\s?\d\b|[*†‡]", t))               # affiliation marks: 'Vajgl 1,*'
    t = re.sub(r"[\d*†‡§¶]+", " ", t)
    groups = [g.strip(" .") for g in re.split(r"\s*(?:,|;|&|\band\b|\bund\b)\s*", t) if g.strip(" .")]
    if not groups:
        return False
    for g in groups:
        toks = g.split()
        if not 1 <= len(toks) <= 5:
            return False
        for tok in toks:
            if tok.lower() in _NAME_PART:
                continue
            if not _NAME_TOK.fullmatch(tok) or tok.lower().strip(".") in _NAME_VETO:
                return False
    full = sum(1 for g in groups if len(g.split()) >= 2)
    if strong:
        return full >= 1
    if marks:
        return full >= 1 and full >= len(groups) - 1
    return loose and len(groups) >= 2 and full == len(groups)


def mark_fractions(page, paras: List[Para], pno: int) -> int:
    """A fraction inside a sentence (Z = fH / h written as a small fraction) has a bar that is a DRAWN line, not
    text.  Typing its letters again leaves the bar behind at the old place.  Such an expression – with the 'Z ='
    in front of it – is copied as one picture of the original, and its bar is erased from the page."""
    try:
        bars = []
        for d in page.get_drawings():
            r = d["rect"]
            if r.height <= 1.2 and 2.5 <= r.width <= 140:
                bars.append((r.x0, r.y0, r.x1, r.y1))
    except Exception:
        return 0
    if not bars:
        return 0
    n = 0
    for p in paras:
        if p.skip or not any(r.parts for r in p.runs):
            continue
        cand = [b for b in bars if p.bbox[0] - 2 <= b[0] and b[2] <= p.bbox[2] + 2 and p.bbox[1] <= b[1] <= p.bbox[3]]
        if not cand:
            continue
        runs = list(p.runs)
        k = 0
        while k < len(runs):
            r = runs[k]
            bb = [x.bbox for x in (r.parts or []) if x.bbox]
            if len(bb) < 2:
                k += 1
                continue
            x0, y0 = min(b[0] for b in bb), min(b[1] for b in bb)
            x1, y1 = max(b[2] for b in bb), max(b[3] for b in bb)
            hit = [b for b in cand if x0 - 2 <= b[0] and b[2] <= x1 + 2 and y0 < b[1] < y1
                   and any((q[1] + q[3]) / 2 < b[1] for q in bb) and any((q[1] + q[3]) / 2 > b[1] for q in bb)]
            if not hit:
                k += 1
                continue
            x0, x1 = min([x0] + [b[0] for b in hit]), max([x1] + [b[2] for b in hit])
            text, first = r.text, r
            j = k - 1
            if j >= 0 and not runs[j].text.strip():
                j -= 1                                    # a blank between 'Z =' and the fraction
            prev = runs[j] if j >= 0 else None
            pb = [x.bbox for x in (prev.parts or []) if x.bbox] if prev is not None else []
            if prev is not None and prev.parts and prev.text.rstrip().endswith("=") and pb \
                    and abs((pb[0][1] + pb[0][3]) / 2 - (y0 + y1) / 2) < 6 and 0 <= x0 - max(q[2] for q in pb) < 30:
                x0, y0, y1 = min(q[0] for q in pb), min([y0] + [q[1] for q in pb]), max([y1] + [q[3] for q in pb])
                text, first = prev.text + " " + r.text.strip(), prev
                del runs[j:k]
                k = j
            box = (x0 - 0.6, y0 - 0.8, x1 + 0.6, y1 + 0.8)
            runs[k] = Run(text, first.size, first.bold, first.italic, first.color, first.mono, "", first.font, box,
                          (pno,) + box, None)
            p.bars += hit
            n += 1
            k += 1
        p.runs = runs
    return n


def mark_names_margins_title(analysis: Dict[int, List[Para]], selected: List[int], body: float,
                             opts: "Options", log: Callable[[str], None]) -> None:
    """Notes in the page margins and lines of person names are kept as they are; the title of the document is
    found (its original is printed under the translated title)."""
    n_margin = n_names = n_fig = 0
    for i in selected:
        ps = analysis[i]
        main = [p for p in ps if p.n_lines >= 3 and 0.85 * body <= p.size <= 1.3 * body and not p.heading
                and not (p.skip or "").startswith(("table", "rotated", "front"))]
        if sum(p.n_lines for p in main) >= 8:                  # the text column(s) of this page
            bx0, bx1 = min(p.bbox[0] for p in main), max(p.bbox[2] for p in main)
            for p in ps:
                if not p.skip and (p.bbox[2] <= bx0 - 2 or p.bbox[0] >= bx1 + 2) \
                        and p.bbox[2] - p.bbox[0] <= 0.45 * (bx1 - bx0):
                    p.skip = "margin note"
                    n_margin += 1
        first_long = min((p.bbox[1] for p in ps if p.n_lines >= 4), default=1e9)
        for p in ps:
            if p.skip or p.n_lines > 3:
                continue
            if names_line(p.text, loose=(i <= 2 and p.bbox[3] <= first_long + 1)):
                p.skip = "names of persons"
                n_names += 1
        if opts.skip_figures:                                  # axis title of a drawn chart, between its tick numbers
            ticks = [q for q in ps if q.skip in ("rotated text", "no words (number / symbol)")]
            for p in ps:
                if p.skip or p.heading or p.n_lines != 1 or len(p.text.split()) > 6 or CAPTION_RE.match(p.text):
                    continue
                near = [q for q in ticks if q.bbox[3] >= p.bbox[1] - 32 and q.bbox[1] <= p.bbox[3] + 32
                        and q.bbox[2] >= p.bbox[0] - 160 and q.bbox[0] <= p.bbox[2] + 160]
                if len(near) >= 5:
                    p.skip = "figure label"
                    n_fig += 1
        if i <= 1:
            cand = [p for p in ps if not p.skip and len(p.text.split()) >= 3 and p.size >= 1.4 * body]
            if cand:
                top = max(cand, key=lambda q: q.size)
                # the other lines of the same title (centred lines of different width come as separate blocks)
                grp = [top]
                grew = True
                while grew:
                    grew = False
                    for q in ps:
                        if q in grp or q.skip or abs(q.size - top.size) > 0.6 or q.bold != top.bold:
                            continue
                        if any(min(abs(q.bbox[1] - g.bbox[3]), abs(g.bbox[1] - q.bbox[3])) < 1.1 * top.size
                               and min(q.bbox[2], g.bbox[2]) - max(q.bbox[0], g.bbox[0]) > 0 for g in grp):
                            grp.append(q)
                            grew = True
                if len(grp) > 1:
                    import dataclasses as _dc
                    grp.sort(key=lambda q: q.bbox[1])
                    top = grp[0]
                    for q in grp[1:]:
                        if top.runs and q.runs:
                            top.runs = top.runs + [_dc.replace(top.runs[-1], text=" ", bbox=None, img=None,
                                                               parts=None)] + q.runs
                        top.text = top.text.rstrip() + " " + q.text.lstrip()
                        top.bbox = (min(top.bbox[0], q.bbox[0]), min(top.bbox[1], q.bbox[1]),
                                    max(top.bbox[2], q.bbox[2]), max(top.bbox[3], q.bbox[3]))
                        top.n_lines += q.n_lines
                        top.erase = list(top.erase) + list(q.erase)
                        top.bars = list(top.bars) + list(q.bars)
                    top.heading = True
                    gone = {id(q) for q in grp[1:]}
                    ps[:] = [q for q in ps if id(q) not in gone]
                top.title = True
                if i == 0 and not any(p.n_lines >= 4 for p in ps):
                    # a cover page (no running text): only the title is translated – the other short lines are
                    # series / issue / publisher data, where a translation model invents text
                    for p in ps:
                        if p is not top and not p.skip:
                            p.skip = "cover page"
    if n_margin or n_names or n_fig:
        log(f"Kept as they are: {n_margin} margin note(s), {n_names} line(s) of person names, "
            f"{n_fig} label(s) of drawn charts.")


RUNNING_RE = re.compile(r"courtesy of springer nature|terms of use apply|all rights reserved\.?$", re.I)
JOURNAL_LINE_RE = re.compile(r"(?:\b(?:19|20)\d\d\b.*\d+\s*[:–-]\s*\d+|\d+\s*[:–-]\s*\d+.*\b(?:19|20)\d\d\b)")


def mark_running_heads(analysis: Dict[int, List[Para]], selected: List[int]) -> None:
    """Running headers / footers (same short line at the same place on several pages) are not translated."""
    for i in selected:                           # works with a single page too: journal line, watermark
        for p in analysis[i]:
            if p.skip or p.n_lines != 1:
                continue
            if RUNNING_RE.search(p.text) or (p.bbox[1] < 70 and JOURNAL_LINE_RE.search(p.text)):
                p.skip = "running header / footer"
    seen: Dict[tuple, List[Para]] = {}
    for i in selected:
        for p in analysis[i]:
            if p.n_lines == 1 and not p.skip:
                seen.setdefault((round(p.bbox[1] / 6), re.sub(r"\d+", "#", p.text.strip().lower())), []).append(p)
    for group in seen.values():
        if len({p.page for p in group}) >= 3:
            for p in group:
                p.skip = "running header / footer"


def analyze(doc, opts: Options, log: Callable[[str], None], cancel: threading.Event,
            progress: Callable[[float, str], None]) -> Tuple[Dict[int, List[Para]], Dict[int, list]]:
    n = doc.page_count
    selected = sorted(parse_pages(opts.pages, n))
    body = estimate_body_size(doc, selected, opts)
    analysis: Dict[int, List[Para]] = {}
    obstacles: Dict[int, list] = {}
    for k, i in enumerate(selected):
        if cancel.is_set():
            raise Cancelled()
        page = doc[i]
        rot = page.rotation
        if rot:
            page.set_rotation(0)
        analysis[i], obstacles[i] = extract_page(page, i, opts)
        mark_fractions(page, analysis[i], i)
        for p in analysis[i]:
            p.heading = is_heading_para(p, body)
        if rot:
            page.set_rotation(rot)
        progress(k / len(selected), f"Analysing layout – page {i + 1}/{n}")
        nh = sum(1 for p in analysis[i] if p.heading)
        act(f"━ Page {i + 1}/{n}: reading layout – {len(analysis[i])} text blocks, {nh} headings, "
            f"{len(obstacles[i])} obstacles (images / tables)", "b")
        for p in analysis[i][:3]:
            if p.heading:
                act(f"    heading {p.size:.0f}pt: {p.text[:70]}", "h")

    in_toc = False
    for i in selected:                                         # a table of contents is never translated
        single = [q for q in analysis[i] if q.n_lines == 1]
        head = any(CONTENTS_RE.match(q.text.strip()) for q in single)
        numbered = sum(1 for q in single if re.search(r"\s\d{1,4}$", q.text.strip()))
        if head or (in_toc and single and numbered >= 0.5 * len(single)):
            in_toc = True
            for q in analysis[i]:
                q.skip = q.skip or "table of contents"
        else:
            in_toc = False
    mark_front_matter(analysis, selected, n, body, log)
    mark_running_heads(analysis, selected)
    mark_names_margins_title(analysis, selected, body, opts, log)
    if opts.skip_backmatter:
        if opts.backmatter_at is None:
            hit = find_back_matter(analysis, selected, n, body, opts.backmatter_keywords)
            if hit:
                pno, y, title = hit
                opts.backmatter_at = (pno, y)              # later parts of the book use the same position
                log(f"Back matter detected at page {pno + 1} (“{title}”): everything from there on is kept unchanged.")
        if opts.backmatter_at is not None:
            pno, y = opts.backmatter_at
            for i in selected:
                for p in analysis[i]:
                    if i > pno or (i == pno and p.bbox[1] >= y - 2):
                        p.skip = p.skip or "references / appendix"
    total = sum(len(v) for v in analysis.values())
    todo = sum(1 for v in analysis.values() for p in v if not p.skip)
    log(f"Analysis finished: {todo} text blocks to translate, {total - todo} blocks kept unchanged "
        f"(tables, figures, code, formulas, appendices …).")
    return analysis, obstacles


# ════════════════════════════════════════════════════════════════════════════
#  Engineering terms that must stay in English
# ════════════════════════════════════════════════════════════════════════════
# Built-in glossary (lower case, matched case-insensitively, plural -s/-es allowed, space/hyphen interchangeable).
# Add your own terms in the app (Glossary button) – they are stored in  ~/.pdf_book_translator/glossary.txt
BUILTIN_TERMS = """
# ---- electrical / electronics
voltage, resistor, resistance, capacitor, capacitance, inductor, inductance, impedance, admittance, reactance,
transistor, mosfet, bjt, jfet, igbt, diode, zener diode, schottky diode, thyristor, triac, op-amp,
operational amplifier, amplifier, oscillator, rectifier, inverter, converter, buck converter, boost converter,
transformer, relay, breadboard, printed circuit board, microcontroller, microprocessor, fpga, asic, soc,
analog-to-digital converter, digital-to-analog converter, multiplexer, demultiplexer, flip-flop, logic gate,
bandwidth, cutoff frequency, resonance, phase shift, duty cycle, power supply, power factor, rms, three-phase,
single-phase, slew rate, common-mode rejection ratio, signal-to-noise ratio, noise figure, low-pass filter,
high-pass filter, band-pass filter, band-stop filter, notch filter, butterworth filter, chebyshev filter,
pull-up resistor, pull-down resistor, decoupling capacitor, bypass capacitor, schmitt trigger, h-bridge,
darlington pair, current mirror, differential amplifier, voltage divider, kirchhoff's law, ohm's law,
thevenin equivalent, norton equivalent, superposition theorem, ground plane, heat sink, back emf, eddy current,
induction motor, synchronous motor, brushless dc motor, stepper motor, servo motor, servo, encoder, sensor,
actuator, thermocouple, rtd, thermistor, strain gauge, load cell, lvdt, accelerometer, gyroscope, imu, lidar,
radar, sonar, plc, scada, hmi, uart, spi, i2c, can bus, usb, jtag, gpio, pwm, adc, dac, eeprom, flash memory,
sram, dram, vlsi, cmos, nmos, pmos, bicmos, spice, verilog, vhdl, hdl, rtl
# ---- control systems
transfer function, state space, state-space, state variable, open-loop, closed-loop, feedback loop, feedforward,
pid controller, pid, root locus, bode plot, nyquist plot, nichols chart, laplace transform, z-transform,
inverse laplace transform, kalman filter, extended kalman filter, lqr, lqg, mpc, model predictive control,
setpoint, overshoot, settling time, rise time, steady-state error, phase margin, gain margin,
controllability, observability, pole placement, dead zone, backlash, anti-windup, lead compensator,
lag compensator, lead-lag compensator, actuator saturation, sampling time, zero-order hold,
impulse response, step response, frequency response, damping ratio, natural frequency, time constant
# ---- signals / communications
sampling rate, sampling theorem, nyquist rate, nyquist frequency, aliasing, quantization, quantization noise,
modulation, demodulation, amplitude modulation, frequency modulation, phase modulation, qam, psk, bpsk, qpsk,
fsk, ask, ofdm, cdma, tdma, fdma, mimo, spread spectrum, baseband, passband, carrier frequency, bit error rate,
antenna, waveguide, coaxial cable, transmission line, standing wave ratio, smith chart, link budget,
path loss, fading, multipath, equalizer, matched filter, fourier transform, fast fourier transform,
discrete fourier transform, short-time fourier transform, wavelet transform, convolution, correlation,
autocorrelation, power spectral density, spectrum analyzer, fir filter, iir filter, window function,
hamming window, hanning window, zero padding, decimation, interpolation, upsampling, downsampling,
huffman coding, error correction, convolutional code, turbo code, ldpc, viterbi algorithm, checksum, crc,
hamming code, reed-solomon, bluetooth, wi-fi, zigbee, lora, gsm, lte, gps, rfid, nfc, ethernet, tcp/ip
# ---- computer science / software
algorithm, data structure, compiler, interpreter, kernel, firmware, bootloader, cache, pipeline, thread,
multithreading, mutex, semaphore, deadlock, race condition, api, sdk, framework, middleware, runtime, database,
sql, nosql, hash table, hash function, linked list, binary tree, binary search, b-tree, red-black tree,
stack, queue, heap, priority queue, recursion, dynamic programming, greedy algorithm, big o notation, pointer,
memory leak, garbage collection, bitwise, endianness, byte, word size, opcode, assembly language,
instruction set, risc, cisc, cpu, gpu, tpu, alu, mmu, tlb, interrupt, dma, scheduler, round robin,
context switch, virtual memory, paging, file system, operating system, bash, shell, git, repository,
pull request, unit test, regression test, debugger, profiler, refactoring, design pattern,
object-oriented programming, polymorphism, inheritance, encapsulation, abstraction,
lambda, closure, callback, promise, async, json, xml, yaml, html, css, http, https, tcp, udp, dns, dhcp, nat,
router, switch fabric, packet, latency, throughput, jitter, vpn, tls, ssl, encryption, rsa, aes, sha,
public key, private key, blockchain, docker, kubernetes, microservice, cloud computing
# ---- machine learning / data / math
machine learning, deep learning, neural network, convolutional neural network, recurrent neural network, cnn,
rnn, lstm, gru, transformer, backpropagation, gradient descent, stochastic gradient descent, adam,
loss function, cost function, activation function, relu, sigmoid, softmax, dropout, batch normalization,
overfitting, underfitting, regularization, cross-validation, hyperparameter, epoch, batch size, learning rate,
support vector machine, svm, random forest, decision tree, k-means, k-nearest neighbors, naive bayes,
logistic regression, linear regression, principal component analysis, pca, autoencoder, gan, reinforcement
learning, q-learning, embedding, tokenization, feature vector, confusion matrix, precision, recall, f1 score,
roc curve, bayesian, markov chain, hidden markov model, monte carlo, matrix, vector, tensor, eigenvalue,
eigenvector, jacobian, hessian, gradient, laplacian, determinant, singular value decomposition, svd,
lu decomposition, qr decomposition, cholesky decomposition, least squares, newton-raphson, runge-kutta,
finite difference, finite element method, finite volume method, boundary element method,
differential equation, partial differential equation, ode, pde, fourier series, taylor series, dirac delta,
heaviside function, gaussian, poisson distribution, standard deviation, variance, covariance, p-value
# ---- mechanical / aerospace / thermo / fluids
torque, flange, bearing, gear, gearbox, shaft, bolt, rivet, welding, lathe, milling, cnc, cad, cam,
cae, fea, cfd, tolerance, fatigue, creep, fracture, young's modulus, poisson's ratio, yield strength,
tensile strength, shear stress, shear modulus, bending moment, von mises stress, stress-strain curve, beam,
truss, cantilever, buckling, vibration, damping, natural frequency, resonance frequency, modal analysis,
flywheel, cam follower, clutch, brake, piston, crankshaft, camshaft, turbocharger, injector, hydraulic,
pneumatic, actuator, valve, pump, compressor, turbine, nozzle, diffuser, heat exchanger, boiler, condenser,
evaporator, refrigerant, enthalpy, entropy, isentropic, adiabatic, isothermal, isobaric, isochoric,
carnot cycle, rankine cycle, brayton cycle, otto cycle, diesel cycle, coefficient of performance,
reynolds number, mach number, prandtl number, nusselt number, froude number, laminar flow, turbulent flow,
boundary layer, bernoulli equation, navier-stokes equations, viscosity, drag coefficient, lift coefficient,
airfoil, angle of attack, thrust, specific impulse, orbital mechanics, delta-v, kinematics, dynamics,
degrees of freedom, jacobian matrix, inverse kinematics, forward kinematics, end effector, manipulator
# ---- civil / materials / chemical
reinforced concrete, prestressed concrete, rebar, shear wall, footing, retaining wall,
load path, dead load, live load, wind load, seismic load, factor of safety, geotechnical, soil mechanics,
hydrology, aquifer, asphalt, alloy, composite, polymer, ceramic, semiconductor, dopant, doping,
n-type, p-type, pn junction, band gap, crystal lattice, grain boundary, annealing, quenching, tempering,
corrosion, galvanic, electrolyte, anode, cathode, catalyst, reactor, distillation, absorption, adsorption,
stoichiometry, molarity, ph, rheology, pid diagram, p&id, hazop"""

# Acronyms / names from the list above that really stay in English; every other built-in or downloaded
# "term" is an ordinary word that is translated (by the glossary below or by the model).
KEEP_ACRO = set("""mosfet bjt jfet igbt fpga asic soc plc scada hmi uart spi i2c usb jtag gpio pwm adc dac eeprom sram dram
vlsi cmos nmos pmos bicmos spice verilog vhdl hdl rtl pid lqr lqg mpc qam psk bpsk qpsk fsk ask ofdm cdma tdma fdma mimo
ldpc crc gsm lte gps rfid nfc api sdk sql nosql cpu gpu tpu alu mmu tlb dma json xml yaml html css http https tcp udp dns
dhcp nat vpn tls ssl rsa aes sha cnn rnn lstm gru gan svm pca svd ode pde rms rtd lvdt imu lidar radar sonar cnc cad
cam cae fea cfd risc cisc docker kubernetes git bash zigbee lora hazop spice relu softmax adam""".split())

# English -> Persian glossary of common technical words.  The first use in the document is written
# "فارسی (English)", later uses only in Persian.  Own entries go into glossary.txt as  english = فارسی
GLOSSARY_FA_TEXT = """
image = تصویر
images = تصاویر
algorithm = الگوریتم
deep learning = یادگیری عمیق
machine learning = یادگیری ماشین
learning = یادگیری
neural network = شبکهٔ عصبی
convolutional neural network = شبکهٔ عصبی کانولوشنی
recurrent neural network = شبکهٔ عصبی بازگشتی
network = شبکه
model = مدل
data set = مجموعه‌داده
dataset = مجموعه‌داده
data = داده
feature = ویژگی
feature vector = بردار ویژگی
feature extraction = استخراج ویژگی
regression = رگرسیون
classification = طبقه‌بندی
segmentation = قطعه‌بندی
object detection = تشخیص شیء
computer vision = بینایی ماشین
depth estimation = تخمین عمق
distance estimation = تخمین فاصله
monocular image = تصویر تک‌چشمی
stereo vision = بینایی استریو
loss function = تابع زیان
cost function = تابع هزینه
activation function = تابع فعال‌سازی
gradient descent = کاهش گرادیان
backpropagation = پس‌انتشار
training = آموزش
testing = آزمون
validation = اعتبارسنجی
overfitting = بیش‌برازش
underfitting = کم‌برازش
regularization = نظم‌دهی
ablation experiment = آزمایش حذفی
pooling layer = لایهٔ تجمیع
layer = لایه
fully connected = کاملاً متصل
accuracy = دقت
ground truth = برچسب مرجع
bounding box = کادر محیطی
real-time = بلادرنگ
autonomous driving = رانندگی خودکار
algorithms = الگوریتم‌ها
sensor = حسگر
camera = دوربین
matrix = ماتریس
vector = بردار
tensor = تانسور
eigenvalue = مقدار ویژه
eigenvector = بردار ویژه
gradient = گرادیان
function = تابع
variable = متغیر
parameter = پارامتر
hyperparameter = ابرپارامتر
optimization = بهینه‌سازی
closed-form solution = جواب بسته
probability = احتمال
distribution = توزیع
random field = میدان تصادفی
conditional random field = میدان تصادفی شرطی
markov random field = میدان تصادفی مارکوف
standard deviation = انحراف معیار
variance = واریانس
noise = نوفه
filter = فیلتر
signal = سیگنال
frequency = بسامد
amplitude = دامنه
voltage = ولتاژ
resistor = مقاومت
capacitor = خازن
inductor = سلف
transistor = ترانزیستور
diode = دیود
amplifier = تقویت‌کننده
oscillator = نوسان‌ساز
transformer = ترانسفورمر
microcontroller = ریزکنترلر
transfer function = تابع تبدیل
feedback = بازخورد
controller = کنترل‌کننده
stability = پایداری
bandwidth = پهنای باند
sampling = نمونه‌برداری
modulation = مدولاسیون
antenna = آنتن
fourier transform = تبدیل فوریه
laplace transform = تبدیل لاپلاس
kalman filter = فیلتر کالمن
operating system = سیستم‌عامل
database = پایگاه داده
compiler = کامپایلر
cache = حافظهٔ نهان
memory = حافظه
hash table = جدول هش
linked list = فهرست پیوندی
binary tree = درخت دودویی
recursion = بازگشت
data structure = ساختار داده
software = نرم‌افزار
hardware = سخت‌افزار
firmware = ریزبرنامه
encryption = رمزنگاری
torque = گشتاور
gear = چرخ‌دنده
shaft = شفت
valve = شیر
pump = پمپ
compressor = کمپرسور
turbine = توربین
heat exchanger = مبدل حرارتی
viscosity = گران‌روی
fatigue = خستگی
vibration = ارتعاش
concrete = بتن
corrosion = خوردگی
catalyst = کاتالیزور
reactor = راکتور
distillation = تقطیر
entropy = آنتروپی
enthalpy = آنتالپی
"""
# Standard headings: translated by a fixed table (a single word without a sentence confuses translation models)
HEADINGS_TEXT = {
    "fa": """abstract = چکیده
institutional review board statement = بیانیهٔ کمیتهٔ اخلاق
informed consent statement = بیانیهٔ رضایت آگاهانه
not applicable = موردی ندارد
acknowledgments and funding = سپاسگزاری و حمایت مالی
publisher s note = یادداشت ناشر
citation = ارجاع
examples = مثال‌ها
example = مثال
article = مقاله
review = مقالهٔ مروری
special issue = ویژه‌نامه
abbreviations = کوته‌نوشت‌ها
nomenclature = فهرست نمادها
definitions = تعریف‌ها
motivation = انگیزه
contributions = دستاوردها
objectives = هدف‌ها
scope = دامنه
architecture = معماری
model = مدل
training = آموزش
testing = آزمون
validation = اعتبارسنجی
implementation = پیاده‌سازی
algorithm = الگوریتم
comparison = مقایسه
case study = مطالعهٔ موردی
case studies = مطالعات موردی
applications = کاربردها
open issues = مسائل باز
remarks = نکته‌ها
concluding remarks = سخن پایانی
summary and conclusions = خلاصه و نتیجه‌گیری
discussion and conclusion = بحث و نتیجه‌گیری
discussion and conclusions = بحث و نتیجه‌گیری
results and analysis = نتایج و تحلیل
experimental evaluation = ارزیابی تجربی
theory = نظریه
proof = اثبات
solution = راه‌حل
solutions = راه‌حل‌ها
notes = یادداشت‌ها
further reading = برای مطالعهٔ بیشتر
supplementary material = مطالب تکمیلی
supplementary materials = مطالب تکمیلی
data availability statement = بیانیهٔ دسترسی به داده‌ها
conflicts of interest = تعارض منافع
highlights = نکات برجسته
cont = ادامه
continued = ادامه
introduction = مقدمه
related work = کارهای مرتبط
related works = کارهای مرتبط
literature review = مروری بر پیشینهٔ پژوهش
background = پیشینه
preliminaries = مقدمات
problem statement = بیان مسئله
problem formulation = صورت‌بندی مسئله
methodology = روش‌شناسی
methods = روش‌ها
method = روش
materials and methods = مواد و روش‌ها
proposed method = روش پیشنهادی
our approach = رویکرد ما
approach = رویکرد
overview = مرور کلی
implementation details = جزئیات پیاده‌سازی
experiments = آزمایش‌ها
experiment = آزمایش
experimental results = نتایج آزمایش‌ها
experimental setup = تنظیمات آزمایش
dataset = مجموعه‌داده
datasets = مجموعه‌داده‌ها
data sets = مجموعه‌داده‌ها
evaluation = ارزیابی
evaluation metrics = معیارهای ارزیابی
results = نتایج
results and discussion = نتایج و بحث
discussion = بحث
analysis = تحلیل
ablation study = مطالعهٔ حذفی
limitations = محدودیت‌ها
conclusion = نتیجه‌گیری
conclusions = نتیجه‌گیری
conclusion and future work = نتیجه‌گیری و کارهای آینده
future work = کارهای آینده
summary = خلاصه
acknowledgements = سپاسگزاری
acknowledgments = سپاسگزاری
acknowledgement = سپاسگزاری
funding = حمایت مالی
author contributions = مشارکت نویسندگان
declarations = اعلامیه‌ها
conflict of interest = تعارض منافع
references = منابع
bibliography = منابع
appendix = پیوست
appendices = پیوست‌ها
keywords = کلیدواژه‌ها
key words = کلیدواژه‌ها
index = نمایه
contents = فهرست مطالب
table of contents = فهرست مطالب
preface = پیشگفتار
foreword = پیشگفتار
glossary = واژه‌نامه
notation = نمادگذاری
exercises = تمرین‌ها
problems = مسائل
""",
    "de": """abstract = Zusammenfassung
examples = Beispiele
example = Beispiel
article = Artikel
special issue = Sonderausgabe
abbreviations = Abkürzungen
definitions = Definitionen
motivation = Motivation
architecture = Architektur
training = Training
implementation = Implementierung
algorithm = Algorithmus
comparison = Vergleich
case study = Fallstudie
applications = Anwendungen
open issues = Offene Fragen
theory = Theorie
proof = Beweis
solution = Lösung
solutions = Lösungen
notes = Anmerkungen
introduction = Einleitung
related work = Verwandte Arbeiten
related works = Verwandte Arbeiten
literature review = Literaturübersicht
background = Hintergrund
preliminaries = Grundlagen
problem statement = Problemstellung
methodology = Methodik
methods = Methoden
method = Methode
materials and methods = Material und Methoden
proposed method = Vorgeschlagene Methode
our approach = Unser Ansatz
approach = Ansatz
overview = Überblick
experiments = Experimente
experimental results = Experimentelle Ergebnisse
dataset = Datensatz
datasets = Datensätze
evaluation = Evaluierung
results = Ergebnisse
results and discussion = Ergebnisse und Diskussion
discussion = Diskussion
analysis = Analyse
limitations = Einschränkungen
conclusion = Fazit
conclusions = Schlussfolgerungen
conclusion and future work = Fazit und Ausblick
future work = Ausblick
summary = Zusammenfassung
acknowledgements = Danksagung
acknowledgments = Danksagung
references = Literatur
bibliography = Literaturverzeichnis
appendix = Anhang
appendices = Anhänge
keywords = Schlüsselwörter
key words = Schlüsselwörter
index = Stichwortverzeichnis
contents = Inhalt
table of contents = Inhaltsverzeichnis
preface = Vorwort
glossary = Glossar
exercises = Übungen
""",
}


def _parse_pairs(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            en, tr = (x.strip() for x in line.split("=", 1))
            if en and tr:
                out[" ".join(re.findall(r"[^\W_]+(?:['’][^\W_]+)*", en.lower()))] = tr
    return out


GREEK_NAMES = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "theta": "θ", "lambda": "λ",
               "sigma": "σ", "omega": "ω", "phi": "φ", "psi": "ψ", "mu": "μ", "rho": "ρ", "tau": "τ", "eta": "η",
               "zeta": "ζ", "kappa": "κ", "nu": "ν", "xi": "ξ", "chi": "χ"}
GLOSSARY_FA = {**_parse_pairs(GLOSSARY_FA_TEXT), **GREEK_NAMES}      # 'theta' stays the letter θ, not «تتا»
HEADINGS = {lg: _parse_pairs(t) for lg, t in HEADINGS_TEXT.items()}


_PYPHEN: List = [None, False]


def hyphenate_de(text: str, lang: str = "de") -> str:
    """Soft hyphens in long words (pyphen, optional): avoids huge gaps in justified narrow columns.  German,
    French, Spanish, English."""
    if lang not in _PYPHEN_D:
        try:
            import pyphen
            _PYPHEN_D[lang] = pyphen.Pyphen(lang=HYPHEN_DICT.get(lang, "de_DE"))
        except Exception:
            _PYPHEN_D[lang] = None
    dic = _PYPHEN_D[lang]
    if dic is None:
        return text
    return re.sub(r"[A-Za-zÀ-ÖØ-öø-ÿ]{8,}", lambda m: dic.inserted(m.group(), hyphen="­"), text)


_PYPHEN_D: Dict[str, object] = {}


def heading_key(text: str) -> str:
    return " ".join(re.findall(r"[a-z]+", text.lower()))


_HEAD_REV: Dict[str, Dict[str, str]] = {}
_HEAD_ALIASES: Dict[str, Dict[str, str]] = {
    "fa": {"کلمات کلیدی": "keywords", "واژگان کلیدی": "keywords", "واژه‌های کلیدی": "keywords",
           "کلید واژه‌ها": "keywords", "خلاصه": "abstract", "پیشگفتار": "introduction", "منابع": "references",
           "مراجع": "references", "نتیجه گیری": "conclusions", "نتیجه‌گیری": "conclusions"},
    "de": {"Stichwörter": "keywords", "Schlagwörter": "keywords", "Abstract": "abstract", "Literatur": "references"},
}


def _fa_key(text: str) -> str:
    """Key of a Persian / German heading: letters only, Arabic forms unified, half-spaces and ezafe marks ignored."""
    t = unicodedata.normalize("NFKC", text).translate({ord("ي"): "ی", ord("ك"): "ک", 0x200C: " ", 0x0654: None})
    return " ".join(re.findall(r"[^\W\d_]+", t.lower()))


def fixed_heading(core: str, src: str, tgt: str) -> Optional[str]:
    """Fixed translation of a standard heading (Abstract, Introduction, Funding …) in EVERY direction.  The tables
    are written English -> X; for a Persian or German original the table is read backwards (چکیده -> abstract) and
    then forwards to the target.  A translation model alone turned «چکیده» into 'It's stuck.'"""
    if src == "en" or src not in HEADINGS:
        return HEADINGS.get(tgt, {}).get(heading_key(core))
    if src not in _HEAD_REV:
        _HEAD_REV[src] = {_fa_key(v): k for k, v in HEADINGS[src].items()}
        for alias, en_key in _HEAD_ALIASES.get(src, {}).items():     # other usual wordings of the same heading
            _HEAD_REV[src].setdefault(_fa_key(alias), en_key)
    en = _HEAD_REV[src].get(_fa_key(core.strip().rstrip(":.")))
    if not en:
        return None
    if tgt == "en":
        return en[:1].upper() + en[1:]
    return HEADINGS.get(tgt, {}).get(en)


def sentence_case(text: str) -> str:
    """'Traditional Distance Estimation Algorithm' -> 'Traditional distance estimation algorithm': a Title Case
    heading confuses translation models.  Acronyms and placeholders stay as they are."""
    words = text.split()
    alpha = [w for w in words if w[:1].isalpha()]
    if len(words) < 2 or len(alpha) < 2 or sum(w[0].isupper() for w in alpha) < 0.7 * len(alpha):
        return text
    # (YOLOv3, DeepLab, R-CNN, 3D: a word with a second capital letter or a digit is a name, not Title Case)
    return " ".join([words[0]] + [w if (w.isupper() and len(w) > 1) or "ZX" in w or w[:1].islower()
                                  or sum(c.isupper() for c in w) >= 2 or any(c.isdigit() for c in w)
                                  else w[0].lower() + w[1:] for w in words[1:]])


DIGIT_NORM = {**{0x0660 + i: ord("0") + i for i in range(10)}, **{0x06F0 + i: ord("0") + i for i in range(10)}}
PH_RE = re.compile(r"Z\s*X\s*([0-9\u0660-\u0669\u06f0-\u06f9]+)\s*X\s*Z", re.I)
MAX_STYLED_WORDS = 8          # an emphasised stretch longer than this is translated as its own segment


def ph_token(i: int) -> str:
    return f"ZX{i}XZ"


def load_user_terms() -> str:
    try:
        return GLOSSARY_FILE.read_text("utf-8")
    except Exception:
        return ""


def save_user_terms(text: str) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    GLOSSARY_FILE.write_text(text, "utf-8")


# ════════════════════════════════════════════════════════════════════════════
#  Specialty terminology: what the user types / what the book is about -> terms from the internet
# ════════════════════════════════════════════════════════════════════════════
TERM_DIR = APP_DIR / "Bulky_Translotor_Terminology"      # next to the other downloads (fonts, models …)
MAX_SPECIALTIES = 4
TERM_MAX_AGE_DAYS = 30
MAX_DOMAIN_TERMS = 30000


def parse_specialties(text: str) -> Tuple[List[str], int]:
    """'Chemistry,  Medical ,AI' -> (['Chemistry', 'Medical', 'AI'], 0).  Spaces around the commas are removed,
    duplicates dropped, at most 4 are kept; the second value says how many were ignored."""
    parts = [re.sub(r"\s+", " ", x).strip() for x in re.split(r"[,،;\n]", text or "")]
    out: List[str] = []
    for x in parts:
        if x and x.lower() not in [o.lower() for o in out]:
            out.append(x)
    return out[:MAX_SPECIALTIES], max(0, len(out) - MAX_SPECIALTIES)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "specialty"


def terminology_file(spec: str) -> Path:
    return TERM_DIR / f"{_slug(spec)}.txt"


def _http_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_TITLE}/{APP_VERSION}", "Accept": "application/json",
                                               **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _clean_term(t: str) -> str:
    t = re.sub(r"\s*\(.*?\)\s*", " ", t).replace("_", " ")
    return re.sub(r"\s+", " ", t).strip(" -–—.,;:'\"")


def _term_ok(t: str, trusted: bool) -> bool:
    words = t.split()
    if not (2 <= len(t) <= 60) or len(words) > 6 or t.isdigit() or ":" in t or t.lower().startswith(("list of", "index of")):
        return False
    if len(words) == 1 and not trusted:          # a lone lower-case word is probably an ordinary English word
        return bool(re.search(r"[A-Z0-9]", t[1:])) or "-" in t
    return True


_HF_SKIP_TAGS = re.compile(r"^(?:[a-z]{2,3}(?:-[a-z]{2,4})?|apache-2\.0|mit|openrail.*|cc.*|license.*|region:.*|"
                           r"endpoints_compatible|autotrain_compatible|has_space|deploy:.*)$")


def fetch_hf_terms(query: str, log: Callable[[str], None]) -> Set[str]:
    """Hugging Face Hub: task names, libraries, model / dataset names that match the specialty."""
    out: Set[str] = set()
    q = urllib.parse.quote(query)
    counts: collections.Counter = collections.Counter()
    for kind in ("models", "datasets"):
        try:
            items = _http_json(f"https://huggingface.co/api/{kind}?search={q}&limit=100&sort=downloads&direction=-1")
        except Exception as exc:
            log(f"  Hugging Face ({kind}) not reachable: {type(exc).__name__}")
            continue
        for it in items if isinstance(items, list) else []:
            rid = str(it.get("id", ""))
            tail = rid.split("/")[-1]
            if tail and len(tail) <= 40:
                out.add(_clean_term(tail.replace("-", " ") if kind == "datasets" else tail))
            for tg in it.get("tags", []) or []:
                if isinstance(tg, str) and not _HF_SKIP_TAGS.match(tg) and ":" not in tg:
                    counts[tg] += 1
            if it.get("pipeline_tag"):
                counts[str(it["pipeline_tag"])] += 2
            if it.get("library_name"):
                counts[str(it["library_name"])] += 2
    out |= {_clean_term(t.replace("-", " ")) for t, c in counts.items() if c >= 2}
    try:                                                    # the official list of tasks (Text Classification, …)
        tasks = _http_json("https://huggingface.co/api/tasks")
        if isinstance(tasks, dict):
            for tid, info in tasks.items():
                out.add(_clean_term(str((info or {}).get("label") or tid).replace("-", " ")))
    except Exception:
        pass
    return {t for t in out if _term_ok(t, True)}


def _kaggle_auth() -> Optional[str]:
    user, key = os.environ.get("KAGGLE_USERNAME"), os.environ.get("KAGGLE_KEY")
    if not (user and key):
        try:
            j = json.loads((Path.home() / ".kaggle" / "kaggle.json").read_text("utf-8"))
            user, key = j.get("username"), j.get("key")
        except Exception:
            return None
    return "Basic " + base64.b64encode(f"{user}:{key}".encode()).decode() if user and key else None


def fetch_kaggle_terms(query: str, log: Callable[[str], None]) -> Set[str]:
    """Kaggle: tags of the datasets / competitions that match the specialty (needs a free Kaggle API key)."""
    auth = _kaggle_auth()
    if not auth:
        log("  Kaggle skipped – put your free API key in ~/.kaggle/kaggle.json (or KAGGLE_USERNAME / KAGGLE_KEY).")
        return set()
    out: Set[str] = set()
    q = urllib.parse.quote(query)
    for url in (f"https://www.kaggle.com/api/v1/datasets/list?search={q}&pageSize=40",
                f"https://www.kaggle.com/api/v1/competitions/list?search={q}"):
        try:
            for it in _http_json(url, {"Authorization": auth}) or []:
                for tg in it.get("tags", []) or []:
                    name = tg.get("name") if isinstance(tg, dict) else tg
                    if name:
                        out.add(_clean_term(str(name)))
        except Exception as exc:
            log(f"  Kaggle not reachable: {type(exc).__name__}")
            break
    return {t for t in out if _term_ok(t, True)}


def fetch_wikipedia_terms(query: str, log: Callable[[str], None]) -> Set[str]:
    """Wikipedia (extra source for fields that Kaggle / Hugging Face do not cover): titles linked from the article."""
    out: Set[str] = set()
    try:
        q = urllib.parse.quote(query)
        hit = _http_json(f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={q}&srlimit=1"
                         f"&format=json")["query"]["search"]
        if not hit:
            return out
        title = urllib.parse.quote(hit[0]["title"])
        cont = ""
        for _ in range(3):
            data = _http_json(f"https://en.wikipedia.org/w/api.php?action=query&prop=links&titles={title}"
                              f"&pllimit=500&plnamespace=0&format=json{cont}")
            for pg in data["query"]["pages"].values():
                out |= {_clean_term(l["title"]) for l in pg.get("links", [])}
            if "continue" not in data:
                break
            cont = "&plcontinue=" + urllib.parse.quote(data["continue"]["plcontinue"])
    except Exception as exc:
        log(f"  Wikipedia not reachable: {type(exc).__name__}")
    return {t for t in out if _term_ok(t, False) and len(t.split()) >= 2}


def _terms_fresh(path: Path) -> bool:
    try:
        first = path.read_text("utf-8").splitlines()[:5]
        stamp = next(l.split(":", 1)[1].strip() for l in first if l.startswith("# date:"))
        age = (time.time() - time.mktime(time.strptime(stamp, "%Y-%m-%d"))) / 86400
        return age <= TERM_MAX_AGE_DAYS
    except Exception:
        return False


def ensure_terminology(spec: str, allow_download: bool, log: Callable[[str], None],
                       cancel: Optional[threading.Event] = None) -> Optional[Path]:
    """Terminology file of one specialty: reuse the stored one, or search the internet and store the result in
    ~/.pdf_book_translator/Bulky_Translotor_Terminology/<specialty>.txt"""
    path = terminology_file(spec)
    if path.exists() and (_terms_fresh(path) or not allow_download):
        log(f"Terminology “{spec}”: using {path.name} (no download needed).")
        return path
    if not allow_download:
        log(f"Terminology “{spec}”: downloads are disabled and nothing is stored yet.")
        return None
    log(f"Terminology “{spec}”: searching the internet (Hugging Face, Kaggle, Wikipedia) …")
    act(f"Searching technical terms of “{spec}” on Hugging Face / Kaggle / Wikipedia …", "b")
    terms: Dict[str, Set[str]] = {}
    for name, fn in (("Hugging Face", fetch_hf_terms), ("Kaggle", fetch_kaggle_terms),
                     ("Wikipedia", fetch_wikipedia_terms)):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        terms[name] = fn(spec, log)
        act(f"  {name}: {len(terms[name])} terms", "h")
    allt = sorted(set().union(*terms.values()), key=str.lower)[:MAX_DOMAIN_TERMS]
    if not allt:
        log(f"Terminology “{spec}”: nothing could be downloaded (offline?)."
            + (" An older file is used." if path.exists() else ""))
        return path if path.exists() else None
    TERM_DIR.mkdir(parents=True, exist_ok=True)
    head = [f"# specialty: {spec}", f"# date: {time.strftime('%Y-%m-%d')}",
            "# sources: " + ", ".join(f"{k} ({len(v)})" for k, v in terms.items()),
            "# one term per line – these terms are copied unchanged (not translated)"]
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(head + allt) + "\n", "utf-8")
    tmp.replace(path)
    log(f"Terminology “{spec}”: {len(allt)} terms stored in {path}")
    return path


def load_terminology(path: Optional[Path]) -> Set[str]:
    if not path or not path.exists():
        return set()
    try:
        return {l.strip() for l in path.read_text("utf-8").splitlines() if l.strip() and not l.startswith("#")}
    except Exception:
        return set()


# subject detection: the app reads the book and works out its field by itself
DOMAIN_WORDS: Dict[str, Tuple[List[str], str]] = {
    "Artificial Intelligence": ("neural network layer training dataset gradient deep learning machine model models "
                                "embedding classification accuracy loss tokens inference transformer backpropagation "
                                "overfitting epoch batch features labels supervised reinforcement agent "
                                "convolutional recurrent attention".split(), "Artificial Intelligence"),
    "Medicine": ("patient patients clinical disease diagnosis treatment symptoms therapy surgery drug dose hospital "
                 "blood cancer syndrome chronic acute pathology infection physician medication".split(), "Medicine"),
    "Chemistry": ("molecule molecules reaction compound acid bond electron solution catalyst organic synthesis ion "
                  "ions solvent oxidation reduction polymer atom atoms concentration".split(), "Chemistry"),
    "History": ("war empire king century revolution dynasty treaty ancient medieval battle kingdom emperor colonial "
                "army conquest reign republic".split(), "History"),
    "Electrical Engineering": ("voltage current resistor circuit capacitor transistor amplifier frequency signal "
                               "inductor impedance diode oscillator ohm".split(), "Electrical Engineering"),
    "Mechanical Engineering": ("torque stress strain beam gear shaft fluid thermodynamic turbine bearing pressure "
                               "heat flow vibration".split(), "Mechanical Engineering"),
    "Computer Science": ("algorithm software database compiler thread memory programming function pointer network "
                         "protocol server code array recursion".split(), "Computer Science"),
    "Physics": ("quantum particle energy momentum relativity wave field force electromagnetic photon entropy "
                "velocity acceleration".split(), "Physics"),
    "Mathematics": ("theorem proof lemma matrix vector integral derivative equation function probability "
                    "polynomial".split(), "Mathematics"),
    "Biology": ("cell cells gene genes protein organism species dna evolution enzyme genome bacteria tissue".split(),
                "Biology"),
    "Economics": ("market price demand supply inflation economy trade investment capital firm consumer "
                  "monetary fiscal".split(), "Economics"),
    "Law": ("court law legal statute contract liability plaintiff defendant judge rights clause".split(), "Law"),
    "Psychology": ("behavior cognitive emotion therapy perception memory personality anxiety stimulus "
                   "psychological".split(), "Psychology"),
}
DOMAIN_QUERIES = {"Artificial Intelligence": "Deep Learning"}      # a better search phrase for the internet


def detect_specialties(texts: List[str], top: int = 2, min_per_1000: float = 4.0) -> List[Tuple[str, float]]:
    """Which field(s) does the book talk about?  Counts typical words of each field per 1000 words."""
    words = re.findall(r"[a-z]+", " ".join(texts).lower())
    if len(words) < 200:
        return []
    freq = collections.Counter(words)
    scores = []
    for name, (kws, _q) in DOMAIN_WORDS.items():
        sc = 1000.0 * sum(freq[w] for w in set(kws)) / len(words)
        if sc >= min_per_1000:
            scores.append((name, round(sc, 1)))
    return sorted(scores, key=lambda t: -t[1])[:top]


_UNITS = ("V mV kV µV A mA µA kA nA Hz kHz MHz GHz THz W mW kW MW GW µW Ω kΩ MΩ mΩ F µF nF pF mF H mH µH nH "
          "dB dBm dBi dBW °C °F K N kN MN mN Pa kPa MPa GPa hPa bar mbar psi J kJ MJ mJ eV keV MeV GeV cal kcal "
          "Wh kWh MWh Ah mAh rpm rad/s bps kbps Mbps Gbps B KB MB GB TB KiB MiB GiB m cm mm µm nm km kg mg µg g s "
          "ms µs ns ps min h L mL % ppm ppb rad deg mol mmol S mS Wb T mT G lm lx cd").split()
_UNIT_RE = re.compile(
    r"(?<![\w.])[-+±−]?\d+(?:[.,]\d+)?(?:\s?[×x·]\s?10\^?[-−]?\d+)?\s?(?:"
    + "|".join(re.escape(u) for u in sorted(_UNITS, key=len, reverse=True))
    + r")(?:/[A-Za-zµΩ]+)?[²³]?(?![A-Za-z])")
_AUTO_RES = [
    ("secnum", re.compile(r"^\s*\d+(?:\.\d+)*\.?(?=\s)")),          # 1.2  – numbering of headings stays one unit
    ("url", re.compile(r"(?:https?://|www\.)[^\s<>()\[\]]+")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("cite", re.compile(r"\[\d+(?:\s*[,–\-]\s*\d+)*\]")),
    ("unit", _UNIT_RE),
    ("ident", re.compile(r"\b[A-Za-z]+(?:_[A-Za-z0-9]+)+\b")),
    ("camel", re.compile(r"\b[a-z]+(?:[A-Z][a-z0-9]+)+\b|\b[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+\b")),
    ("func", re.compile(r"\b[A-Za-z_][\w.]*\(\)")),
    ("alnum", re.compile(r"\b[A-Za-z]+-?\d+(?:[A-Za-z0-9\-./]*[A-Za-z0-9])?\b|\b\d+[A-Za-z]+\b")),
    ("version", re.compile(r"\b\d+(?:\.\d+)+[A-Za-z]+\b|\b\d+\.\d+\.\d+(?:\.\d+)*\b")),
    ("math", re.compile(r"[\w().\[\]^_]*\s?[=≈≠≤≥<>±∝]+\s?[\w().\[\]^_+\-*/]+(?:\s?[+\-*/×·]\s?[\w().\[\]^_]+)*")),
    ("symbol", re.compile(r"[\w^_]*[α-ωΑ-Ω∑∫√∂∇∞°µΩ²³][\w^_²³]*")),
    ("acronym", re.compile(r"\b[A-Z]{2,}[0-9]*(?:[-/][A-Z0-9]+)*s?\b")),
]
_ACRONYM_STOP = {"NOTE", "WARNING", "CAUTION", "IMPORTANT", "EXAMPLE", "FIGURE", "TABLE", "CHAPTER", "SECTION",
                 "PART", "THE", "FOR", "WITH", "FROM", "THIS", "THAT", "AND", "ALL", "EXERCISES", "PROBLEMS",
                 "SUMMARY", "CONTENTS", "PREFACE", "INTRODUCTION"}


def _term_regex(terms: Set[str]) -> Optional["re.Pattern"]:
    alts = []
    for t in sorted(terms, key=len, reverse=True):
        words = [w for w in re.split(r"[\s\-]+", t) if w]
        if words:
            alts.append(r"[\s\-]+".join(re.escape(w) for w in words))
    if not alts:
        return None
    return re.compile(r"(?<![\w])(?:" + "|".join(alts) + r")(?:s|es)?(?![\w])", re.I)


def is_allcaps(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 4 and sum(c.isupper() for c in letters) >= 0.85 * len(letters)


_TOKEN_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")
_LATIN_RUN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+./\-]*(?:[ \-][A-Za-z0-9][A-Za-z0-9+./\-]*)*")
_FWORD_RE = re.compile("[^\\W_\\d](?:[^\\W_]|\u200c)*")          # a word, Persian half-space included
# small function-word lists: a technical term never starts or ends with one of these
STOPWORDS = {
    "fa": set("""و در به از که این را با است برای آن یک تا می هم بر شود شده کرد کند کنند شد ها های ای اند بود
               باشد دارد دارند نیز اما یا اگر چه چون پس هر همه خود او ما آنها ایشان وی من تو شما بین روی زیر پیش
               بعد قبل دیگر بسیار نه هیچ کرده شوند گیرد داد دهد توان تواند توانند باید نمی آن‌ها این‌ها چنین چنان
               همین همان وجود مورد طور طریق عنوان دو سه چند ولی زیرا تنها فقط حتی حال سپس ابتدا قابل استفاده بررسی
               مرحله پیشنهادی نتیجه نتایج روش روشی کار کارها انجام ایجاد ارائه نشان مختلف جدید اصلی مهم بیشتر کمتر
               زمان نوع انواع بخش قسمت امکان باعث بلکه درباره همچنین سایر مانند مثال یعنی لذا اینکه آنکه""".split()),
    "de": set("""der die das und ist nicht mit den von zu auf für eine ein sich des dem auch werden wird als bei
               durch im in an es sie er wir ihr zum zur aus nach über unter vor oder aber wenn dass so wie nur noch
               sind war waren hat haben kann können muss einer eines einem einen diese dieser dieses wurde wurden
               mehr sehr man um bis zwischen ohne gegen""".split()),
    "fr": set("""le la les des et est une un dans que pour qui sur pas par au avec ce sont plus nous être cette aux
               du de en il elle ils on se sa son ses leur leurs mais ou où donc ni car comme si tout tous très peut
               peuvent été ont a entre sans sous vers chez""".split()),
    "es": set("""el la los las de que y en es una un por con para se del como más pero sus este son al esta entre
               lo le les su ya o u ni si sin sobre también muy puede pueden ha han fue ser está están hay todo
               todos cuando donde desde hasta""".split()),
    "en": set("""the of and to in is that for with as are this be by on from which or an it was we can not have
               a at its their these those such into than then there here also been has had were will would""".split()),
}
_PLAIN_TERM_RE = re.compile(r"[A-Za-z0-9\s\-'’]+")
_NAME_RE = re.compile(r"(?<![\w])[A-Z][a-z][\w'’\-]*(?:[ \t]+[A-Z][a-z][\w'’\-]*)*")
NAME_STOP = set("""The A An In On At For To Of And But Or If When While This That These Those It Its We Our You Your He
She They There Here As By With From Each Every Some Many Most All Any Such Then Thus However Also First Second Third
Finally Note See Figure Fig Table Chapter Section Example Exercise Exercises Problem Problems Consider Let Suppose
Using Given What Why How Which Who Whose Whom Where After Before During Since Because Although Though Unless Until
Both Either Neither Not No Yes One Two Three Four Five Six Seven Eight Nine Ten Part Appendix Equation Eq Page
Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April May June July August September
October November December Mr Mrs Ms Dr Prof""".split())


class Protector:
    """Finds the parts of a text that must NOT be translated: technical terms (built-in, own glossary, downloaded
    specialty terminology), proper names and Capitalized / compound-Capitalized words, acronyms, units, formulas,
    identifiers …"""

    def __init__(self, opts: Options, extra_terms: str = "", domain_terms: Optional[Set[str]] = None,
                 instructions: Optional[List[Tuple[str, str, str]]] = None):
        self.opts = opts
        self.lang = "fa"
        self.seen: Set[str] = set()                 # glossary words already written once as  فارسی (English)
        keep: Set[str] = set()
        self.user_gloss: Dict[str, str] = {}
        # "My instructions" (the newest wins): fixed translations per language, always-keep, always-translate
        self.lang_gloss: Dict[str, Dict[str, str]] = {}
        self.exclude: Set[str] = set()
        self.user_keep: Set[str] = set()
        for kind, en, tr_ in (load_instructions() if instructions is None else instructions):
            k = " ".join(_TOKEN_RE.findall(en.lower()))
            if not k:
                continue
            for d_ in self.lang_gloss.values():
                if kind in ("keep", "translate"):
                    d_.pop(k, None)
            self.exclude.discard(k)
            self.user_keep.discard(k)
            if kind in GLOSS_KINDS:
                self.lang_gloss.setdefault(kind, {})[k] = tr_
            elif kind == "keep":
                self.user_keep.add(k)
            else:
                self.exclude.add(k)
        if opts.keep_terms:
            # only real acronyms / names stay English; ordinary words of a field are translated, not copied
            for line in BUILTIN_TERMS.splitlines():
                if line.strip().startswith("#"):
                    continue
                for t in line.split(","):
                    tl = t.strip().lower()
                    if tl and (tl in KEEP_ACRO or re.search(r"[\d&/]", tl)):
                        keep.add(tl)
            for t in (domain_terms or set()):
                t = t.strip()
                if t and (re.search(r"[A-Z].*[A-Z]|\d", t) or t.lower() in KEEP_ACRO):
                    keep.add(t.lower())
        for raw in extra_terms.splitlines():                           # user terms are always honoured
            raw = raw.split("#")[0].strip()
            if not raw:
                continue
            sep = "=" if "=" in raw else ("→" if "→" in raw else "")
            if sep:                                                    # english = فارسی   (own translation)
                en, tr = (x.strip() for x in raw.split(sep, 1))
                if en and tr:
                    self.user_gloss[" ".join(_TOKEN_RE.findall(en.lower()))] = tr
            else:
                keep |= {x.strip().lower() for x in raw.split(",") if x.strip()}
        self._keep = (keep | self.user_keep) - self.exclude
        self.set_lang("fa")

    def set_lang(self, lang: str) -> None:
        """Called at the start of every target language: builds the lookup tables for it."""
        self.lang = lang
        self.seen = set()
        self.gloss: Dict[str, str] = dict(GLOSSARY_FA) if lang == "fa" else {}
        self.gloss.update(self.user_gloss)
        for k in self.exclude | self.user_keep:        # 'translate X' / 'keep X': no fixed translation any more
            self.gloss.pop(k, None)
        self.gloss.update(self.lang_gloss.get(lang, {}))
        self._index(self._keep | set(self.gloss))

    def gloss_parts(self, span: str) -> Optional[Tuple[str, str]]:
        """(Persian, key) of a glossary word / phrase, or None."""
        key = " ".join(_TOKEN_RE.findall(span.lower()))
        plural = False
        tr = self.gloss.get(key)
        if tr is None and key.endswith("es") and key[:-2] in self.gloss:
            tr, key, plural = self.gloss[key[:-2]], key[:-2], True
        elif tr is None and key.endswith("s") and key[:-1] in self.gloss:
            tr, key, plural = self.gloss[key[:-1]], key[:-1], True
        if tr is None:
            return None
        if plural and self.lang == "fa" and not tr.endswith("ها"):
            tr += "\u200cها"
        return tr, key

    def gloss_chain(self, spans: List[str]) -> str:
        """Fixed translation of one or more glossary words in a row.  'deep learning algorithms' ->
        'الگوریتم‌های یادگیری عمیق': Persian puts the head first, so the units are reversed and joined with ezafe.
        The first use in the document is written  فارسی (English)."""
        parts = [self.gloss_parts(x) for x in spans]
        fa_units = [p[0] for p in parts if p]
        keys = [p[1] for p in parts if p]
        if self.lang == "fa" and len(fa_units) > 1:
            def ez(u: str) -> str:
                return u + ("ی" if u.endswith(("ها", "ا", "و")) else "\u0654" if u.endswith("ه") else "")
            ordered = list(reversed(fa_units))
            tr = " ".join([ez(u) for u in ordered[:-1]] + [ordered[-1]])
        else:
            tr = " ".join(fa_units)
        if self.lang != "fa" or all(k in self.seen for k in keys) or all(k in GREEK_NAMES for k in keys):
            return tr
        self.seen.update(keys)
        return f"{tr} ({' '.join(spans)})"            # first use: Persian (English original)

    def gloss_text(self, span: str) -> str:
        return self.gloss_chain([span]) if self.gloss_parts(span) else ""

    def _index(self, terms: Set[str]) -> None:
        # plain terms are found by a fast word-by-word lookup, terms with symbols (p&id, tcp/ip) by a regex
        self.term_set: Set[str] = set()
        special: Set[str] = set()
        self.max_words = 1
        for t in terms:
            if _PLAIN_TERM_RE.fullmatch(t):
                words = _TOKEN_RE.findall(t)
                if words:
                    self.term_set.add(" ".join(words))
                    self.max_words = max(self.max_words, len(words))
            else:
                special.add(t)
        self.term_re = _term_regex(special)
        self.n_terms = len(terms)

    def _term_spans(self, text: str) -> List[Tuple[int, int]]:
        toks = [(m.group().lower(), m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]
        out: List[Tuple[int, int]] = []
        i = 0
        while i < len(toks):
            hit = 0
            for n in range(min(self.max_words, len(toks) - i), 0, -1):
                seq = toks[i:i + n]
                if any(not re.fullmatch(r"[\s\-]+", text[seq[j][2]:seq[j + 1][1]]) for j in range(n - 1)):
                    continue                                    # words are separated by something else than space / hyphen
                key = " ".join(t[0] for t in seq)
                if key in self.term_set or (key.endswith("es") and key[:-2] in self.term_set) or \
                        (key.endswith("s") and key[:-1] in self.term_set):
                    out.append((seq[0][1], seq[-1][2]))
                    hit = n
                    break
            i += hit or 1
        return out

    def _name_spans(self, text: str) -> List[Tuple[int, int]]:
        """Proper names and Capitalized terms (Python, Kaggle, Hugging Face, Convolutional Neural Network …).
        A lone Capitalized word at the start of a sentence is only grammar, so it is not touched."""
        words = re.findall(r"[A-Za-z]{3,}", text)
        if len(words) >= 3 and sum(w[0].isupper() for w in words) >= 0.7 * len(words):
            return []                                   # a Title Case heading: capitals are typography here
        out: List[Tuple[int, int]] = []
        for m in _NAME_RE.finditer(text):
            ws = [(w.group(), m.start() + w.start(), m.start() + w.end()) for w in re.finditer(r"\S+", m.group())]
            while ws and ws[0][0].strip("'’-") in NAME_STOP:
                ws.pop(0)
            while ws and ws[-1][0].strip("'’-") in NAME_STOP:
                ws.pop()
            if not ws:
                continue
            s0, e0 = ws[0][1], ws[-1][2]
            if len(ws) == 1:
                pre = text[:s0].rstrip()
                if not pre or pre[-1] in ".!?:;\"“”([•–—-·|" or len(ws[0][0]) < 3 or re.fullmatch(r"[\dIVXivx.]+", pre):
                    continue                            # start of a sentence: capital letter by grammar only
            out.append((s0, e0))
        return out

    def spans(self, text: str, allcaps: bool = False) -> List[Tuple[int, int]]:
        cands: List[Tuple[int, int]] = []
        cands += self._term_spans(text)
        if self.term_re:
            cands += [(m.start(), m.end()) for m in self.term_re.finditer(text)]
        if self.opts.keep_names and not allcaps:
            cands += self._name_spans(text)
        if LANGS.get(getattr(self.opts, "src_lang", "en"), {}).get("rtl"):
            # a Persian / Arabic original: the English words in it (terms, names, 'bounding box') are kept
            cands += [(m.start(), m.end()) for m in _LATIN_RUN_RE.finditer(text)]
        if self.opts.auto_terms:
            for name, rx in _AUTO_RES:
                if name == "acronym" and allcaps:
                    continue
                for m in rx.finditer(text):
                    s, e = m.start(), m.end()
                    while e > s and text[e - 1] in ".,;:":
                        e -= 1
                    while s < e and text[s] in " ":
                        s += 1
                    if e - s < 1:
                        continue
                    if name == "acronym" and m.group().rstrip("s") in _ACRONYM_STOP:
                        continue
                    if name == "math" and sum(c.isalpha() for c in text[s:e]) > 0.7 * (e - s) and e - s > 25:
                        continue            # do not swallow a long sentence because of a stray '<'
                    if name == "math":      # 'k = number of layers': the English word after '=' is translated
                        while True:
                            mm = re.search(r"\s*\b([a-z]{3,})\b[^\w\s]*$", text[s:e])
                            if not mm or mm.group(1) in _MATHFUNCS or mm.start() == 0:
                                break
                            e = s + mm.start()
                        e = s + len(text[s:e].rstrip(" =+-*/×·"))
                        if not re.search(r"[=≈≠≤≥<>±∝]", text[s:e]) or e - s < 3:
                            continue
                    cands.append((s, e))
        if self.exclude:                                # "translate X": the user wants these words translated
            cands = [(s, e) for s, e in cands
                     if " ".join(_TOKEN_RE.findall(text[s:e].lower())) not in self.exclude]
        cands.sort(key=lambda se: (se[0], -(se[1] - se[0])))
        out: List[Tuple[int, int]] = []
        last = 0
        for s, e in cands:
            if s >= last:
                out.append((s, e))
                last = e
        return out

    def is_technical(self, text: str) -> bool:
        t = text.strip()
        letters = sum(c.isalpha() for c in t)
        if letters < 2 or (letters <= 3 and len(t.split()) == 1):
            return True
        sp = self.spans(t, is_allcaps(t))
        return bool(sp) and sum(e - s for s, e in sp) >= 0.7 * len(t)


# ════════════════════════════════════════════════════════════════════════════
#  Paragraph -> translation items (text with placeholders) -> pieces with styles
# ════════════════════════════════════════════════════════════════════════════
@dataclass
class Ph:
    text: str
    keep: bool                          # True: stays exactly as it is (English)
    style: Optional[Run] = None         # None = style of the paragraph
    va: str = ""
    item: Optional["Item"] = None       # translated emphasised stretch
    gloss: str = ""                     # fixed translation from the glossary (replaces the kept English text)
    img: Optional[Tuple[int, float, float, float, float]] = None   # cropped picture of the original
    parts: Optional[List[Run]] = None   # inline maths: original runs, re-typed exactly as they are


@dataclass
class Item:
    src: str
    ph: Dict[int, Ph]
    style: Optional[Run] = None         # own style (long emphasised stretch)
    needs_mt: bool = True
    lead: str = ""                      # heading number placeholder(s): kept out of the text sent to the model
    literal: bool = False               # plain words were sent to the model: nothing to put back
    eng: str = ""                       # English original of a heading, written in brackets after the translation
    eng_style: Optional[Run] = None     # title: the original goes on a line of its own UNDER the translation (smaller)


@dataclass
class Piece:
    text: str
    style: Optional[Run] = None
    va: str = ""
    latin: bool = False                 # kept English text (may use a Latin font)
    img: Optional[Tuple[int, float, float, float, float]] = None   # picture of the original (parameter names, maths)
    math: bool = False                  # part of an inline maths expression (kept, typeset with a maths-capable font)
    br: bool = False                    # a line break (the original title under the translated title)


def _color_dist(a: str, b: str) -> int:
    try:
        ra, ga, ba = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
        rb, gb, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
        return abs(ra - rb) + abs(ga - gb) + abs(ba - bb)
    except Exception:
        return 0 if a == b else 999


def same_style(a: Run, b: Run) -> bool:
    return (abs(a.size - b.size) <= 0.6 and a.bold == b.bold and a.italic == b.italic and a.mono == b.mono
            and _color_dist(a.color, b.color) <= 60)


def _alpha(t: str) -> int:
    return sum(c.isalpha() for c in t)


def _build_item(runs: List[Run], dom: Run, proto: Protector, style: Optional[Run], depth: int = 0) -> Item:
    ph: Dict[int, Ph] = {}
    parts: List[Tuple[str, str]] = []          # ("t", text) | ("p", token)
    n = 0
    full = "".join(r.text for r in runs)
    allcaps = is_allcaps(full)

    def protect_text(text: str) -> None:
        nonlocal n
        pos = 0
        sp = proto.spans(text, allcaps)
        i = 0
        while i < len(sp):
            s, e = sp[i]
            j = i
            if proto.gloss_parts(text[s:e]):                 # words of the glossary in a row form one phrase
                while (j + 1 < len(sp) and proto.gloss_parts(text[sp[j + 1][0]:sp[j + 1][1]])
                       and not text[sp[j][1]:sp[j + 1][0]].strip()):
                    j += 1
                e = sp[j][1]
                g = proto.gloss_chain([text[a:b] for a, b in sp[i:j + 1]])
            else:
                g = ""
            if s > pos:
                parts.append(("t", text[pos:s]))
            n += 1
            ph[n] = Ph(text[s:e], True, gloss=g)
            parts.append(("p", ph_token(n)))
            pos = e
            i = j + 1
        if pos < len(text):
            parts.append(("t", text[pos:]))

    for r in runs:
        if (r.parts or r.img) and depth == 0 and r.text.strip():   # inline maths: kept exactly as it is, ONE unit
            lead = r.text[:len(r.text) - len(r.text.lstrip())]
            if lead:
                parts.append(("t", lead))
            n += 1
            ph[n] = Ph(r.text.strip(), True, r, "", None, "", None if r.parts else r.img, r.parts)
            parts.append(("p", ph_token(n)))
            trail = r.text[len(r.text.rstrip()):]
            if trail:
                parts.append(("t", trail))
            continue
        if depth > 0 or same_style(r, dom) and not r.va:
            protect_text(r.text)
            continue
        lead = r.text[:len(r.text) - len(r.text.lstrip())]
        trail = r.text[len(r.text.rstrip()):]
        core = r.text.strip()
        if not core:
            parts.append(("t", r.text))
            continue
        if lead:
            parts.append(("t", lead))
        n += 1
        fixed = fixed_heading(core, getattr(proto.opts, "src_lang", "en"), proto.lang) if not r.va and len(core.split()) <= 6 else None
        if fixed:
            ph[n] = Ph(core, True, r, "", None, fixed)
            parts.append(("p", ph_token(n)))
            if trail:
                parts.append(("t", trail))
            continue
        keep = bool(r.va) or r.mono or _alpha(core) < 2 or proto.is_technical(core)
        if keep:
            ph[n] = Ph(core, True, r, r.va)
        else:
            sub = _build_item([Run(core, r.size, r.bold, r.italic, r.color, r.mono, "", r.font)], r, proto, r,
                              depth + 1)
            ph[n] = Ph(core, False, r, "", sub)
        parts.append(("p", ph_token(n)))
        if trail:
            parts.append(("t", trail))

    if allcaps:
        parts = [("t", t.lower()) if k == "t" else (k, t) for k, t in parts]
        for i, (k, t) in enumerate(parts):
            if k == "t" and any(c.isalpha() for c in t):
                j = next(j for j, c in enumerate(t) if c.isalpha())
                parts[i] = (k, t[:j] + t[j].upper() + t[j + 1:])
                break
    src = "".join(t for _, t in parts)
    needs = _alpha(PH_RE.sub("", src)) >= 2
    return Item(src, ph, style, needs)


def prepare_para(p: Para, proto: Protector) -> List[Item]:
    dom = Run("", p.size, p.bold, p.italic, p.color, p.mono)
    groups: List[Tuple[List[Run], Optional[Run]]] = []
    cur: List[Run] = []
    for r in merge_cites(p.runs):
        diff = not same_style(r, dom)
        if diff and not r.va and len(r.text.split()) > MAX_STYLED_WORDS and not r.mono:
            if cur:
                groups.append((cur, None))
                cur = []
            groups.append(([r], r))
        else:
            cur.append(r)
    if cur:
        groups.append((cur, None))
    items = []
    for runs, style in groups:
        items.append(_build_item(runs, style or dom, proto, style))
    is_head = getattr(p, "heading", False)
    if len(items) == 1 and (is_head or (p.n_lines == 1 and len(p.text.split()) <= 12 and _title_like(p.text))):
        _prepare_heading(items[0], proto, is_head and not p.title)
    if p.title and items and proto.opts.bilingual_headings:
        # the title of the document: the original title is printed under the translation, at 55 % of its size
        items[-1].eng = " ".join(p.text.split())
        items[-1].eng_style = Run("", round(p.size * 0.55, 2), p.bold, p.italic, p.color, False, "", p.font)
    return items


_CITE_RE = re.compile(r"\[\d+(?:\s*[,–\-]\s*\d+)*\]")


def merge_cites(runs: List[Run]) -> List[Run]:
    """'[' + blue '9' + ', ' + blue '10' + ']' come from the PDF as separate runs: join every citation into ONE run
    so that it is kept as a unit ([9, 10]) and its brackets cannot get lost in the translation."""
    import dataclasses as dc
    full = "".join(r.text for r in runs)
    ms = list(_CITE_RE.finditer(full))
    if not ms:
        return runs
    segs, c = [], 0
    for r in runs:
        segs.append((r, c, c + len(r.text)))
        c += len(r.text)
    # '[0, 1]' inside maths (λ ∈ [0, 1]) is an interval, not a citation: the maths unit is never cut
    ms = [m for m in ms if not any(r.parts and s < m.end() and m.start() < e for r, s, e in segs)]
    if not ms:
        return runs

    def cut(a: int, b: int) -> List[Run]:
        return [dc.replace(r, text=r.text[max(a, s) - s:min(b, e) - s],
                           bbox=r.bbox if (max(a, s), min(b, e)) == (s, e) else None,
                           img=r.img if (max(a, s), min(b, e)) == (s, e) else None,
                           parts=r.parts if (max(a, s), min(b, e)) == (s, e) else None)
                for r, s, e in segs if max(a, s) < min(b, e)]

    out: List[Run] = []
    last = 0
    for m in ms:
        out += cut(last, m.start())
        first = cut(m.start(), m.end())
        if first:
            out.append(dc.replace(first[0], text=m.group()))
        last = m.end()
    return out + cut(last, len(full))


def _title_like(t: str) -> bool:
    """A short one-line paragraph that may be a title / label – not the tail of a sentence cut off by an equation
    ('describe the difference between adjacent image patches.') and not a short full sentence."""
    t = t.strip()
    first = next((c for c in t if c.isalpha()), "")
    return bool(t) and not first.islower() and not re.search(r"[.,;:]\s*$", t)


def _prepare_heading(it: Item, proto: Protector, bilingual: bool = True) -> None:
    """Headings: the number ('3.1.1') is kept out of the text sent to the model, standard headings (Abstract,
    Introduction, Related work …) come from a fixed table, other headings are sent in sentence case."""
    src, lead = it.src, ""
    while True:
        m = re.match(r"\s*ZX(\d+)XZ\s*", src)
        ph = it.ph.get(int(m.group(1))) if m else None
        if not (m and ph and ph.keep and re.fullmatch(r"\s*(?:[\d.]+|[A-Z]\.|[IVX]+\.)\s*", ph.text)):
            break
        lead += m.group(0).strip() + " "
        src = src[m.end():]
    src = re.sub(r"^[\s.:)\-–—]+(?=\S)", "", src)       # '3' + '. Benchmark': the dot belongs to the number
    core = src.strip()
    if not core:
        return
    if "ZX" not in core:
        fixed = fixed_heading(core, getattr(proto.opts, "src_lang", "en"), proto.lang)
        if fixed:
            it.src, it.lead, it.needs_mt = fixed, lead.strip(), False
            if bilingual and proto.opts.bilingual_headings and proto.lang == "fa" and lead.strip():
                it.eng = core.strip().lstrip(".:-–— ")                   # '5 نتیجه‌گیری (Conclusion)' – numbered headings only
            return
    core = sentence_case(core)
    plain = PH_RE.sub(lambda m_: it.ph[int(m_.group(1))].text if int(m_.group(1)) in it.ph else "", core)
    if len(plain.split()) <= 8 and it.ph:
        # a short heading with placeholders makes translation models hallucinate (and capitalised words look like
        # names): send the plain English words; the English heading is added in brackets after the translation
        for k, ph in list(it.ph.items()):
            if ph_token(k) in core:
                core = core.replace(ph_token(k), ph.text)
                del it.ph[k]
        it.literal = True
        if bilingual and proto.opts.bilingual_headings and proto.lang == "fa":
            it.eng = plain.strip().lstrip(".:-–— ")
    elif len(plain.split()) <= 8 and not it.ph:
        it.literal = True
        if bilingual and proto.opts.bilingual_headings and proto.lang == "fa":
            it.eng = plain.strip().lstrip(".:-–— ")
    it.src, it.lead = core, lead.strip()
    it.needs_mt = _alpha(PH_RE.sub("", it.src)) >= 2


def collect_texts(items: List[Item]) -> List[str]:
    out: List[str] = []
    for it in items:
        if it.needs_mt:
            out.append(it.src)
        for ph in it.ph.values():
            if ph.item is not None:
                out += collect_texts([ph.item])
    return out


# ---------------------------------------------------------------- Persian typography
_AR2FA = {ord("ي"): "ی", ord("ك"): "ک", ord("ى"): "ی", ord("ە"): "ه", ord("ۃ"): "ه",
          **{0x0660 + i: 0x06F0 + i for i in range(10)}}
_LAT2FA = {ord("0") + i: 0x06F0 + i for i in range(10)}
_PUA0 = 0xE000


def persian_typography(t: str, digits: bool = True) -> str:
    t = t.translate(_AR2FA)
    if digits:
        t = t.translate(_LAT2FA)
    t = re.sub(r"(?<=\D),|,(?=\D)", "،", t)
    t = t.replace("?", "؟").replace(";", "؛")
    t = re.sub(r'"([^"\n]+)"', r"«\1»", t)
    t = re.sub(r"“([^”\n]+)”", r"«\1»", t)
    t = re.sub(r"(?<![\u0600-\u06FF])(ن?می) (?=[\u0621-\u06CC])", "\\1\u200c", t)
    t = re.sub(r"(?<=[\u0621-\u06CC]) (ها|های)(?![\u0621-\u06CC])", "\u200c\\1", t)
    t = re.sub(r" +([،؛.:!؟])", r"\1", t)
    return re.sub(r" {2,}", " ", t)


def rtl_bracket_fix(t: str) -> str:
    """Brackets in right-to-left text: an invisible right-to-left mark (U+200F) outside each bracket makes the
    opening and the closing bracket resolve to the paragraph direction, so ( ) [ ] { } are mirrored correctly
    (one opens, the other closes) – the recommendation of the Unicode Bidirectional Algorithm (UAX #9)."""
    t = re.sub(r"(?<!\u200f)([(\[{])", "\u200f\\1", t)
    return re.sub(r"([)\]}])(?!\u200f)", "\\1\u200f", t)


def _post(t: str, lang: str, opts: Options) -> str:
    if lang == "fa":
        return rtl_bracket_fix(persian_typography(t, opts.persian_digits))
    if lang != "fa":                                    # Persian / Arabic digits of the original -> 0-9
        t = t.translate(DIGIT_NORM).replace("،", ",").replace("؛", ";").replace("؟", "?")
    if lang == "de":                                    # German quotation marks „…“
        t = re.sub(r'"([^"\n]+)"', "„\\1“", t)
        t = re.sub(r"“([^”\n]+)”", "„\\1“", t)
    return re.sub(r" {2,}", " ", t)


def assemble_item(item: Item, tr: Dict[str, str], lang: str, opts: Options,
                  style: Optional[Run] = None) -> List[Piece]:
    style = style or item.style
    out = tr.get(item.src, item.src) if item.needs_mt else item.src
    if item.lead:
        out = item.lead + " " + out
    chunks = PH_RE.split(out)                     # text, id, text, id, …
    tmp, ids = "", []
    for k, seg in enumerate(chunks):
        if k % 2 == 0:
            tmp += seg
        else:
            try:
                ids.append(int(seg.translate(DIGIT_NORM)))
            except ValueError:
                continue
            tmp += chr(_PUA0 + min(len(ids) - 1, 250))
    tmp = _post(tmp, lang, opts)
    pieces: List[Piece] = []
    used: Set[int] = set()

    def add_ph(i: int) -> None:
        ph = item.ph.get(i)
        if ph is None or i in used:
            return
        used.add(i)
        if ph.keep and ph.gloss:                        # glossary / standard heading: fixed translation
            g = rtl_bracket_fix(ph.gloss) if lang == "fa" else ph.gloss.translate(DIGIT_NORM)
            pieces.append(Piece(g, ph.style or style, ph.va, False))
        elif ph.keep and ph.parts:                      # inline maths: every original run, exactly as it was
            sub = [pr_ for pr_ in ph.parts if pr_.text]
            for m, pr_ in enumerate(sub):
                t = pr_.text
                if m == 0:
                    t = t.lstrip()
                if m == len(sub) - 1:
                    t = t.rstrip()
                if t and lang != "fa":
                    t = t.translate(DIGIT_NORM)                 # Persian original: [۰, ۱۵۰] -> [0, 150]
                if t:
                    # non-breaking spaces: one expression is never split over two lines
                    pieces.append(Piece(math_text(t).replace(" ", " "), pr_, pr_.va, True, pr_.img, True))
        elif ph.keep and ph.img:
            pieces.append(Piece(ph.text, ph.style or style, "", True, ph.img))
        elif ph.keep:
            txt = ph.text
            if lang == "fa" and opts.persian_digits and re.fullmatch(r"\s*[\d.,:/–\-]+\.?\s*", txt):
                txt = txt.translate(_LAT2FA)            # plain numbers / heading numbers: always Persian digits
            elif lang != "fa":
                txt = txt.translate(DIGIT_NORM)         # Persian original: ۱ -> 1
            if _INLINE_MATH_CH.search(txt):             # 'ε = 10', 'x ≤ y': kept on one line, in a maths font
                txt = math_text(txt).replace(" ", " ")
            pieces.append(Piece(txt, ph.style or style, ph.va, True, None, bool(_SYMBOL_CHARS.search(txt))))
        elif ph.item is not None:
            pieces.extend(assemble_item(ph.item, tr, lang, opts, ph.style))

    for ch in re.split("([\ue000-\ue0fa])", tmp):
        if not ch:
            continue
        if len(ch) == 1 and _PUA0 <= ord(ch) <= _PUA0 + 250:
            k = ord(ch) - _PUA0
            if k < len(ids):
                add_ph(ids[k])
        else:
            pieces.append(Piece(ch, style))
    for i in item.ph:                              # tokens the model lost: put them at the end
        if i not in used and not (item.literal and not PH_RE.search(item.src)):
            pieces.append(Piece(" ", style))
            add_ph(i)
    if item.eng and item.eng_style is not None:    # title: the original on the next line, in a smaller size
        pieces.append(Piece("\n", style, br=True))
        pieces.append(Piece(item.eng, item.eng_style, "", True))
    elif item.eng and lang == "fa":                # 5 نتیجه‌گیری (Conclusion)
        pieces.append(Piece(rtl_bracket_fix(" ("), style))
        pieces.append(Piece(item.eng, style, "", True))
        pieces.append(Piece(rtl_bracket_fix(")"), style))
    return pieces


def assemble_para(items: List[Item], tr: Dict[str, str], lang: str, opts: Options) -> List[Piece]:
    pieces: List[Piece] = []
    for k, it in enumerate(items):
        part = assemble_item(it, tr, lang, opts)
        if k and part and pieces and not pieces[-1].text.endswith(" ") and not part[0].text.startswith(" "):
            pieces.append(Piece(" "))
        pieces += part
    return pieces


# ════════════════════════════════════════════════════════════════════════════
#  Local translation engine  (open source, runs on this computer, no website / API key)
# ════════════════════════════════════════════════════════════════════════════
INSTALL_MSG = ("The translation engine needs these open-source packages (install once):\n"
               "    pip install ctranslate2 transformers sentencepiece protobuf accelerate torch\n"
               "('torch' is only used once, to convert the model to a fast format.)")

_SENT_RE = re.compile(r"(?<=[.!?؟])\s+(?=[\"'“‘«(\[]?[A-Z0-9\u00c0-\u00de\u0600-\u06ff]|ZX\d)")
_ABBREV_RE = re.compile(r"(?:\b(?:Fig|Figs|Eq|Eqs|Dr|Mr|Mrs|Ms|Prof|St|vs|etc|No|Nos|Vol|pp|cf|Sec|Ch|Inc|Ltd|Jr|Sr|al)"
                        r"|\b[A-Z]|\be\.g|\bi\.e)\.$")


def split_sentences(text: str, max_words: int = 60) -> List[str]:
    """Sentence splitter (neural translation models work best sentence by sentence)."""
    raw = [s for s in _SENT_RE.split(text.strip()) if s.strip()]
    merged: List[str] = []
    for s in raw:
        if merged and _ABBREV_RE.search(merged[-1]):
            merged[-1] += " " + s
        else:
            merged.append(s)
    out: List[str] = []
    for s in merged:
        if len(s.split()) <= max_words:
            out.append(s)
            continue
        pieces: List[str] = []
        for part in re.split(r"(?<=[;:,])\s+", s):
            w = part.split()
            pieces += [" ".join(w[i:i + max_words]) for i in range(0, len(w), max_words)]
        cur: List[str] = []
        n = 0
        for pc in pieces:
            k = len(pc.split())
            if cur and n + k > max_words:
                out.append(" ".join(cur))
                cur, n = [], 0
            cur.append(pc)
            n += k
        if cur:
            out.append(" ".join(cur))
    return out


def _guess_family(ref: str) -> str:
    s = ref.lower()
    if "madlad" in s:
        return "madlad"
    if "nllb" in s or "m2m" in s:
        return "nllb"
    p = Path(ref)
    for name in ("family.txt",):
        if (p / name).is_file():
            return (p / name).read_text().strip() or "nllb"
    try:
        mt = json.loads((p / "config.json").read_text("utf-8")).get("model_type", "")
        if mt == "t5":
            return "madlad"
    except Exception:
        pass
    return "nllb"


def _fetch_source_model(model_ref: str, dest: Path, log: Callable[[str], None]) -> Path:
    """Download the original model files ONCE into our own folder (resumable, no symlinks – works on Windows).
    The folder is kept until the conversion has succeeded, so a failed conversion never triggers a new download."""
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError(INSTALL_MSG) from exc
    marker = dest / ".download_complete"
    if marker.exists():
        log(f"Model files already downloaded ({dest}) – no new download.")
        return dest
    log(f"Downloading “{model_ref}” into {dest} (resumable) …")
    dest.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=model_ref, local_dir=str(dest),
                      allow_patterns=["*.json", "*.model", "*.txt", "*.safetensors", "*.bin", "spiece*"],
                      ignore_patterns=["*.msgpack", "*.h5", "*.onnx", "*.ot", "flax_*", "tf_*", "rust_*"])
    marker.write_text("ok")
    return dest


def _untie_t5_output_scale(src: str) -> None:
    """MADLAD-400 has SEPARATE input and output embeddings (config.json: tie_word_embeddings = false).  transformers
    5 reports them as tied, and the CTranslate2 converter then multiplies the decoder output by d_model ** -0.5
    (1/32): the best token stays the best, but every probability becomes almost uniform (log p ≈ -12 for each
    token), which spoils beam search ('Best quality') and the ranking of hypotheses in the retry ladder.  The
    converter is told the truth from the model's own config.json."""
    try:
        tie = json.loads((Path(src) / "config.json").read_text("utf-8")).get("tie_word_embeddings", True)
        if tie is not False:
            return
        import ctranslate2.converters.transformers as ctt
        loader = getattr(ctt, "T5Loader", None)
        if loader is None or getattr(loader, "_dt_untied", False):
            return
        orig = loader.get_model_spec

        def get_model_spec(self, model):
            spec = orig(self, model)
            try:
                from ctranslate2.specs import model_spec as _ms
                spec.decoder.scale_outputs = _ms.OPTIONAL      # no output scaling: the embeddings are not tied
            except Exception:
                pass
            return spec
        loader.get_model_spec = get_model_spec
        loader._dt_untied = True
    except Exception:
        pass


def prepare_model(model_ref: str, log: Callable[[str], None], allow_download: bool = True) -> Tuple[Path, str]:
    """Return (folder of the converted CTranslate2 model, family). Downloads + converts only the first time."""
    p = Path(model_ref).expanduser()
    if p.is_dir():
        if (p / "model.bin").exists():
            return p, _guess_family(str(p))
        if not (p / "config.json").exists():
            raise FileNotFoundError(f"{p} is not a model folder (no model.bin / config.json).")
        src, name = str(p), p.name
    else:
        src, name = model_ref, model_ref.replace("/", "__")
    fam = _guess_family(model_ref)
    out = MODEL_DIR / (name + "-ct2-int8")
    if (out / "model.bin").exists():
        log(f"Converted model found: {out}  (offline, nothing is downloaded)")
        return out, fam
    if not p.is_dir() and not allow_download:
        raise RuntimeError(f"The model '{model_ref}' is not on this computer and downloads are disabled.")
    try:
        from ctranslate2.converters import TransformersConverter
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise RuntimeError(INSTALL_MSG) from exc
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if not p.is_dir():
        src = str(_fetch_source_model(model_ref, MODEL_DIR / (name + "-src"), log))
    log("One-time conversion to a fast 8-bit format (several minutes, needs RAM) – afterwards the app works "
        "completely offline …")
    tmp = out.with_name(out.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    _untie_t5_output_scale(src)
    last: Optional[Exception] = None
    for kw in ({"load_as_float16": True, "low_cpu_mem_usage": True}, {"load_as_float16": True}, {}):
        try:                                           # first try the low-memory options, then plainer ones
            TransformersConverter(src, **kw).convert(str(tmp), quantization="int8", force=True)
            last = None
            break
        except (TypeError, ImportError) as exc:
            last = exc
        except Exception as exc:                       # real failure: keep the downloaded files, show the reason
            raise RuntimeError(f"Model conversion failed ({type(exc).__name__}: {exc}). The downloaded files are "
                               f"kept in {src}; the next run continues from there without downloading again.") from exc
    if last is not None:
        raise RuntimeError(f"Model conversion failed: {last}\n{INSTALL_MSG}") from last
    AutoTokenizer.from_pretrained(src, use_fast=False).save_pretrained(str(tmp))
    for spm_name in ("spiece.model", "sentencepiece.bpe.model"):
        # transformers 5 saves only tokenizer.json; the SentencePiece model itself is needed for the token count
        # of the main window (local_tokenizer) after the downloaded folder is deleted
        if (Path(src) / spm_name).is_file() and not (tmp / spm_name).is_file():
            shutil.copy(Path(src) / spm_name, tmp / spm_name)
    (tmp / "family.txt").write_text(fam)
    shutil.rmtree(out, ignore_errors=True)
    tmp.rename(out)
    if not p.is_dir():
        shutil.rmtree(MODEL_DIR / (name + "-src"), ignore_errors=True)      # free the disk space
    log(f"Model converted and stored in {out} – it will not be downloaded again.")
    return out, fam


_MT_CACHE: Dict[str, tuple] = {}
_MT_LOCK = threading.Lock()


def physical_cores() -> int:
    """Real CPU cores (not hyper-threads).  The translation engine is fastest with one thread per real core:
    measured on a 4-core / 8-thread CPU, 4 threads are 25 % faster than 8."""
    n = os.cpu_count() or 4
    try:
        import psutil                                   # type: ignore
        return max(1, psutil.cpu_count(logical=False) or n)
    except Exception:
        pass
    if os.name == "nt":
        try:
            import subprocess
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  "(Get-CimInstance Win32_Processor | Measure-Object NumberOfCores -Sum).Sum"],
                                 capture_output=True, text=True, timeout=20,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
            if out.isdigit() and 1 <= int(out) <= n:
                return int(out)
        except Exception:
            pass
    return n


class _SpmTok:
    """The MADLAD-400 tokenizer with the small sentencepiece library alone.  It gives exactly the tokens of the
    transformers T5 tokenizer (tested on English, Persian, German, French and Spanish sentences, placeholders,
    digits, tabs and no-break spaces), but loads in 0.1 s: importing transformers took 111 s on a 4-core PC, which
    was most of the waiting time of Quick translate and of every job start."""

    def __init__(self, sp):
        self.sp = sp
        self.eos = sp.eos_id()
        self.src_lang = ""

    @classmethod
    def load(cls, path: Path) -> Optional["_SpmTok"]:
        f = Path(path) / "spiece.model"
        if not f.is_file():
            return None
        try:
            import sentencepiece as spm
            return cls(spm.SentencePieceProcessor(model_file=str(f)))
        except Exception:
            return None

    def encode(self, s: str, truncation: bool = True, max_length: int = 300) -> List[int]:
        ids = self.sp.encode(re.sub(r"\s+", " ", s).strip())       # T5 collapses every run of white space
        if truncation and len(ids) > max_length - 1:
            ids = ids[:max_length - 1]
        return ids + [self.eos]

    def convert_ids_to_tokens(self, ids: List[int]) -> List[str]:
        return [self.sp.id_to_piece(int(i)) for i in ids]

    def convert_tokens_to_ids(self, tokens: List[str]) -> List[int]:
        return [self.sp.piece_to_id(t) for t in tokens]

    def decode(self, ids: List[int], skip_special_tokens: bool = True) -> str:
        if skip_special_tokens:
            ids = [i for i in ids if not (self.sp.is_control(i) or self.sp.is_unknown(i))]
        return self.sp.decode(list(ids))


class LocalMT:
    """CTranslate2 inference for MADLAD-400 (T5) and NLLB-200 models."""

    def __init__(self, model_ref: str, lang: str, log: Callable[[str], None] = print, allow_download: bool = True,
                 src: str = "en"):
        self.lang = lang
        self.src = src
        self.latin_tgt = lang in LATIN_LANGS
        with _MT_LOCK:
            if model_ref not in _MT_CACHE:
                try:
                    import ctranslate2
                except ImportError as exc:
                    raise RuntimeError(INSTALL_MSG) from exc
                path, fam = prepare_model(model_ref, log, allow_download)
                log(f"Loading translation model ({fam}) …")
                tok = _SpmTok.load(path) if fam == "madlad" else None
                if tok is None:                       # NLLB (or no SentencePiece file): the tokenizer of transformers
                    try:
                        from transformers import AutoTokenizer
                    except ImportError as exc:
                        raise RuntimeError(INSTALL_MSG) from exc
                    kw = {"src_lang": "eng_Latn"} if fam == "nllb" else {}
                    tok = AutoTokenizer.from_pretrained(str(path), use_fast=False, **kw)
                threads = physical_cores()
                ct = ctranslate2.Translator(str(path), device="auto", compute_type="auto",
                                            inter_threads=1, intra_threads=threads)
                log(f"Translation engine runs on {threads} CPU thread(s) (one per real core).")
                _MT_CACHE[model_ref] = (ct, tok, fam)
        self.ct, self.tok, self.fam = _MT_CACHE[model_ref]
        if self.fam == "nllb":
            try:
                self.tok.src_lang = LANGS.get(src, LANGS["en"])["nllb"]
            except Exception:
                pass
        self.tgt = LANGS[lang]["nllb"]
        self.beams = 1                      # 1 = greedy (fast, default); 2 = beam search ("Best quality")
        self.n_sent = self.n_retry = self.n_tok = 0

    # -- low level -----------------------------------------------------------
    def _encode(self, s: str) -> List[str]:
        if self.fam == "madlad":
            s = f"<2{self.lang}> {s}"
        return self.tok.convert_ids_to_tokens(self.tok.encode(s, truncation=True, max_length=300))

    def _decode(self, tokens: List[str]) -> str:
        if self.fam == "nllb":
            tokens = tokens[1:]
        ids = self.tok.convert_tokens_to_ids(tokens)
        return self.tok.decode(ids, skip_special_tokens=True).strip()

    latin_tgt = False                                   # the target language is written in Latin letters

    def _garbled(self, src: str, out: str) -> bool:
        """Hallucination check: replacement characters, words mixing Latin and Arabic letters, Latin words that are
        not in the source, absurd length."""
        if not out.strip() or "\ufffd" in out:
            return True
        sw = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", PH_RE.sub(" ", src))]
        if len(sw) >= 4 and sum(w in out.lower() for w in set(sw)) >= 0.6 * len(set(sw)) \
                and not re.search(r"[\u0600-\u06FF]", out) and out.strip().lower()[:30] == src.strip().lower()[:30]:
            return True                       # the model just copied the English sentence
        if re.search(r"[A-Za-z][\u0600-\u06FF]|[\u0600-\u06FF][A-Za-z]", out):
            return True
        if self.latin_tgt and re.search(r"[\u0600-\u06FF]{2,}", out):
            return True                       # Persian words left in a German / English … translation
        src_words = {w.lower() for w in re.findall(r"[A-Za-z]{2,}", src)}
        # (only for targets in another script: in German every word is a 'Latin word that is not in the source')
        if not self.latin_tgt and any(w.lower() not in src_words and not PH_RE.fullmatch(w) and w not in ("ZX", "XZ")
               for w in re.findall(r"[A-Za-z]{3,}", PH_RE.sub(" ", out))):
            return True
        # numbers must come back unchanged ('27 January 2022' -> '… 2018' is an invented date)
        if self._num_changed(src, out):
            return True
        ow = PH_RE.sub(" ", out).split()                  # the same two words three times in a row: a stuck model
        if any(ow[k:k + 2] == ow[k + 2:k + 4] == ow[k + 4:k + 6] for k in range(len(ow) - 5)):
            return True
        if any(ow[k:k + m] == ow[k + m:k + 2 * m] for m in (3, 4, 5, 6) for k in range(len(ow) - 2 * m + 1)):
            return True                                   # a phrase of 3+ words said twice in a row
        n_src = len(PH_RE.sub(" x ", src).split())
        if n_src <= 5:
            # a title / label of a few words: the model sometimes invents a sentence around it
            # ('Examples' -> 'Oh my God. Examples').  More than twice the words, or a new sentence inside, is wrong.
            n_out = len(PH_RE.sub(" x ", out).split())
            if n_out > 1.5 * n_src + 2:
                return True
            if re.search(r"[.!?؟]\s+\S", out.strip()) and not re.search(r"[.!?]\s+\S", src.strip()):
                return True
        return len(out) > 4 * len(src) + 40

    @staticmethod
    def _num_changed(src: str, out: str) -> bool:
        nums = lambda t: re.findall(r"\d{2,}", PH_RE.sub(" ", t).translate(DIGIT_NORM))
        got = nums(out)
        for d in nums(src):
            if d not in got:
                return True
            got.remove(d)
        return False

    n_kept = 0                                            # sentences left in the original language (see above)

    @staticmethod
    def _short(s0: str) -> bool:
        return len(PH_RE.sub(" x ", s0).split()) <= 6

    def translate_sentences(self, sents: List[str]) -> List[str]:
        """A sentence never starts with punctuation when it goes to the model: a leading '. ' or ': ' (left over
        after a number or a protected term) makes it invent an exclamation in front of the translation."""
        heads, cores = [], []
        for s0 in sents:
            m = re.match(r"[\s.:;,·•\-–—]+(?=[A-Za-z])", s0)
            heads.append(m.group(0) if m else "")
            cores.append(s0[m.end():] if m else s0)
        return [h + r for h, r in zip(heads, self._translate_checked(cores))]

    def _translate_checked(self, sents: List[str]) -> List[str]:
        # lines of a few words (titles, labels) are where greedy decoding invents text: they get the wide search
        # at once – they are short, so it costs almost nothing
        res = [""] * len(sents)
        short = [i for i, s0 in enumerate(sents) if self._short(s0)]
        rest = [i for i in range(len(sents)) if i not in set(short)]
        if short:
            # Title Case makes the model answer with invented list titles: 'Institutional Review Board Statement'
            # is sent as 'Institutional review board statement'
            for i, r1 in zip(short, self._translate_sentences([sentence_case(sents[i]) for i in short], beams=4,
                                                              clean=True)):
                res[i] = r1
        if rest:
            for i, r1 in zip(rest, self._translate_sentences([sents[i] for i in rest])):
                res[i] = r1

        def lost(s0: str, r0: str) -> bool:               # a protected term (ZX…XZ marker) did not come back
            need = {int(x.translate(DIGIT_NORM)) for x in PH_RE.findall(s0)}
            return bool(need - {int(x.translate(DIGIT_NORM)) for x in PH_RE.findall(r0)})

        bad = [i for i, (s0, r0) in enumerate(zip(sents, res)) if self._garbled(s0, r0) or lost(s0, r0)]
        self.n_sent += len(sents)
        self.n_retry += len(bad)
        if bad:                                           # second chance: wider search, first clean candidate wins
            again = self._translate_sentences([sents[i] for i in bad], beams=4, clean=True)
            for i, r1 in zip(bad, again):
                res[i] = r1
            # a short line that is still invented text: translate it inside a carrier sentence and cut the carrier off
            for i in bad:
                s0 = sents[i]
                if not (self._garbled(s0, res[i]) or lost(s0, res[i])):
                    continue
                if self._short(s0):
                    # protected terms at the two ends are set aside, the words between them are translated alone
                    m = re.fullmatch(r"((?:\s*ZX\d+XZ\s*)*)(.*?)((?:\s*ZX\d+XZ[.:;,]?\s*)*)", s0, re.S)
                    pre, core, post = m.groups() if m else ("", s0, "")
                    alt = ""
                    if core.strip() and "ZX" not in core:
                        if pre or post:
                            alt = self._translate_sentences([sentence_case(core.strip())], beams=4, clean=True)[0]
                        if not alt or self._garbled(core, alt):
                            alt = self._in_carrier(core)
                    # nothing usable: the original words are better than invented ones
                    res[i] = (pre + (alt or core.strip()) + " " + post).strip() if (alt or m) else s0
                    self.n_kept += 0 if alt else 1
                elif self._num_changed(s0, res[i]):
                    res[i] = s0                           # a changed number / date: keep the original sentence
                    self.n_kept += 1
            # still damaged (the model dropped a part of a long sentence, with its protected terms): translate the
            # sentence in two halves, cut at the ';' / ':' / ',' nearest to its middle
            for i in bad:
                s0 = sents[i]
                words = s0.split()
                short = len(res[i]) < 0.45 * len(PH_RE.sub("", s0))
                if len(words) < 16 or not (lost(s0, res[i]) or short):
                    continue
                cuts = [m.end() for m in re.finditer(r"[;:]\s", s0)] or [m.end() for m in re.finditer(r",\s", s0)]
                cuts = [c for c in cuts if 0.2 * len(s0) < c < 0.8 * len(s0)]
                if not cuts:
                    continue
                c = min(cuts, key=lambda x: abs(x - len(s0) / 2))
                halves = self._translate_sentences([s0[:c].strip(), s0[c:].strip()], beams=2)
                joined = " ".join(h.strip() for h in halves if h.strip())
                if not lost(s0, joined) or len(PH_RE.findall(joined)) > len(PH_RE.findall(res[i])):
                    res[i] = joined
        return [r.replace("\ufffd", "") for r in res]

    def _in_carrier(self, s0: str) -> str:
        """'Examples' alone confuses the model; 'The title of this section is "Examples".' does not.  The quoted part
        of the result is the translation.  Empty string = no usable result."""
        core = s0.strip().rstrip(".")
        if getattr(self, "src", "en") != "en":
            return ""                                     # the carrier sentence is English
        out = self._translate_sentences([f'The title of this section is "{core}".'], beams=4)[0]
        m = re.search(r'[«"“]([^»"”]{2,})[»"”]', out)
        if not m:
            return ""
        alt = m.group(1).strip()
        return alt if alt and not self._garbled(s0, alt) and (self.latin_tgt or not alt.isascii()) else ""

    def _translate_sentences(self, sents: List[str], beams: int = 0, clean: bool = False) -> List[str]:
        if not sents:
            return []
        src = [self._encode(s) for s in sents]
        beams = beams or max(1, int(getattr(self, "beams", 1)))        # 1 = greedy; 2 = "Best quality"
        longest = max(len(x) for x in src)
        kw = dict(beam_size=beams, num_hypotheses=beams, max_batch_size=2048, batch_type="tokens",
                  max_input_length=300, max_decoding_length=int(min(420, 2.5 * longest + 24)))
        if self.fam == "nllb":
            kw["target_prefix"] = [[self.tgt]] * len(src)
        res = self.ct.translate_batch(src, **kw)
        self.n_tok += sum(len(r.hypotheses[0]) for r in res if r.hypotheses)
        out: List[str] = []
        for s, r in zip(sents, res):
            need = {int(x.translate(DIGIT_NORM)) for x in PH_RE.findall(s)}
            best: Optional[str] = None
            for hyp in r.hypotheses:                     # prefer a hypothesis that kept every protected term
                txt = self._decode(hyp)
                got = {int(x.translate(DIGIT_NORM)) for x in PH_RE.findall(txt)}
                if need <= got and not (clean and self._garbled(s, txt)):
                    best = txt
                    break
                if best is None:
                    best = txt
            out.append(best or "")
        return out

    def translate_texts(self, texts: List[str]) -> List[str]:
        """Every text is cut into sentences (a keyword line 'a · b · c' into its items) and translated in one batch."""
        pieces: List[str] = []
        owner: List[Tuple[int, int]] = []
        units: List[List[str]] = []
        for i, t in enumerate(texts):
            segs = [x for x in t.split(" · ") if x.strip()] if t.count(" · ") >= 2 else [t]
            units.append(segs)
            for u, seg in enumerate(segs):
                for s in split_sentences(seg):
                    pieces.append(s)
                    owner.append((i, u))
        res: List[List[List[str]]] = [[[] for _ in segs] for segs in units]
        for (o, u), s in zip(owner, self.translate_sentences(pieces)):
            res[o][u].append(s)
        return [" · ".join(" ".join(x).strip() for x in r).strip() for r in res]


_LANG_WORDS = {
    "en": "the of and to in is that for with as are this be by on from which or an it was we can not have",
    "de": "der die und das ist nicht mit den von zu auf für eine ein sich des dem auch werden wird als bei durch",
    "fr": "le la les des et est une un dans que pour qui sur pas par au avec ce sont plus nous être cette aux",
    "es": "el la los las de que y en es una un por con para se del como más pero sus este son al esta entre",
}


_FA_ONLY = set("پچژگکیۀ")             # letters that Persian has and Arabic has not
_ARABIC_SCRIPT = re.compile("[\u0600-\u06ff\ufb50-\ufdff\ufe70-\ufefe]")
_RTL_FONT_RE = re.compile(r"(?:^|\+)(?:B[ _-]?(?:Nazanin|Zar|Lotus|Mitra|Yagut|Yaghout|Titr|Koodak|Traffic|Roya|"
                          r"Compset|Homa|Badr|Davat|Elham|Ferdosi|Jadid|Kamran|Karim|Morvarid|Nasim|Sina|"
                          r"Setareh|Shiraz|Tabassom|Yas|Yekan)|IRANSans|IranSans|Vazir|Sahel|Samim|Shabnam|Tanha|"
                          r"Parastoo|Yekan|XB[ _-]|Nazli|Nazanin|Zar\b|Lotus\b|Mitra|Traditional ?Arabic|"
                          r"Arabic|Naskh|Nastaliq|Tahoma)", re.I)


def text_damage(text: str) -> float:
    """Share of characters that can not be real text: control characters, private-use and replacement characters.
    A PDF whose fonts have no correct character table gives such text when it is read ('\x9e¤8د \x99¦')."""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    bad = sum(1 for c in chars if "\x80" <= c <= "\x9f" or "\ue000" <= c <= "\uf8ff" or c in "\ufffd¤¦§¨")
    return bad / len(chars)


def detect_language(text: str, fonts: Optional[List[str]] = None) -> str:
    """Language of a text.  Persian by its letters (also when only a part of the text layer is readable: Arabic
    script that contains a Persian-only letter, or Persian fonts), English / German / French / Spanish by their
    most frequent words.  '' = not enough text to tell."""
    letters = [c for c in text if c.isalpha()]
    arab = [c for c in letters if _ARABIC_SCRIPT.match(c)]
    fa_font = bool(fonts) and sum(1 for f in fonts if _RTL_FONT_RE.search(f)) >= max(1, len(fonts) // 4)
    if len(arab) >= 30 or (fa_font and len(arab) >= 5):
        norm = unicodedata.normalize("NFKC", "".join(arab))
        share = len(arab) / max(1, len(letters))
        # a damaged text layer turns the Latin part into rubbish, so the share of Arabic letters can be low
        if share > 0.35 or (share > 0.12 and (any(c in _FA_ONLY for c in norm) or fa_font)) or \
                (fa_font and text_damage(text) > 0.02):
            return "fa"
    if len(letters) < 40:
        return ""
    words = re.findall(r"[a-zà-ÿ]+", text.lower())
    real = [w for w in words if len(w) >= 2]                     # single letters say nothing (and rubbish is full of them)
    if len(real) < 20:
        return ""
    score = {lg: sum(real.count(w) for w in set(ws.split())) for lg, ws in _LANG_WORDS.items()}
    best = max(score, key=score.get)
    second = sorted(score.values())[-2]
    if score[best] < 0.06 * len(real) or score[best] < 1.5 * second:
        return ""
    return best


_TOKENIZER: List = []


def local_tokenizer():
    """The SentencePiece model of the translation model that is on this computer (MADLAD-400, else NLLB-200),
    loaded once with the small sentencepiece library (fast - transformers is not needed for counting).  None when
    no model is there yet (nothing is downloaded for this)."""
    if _TOKENIZER:
        return _TOKENIZER[0]
    tok = None
    try:
        import sentencepiece as spm
        dirs = (sorted(MODEL_DIR.glob("*madlad*")) + sorted(MODEL_DIR.glob("*nllb*"))) if MODEL_DIR.is_dir() else []
        for d in dirs:
            f = d / "spiece.model" if (d / "spiece.model").is_file() else d / "sentencepiece.bpe.model"
            if f.is_file():
                tok = spm.SentencePieceProcessor(model_file=str(f))
                break
    except Exception:
        tok = None
    _TOKENIZER.append(tok)
    return tok


def file_stats(pdf_path: str, cancel: Optional[Callable[[], bool]] = None) -> dict:
    """What the window shows after a file was chosen: its language, pages, words and (about) tokens, and whether
    its text layer can be read at all."""
    out = {"lang": "", "pages": 0, "words": 0, "tokens": 0, "text": True, "damaged": False}
    fonts: List[str] = []
    with fitz.open(xl(pdf_path)) as doc:
        out["pages"] = doc.page_count
        sample: List[str] = []
        words = 0
        step = max(1, doc.page_count // 12)
        for i in range(doc.page_count):
            if cancel and cancel():
                return out
            t = doc[i].get_text("text")
            words += len(t.split())
            if i % step == 0 and sum(len(x) for x in sample) < 60000:
                sample.append(t)
                try:
                    fonts += [f[3] for f in doc[i].get_fonts()]
                except Exception:
                    pass
    joined = " ".join(sample)
    out["words"] = words
    # tokens: counted with the real subword tokenizer of the model when it is on this computer (sample pages,
    # scaled to the whole file); otherwise about 2 tokens per word (measured on scientific English with MADLAD)
    ratio, out["tok_exact"] = 2.0, False
    tok = local_tokenizer()
    if tok is not None and joined.strip():
        try:
            ratio = len(tok.encode(joined)) / max(1, len(joined.split()))       # subword pieces per word
            out["tok_exact"] = True
        except Exception:
            pass
    est = words * ratio
    out["tokens"] = int(round(est / 100.0) * 100) if est >= 1000 else int(est)
    out["lang"] = detect_language(joined, sorted(set(fonts)))
    out["other"] = "" if out["lang"] else detect_other_language(joined)
    out["text"] = words >= 5 * max(1, out["pages"]) or words > 200
    out["damaged"] = text_damage(joined) > 0.02
    return out


MAX_FILE_PAGES = 700          # larger files are refused
REVIEW_SYMBOLS = list("±×÷·≤≥≠≈≡∝∞√∑∏∫∂∇∈∉⊂∪∩→←↔⇒°′αβγδεθλμπρστφχψωΔΣΩ²³½‰")
SPLIT_PAGES = 20              # long jobs on a slow computer: one PDF file per 20 pages


def system_info() -> Tuple[int, float]:
    """(real CPU cores, GB of memory)."""
    gb = 0.0
    try:
        import ctypes

        class _MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        ms = _MS()
        ms.dwLength = ctypes.sizeof(_MS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
            gb = ms.ullTotalPhys / 2 ** 30
    except Exception:
        gb = 0.0
    return physical_cores(), gb


def system_is_weak() -> bool:
    """A computer on which a long translation takes hours: 4 real cores or fewer, or less than 12 GB of memory."""
    cores, gb = system_info()
    return cores <= 4 or (0 < gb < 12)


def engine_tag(opts: "Options") -> str:
    """Name of the translation engine for cache files and the timing history."""
    if opts.engine == "local":
        return re.sub(r"\W+", "", opts.model.split("/")[-1] or "model")
    return re.sub(r"\W+", "", f"{opts.engine}_{opts.llm_model or 'model'}")


LLM_DEFAULT_URL = {"ollama": "http://localhost:11434/v1", "api": "https://api.openai.com/v1"}
OLLAMA_SUGGESTED = ["gemma3:12b", "gemma3:4b", "qwen3:8b", "qwen2.5:7b", "aya-expanse:8b"]


def llm_base_url(engine: str, url: str = "") -> str:
    u = (url or "").strip().rstrip("/") or LLM_DEFAULT_URL.get(engine, "")
    if engine == "ollama" and not u.endswith("/v1"):
        u += "/v1"                                         # Ollama speaks the OpenAI protocol under /v1
    return u


def llm_models(engine: str, url: str = "", key: str = "", timeout: float = 4.0) -> List[str]:
    """Models the server offers (Ollama: the models that are installed).  [] = server not reachable."""
    import urllib.request
    try:
        req = urllib.request.Request(llm_base_url(engine, url) + "/models",
                                     headers={"Authorization": f"Bearer {key or 'ollama'}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return sorted(str(m.get("id")) for m in data.get("data", []) if m.get("id"))
    except Exception:
        return []


class LLMMT(LocalMT):
    """A large language model as translation engine: Ollama on this computer, or any online service that speaks the
    OpenAI chat protocol.  Same interface and the same checks as the built-in engine; the glossary and "My
    instructions" of the user are written into the prompt, and a whole paragraph is translated in its context."""

    def __init__(self, opts: "Options", lang: str, log: Callable[[str], None] = print):
        self.lang, self.src = lang, opts.src_lang
        self.latin_tgt = lang in LATIN_LANGS
        self.engine = opts.engine
        self.model = (opts.llm_model or "").strip()
        self.url = llm_base_url(opts.engine, opts.llm_url)
        self.key = (opts.llm_key or "").strip()
        self.beams = 1
        self.n_sent = self.n_retry = self.n_tok = 0
        self.fam = "llm"
        self.t_used = 0.0
        if not self.model:
            raise RuntimeError("No model name is set for the translation engine (section 3, “LLM model”).")
        if opts.engine == "api" and not self.key:
            raise RuntimeError("The online engine needs an API key (section 3, “API key”).")
        if opts.engine == "ollama":
            have = llm_models("ollama", opts.llm_url)
            if not have:
                raise RuntimeError(f"Ollama does not answer at {self.url}. Install Ollama (https://ollama.com), "
                                   f"start it, and download a model, for example:  ollama pull {self.model}")
            if self.model not in have and self.model + ":latest" not in have:
                raise RuntimeError(f"The model “{self.model}” is not installed in Ollama. Installed: "
                                   f"{', '.join(have) or '(none)'}.  Download it with:  ollama pull {self.model}")
        ins = load_instructions_text().strip()
        gl = load_user_terms().strip()
        s_name, t_name = LANGS.get(self.src, LANGS["en"])["name"], LANGS[lang]["name"]
        self.system = (
            f"You are a professional translator of scientific and technical documents. Translate from {s_name} "
            f"to {t_name}.\n"
            "Rules:\n"
            "1. Tokens of the form ZX12XZ are protected terms or formulas. Copy every one of them unchanged, exactly "
            "once, at the place where it belongs in the translated sentence. Never translate, drop or invent one.\n"
            "2. Never add anything that is not in the source: no explanations, no notes, no greetings.\n"
            "3. Keep numbers, citations like [12], units, names of persons, product names and code unchanged.\n"
            "4. Use the natural, formal style of a textbook in the target language.\n"
            "5. You get numbered texts. Answer with the same numbers, one translation per number, in this form:\n"
            "[1] translation of text 1\n[2] translation of text 2\n"
            + (f"\nGlossary of the user (always follow it; lines 'term' alone mean: keep the term untranslated):\n"
               f"{gl[:3000]}\n" if gl else "")
            + (f"\nInstructions of the user (always follow them):\n{ins[:3000]}\n" if ins else ""))
        log(f"Translation engine: {'Ollama' if opts.engine == 'ollama' else 'online API'} – model {self.model} "
            f"at {self.url}" + ("; the glossary and “My instructions” are part of the prompt." if (gl or ins) else "."))

    def _chat(self, user: str) -> str:
        import urllib.request, urllib.error
        body = json.dumps({"model": self.model, "temperature": 0.1, "stream": False,
                           "messages": [{"role": "system", "content": self.system},
                                        {"role": "user", "content": user}]}).encode("utf-8")
        req = urllib.request.Request(self.url + "/chat/completions", data=body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {self.key or 'ollama'}"})
        last = ""
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=900) as r:
                    data = json.loads(r.read().decode("utf-8"))
                self.n_tok += int((data.get("usage") or {}).get("completion_tokens") or 0)
                txt = data["choices"][0]["message"]["content"] or ""
                return re.sub(r"<think>.*?</think>", "", txt, flags=re.S).strip()   # reasoning models
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:300]
                if exc.code in (401, 403):
                    raise RuntimeError(f"The translation service refused the API key (HTTP {exc.code}).") from exc
                if exc.code == 404:
                    raise RuntimeError(f"Model “{self.model}” or address {self.url} not found (HTTP 404). "
                                       f"{detail}") from exc
                last = f"HTTP {exc.code}: {detail}"
                time.sleep(3 * (attempt + 1))
            except Exception as exc:                       # noqa: BLE001 – network hiccup: try again
                last = f"{type(exc).__name__}: {exc}"
                time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"The translation engine does not answer ({last}).")

    def _ask(self, texts: List[str]) -> List[str]:
        user = "\n".join(f"[{i + 1}] {t}" for i, t in enumerate(texts))
        out = self._chat(user)
        got: Dict[int, str] = {}
        for m in re.finditer(r"^\s*\[(\d+)\]\s*(.*?)(?=^\s*\[\d+\]|\Z)", out, re.S | re.M):
            got[int(m.group(1))] = " ".join(m.group(2).split())
        if len(texts) == 1 and not got:
            got[1] = " ".join(out.split())
        return [got.get(i + 1, "") for i in range(len(texts))]

    def translate_texts(self, texts: List[str]) -> List[str]:
        """Whole paragraphs go to the model (it sees the context); a paragraph that comes back damaged is asked
        again alone, and if it is still damaged the original text is kept."""
        res = [""] * len(texts)
        batch: List[int] = []
        size = 0
        limit = 1800 if self.engine == "ollama" else 5000

        def lost(s0: str, r0: str) -> bool:
            need = {int(x.translate(DIGIT_NORM)) for x in PH_RE.findall(s0)}
            return bool(need - {int(x.translate(DIGIT_NORM)) for x in PH_RE.findall(r0)})

        def bad(s0: str, r0: str) -> bool:
            return (not r0.strip()) or lost(s0, r0) or self._num_changed(s0, r0) or "\ufffd" in r0 \
                or len(r0) > 4 * len(s0) + 60 or (self.latin_tgt and bool(re.search(r"[\u0600-\u06FF]{2,}", r0)))

        def flush() -> None:
            nonlocal batch, size
            if not batch:
                return
            for i, r in zip(batch, self._ask([texts[i] for i in batch])):
                res[i] = r
            batch, size = [], 0

        for i, t in enumerate(texts):
            if batch and size + len(t) > limit:
                flush()
            batch.append(i)
            size += len(t)
        flush()
        self.n_sent += len(texts)
        for i, t in enumerate(texts):
            if bad(t, res[i]):
                self.n_retry += 1
                again = self._ask([t])[0]
                if not bad(t, again):
                    res[i] = again
                elif lost(t, res[i]) and not lost(t, again):
                    res[i] = again
                elif not res[i].strip() or self._num_changed(t, res[i]):
                    res[i] = again if again.strip() and not self._num_changed(t, again) else t
        return res


def make_engine(opts: "Options", lang: str, log: Callable[[str], None]):
    if opts.engine in ("ollama", "api"):
        return LLMMT(opts, lang, log)
    return LocalMT(opts.model, lang, log, opts.allow_download, opts.src_lang)


def translate_all(texts: List[str], lang: str, mt, opts: Options, log: Callable[[str], None],
                  cancel: threading.Event, progress: Callable[[float, str], None],
                  stats: Optional[Dict[str, int]] = None) -> Dict[str, str]:
    """Translate the unique texts in batches, with an on-disk cache so interrupted jobs resume."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tag = engine_tag(opts) + ("" if opts.src_lang == "en" else f"_from_{opts.src_lang}")
    # "Best quality" has a cache of its own: ticking it really translates again instead of reusing the fast result
    cache_file = CACHE_DIR / f"mt_{tag}_{lang}{'_bq' if getattr(mt, 'beams', 1) > 1 else ''}.json"
    cache: Dict[str, str] = {}
    if cache_file.exists():
        try:
            cache = json.loads(cache_file.read_text("utf-8"))
        except Exception:
            cache = {}
    hk = lambda t: hashlib.sha1(t.encode("utf-8")).hexdigest()
    unique = list(dict.fromkeys(texts))
    def damaged(t: str) -> bool:                         # a cached result that lost protected terms is not reused
        need = {int(x.translate(DIGIT_NORM)) for x in PH_RE.findall(t)}
        return bool(need - {int(x.translate(DIGIT_NORM)) for x in PH_RE.findall(cache.get(hk(t), ""))})

    def invented(t: str) -> bool:                        # an old cached result that today's checks would refuse
        g = getattr(mt, "_garbled", None)
        return bool(g) and len(t.split()) <= 8 and g(t, cache.get(hk(t), ""))

    todo = [t for t in unique if hk(t) not in cache or damaged(t) or invented(t)]
    name = LANGS[lang]["name"]
    log(f"Translating {len(todo)} text blocks to {name} ({len(unique) - len(todo)} taken from cache) …")
    if stats is not None:
        stats["todo"] = stats.get("todo", 0) + len(todo)
        stats["all"] = stats.get("all", 0) + len(unique)

    def save() -> None:                                  # atomic: a killed job can never leave a broken cache
        tmp_f = cache_file.with_suffix(".tmp")
        tmp_f.write_text(json.dumps(cache, ensure_ascii=False), "utf-8")
        tmp_f.replace(cache_file)

    t0 = time.time()
    try:
        if todo:
            llm = getattr(mt, "fam", "") == "llm"
            # built-in engine: similar lengths in one batch = faster; LLM: reading order, so it sees the context
            order = list(todo) if llm else sorted(todo, key=len)
            step, done = (6 if llm else 12), 0
            for bi, i in enumerate(range(0, len(order), step)):
                if cancel.is_set():
                    raise Cancelled()
                grp = order[i:i + step]
                t_b = time.time()
                out_b = mt.translate_texts(grp)
                if stats is not None:                    # seconds of every text: its share of the batch
                    dt_b, n_b = time.time() - t_b, max(1, sum(len(t) for t in grp))
                    for t in grp:
                        stats.setdefault("cost", {})[t] = dt_b * len(t) / n_b
                for t, r in zip(grp, out_b):
                    cache[hk(t)] = r
                    act(f"  EN  {t[:90]}", "w")
                    act(f"  {lang.upper()}  {r[:90]}", "h" if len(t) < 60 else "w")
                done += len(grp)
                progress(done / len(todo), f"Translating to {name} – {done}/{len(todo)}")
                if bi % 5 == 4:
                    save()
    finally:
        save()
    return {t: cache[hk(t)] for t in unique if hk(t) in cache}


# ════════════════════════════════════════════════════════════════════════════
#  Rendering of the translated PDF
# ════════════════════════════════════════════════════════════════════════════
def piece_font_name(pc: Piece, p: Para) -> str:
    """Original PDF font name of an untranslated piece."""
    return (pc.style.font if pc.style is not None and pc.style.font else "") or p.font


def font_has_marks(paths) -> bool:
    """Does EVERY face of the font (regular, bold …) own glyphs for the invisible direction marks?  Otherwise a
    '�' box is drawn where such a mark stands (this happened in bold headings)."""
    try:
        from fontTools.ttLib import TTFont
        for path in (paths if isinstance(paths, (list, tuple)) else [paths]):
            if not path:
                continue
            cmap = TTFont(str(path), fontNumber=0, lazy=True).getBestCmap() or {}
            if not all(c in cmap for c in (0x200F, 0x202A, 0x202C)):
                return False
        return True
    except Exception:
        return False


def _face(fam: str, weight: str, style: str, fname: str) -> str:
    return f"@font-face{{font-family:{fam};font-weight:{weight};font-style:{style};src:url({fname});}}"


MUPDF_RTL_ALIGN_SWAPPED = True      # set to False if the PDF shows Align Right on the wrong side again


def wants_justify(p: Para, opts: Options) -> bool:
    """'Justify body text': every body paragraph, but not headings, titles and captions."""
    return bool(opts.justify_body and not p.heading and not p.mono and p.n_lines >= 2
                and not CAPTION_RE.match(p.text))


class CropSource:
    """Pictures of the ORIGINAL pages.  Letters of neighbouring lines that reach into the cut-out are painted over,
    so a picture of a formula never carries pieces of the words above or below it."""

    def __init__(self, path: str):
        self.doc = fitz.open(xl(path))
        self._chars: Dict[int, list] = {}

    def close(self) -> None:
        try:
            self.doc.close()
        except Exception:
            pass

    def chars(self, pno: int) -> list:
        if pno not in self._chars:
            found = []
            try:
                for b in self.doc[pno].get_text("rawdict")["blocks"]:
                    for ln in b.get("lines", []):
                        for sp in ln["spans"]:
                            for ch in sp["chars"]:
                                if not ch["c"].isspace():
                                    found.append(tuple(ch["bbox"]))
            except Exception:
                pass
            self._chars[pno] = found
        return self._chars[pno]

    def _render(self, pno: int, clip, keeps: list, dpi: int):
        page = self.doc[int(pno)]
        pix = page.get_pixmap(clip=clip, dpi=dpi, alpha=False)
        sx, sy = pix.width / max(clip.width, 0.01), pix.height / max(clip.height, 0.01)
        for x0, y0, x1, y1 in self.chars(int(pno)):
            if x1 < clip.x0 or x0 > clip.x1 or y1 < clip.y0 or y0 > clip.y1:
                continue
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if any(k.x0 <= cx <= k.x1 and k.y0 <= cy <= k.y1 for k in keeps):
                continue
            h, w = y1 - y0, x1 - x0
            r = fitz.Rect(x0 + 0.06 * w, y0 + 0.14 * h, x1 - 0.06 * w, y1 - 0.14 * h) & clip
            if r.is_empty:
                continue
            ir = fitz.IRect(int((r.x0 - clip.x0) * sx), int((r.y0 - clip.y0) * sy),
                            int(math.ceil((r.x1 - clip.x0) * sx)), int(math.ceil((r.y1 - clip.y0) * sy)))
            ir = ir & pix.irect
            if not ir.is_empty:
                pix.set_rect(ir, (255, 255, 255))
        return pix, sx, sy

    @staticmethod
    def _ink(pix) -> Optional[Tuple[int, int, int, int]]:
        """Pixel box (x0, y0, x1, y1) of everything that is not white."""
        n, w, h, stride = pix.n, pix.width, pix.height, pix.stride
        data = pix.samples
        white = b"\xff" * (w * n)
        top = bottom = None
        left, right = w * n, 0
        pat = re.compile(rb"[^\xff]")
        for y in range(h):
            row = data[y * stride: y * stride + w * n]
            if row == white:
                continue
            if top is None:
                top = y
            bottom = y
            m = pat.search(row)
            if m:
                left = min(left, m.start())
                right = max(right, len(row.rstrip(b"\xff")))
        if top is None:
            return None
        return left // n, top, (right + n - 1) // n, bottom + 1

    def png(self, pno: int, box: tuple, keep: Optional[list] = None, dpi: int = 300,
            pad: Tuple[float, float] = (0.4, 0.3)) -> Tuple[bytes, Tuple[float, float, float, float]]:
        """PNG of the ink of a stretch of the original page plus the page rectangle it really occupies (the cut-out is
        trimmed to the ink: the font boxes of maths are much taller than the formula itself)."""
        page = self.doc[int(pno)]
        clip = (fitz.Rect(box) + (-pad[0], -pad[1], pad[0], pad[1])) & page.rect
        keeps = [fitz.Rect(k) + (-1.2, -1.2, 1.2, 1.2) for k in (keep or [box])]
        pix, sx, sy = self._render(pno, clip, keeps, dpi)
        ink = self._ink(pix)
        if ink is not None:
            m = 1.2
            tight = fitz.Rect(clip.x0 + (ink[0] - m) / sx, clip.y0 + (ink[1] - m) / sy,
                              clip.x0 + (ink[2] + m) / sx, clip.y0 + (ink[3] + m) / sy) & clip
            if tight.width > 1 and tight.height > 1 and tight.get_area() < 0.98 * clip.get_area():
                clip = tight
                pix, sx, sy = self._render(pno, clip, keeps, dpi)
        return pix.tobytes("png"), (clip.x0, clip.y0, clip.x1, clip.y1)


class Renderer:
    """Puts translated paragraphs back where the originals were: same size (x the font-size factor), weight,
    style, colour and line spacing.  Headings use the heading font, everything else the body font; terms that are
    not translated keep the font and size of the source document."""

    def __init__(self, lang: str, opts: Options, body: Optional[Dict[str, Optional[Path]]],
                 heading: Optional[Dict[str, Optional[Path]]] = None, orig_names: Optional[Set[str]] = None,
                 charset: str = "", log: Callable[[str], None] = print, same_orig: bool = False):
        self.lang, self.info, self.opts = lang, LANGS[lang], opts
        self.same_orig = same_orig
        self.tmp = Path(tempfile.mkdtemp(prefix="pbt_fonts_"))
        chars = "".join(sorted(set(charset)))
        self.builtin = body is None
        self.head_family = "fs"
        self.orig_fam: Dict[str, str] = {}
        self._marks: Dict[str, bool] = {}
        self._crops: Dict[tuple, str] = {}
        self._src_path = ""
        self._src_doc = None
        self._font_files = {"body": body, "head": heading or body}
        css = ""

        def add_family(fam: str, fonts: Dict[str, Optional[Path]]) -> str:
            out = ""
            reg, bold = fonts["regular"], fonts.get("bold")
            ext = reg.suffix.lower()
            subset_font(reg, self.tmp / f"{fam}_r{ext}", chars, log)
            out += _face(fam, "normal", "normal", f"{fam}_r{ext}")
            if bold:
                subset_font(bold, self.tmp / f"{fam}_b{bold.suffix.lower()}", chars, log)
                out += _face(fam, "bold", "normal", f"{fam}_b{bold.suffix.lower()}")
            # italic faces are synthesised (Persian has no true italic): same glyphs, slanted
            obl = self.tmp / f"{fam}_i_src.ttf"
            if fonts.get("italic"):                          # a real italic face exists (Times New Roman …)
                it, bi = fonts["italic"], fonts.get("bolditalic")
                subset_font(it, self.tmp / f"{fam}_i{it.suffix.lower()}", chars, log)
                out += _face(fam, "normal", "italic", f"{fam}_i{it.suffix.lower()}")
                if bi:
                    subset_font(bi, self.tmp / f"{fam}_bi{bi.suffix.lower()}", chars, log)
                    out += _face(fam, "bold", "italic", f"{fam}_bi{bi.suffix.lower()}")
            elif make_oblique(reg, obl):
                subset_font(obl, self.tmp / f"{fam}_i.ttf", chars, log)
                out += _face(fam, "normal", "italic", f"{fam}_i.ttf")
                obl_b = self.tmp / f"{fam}_bi_src.ttf"
                if bold and make_oblique(bold, obl_b):
                    subset_font(obl_b, self.tmp / f"{fam}_bi.ttf", chars, log)
                    out += _face(fam, "bold", "italic", f"{fam}_bi.ttf")
            else:
                log(f"Note: no italic face could be generated for {reg.name}; italic text will be upright.")
            if not bold:
                log(f"Note: {reg.name} has no Bold weight; bold text will look regular.")
            return out

        if not self.builtin:
            css += add_family("fs", body)                    # type: ignore[arg-type]
            if heading is not None and heading["regular"] != body["regular"]:   # type: ignore[index]
                css += add_family("fh", heading)
                self.head_family = "fh"
        # fonts of the source document, for the text that is not translated (terms, names, formulas …)
        done: Dict[str, str] = {}
        for k, name in enumerate(sorted(orig_names or ())):
            key = clean_font_name(name)
            if key in done:
                self.orig_fam[name] = done[key]
                continue
            files = find_original_font(name)
            if files:
                fam = f"o{k}"
                try:
                    css += add_family(fam, files)
                    done[key] = self.orig_fam[name] = fam
                    continue
                except Exception as exc:
                    log(f"Original font '{name}' could not be embedded ({type(exc).__name__}); using a similar one.")
            done[key] = self.orig_fam[name] = generic_family(name)
        # a maths-capable Latin font (Greek letters, ∑ ∂ ∫ ≤ …, and the invisible direction marks): inline maths and
        # untranslated terms whose original font is not on this computer are typed with it
        self.math_fam = ""
        mfiles = find_math_font()
        if mfiles:
            try:
                css += add_family("mx", mfiles)
                self.math_fam = "mx"
            except Exception as exc:
                log(f"Maths font could not be embedded ({type(exc).__name__}); inline maths uses a built-in font.")
        self.css = css
        self.archive = fitz.Archive(str(self.tmp)) if css else None

    def close(self) -> None:
        try:
            if self._src_doc is not None:
                self._src_doc.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    @property
    def rtl(self) -> bool:
        return bool(self.info["rtl"] and self.opts.rtl_direction)

    # -- geometry ----------------------------------------------------------
    def _rect_for(self, page, p: Para, obstacles: list, content: Optional[Tuple[float, float]] = None) -> "fitz.Rect":
        r = fitz.Rect(p.bbox)
        if p.dh:
            r.y1 = max(r.y0 + 4, r.y1 + p.dh)
        if p.moved or p.dh:
            return r                                     # placed by hand: exactly where the user put it
        pr = page.rect
        me = fitz.Rect(p.bbox)
        c_l, c_r = content if content else (pr.x0 + 14, pr.x1 - 14)
        mirror = bool(self.info["rtl"] and self.opts.align_right and self._align(p) == "right")
        others = [o for o in obstacles if abs(o.x0 - me.x0) > 0.01 or abs(o.y0 - me.y0) > 0.01
                  or abs(o.x1 - me.x1) > 0.01 or abs(o.y1 - me.y1) > 0.01]
        # grow downwards into free space (long translations)
        lim = pr.y1 - 12
        mid = (r.y0 + r.y1) / 2
        for o in others:
            if o.y0 >= mid and o.x0 < r.x1 - 1 and o.x1 > r.x0 + 1:      # a block that starts below my middle
                lim = min(lim, max(o.y0 - 1, r.y1))
        r.y1 = max(r.y1, min(r.y1 + max(0.6 * r.height, 2.2 * p.size), lim))
        if p.n_lines == 1:
            # single line (headings, captions): may grow sideways
            left_lim, right_lim = pr.x0 + 14, pr.x1 - 14
            for o in others:
                if o.y0 < r.y1 and o.y1 > r.y0:
                    if o.x1 <= r.x0 + 1:
                        left_lim = max(left_lim, o.x1 + 2)
                    elif o.x0 >= r.x1 - 1:
                        right_lim = min(right_lim, o.x0 - 2)
            extra = 0.5 * r.width
            if p.align == "center":
                e = max(0.0, min(extra / 2, r.x0 - left_lim, right_lim - r.x1))
                r.x0 -= e
                r.x1 += e
            elif mirror:
                # an English heading sits at the left margin (plus its indentation); its Persian twin sits at the
                # RIGHT margin of the column (minus the same indentation)
                off = max(0.0, r.x0 - c_l)
                r.x1 = max(r.x1, min(right_lim, c_r - off))
                r.x0 -= max(0.0, min(extra, r.x0 - max(left_lim, c_l - 2)))
            elif p.align == "right":
                r.x0 -= max(0.0, min(extra, r.x0 - left_lim))
            else:
                r.x1 += max(0.0, min(extra, right_lim - r.x1))
        elif mirror and 0 <= c_r - r.x1 <= 0.06 * pr.width:
            r.x1 = c_r                                         # a ragged-right paragraph: use the full column width
        return r

    def _css_align(self, p: Para) -> str:
        """text-align value for the HTML engine.  In a right-to-left paragraph the engine counts left / right from
        the START edge, so the visual side has to be swapped (this was the reversed 'Align Right' in the PDF)."""
        a = self._align(p)
        if self.rtl and MUPDF_RTL_ALIGN_SWAPPED and a in ("left", "right"):
            return "left" if a == "right" else "right"
        return a

    def _align(self, p: Para) -> str:
        if wants_justify(p, self.opts):
            return "justify"
        if p.align in ("center", "justify"):
            return p.align
        if self.info["rtl"] and self.opts.align_right:
            return "right"                                     # Align Left (English)  ->  Align Right (Persian)
        return p.align      # (a right-to-left original was measured mirrored: 'left' = the side where reading starts)

    # -- bidirectional text ------------------------------------------------
    _NEUTRAL_GAP = re.compile(r"[\s,\u060c\-–/·:;]*")

    def _embed_latin(self, pieces: List[Piece], htmls: List[str]) -> List[str]:
        """Untranslated Latin runs that follow each other ('Nathan Silberman, Pushmeet Kohli, Rob Fergus', '[9, 10]')
        are wrapped as ONE left-to-right embedding, so the right-to-left paragraph can neither reorder the words
        nor swap their brackets."""
        out: List[str] = []
        i, n = 0, len(pieces)
        while i < n:
            if not pieces[i].latin:
                out.append(htmls[i])
                i += 1
                continue
            j, k = i, i + 1
            while k < n:
                if pieces[k].latin:
                    j, k = k, k + 1
                elif self._NEUTRAL_GAP.fullmatch(pieces[k].text) and k + 1 < n and pieces[k + 1].latin:
                    k += 1
                else:
                    break
            out.append(self._LRE + "".join(htmls[i:j + 1]) + self._PDF)
            i = j + 1
        return out

    # stand-ins for the direction marks LRE / PDF; replaced in place() once it is known which font can draw them
    _LRE, _PDF = "\x01", "\x02"

    def _marks_html(self, inner: str, plain_ok: bool) -> str:
        """Left-to-right embedding marks around maths / English inside Persian.  They are typed with the maths font
        (it owns the invisible glyphs), so they work in headings and bold text too and never show up as '\ufffd' boxes."""
        # RLM outside the embedding: a bracket / space between English text and the maths then follows the Persian
        # direction, so '(gradient) \u2207f(x)' can not turn into 'gradient) \u2207f(x)('
        if self.math_fam:
            lre = f'<span style="font-family:{self.math_fam};font-weight:normal;font-style:normal">\u200f\u202a</span>'
            pdf = f'<span style="font-family:{self.math_fam};font-weight:normal;font-style:normal">\u202c\u200f</span>'
        elif plain_ok:
            lre, pdf = "\u200f\u202a", "\u202c\u200f"
        else:
            lre = pdf = ""
        return inner.replace(self._LRE, lre).replace(self._PDF, pdf)

    def _marks_ok(self, heading: bool) -> bool:
        key = "head" if heading and self.head_family == "fh" else "body"
        if key not in self._marks:
            files = None if self.builtin else self._font_files[key]
            self._marks[key] = bool(files) and font_has_marks([files.get("regular"), files.get("bold")])  # type: ignore
        return self._marks[key]

    # -- pictures of the original (parameter names, maths inside the text) ---------
    def set_source(self, path: str) -> None:
        self._src_path = path
        self._src_doc = None

    def _crop(self, img: tuple, keep: Optional[list] = None, pad: float = 0.0):
        """Picture (PNG, 300 dpi, trimmed to its ink) of a stretch of the ORIGINAL page.  Returns
        (file name inside the font archive, page rectangle of the ink) or ("", None)."""
        key = tuple(round(v, 1) for v in img)
        if key in self._crops:
            return self._crops[key]
        res: tuple = ("", None)
        try:
            if self._src_doc is None:
                self._src_doc = CropSource(self._src_path)
            pno, x0, y0, x1, y1 = img
            data, rect = self._src_doc.png(int(pno), (x0, y0, x1, y1), keep)
            name = f"m{len(self._crops)}.png"
            (self.tmp / name).write_bytes(data)
            res = (name, rect)
        except Exception:
            res = ("", None)
        self._crops[key] = res
        return res

    def paste_formulas(self, page, formula_paras: List[Para], pno: int) -> None:
        """Every displayed equation is photographed from the ORIGINAL page (300 dpi) as ONE picture – all its rows,
        fractions, limits and its number – trimmed to the ink and pasted at its own place."""
        if not formula_paras or not self._src_path:
            return
        for p in formula_paras:
            try:
                x0, y0, x1, y1 = p.bbox
                box = fitz.Rect(x0 - 1.0, y0 - 1.0, x1 + 1.0, y1 + 1.0) & page.rect
                name, rect = self._crop((pno, box.x0, box.y0, box.x1, box.y1), list(p.members) or [p.bbox])
                if name and rect:
                    page.insert_image(fitz.Rect(rect), filename=str(self.tmp / name), keep_proportion=False,
                                      overlay=True)
            except Exception:
                continue

    # -- markup ------------------------------------------------------------
    def _piece_html(self, pc: Piece, p: Para) -> str:
        if pc.img and getattr(self, "_src_path", None):
            name, rect = self._crop(pc.img, [pc.img[1:]])
            if name and rect:
                h = rect[3] - rect[1]
                return f'<img src="{name}" style="height:{h:.2f}pt;vertical-align:middle">'
        if pc.br:
            return "<br>"
        raw = pc.text.replace("\n", " ")
        if self.lang in HYPHEN_DICT and not pc.latin:
            raw = hyphenate_de(raw, self.lang)
        txt = html.escape(raw)
        if not pc.latin and "  " in txt:
            txt = re.sub("  +", lambda m: " " + "&#160;" * (len(m.group()) - 1), txt)
        st = pc.style
        f = self.opts.font_scale * LANG_SHRINK.get(self.lang, 1.0)
        css: List[str] = []
        if pc.latin:
            # not translated: original font and original size, whatever the font-size factor is
            size = st.size if st is not None else p.size
            if abs(size - p.size * f) > 0.3:
                css.append(f"font-size:{size:.2f}pt")
            name = piece_font_name(pc, p)
            mono = (st.mono if st is not None else p.mono)
            fam = "monospace" if mono else self.orig_fam.get(name) or generic_family(name)
            if not self.info["rtl"] and _RTL_FONT_RE.search(name or "") and not mono:
                # a Persian original font (B Yagut, B Nazanin …) draws 0-9 as Persian digits: a Latin-script
                # translation must not type its kept terms and numbers with it
                fam = self.math_fam or "serif"
            if not mono and self.math_fam and (pc.math or MATHFONT_RE.search(name or "") or _SYMBOL_CHARS.search(raw)
                                               or fam in ("serif", "sans-serif")):
                fam = self.math_fam                     # θ, ∑, ≤ … : a font that really has these glyphs
            css.append(f"font-family:{fam}")
        elif st is not None and abs(st.size - p.size) > 0.6:
            css.append(f"font-size:{st.size * f:.2f}pt")
        if st is not None:
            if st.bold != p.bold:
                css.append(f"font-weight:{'bold' if st.bold else 'normal'}")
            if st.italic != p.italic:
                css.append(f"font-style:{'italic' if st.italic else 'normal'}")
            if _color_dist(st.color, p.color) > 60:
                css.append(f"color:{st.color}")
            if st.mono and not p.mono and not pc.latin:
                css.append("font-family:monospace")
        if pc.va in ("sup", "sub"):
            # the run already has its own (small) size: no <sub>/<sup>, which would make it smaller a second time
            css.append(f"vertical-align:{'super' if pc.va == 'sup' else 'sub'}")
            if pc.latin and not any(c.startswith("font-size") for c in css) and st is not None:
                css.append(f"font-size:{st.size:.2f}pt")
        if css:
            txt = f'<span style="{";".join(css)}">{txt}</span>'
        return txt

    def place(self, page, p: Para, pieces: List[Piece], obstacles: list,
              content: Optional[Tuple[float, float]] = None) -> Optional[float]:
        rtl = self.rtl
        rect = self._rect_for(page, p, obstacles, content)
        lh = max(min(p.lh, 1.6), 1.15, self.info["min_lh"]) * (p.lh_mult or 1.0)
        fam = "" if self.builtin else (self.head_family if p.heading else "fs")
        if self.same_orig:                              # Latin languages: the font of the original document
            fam = self.orig_fam.get(p.font) or generic_family(p.font, p.mono)
            if _RTL_FONT_RE.search(p.font or "") and not p.mono:
                fam = self.math_fam or "serif"           # Persian original font: Latin text needs a Latin face
            if fam in ("serif", "sans-serif") and p.serif and not p.mono and self.math_fam:
                fam = self.math_fam                     # serif original that is not on this computer: Times-like face
        size = p.size * self.opts.font_scale * LANG_SHRINK.get(self.lang, 1.0)
        style = (f"margin:0;padding:0;{'font-family:' + fam + ';' if fam else ''}"
                 f"font-size:{size:.2f}pt;line-height:{lh:.2f};color:{p.color};"
                 f"text-align:{self._css_align(p)};direction:{'rtl' if rtl else 'ltr'};")
        if p.bold:
            style += "font-weight:bold;"
        if p.italic:
            style += "font-style:italic;"
        if p.mono:
            style += "font-family:monospace;"
        htmls = [self._piece_html(pc, p) for pc in pieces]
        if rtl:
            htmls = self._embed_latin(pieces, htmls)
            plain_ok = not (p.heading or p.bold or not self._marks_ok(False))
            if not plain_ok:                            # headings / bold / fonts without the glyphs: no plain marks
                htmls = [re.sub("[\u200e\u200f\u202a\u202c]", "", h) for h in htmls]
            htmls = [self._marks_html(h, plain_ok) for h in htmls]
        inner = "".join(htmls)
        markup = f'<p dir="{"rtl" if rtl else "ltr"}" style="{style}">{inner}</p>'
        for low in (self.opts.min_scale, 0.35, 0.25, 0.18, 0.12, 0.08):     # shrink the whole paragraph until it fits
            spare, scale = page.insert_htmlbox(rect, markup, css=self.css, archive=self.archive, scale_low=low)
            if spare >= 0:
                return scale
        return None


def _translate_bookmarks(doc, titles_fn: Callable[[List[str]], List[str]], opts: Options,
                         log: Callable[[str], None]) -> None:
    try:
        toc = doc.get_toc(simple=True)
        if not toc:
            return
        kws = [k.strip().lower() for k in opts.backmatter_keywords.split(",") if k.strip()]
        idx = [i for i, (_, title, _) in enumerate(toc)
               if title.strip() and sum(c.isalpha() for c in title) >= 2
               and not any(title.strip().lower().startswith(k) for k in kws)]
        new = [list(t) for t in toc]
        for i, t2 in zip(idx, titles_fn([toc[i][1].strip() for i in idx])):
            if t2:
                new[i][1] = t2
        doc.set_toc(new)
    except Exception as exc:
        log(f"Bookmarks could not be translated: {exc}")


def column_bounds(paras: List[Para], page_rect) -> Tuple[float, float]:
    """Left / right edge of the text column of a page (used to mirror left-aligned headings to the right side)."""
    wide = [p for p in paras if not p.skip and (p.bbox[2] - p.bbox[0]) >= 0.35 * page_rect.width]
    if not wide:
        wide = [p for p in paras if (p.bbox[2] - p.bbox[0]) >= 0.35 * page_rect.width]
    if not wide:
        return page_rect.x0 + 14, page_rect.x1 - 14
    return min(p.bbox[0] for p in wide), max(p.bbox[2] for p in wide)


def column_bounds_for(p: Para, paras: List[Para], page_rect) -> Tuple[float, float]:
    """Left / right edge of the text column that contains p (two-column articles have two of them)."""
    cx = (p.bbox[0] + p.bbox[2]) / 2
    cand = [q for q in paras if q is not p and q.n_lines >= 2 and not q.skip
            and (q.bbox[2] - q.bbox[0]) >= 0.2 * page_rect.width and q.bbox[0] - 2 <= cx <= q.bbox[2] + 2
            and (q.bbox[2] - q.bbox[0]) <= 0.75 * page_rect.width]
    if cand:
        return min(q.bbox[0] for q in cand), max(q.bbox[2] for q in cand)
    return column_bounds(paras, page_rect)


def pushed_boxes(paras: List[Para], pushes: List[tuple]) -> Dict[int, List[float]]:
    """Places of the blocks of a page after the user inserted or removed room ('pushes', one after the other):
    a push (y, dy, x0, x1) moves everything that starts below y, between x0 and x1, by dy."""
    boxes = {id(q): list(q.bbox) for q in paras}
    for y, dy, x0, x1 in pushes or []:
        for b in boxes.values():
            if b[1] >= y - 0.5 and b[0] < x1 and b[2] > x0:
                b[1] += dy
                b[3] += dy
    return boxes


def _snap_pushes(page, pushes: List[tuple]) -> List[tuple]:
    """A click inside a picture would cut it in two: the room is inserted above the picture instead."""
    try:
        rects = [fitz.Rect(im["bbox"]) for im in page.get_image_info()]
    except Exception:
        rects = []
    out = []
    for y, dy, x0, x1 in pushes:
        for r in rects:
            if r.y0 + 1 < y < r.y1 - 1 and r.x0 < x1 and r.x1 > x0:
                y = r.y0 - 0.5
        out.append((y, dy, x0, x1))
    return out


def _push_page(doc, i: int, pushes: List[tuple]):
    """Inserts (dy > 0) or removes (dy < 0) room on page i: the strip below y (between x0 and x1) - pictures,
    formulas, lines and the text that is not translated - is moved by dy.  The page is rebuilt from its own
    content, so everything stays sharp.  Margins do not limit it.  Returns the new page object."""
    for y, dy, x0, x1 in pushes:
        pr = doc[i].rect
        strip = fitz.Rect(max(pr.x0, x0), y, min(pr.x1, x1), pr.y1)
        if strip.is_empty or not dy:
            continue
        nd = fitz.open()
        npg = nd.new_page(width=pr.width, height=pr.height)
        npg.show_pdf_page(npg.rect, doc, i)
        npg.draw_rect(strip, color=None, fill=(1, 1, 1), overlay=True)
        npg.show_pdf_page(fitz.Rect(strip.x0, strip.y0 + dy, strip.x1, strip.y1 + dy), doc, i, clip=strip)
        doc.delete_page(i)
        doc.insert_pdf(nd, start_at=i)
        nd.close()
    return doc[i]


def render_pdf(src: str, dst: str, analysis: Dict[int, List[Para]], obstacles: Dict[int, list],
               pieces_map: Dict[int, List[Piece]], renderer: Renderer, lang: str, opts: Options,
               titles_fn: Callable[[List[str]], List[str]], log: Callable[[str], None],
               cancel: threading.Event, progress: Callable[[float, str], None],
               on_page: Callable[[int, Para], None] = lambda i, p: None,
               keep: Optional[List[int]] = None, pushes: Optional[Dict[int, List[tuple]]] = None) -> None:
    doc = fitz.open(xl(src))
    renderer.set_source(src)
    pages = sorted(analysis)
    overflow = 0
    for k, i in enumerate(pages):
        if cancel.is_set():
            doc.close()
            raise Cancelled()
        page = doc[i]
        todo = [p for p in analysis[i]
                if not p.skip and id(p) in pieces_map and "".join(c.text for c in pieces_map[id(p)]).strip()]
        if not todo:
            continue
        rot = page.rotation
        if rot:
            page.set_rotation(0)
        keep_zones = [fitz.Rect(q.bbox) for q in analysis[i] if q.skip == "formula-like"]
        for p in todo:                                   # remove ONLY the English text – images / lines stay
            # EVERY span of the paragraph (not only the one-line runs: those left most lines on the page, and the
            # translation was printed over the English text)
            boxes = list(p.erase) or [rn.bbox for rn in p.runs if rn.bbox] or [p.bbox]
            for bx in boxes:                             # only where English glyphs really are: neighbouring equations stay whole
                hh = bx[3] - bx[1]
                r = fitz.Rect(bx[0] + 0.3, bx[1] + 0.18 * hh, bx[2] - 0.3, bx[3] - 0.18 * hh)
                for z in keep_zones:                     # never cut into a displayed equation next to the text
                    if r.intersects(z) and not fitz.Rect(p.bbox).contains(z):
                        if z.y0 >= (r.y0 + r.y1) / 2:
                            r.y1 = min(r.y1, z.y0 - 0.2)
                        elif z.y1 <= (r.y0 + r.y1) / 2:
                            r.y0 = max(r.y0, z.y1 + 0.2)
                if not r.is_empty and r.height > 0.5:
                    page.add_redact_annot(r, fill=False)
        try:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
        except (TypeError, AttributeError):
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        for p in todo:                                   # fraction bars of expressions that are pasted as pictures
            for b in p.bars:
                page.draw_rect(fitz.Rect(b[0] - 0.4, b[1] - 0.9, b[2] + 0.4, b[3] + 0.9), color=None, fill=(1, 1, 1),
                               overlay=True)
        boxes: Dict[int, List[float]] = {}
        obs = obstacles[i]
        if pushes and pushes.get(i):                     # review window: room inserted / removed by the user
            pushes = dict(pushes)
            pushes[i] = _snap_pushes(page, pushes[i])
            page = _push_page(doc, i, pushes[i])
            boxes = pushed_boxes(analysis[i], pushes[i])
            obs = [fitz.Rect(o) for o in obs]
            for y, dy, x0, x1 in pushes[i]:
                for o in obs:
                    if o.y0 >= y - 0.5 and o.x0 < x1 and o.x1 > x0:
                        o.y0 += dy
                        o.y1 += dy
        content = column_bounds(analysis[i], page.rect)
        act(f"━ Page {i + 1}/{doc.page_count}: erasing {len(todo)} English blocks, typesetting the translation "
            f"({len(analysis[i]) - len(todo)} blocks stay unchanged)", "b")
        for p in todo:
            on_page(i, p)
            col = column_bounds_for(p, analysis[i], page.rect) if p.heading or p.n_lines == 1 else content
            old_box = p.bbox
            if id(p) in boxes:
                p.bbox = tuple(boxes[id(p)])
            try:
                if renderer.place(page, p, pieces_map[id(p)], obs, col) is None:
                    overflow += 1
            finally:
                p.bbox = old_box
        # displayed equations, figures and tables are NOT touched: only the English words are erased, so the original
        # vector formulas stay exactly where they are (no screenshots, nothing can cover the text around them)
        if rot:
            page.set_rotation(rot)
        progress((k + 1) / len(pages), f"Typesetting {LANGS[lang]['name']} – page {i + 1}/{doc.page_count}")
    if overflow:
        log(f"Note: {overflow} blocks were too long even at the smallest allowed size and may be clipped.")
    if opts.translate_bookmarks:
        _translate_bookmarks(doc, titles_fn, opts, log)
    if renderer.builtin:
        try:
            doc.subset_fonts()
        except Exception:
            pass
    if keep is not None and len(keep) < doc.page_count:          # the result holds ONLY the requested pages
        doc.set_toc([])
        doc.select(keep)
    doc.save(dst, garbage=4, deflate=True, clean=True)
    doc.close()


# ════════════════════════════════════════════════════════════════════════════
#  Word (.docx) and plain-text (.txt) output
# ════════════════════════════════════════════════════════════════════════════
# blocks of the source that are not text of the book (page numbers, labels inside images …) are left out of .docx / .txt
EXPORT_DROP = ("no words (number / symbol)", "text inside image", "figure label", "rotated text")


def export_sequence(analysis: Dict[int, List[Para]], pieces_map: Dict[int, List[Piece]]):
    """Yield (page, paragraph, pieces, translated) in reading order.  Untranslated blocks (tables, code, back
    matter …) are passed through unchanged so nothing of the book is lost."""
    for pno in sorted(analysis):
        for p in analysis[pno]:
            if p.skip:
                if p.skip in EXPORT_DROP or not p.text.strip():
                    continue
                yield pno, p, [Piece(p.text, None, "", True)], False
                continue
            pcs = pieces_map.get(id(p))
            if pcs and "".join(c.text for c in pcs).strip():
                yield pno, p, pcs, True


def write_txt(dst: str, analysis: Dict[int, List[Para]], pieces_map: Dict[int, List[Piece]], lang: str) -> None:
    rtl = LANGS[lang]["rtl"]
    out: List[str] = []
    for _pno, p, pcs, translated in export_sequence(analysis, pieces_map):
        t = re.sub(r"[ \t]+", " ", "".join(c.text for c in pcs)).strip()
        if not t:
            continue
        if rtl and translated and re.match(r"[A-Za-z0-9]", t):
            t = "\u200f" + t                                   # keeps a paragraph that starts with a Latin term RTL
        out.append(t)
    Path(dst).write_text("\n\n".join(out) + "\n", encoding="utf-8-sig")


def docx_font_name(pdf_name: str, mono: bool = False) -> str:
    """Readable font name for Word from a PDF font name ('ABCDEF+TimesNewRomanPS-BoldMT' -> 'Times New Roman')."""
    base = clean_font_name(pdf_name)
    known = {"timesnewroman": "Times New Roman", "timesnewromanps": "Times New Roman", "times": "Times New Roman",
             "arial": "Arial", "arialmt": "Arial", "helvetica": "Arial", "calibri": "Calibri",
             "cambria": "Cambria", "couriernew": "Courier New", "couriernewps": "Courier New",
             "courier": "Courier New", "verdana": "Verdana", "tahoma": "Tahoma", "georgia": "Georgia",
             "palatino": "Palatino Linotype", "garamond": "Garamond", "segoeui": "Segoe UI"}
    if base in known:
        return known[base]
    if mono or MONO_RE.search(pdf_name or ""):
        return "Courier New"
    if not base:
        return "Times New Roman"
    nm = _SUBSET_PREFIX.sub("", pdf_name).split("-")[0].split(",")[0]
    nm = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", nm)
    nm = re.sub(r"(MT|PS|PSMT)$", "", nm).strip()
    return nm or "Times New Roman"


def _png_of_image(doc, xref: int) -> Optional[bytes]:
    try:
        pix = fitz.Pixmap(doc, xref)
        if pix.n - pix.alpha >= 4:                           # CMYK -> RGB
            pix = fitz.Pixmap(fitz.csRGB, pix)
        if pix.alpha:
            pix = fitz.Pixmap(pix, 0)                        # drop alpha (Word shows it on white anyway)
        return pix.tobytes("png")
    except Exception:
        return None


def write_docx(dst: str, src_pdf: str, analysis: Dict[int, List[Para]], pieces_map: Dict[int, List[Piece]],
               lang: str, opts: Options, head_name: str, body_name: str, log: Callable[[str], None]) -> None:
    """Word document with the same reading order, the same pictures and the same relative sizes / styles.
    Right-to-left languages: paragraph direction RTL + Align Right (no first-line Tab)."""
    import io
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt

    info = LANGS[lang]
    rtl_lang = bool(info["rtl"])
    rtl = rtl_lang and opts.rtl_direction
    f = opts.font_scale
    src = fitz.open(xl(src_pdf))
    first = sorted(analysis)[0]
    prect = src[first].rect

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Pt(prect.width), Pt(prect.height)
    bounds = [column_bounds(analysis[i], src[i].rect) for i in analysis]
    left = max(18.0, min(b[0] for b in bounds))
    right = max(18.0, prect.width - max(b[1] for b in bounds))
    sec.left_margin, sec.right_margin = Pt(min(left, prect.width / 3)), Pt(min(right, prect.width / 3))
    sec.top_margin = sec.bottom_margin = Pt(54)
    doc.core_properties.title = f"{Path(src_pdf).stem} ({info['name']})"
    doc.core_properties.author = APP_TITLE

    def el(tag: str, **attrs):
        e = OxmlElement(tag)
        for k, v in attrs.items():
            e.set(qn("w:" + k), str(v))
        return e

    def style_font(style, name: str) -> None:
        style.font.name = name
        rpr = style.element.get_or_add_rPr()
        rf = rpr.find(qn("w:rFonts"))
        if rf is None:
            rf = el("w:rFonts")
            rpr.insert(0, rf)
        for a in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
            if rf.get(qn("w:" + a)) is not None:
                del rf.attrib[qn("w:" + a)]
        for a in ("ascii", "hAnsi", "cs", "eastAsia"):
            rf.set(qn("w:" + a), name)

    style_font(doc.styles["Normal"], body_name)
    heading_sizes = sorted({round(p.size, 1) for v in analysis.values() for p in v if p.heading and not p.skip},
                           reverse=True)

    def level_of(p: Para) -> int:
        try:
            return min(heading_sizes.index(round(p.size, 1)) + 1, 3)
        except ValueError:
            return 3

    for n in (1, 2, 3):
        try:
            style_font(doc.styles[f"Heading {n}"], head_name)
        except KeyError:
            pass

    def set_rpr(run, font: str, size: float, bold: bool, italic: bool, color: str, rtl_run: bool, va: str,
                keep_run: bool = False) -> None:
        r = run._r
        old = r.find(qn("w:rPr"))
        if old is not None:
            r.remove(old)
        rpr = el("w:rPr")
        rf = el("w:rFonts")
        for a in ("ascii", "hAnsi", "cs", "eastAsia"):
            rf.set(qn("w:" + a), font)
        rpr.append(rf)
        if bold:
            rpr.append(el("w:b"))
            rpr.append(el("w:bCs"))
        if italic:
            rpr.append(el("w:i"))
            rpr.append(el("w:iCs"))
        if color and re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            rpr.append(el("w:color", val=color[1:].upper()))
        half = max(2, int(round(size * 2)))
        rpr.append(el("w:sz", val=half))
        rpr.append(el("w:szCs", val=half))
        if va in ("sup", "sub"):
            rpr.append(el("w:vertAlign", val="superscript" if va == "sup" else "subscript"))
        if rtl_run:
            rpr.append(el("w:rtl"))
            rpr.append(el("w:lang", bidi="fa-IR" if lang == "fa" else "ar-SA"))
        elif lang == "de" and not keep_run:
            rpr.append(el("w:lang", val="de-DE"))
        r.insert(0, rpr)

    crop = CropSource(src_pdf)
    crop_cache: Dict[tuple, tuple] = {}

    def add_break(par) -> None:
        r = par.add_run()
        r._r.append(el("w:br", type="column"))

    def inline_picture(par, pc: Piece, size: float) -> bool:
        """Hard maths inside a sentence: a picture of the original, put where the translation needs it."""
        try:
            key = tuple(round(v, 1) for v in pc.img)
            if key not in crop_cache:
                crop_cache[key] = crop.png(int(pc.img[0]), tuple(pc.img[1:]), [tuple(pc.img[1:])], dpi=250)
            data, rect = crop_cache[key]
            h = max(rect[3] - rect[1], 4.0)
            run = par.add_run()
            run.add_picture(io.BytesIO(data), height=Pt(h))
            run._r.get_or_add_rPr().append(el("w:position", val=-int(round(0.22 * size * 2))))
            return True
        except Exception:
            return False

    def add_par(p: Para, pcs: List[Piece], translated: bool, page_break: bool, col_break: bool = False) -> None:
        heading = p.heading and translated
        par = doc.add_paragraph(style=f"Heading {level_of(p)}" if heading else None)
        if col_break:
            add_break(par)
        ppr = par._p.get_or_add_pPr()
        right_to_left = rtl and translated
        if right_to_left:
            ppr.insert_element_before(el("w:bidi"), "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind",
                                      "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
                                      "w:textDirection", "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl",
                                      "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange")
        pf = par.paragraph_format
        # Alignment.  The source "Align Left" becomes "Align Right".  Word counts alignment from the start edge of
        # a right-to-left paragraph, so "left" there is what the reader sees on the right-hand side.
        if translated and wants_justify(p, opts):
            par.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        elif p.align == "center":
            par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif p.align == "justify":
            par.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        elif right_to_left and opts.align_right:
            par.alignment = WD_ALIGN_PARAGRAPH.LEFT
        elif right_to_left:
            par.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        elif p.align == "right":
            par.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        else:
            par.alignment = WD_ALIGN_PARAGRAPH.LEFT
        pf.line_spacing = max(min(p.lh, 1.6), 1.1)
        pf.space_before = Pt(10 if heading else 0)
        pf.space_after = Pt(4 if heading else 6)
        if heading:
            pf.keep_with_next = True
        if page_break:
            pf.page_break_before = True
        for pc in pcs:
            if not pc.text:
                continue
            st = pc.style
            if pc.img and inline_picture(par, pc, (st.size if st is not None else p.size)):
                continue
            run = par.add_run(pc.text)
            if pc.latin:                                          # not translated: original font AND size
                mono = st.mono if st is not None else p.mono
                font = docx_font_name(piece_font_name(pc, p), mono)
                if pc.math and not mono:
                    font = "Times New Roman"                      # inline maths: Greek letters, ∑, ≤ … are there
                size = st.size if st is not None else p.size
                set_rpr(run, font, size, st.bold if st is not None else p.bold,
                        st.italic if st is not None else p.italic, st.color if st is not None else p.color,
                        False, pc.va, True)
            else:
                font = head_name if heading else body_name
                if font == SAME_FONT:
                    font = docx_font_name(p.font, p.mono)
                size = (st.size if st is not None else p.size) * f
                set_rpr(run, font, size, st.bold if st is not None else p.bold,
                        st.italic if st is not None else p.italic, st.color if st is not None else p.color,
                        right_to_left, pc.va)

    # tables, figures, graphs and formulas: a sharp picture of the original region, put at its original place.
    # Captions are cut out of the pictures because they are translated as text.
    def page_regions(pno: int) -> List[Tuple[float, tuple, bytes]]:
        found: List[Tuple[float, tuple, bytes]] = []
        try:
            page = src[pno]
            area = page.rect.get_area()
            rects = [fitz.Rect(r) for _k, r in REGIONS.get(pno, [])]
            merged: List["fitz.Rect"] = []
            for r in sorted(rects, key=lambda q: q.y0):          # merge overlapping regions
                for m in merged:
                    if (m & r).get_area() > 0:
                        m |= r
                        break
                else:
                    merged.append(fitz.Rect(r))
            texts = [q for q in analysis.get(pno, []) if not q.skip]
            for r in merged:
                for q in texts:                                  # keep translated text (captions) out of the picture
                    qb = fitz.Rect(q.bbox)
                    if (qb & r).get_area() > 0.2 * qb.get_area():
                        if (qb.y0 + qb.y1) / 2 >= (r.y0 + r.y1) / 2:
                            r.y1 = min(r.y1, qb.y0 - 1)
                        else:
                            r.y0 = max(r.y0, qb.y1 + 1)
                if r.is_empty or r.width < 12 or r.height < 8 or r.get_area() > 0.85 * area:
                    continue
                pix = page.get_pixmap(clip=r, dpi=250, alpha=False)
                found.append((r.y0, (r.x0, r.y0, r.x1, r.y1), pix.tobytes("png")))
        except Exception as exc:
            log(f"A picture region could not be cut out on page {pno + 1} ({type(exc).__name__}).")
        return sorted(found, key=lambda t: t[0])

    usable = prect.width - sec.left_margin.pt - sec.right_margin.pt
    guts: Dict[int, Optional[Tuple[float, float]]] = {i: find_gutter(analysis[i], src[i].rect) for i in analysis}
    gaps = [g[1] - g[0] for g in guts.values() if g]
    gap = max(12.0, statistics.median(gaps)) if gaps else 18.0
    two_col_doc = bool(gaps)
    col_w = (usable - gap) / 2
    col_bottoms = [p.bbox[3] for v in analysis.values() for p in v if not p.skip and p.n_lines >= 3]
    body_bottom = max(col_bottoms) if col_bottoms else prect.height
    partial_limit = body_bottom - 0.14 * prect.height

    def set_cols(section, n: int) -> None:
        sp = section._sectPr
        for tag in ("w:cols", "w:bidi"):
            for e in sp.findall(qn(tag)):
                sp.remove(e)
        grid = sp.find(qn("w:docGrid"))
        new_cols = el("w:cols", num=n, space=int(gap * 20) if n > 1 else 720, equalWidth=1)
        items = [new_cols] + ([el("w:bidi")] if rtl_lang and rtl else [])
        for e in items:
            if grid is not None:
                grid.addprevious(e)
            else:
                sp.append(e)

    state = {"cols": 0, "any": False}

    def ensure(n: int) -> None:
        if state["cols"] == n:
            return
        if state["any"]:
            from docx.enum.section import WD_SECTION
            section = doc.add_section(WD_SECTION.CONTINUOUS)
        else:
            section = doc.sections[0]
        set_cols(section, n)
        state["cols"] = n

    def add_picture(width: float, png: bytes, col_break: bool = False) -> None:
        par = doc.add_paragraph()
        if col_break:
            add_break(par)
        par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        par.paragraph_format.space_after = Pt(6)
        limit = col_w if state["cols"] == 2 else usable
        try:
            par.add_run().add_picture(io.BytesIO(png), width=Pt(min(width, limit)))
        except Exception as exc:
            log(f"A picture could not be placed in the Word file ({type(exc).__name__}).")

    # ---- collect what belongs to each page: translated paragraphs and pictures of tables / figures / equations
    entries: Dict[int, list] = {}
    for pno, p, pcs, translated in export_sequence(analysis, pieces_map):
        if p.skip:                                              # its text is inside a picture of the region
            cx, cy = (p.bbox[0] + p.bbox[2]) / 2, (p.bbox[1] + p.bbox[3]) / 2
            if any(r[0] <= cx <= r[2] and r[1] <= cy <= r[3] for _k, r in REGIONS.get(pno, [])):
                continue
        entries.setdefault(pno, []).append(("par", p.bbox, (p, pcs, translated)))
    for pno in sorted(analysis):
        for _y, bb, png in page_regions(pno):
            entries.setdefault(pno, []).append(("pic", bb, png))

    n_par = 0
    pending_break = False
    for pno in sorted(entries):
        gut = guts.get(pno)
        items = sorted(entries[pno], key=lambda e: (e[1][1], e[1][0]))
        bands: list = []
        cur = None
        for e in items:
            c = column_of(e[1], gut)
            if c == 2:
                if cur is None or cur[0] != "span":
                    cur = ["span", [], []]
                    bands.append(cur)
                cur[1].append(e)
            else:
                if cur is None or cur[0] != "cols":
                    cur = ["cols", [], []]
                    bands.append(cur)
                cur[1 + c].append(e)
        first_on_page = True
        for kind, left_items, right_items in bands:
            ensure(1 if kind == "span" else 2)
            if kind == "span":
                pending_break = False
            seq = [(e, False) for e in left_items] + [(e, False) for e in right_items]
            order = left_items + right_items
            for idx, e in enumerate(order):
                brk = False
                if kind == "cols":
                    if idx == 0 and pending_break:
                        brk = True
                    if idx == len(left_items) and right_items and left_items \
                            and left_items[-1][1][3] < partial_limit:
                        brk = True                              # the left column of the original stops early
                if e[0] == "pic":
                    add_picture(e[1][2] - e[1][0], e[2], brk)
                else:
                    p, pcs, translated = e[2]
                    top_level = translated and p.heading and level_of(p) == 1
                    add_par(p, pcs, translated,
                            page_break=bool(top_level and first_on_page and n_par > 0 and not two_col_doc),
                            col_break=brk)
                    n_par += 1
                state["any"] = True
                first_on_page = False
            if kind == "cols":
                last = (right_items or left_items)[-1]
                pending_break = last[1][3] < partial_limit
    crop.close()
    src.close()
    doc.save(dst)


# ════════════════════════════════════════════════════════════════════════════
#  Job orchestration
# ════════════════════════════════════════════════════════════════════════════
def _font_display_name(key: str, custom: Optional[str]) -> str:
    """Name under which Word will look the font up."""
    if key == CUSTOM_FONT_LABEL and custom:
        return font_family_name(Path(custom), Path(custom).stem)
    return key


def proofread(texts: List[str], tr: Dict[str, str], log: Callable[[str], None]) -> Dict[str, str]:
    """Automatic checks after the translation: empty results fall back to the original text, protected-term markers
    that the engine lost are counted (the layout step puts them back), repeated words are cleaned."""
    empty = lost = 0
    out = dict(tr)
    for t in dict.fromkeys(texts):
        r = out.get(t, "")
        if not r.strip():
            out[t] = t
            empty += 1
            continue
        need = {int(x.translate(DIGIT_NORM)) for x in PH_RE.findall(t)}
        got = {int(x.translate(DIGIT_NORM)) for x in PH_RE.findall(r)}
        lost += len(need - got)
        out[t] = re.sub(r"\b([^\W\d_]{3,})(\s+\1\b)+", r"\1", r)           # 'the the' -> 'the'
    log(f"Proofreading finished: {len(out)} blocks checked, {lost} protected terms restored, "
        f"{empty} empty results replaced by the original text.")
    if empty:
        log(f"Warning: {empty} blocks could not be translated and stay in the original language.")
    return out


def _pages_spec(pages: List[int]) -> str:
    return ",".join(str(i + 1) for i in pages)


# ── Persian: two-column pages are mirrored (the reader starts with the RIGHT column) ──
def column_swap_zones(paras: List[Para], obstacles: list, page, pno: int) -> List[tuple]:
    """[(y0, y1, x of the gutter, left edge, right edge, shift)] – the horizontal bands of a two-column page whose left and right half change
    places.  Everything that spans both columns (title, abstract, wide figures / tables / equations) stays where
    it is and ends a band."""
    pr = page.rect
    if page.rotation or abs(pr.x0) > 0.5 or abs(pr.y0) > 0.5:
        return []
    gut = find_gutter(paras, pr)
    if gut is None:
        return []
    g0, g1 = gut
    gx = (g0 + g1) / 2
    boxes = [fitz.Rect(o) for o in obstacles] + [fitz.Rect(r) for _k, r in REGIONS.get(pno, [])]
    boxes = [b for b in boxes if not b.is_empty and b.get_area() < 0.85 * pr.get_area()]
    cross = [b for b in boxes if b.x0 < g0 - 2 and b.x1 > g1 + 2]
    side = [b for b in boxes if (b.x1 <= g1 + 2 or b.x0 >= g0 - 2) and b.width >= 0.15 * pr.width]
    if not any(b.x1 <= g1 + 2 for b in side) or not any(b.x0 >= g0 - 2 for b in side):
        return []
    lefts = [b for b in side if b.x1 <= g1 + 2]
    rights = [b for b in side if b.x0 >= g0 - 2]
    a0, c0 = min(b.x0 for b in lefts), min(b.x0 for b in rights)       # left edge of the two columns
    c1 = max(b.x1 for b in rights)
    shift = c0 - a0                                                    # a column moves exactly onto the other one
    zones = [(max(pr.y0, min(b.y0 for b in side) - 2), min(pr.y1, max(b.y1 for b in side) + 2))]
    for c in sorted(cross, key=lambda r: r.y0):
        nxt = []
        for y0, y1 in zones:
            if c.y1 + 1 <= y0 or c.y0 - 1 >= y1:
                nxt.append((y0, y1))
                continue
            if c.y0 - 1 > y0:
                nxt.append((y0, c.y0 - 1))
            if c.y1 + 1 < y1:
                nxt.append((c.y1 + 1, y1))
        zones = nxt
    out = []
    for y0, y1 in zones:
        inside = [b for b in side if y0 <= (b.y0 + b.y1) / 2 <= y1]
        if y1 - y0 >= 12 and inside:
            # a band never cuts through something that only touches its edge
            y0 = min([y0] + [b.y0 - 1 for b in inside])
            y1 = max([y1] + [b.y1 + 1 for b in inside])
            out.append((y0, y1, gx, max(pr.x0, a0 - 14), min(pr.x1, c1 + 14), shift))
    return out


def swap_columns_pdf(path: str, zones: Dict[int, List[tuple]]) -> int:
    """Rewrites the PDF: in every band of `zones` (key = page index in this file) the left and the right half of the
    page change places.  Returns the number of mirrored pages."""
    zones = {k: v for k, v in zones.items() if v}
    if not zones:
        return 0
    src = fitz.open(path)
    out = fitz.open()
    n = 0
    for k in range(src.page_count):
        zs = sorted(zones.get(k, []))
        if not zs:
            out.insert_pdf(src, from_page=k, to_page=k)
            continue
        r = src[k].rect
        page = out.new_page(width=r.width, height=r.height)
        y = r.y0

        def strip(clip, target) -> None:
            if clip.height > 0.5 and clip.width > 0.5:
                page.show_pdf_page(target, src, k, clip=clip)

        for y0, y1, gx, xa, xc, sh in zs:
            y0, y1 = max(y0, y), min(y1, r.y1)
            if y1 - y0 < 1:
                continue
            strip(fitz.Rect(r.x0, y, r.x1, y0), fitz.Rect(r.x0, y, r.x1, y0))
            strip(fitz.Rect(r.x0, y0, xa, y1), fitz.Rect(r.x0, y0, xa, y1))             # outer margins stay
            strip(fitz.Rect(xc, y0, r.x1, y1), fitz.Rect(xc, y0, r.x1, y1))
            strip(fitz.Rect(xa, y0, gx, y1), fitz.Rect(xa + sh, y0, gx + sh, y1))       # left column -> right column
            strip(fitz.Rect(gx, y0, xc, y1), fitz.Rect(gx - sh, y0, xc - sh, y1))       # right column -> left column
            y = y1
        strip(fitz.Rect(r.x0, y, r.x1, r.y1), fitz.Rect(r.x0, y, r.x1, r.y1))
        n += 1
    tmp = str(path) + ".swap.tmp"
    out.save(tmp, garbage=3, deflate=True)
    out.close()
    src.close()
    os.replace(tmp, path)
    return n


def resolve_specialties(sample: List[str], opts: Options, log: Callable[[str], None],
                        cancel: threading.Event) -> Tuple[List[str], Set[str]]:
    """Fields of the text (typed by the user + detected from the text) and their terminology.  The lists come from
    the terminology folder; a missing or old list is downloaded once."""
    specs = list(opts.specialties)[:MAX_SPECIALTIES]
    if opts.auto_specialty:
        for name, score in detect_specialties(sample):
            q = DOMAIN_QUERIES.get(name, name)
            log(f"Subject of the book detected automatically: {name} ({score} typical words per 1000).")
            act(f"This book seems to be about “{name}” – {score} typical words per 1000", "h")
            if q.lower() not in [x.lower() for x in specs] and name.lower() not in [x.lower() for x in specs]:
                specs.append(q)
    domain_terms: Set[str] = set()
    for spec in specs:
        if cancel.is_set():
            raise Cancelled()
        try:
            f = terminology_file(spec)
            had = f.exists()
            domain_terms |= load_terminology(ensure_terminology(spec, opts.allow_download, log, cancel))
            if had:
                log(f"Terminology for “{spec}”: taken from the terminology folder ({f.name}).")
        except Cancelled:
            raise
        except Exception as exc:
            log(f"Warning: terminology for “{spec}” could not be prepared ({type(exc).__name__}: {exc}).")
    return specs, domain_terms


def scan_terms_foreign(texts: List[str], src: str) -> List[Tuple[str, int, str]]:
    """Technical terms of a file that is NOT English -> [(term as written, count, 'keep' | 'term')].
      'keep': English words / acronyms inside the text - they normally stay as they are
      'term': words and word groups of the origin language that occur again and again (the subject's vocabulary)"""
    full = _fix_lig(" ".join(texts))
    full = re.sub(r"[ \t]*\n[ \t]*", " \n ", full)
    stop = STOPWORDS.get(src, set())
    out: collections.Counter = collections.Counter()
    kind: Dict[str, str] = {}
    shown: Dict[str, str] = {}
    rtl = bool(LANGS.get(src, {}).get("rtl"))
    # 1. English words, acronyms, identifiers inside the text
    rx = _LATIN_RUN_RE if rtl else re.compile(r"\b(?:[A-Z]{2,}[a-z]?s?\d*|[A-Za-z]+\d[\w\-]*|[a-z]+[A-Z]\w*)\b")
    for m in rx.finditer(full):
        w = m.group().strip(" .-/")
        if len(w) < 2 or w.lower() in STOPWORDS["en"] or re.fullmatch(r"[\d.\-/]+", w):
            continue
        k = w.lower()
        out[k] += 1
        kind[k] = "keep"
        shown.setdefault(k, w)
    # 2. vocabulary of the origin language: word groups of 1-3 words, cut at punctuation, that recur
    for sent in re.split(r"[.!?؟؛;:,،()\[\]{}«»\"\n]+", full):
        toks = [t for t in _FWORD_RE.findall(sent) if not _LATIN_RUN_RE.fullmatch(t)]
        toks = [t for t in toks if t]
        for n in (3, 2, 1):
            for i in range(len(toks) - n + 1):
                g = toks[i:i + n]
                if g[0].lower() in stop or g[-1].lower() in stop or any(len(x) < 2 for x in g):
                    continue
                if n == 1 and (len(g[0]) < (4 if rtl else 6) or g[0].lower() in stop):
                    continue
                if rtl and any(x.startswith(("می‌", "نمی‌")) for x in g):
                    continue                              # a verb ('می‌کند'), not a term
                k = " ".join(x.lower() for x in g)
                if kind.get(k) == "keep":
                    continue
                out[k] += 1
                kind.setdefault(k, "term")
                shown.setdefault(k, " ".join(g))
    picked: List[Tuple[str, int, str]] = []
    terms = [(k, c) for k, c in out.items() if kind[k] == "term" and c >= (2 if " " in k else 3)]
    terms.sort(key=lambda kc: (-(kc[1] * (1 + 0.6 * kc[0].count(" "))), kc[0]))
    taken: List[Tuple[str, int]] = []
    for k, c in terms:
        # a word that only occurs inside a longer group that was already taken adds nothing
        if any(k != t and f" {k} " in f" {t} " and c <= ct + 1 for t, ct in taken):
            continue
        taken.append((k, c))
        if len(taken) >= 40:
            break
    keeps = sorted(((k, c) for k, c in out.items() if kind[k] == "keep"), key=lambda kc: -kc[1])[:40]
    keeps = [(k, c) for k, c in keeps if k.count(" ") <= 3]           # a long English sentence is no term
    picked += [(shown[k], c, "term") for k, c in taken]
    picked += [(shown[k], c, "keep") for k, c in keeps]
    return picked


def scan_terms(pdf_path: str, opts: Options, log: Callable[[str], None],
               cancel: threading.Event) -> Tuple[List[Tuple[str, int]], List[str]]:
    """Quick look at the selected pages BEFORE the translation: which technical terms (kept in English) and which
    of the user's instructions occur in this file.  -> ([(term as written in the file, count)], [instruction lines])"""
    doc = fitz.open(xl(pdf_path))
    pages = sorted(parse_pages(opts.pages, doc.page_count))
    texts = []
    for i in pages:
        if cancel.is_set():
            break
        texts.append(_fix_lig(doc[i].get_text("text")))
    doc.close()
    if getattr(opts, "src_lang", "en") != "en":
        found = scan_terms_foreign(texts, opts.src_lang)
        ins = load_instructions()
        keys = {" ".join(_TOKEN_RE.findall(t.lower())) for t, _c, _k in found}
        used = [format_instruction(i) for i in ins if " ".join(_TOKEN_RE.findall(i[1].lower())) in keys]
        return found, used
    full = "\n".join(texts)
    full = re.sub(r"-\n(?=[a-z])", "", full).replace("\n", " ")
    _specs, domain_terms = resolve_specialties([t for t in texts if t.strip()][:4000], opts, log, cancel)
    ins = load_instructions()
    proto = Protector(opts, load_user_terms(), domain_terms, ins)
    keep = proto._keep
    cnt: collections.Counter = collections.Counter()
    shown: Dict[str, str] = {}
    spans = proto._term_spans(full)
    if proto.term_re:
        spans += [(m.start(), m.end()) for m in proto.term_re.finditer(full)]
    for s0, e0 in spans:
        k = " ".join(_TOKEN_RE.findall(full[s0:e0].lower()))
        base = k if k in keep else k[:-2] if k[:-2] in keep else k[:-1] if k[:-1] in keep else \
            full[s0:e0].lower() if full[s0:e0].lower() in keep else ""
        if not base:
            continue                                    # a glossary word with a fixed translation, not a kept term
        cnt[base] += 1
        shown.setdefault(base, full[s0:e0])
    for name, rx in _AUTO_RES:                           # acronyms found by the automatic detection (CNN, RGB …)
        if name != "acronym" or not opts.auto_terms:
            continue
        for m in rx.finditer(full):
            w = m.group().strip(" .,;:")
            k = w.lower()
            if len(w) < 2 or w.rstrip("s") in _ACRONYM_STOP or k in proto.exclude or k in cnt:
                continue
            cnt[k] += 1
            shown.setdefault(k, w)
    low = " " + " ".join(_TOKEN_RE.findall(full.lower())) + " "
    used = [format_instruction(i) for i in ins if " " + " ".join(_TOKEN_RE.findall(i[1].lower())) + " " in low]
    return [(shown[k], c) for k, c in cnt.most_common()], used


def _retext(pieces: List[Piece], new: str, base: Optional[Run]) -> List[Piece]:
    """The text of a paragraph was edited by hand.  Only what was really changed becomes new text; every piece
    that was not touched (words, formulas, English terms, pictures, their fonts and sizes) stays exactly as it
    was.  New words get the font and size of the text around them; new maths symbols get the maths font."""
    import dataclasses
    import difflib
    norm = lambda t: t.replace("\u00a0", " ")                    # (a line break typed with Enter stays)
    spans: List[Tuple[int, int, Piece]] = []
    pos = 0
    for pc in pieces:
        t = norm(pc.text)
        spans.append((pos, pos + len(t), pc))
        pos += len(t)
    old = "".join(norm(pc.text) for pc in pieces)
    new = norm(new)
    out: List[Piece] = []

    def style_at(i: int) -> Optional[Run]:
        for a, b, pc in spans:
            if a <= i < b or (i == b == len(old)):
                if not (pc.latin or pc.math or pc.img or pc.br):
                    return pc.style
        for a, b, pc in reversed(spans):                 # the nearest translated text before this place
            if b <= i and not (pc.latin or pc.math or pc.img or pc.br):
                return pc.style
        return base

    def add_new(text: str, st: Optional[Run]) -> None:
        if "\n" in text:                              # Enter: a new line (twice: an empty line between)
            for k, line in enumerate(text.split("\n")):
                if k:
                    out.append(Piece("\n", st, br=True))
                if line:
                    add_new(line, st)
            return
        for k, seg in enumerate(re.split("([" + _SYMBOL_CHARS.pattern[1:-1] + "]+)", text)):
            if not seg:
                continue
            if k % 2:
                out.append(Piece(seg, st, "", True, None, True))       # ∑ ≤ θ … : typeset with the maths font
            else:
                out.append(Piece(seg, st))

    for tag, a1, a2, b1, b2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal":
            for a, b, pc in spans:
                lo, hi = max(a1, a), min(a2, b)
                if lo >= hi:
                    continue
                if (lo, hi) == (a, b):
                    out.append(pc)                       # untouched: the very same piece
                elif pc.img or pc.br:
                    continue                             # a picture can not be cut in two
                else:
                    out.append(dataclasses.replace(pc, text=norm(pc.text)[lo - a:hi - a]))
        elif tag in ("replace", "insert"):
            add_new(new[b1:b2], style_at(a1))
    return out


def _format_ranges(p: Para, pieces: List[Piece], fmt: List[list]) -> List[Piece]:
    """[[start, end, size factor, bold (1/0/-1 = unchanged), italic], …] measured in the text of the block: the
    pieces are cut at these places and the words inside get the new style."""
    import dataclasses
    para_style = Run("", p.size, p.bold, p.italic, p.color, p.mono, "", p.font)
    for a, b, scale, bold, ital in fmt:
        out: List[Piece] = []
        pos = 0
        for pc in pieces:
            n = len(pc.text)
            lo, hi = max(a, pos), min(b, pos + n)
            if lo >= hi or pc.img or pc.br:
                out.append(pc)
                pos += n
                continue
            cut = [(pos, lo, False), (lo, hi, True), (hi, pos + n, False)]
            for c0, c1, inside in cut:
                if c1 <= c0:
                    continue
                part = dataclasses.replace(pc, text=pc.text[c0 - pos:c1 - pos])
                if inside:
                    st0 = pc.style or para_style
                    kw = {"size": st0.size * float(scale)}
                    if bold in (0, 1):
                        kw["bold"] = bool(bold)
                    if ital in (0, 1):
                        kw["italic"] = bool(ital)
                    part.style = dataclasses.replace(st0, **kw)
                out.append(part)
            pos += n
        pieces = out
    return pieces


def apply_area_ops(path: str, ops: List[dict]) -> int:
    """Review window, "Area" tool: a rectangle of the finished page (a picture, a table, a line, a row of text …)
    is moved to another place or erased.  The page is rebuilt with that area cut out and pasted at its new
    place; everything stays sharp (vector), nothing is photographed."""
    if not ops:
        return 0
    src = fitz.open(path)
    out = fitz.open()
    n = 0
    for pi in range(src.page_count):
        mine = [o for o in ops if int(o.get("page", -1)) == pi]
        if not mine:
            out.insert_pdf(src, from_page=pi, to_page=pi)
            continue
        cur, cno = src, pi
        made: List = []
        for o in mine:
            pr = cur[cno].rect
            r = fitz.Rect(o["rect"]) & pr
            if r.is_empty or r.width < 1 or r.height < 1:
                continue
            nd = fitz.open()
            npg = nd.new_page(width=pr.width, height=pr.height)
            npg.show_pdf_page(npg.rect, cur, cno)
            npg.draw_rect(r, color=None, fill=(1, 1, 1), overlay=True)
            if not o.get("delete"):
                t = fitz.Rect(r.x0 + float(o.get("dx", 0)), r.y0 + float(o.get("dy", 0)),
                              r.x1 + float(o.get("dx", 0)), r.y1 + float(o.get("dy", 0)))
                npg.show_pdf_page(t, cur, cno, clip=r)
            made.append(nd)
            cur, cno = nd, 0
            n += 1
        out.insert_pdf(cur, from_page=cno, to_page=cno)
        for dd in made:
            dd.close()
    src.close()
    tmp = path + ".area.tmp"
    out.save(tmp, garbage=3, deflate=True)
    out.close()
    os.replace(tmp, path)
    return n


def apply_review_edit(p: Para, pieces: List[Piece], e: dict) -> List[Piece]:
    """One paragraph edited in the review window: new text, size factor, bold, italic, heading font, alignment,
    a new place on the page.  Parts that were not touched stay exactly as they were."""
    import dataclasses
    plain = [pc for pc in pieces if not (pc.latin or pc.math or pc.img) and pc.text.strip()]
    base = next((pc.style for pc in plain if pc.style is not None), None)
    new = e.get("text")
    old = "".join(pc.text for pc in pieces)
    norm = lambda t: t.replace("\u00a0", " ")
    if new is not None and norm(new).strip() != norm(old).strip():
        pieces = _retext(pieces, new, base)
    if e.get("fmt"):                                    # size / bold / italic of SOME words (selected in the editor)
        pieces = _format_ranges(p, pieces, e["fmt"])
    if e.get("lh"):
        p.lh_mult = max(0.5, min(3.0, float(e["lh"])))
    if e.get("dh"):
        p.dh += float(e["dh"])
    dx, dy, dw = float(e.get("dx", 0) or 0), float(e.get("dy", 0) or 0), float(e.get("dw", 0) or 0)
    if dx or dy or dw:                                  # the block is typeset at another place / in another width
        x0, y0, x1, y1 = p.bbox
        p.bbox = (x0 + dx, y0 + dy, max(x0 + dx + 20, x1 + dx + dw), y1 + dy)
        p.moved = True
    scale = float(e.get("scale", 1.0) or 1.0)
    if abs(scale - 1.0) > 0.005:
        p.size *= scale
        seen: Set[int] = set()
        for pc in pieces:
            if pc.style is not None and not pc.latin and id(pc.style) not in seen:
                pc.style = dataclasses.replace(pc.style, size=pc.style.size * scale)
                seen.add(id(pc.style))
    for attr in ("bold", "italic"):
        if attr in e and bool(e[attr]) != bool(getattr(p, attr)):
            setattr(p, attr, bool(e[attr]))
            for pc in pieces:
                if pc.style is not None and not pc.latin:
                    pc.style = dataclasses.replace(pc.style, **{attr: bool(e[attr])})
    if "heading" in e:
        p.heading = bool(e["heading"])
    if e.get("align") in ("left", "right", "center", "justify"):
        p.align = e["align"]
    return pieces


def run_job(pdf_path: str, out_dir: str, langs: List[str], opts: Options, log: Callable[[str], None],
            progress: Callable[[float, str], None], cancel: threading.Event, ctl: Optional[dict] = None) -> List[str]:
    """Translates the book part by part (`opts.part_pages` = 2 pages).  Every finished part is stored in the job
    cache; at the end all parts are merged into ONE file per format.  An interrupted job continues after the last
    finished part.  `ctl` (window only): {'review': Event, 'resp': Queue} for "Translate with review"."""
    if is_subtitle(pdf_path):                           # subtitles: only the spoken text, same format
        return run_subtitle_job(pdf_path, out_dir, langs, opts, log, progress, cancel)
    import dataclasses
    import shutil
    if opts.speed == "fast":                      # text only: no typesetting, no internet terminology search
        opts = dataclasses.replace(opts, out_pdf=False, out_docx=False, out_txt=True, auto_specialty=False,
                                   specialties=[])
    if tuple(int(x) for x in fitz.version[1].split(".")[:3]) < (1, 24, 3):
        raise RuntimeError("PyMuPDF 1.24.3 or newer is required (pip install -U pymupdf).")
    if not is_file(pdf_path):
        raise FileNotFoundError("Please choose an input PDF file.")
    if not langs:
        raise ValueError("Select at least one target language.")
    if not (opts.out_pdf or opts.out_docx or opts.out_txt):
        raise ValueError("Select at least one output format (Doc, Text or PDF).")
    pdf_path, out_dir = long_path(pdf_path), long_path(out_dir)
    os.makedirs(xl(out_dir), exist_ok=True)
    purge_old_jobs()
    try:
        add_history(pdf_path, [], langs)                 # the job is in the History from its first minute
    except Exception:
        pass

    doc = fitz.open(xl(pdf_path))
    if doc.needs_pass:
        raise RuntimeError("The PDF is password-protected.")
    n_pages = doc.page_count
    selected = sorted(parse_pages(opts.pages, n_pages))
    doc.close()
    if n_pages > MAX_FILE_PAGES:
        raise ValueError(f"This file has {n_pages} pages. Files of more than {MAX_FILE_PAGES} pages are not "
                         f"accepted – split the PDF into smaller files first.")
    if not selected:
        raise ValueError("The page selection is empty.")
    step = max(1, int(opts.part_pages))
    win = step * max(1, -(-max(step, opts.chunk_pages) // step))          # analysis window: a multiple of the part size
    windows = [selected[i:i + win] for i in range(0, len(selected), win)]
    split = lambda pages: [pages[i:i + step] for i in range(0, len(pages), step)]
    nparts = sum(len(split(w)) for w in windows)
    total_sel = len(selected)
    whole = total_sel == n_pages
    log(f"Program build {APP_BUILD}.")
    log(f"Opened “{Path(pdf_path).name}” – {n_pages} pages, {total_sel} selected.")
    if opts.src_lang == langs[0] and len(langs) == 1:
        raise RuntimeError("The origin language and the target language are the same. Choose two different ones.")
    if opts.src_lang != "en":
        # the lists of English technical terms, Capitalized names and English headings belong to English originals
        # (German writes every noun with a capital letter; Persian has no capital letters at all)
        opts = dataclasses.replace(opts, keep_terms=False, keep_names=False, bilingual_headings=False,
                                   auto_specialty=False, specialties=[])
        log(f"Origin language: {LANGS[opts.src_lang]['name']} – the English term lists and the English heading "
            f"table are not used; formulas, numbers, acronyms and code are still kept.")
    log(f"Translation engine: {opts.model if opts.engine == 'local' else opts.engine + ' / ' + opts.llm_model}")
    log(f"{total_sel} page(s) = {nparts} part(s) of {step} pages. After every part the output file is updated, "
        f"so the pages that are finished are never lost.")
    formats = [n for n, on in (("PDF", opts.out_pdf), ("Word", opts.out_docx), ("Text", opts.out_txt)) if on]
    if opts.speed == "fast":
        log("Mode: FAST – only the text is translated (greedy decoding, no typesetting). Output: text file.")
    else:
        log(f"Mode: ACCURATE – full translation quality and page layout.")
        log(f"Output: {', '.join(formats)}   ·   font-size factor {opts.font_scale * 100:.0f} %")
    log(f"Output folder: {out_dir}")

    review_on = lambda: bool(ctl and ctl.get("review") is not None and ctl["review"].is_set())
    outputs: List[str] = []
    nl = len(langs)
    proto: Optional[Protector] = None
    instructions = load_instructions()
    if instructions:
        log(f"My instructions: {len(instructions)} instruction(s) of the user are applied to this translation.")
    for li, lang in enumerate(langs):
        info = LANGS[lang]
        log(f"━━ {info['name']} ━━")
        if lang == "fa":
            head_key, body_key = opts.heading_font, opts.body_font
            head_file = opts.heading_font_file if head_key == CUSTOM_FONT_LABEL else None
            body_file = opts.body_font_file if body_key == CUSTOM_FONT_LABEL else None
        elif lang in LATIN_LANGS:                          # Latin script: the user's choice, default = original fonts
            ok = set(LATIN_FONTS) | {CUSTOM_FONT_LABEL}
            # a Persian / Arabic original has no usable Latin font of its own
            dflt = "Times New Roman" if LANGS.get(opts.src_lang, {}).get("rtl") else SAME_FONT
            head_key = opts.heading_font if opts.heading_font in ok else dflt
            body_key = opts.body_font if opts.body_font in ok else dflt
            if dflt != SAME_FONT:
                head_key = dflt if head_key == SAME_FONT else head_key
                body_key = dflt if body_key == SAME_FONT else body_key
            head_file = opts.heading_font_file if head_key == CUSTOM_FONT_LABEL else None
            body_file = opts.body_font_file if body_key == CUSTOM_FONT_LABEL else None
        else:                                              # other languages: the font that suits the script
            head_key = body_key = info["font"] or ""
            head_file = body_file = None
        head_name = _font_display_name(head_key, head_file) if head_key else "Times New Roman"
        body_name = _font_display_name(body_key, body_file) if body_key else "Times New Roman"

        def prog(frac: float, msg: str, li=li) -> None:
            progress((li + frac) / nl, msg)

        prog(0.0, "Loading the translation model …")
        act("", "eta")
        if opts.engine == "local":
            act("Status: loading the translation model – this takes 1 to 3 minutes, please wait …", "s")
            log("Loading the translation model. This takes 1 to 3 minutes on a slow disk; the translation starts "
                "right after it …")
        else:
            act("Status: connecting to the translation engine …", "s")
        if proto is not None:
            proto.set_lang(lang)
        mt = make_engine(opts, lang, log)
        probe = mt.translate_texts(["This text is for testing the performance of the \"translation\" engine."])[0]
        if not probe.strip():
            raise RuntimeError("The translation model returned an empty result. Re-install / re-convert the model.")
        log(f"Engine check OK ({engine_tag(opts)}): {probe}")
        if opts.engine == "local":
            mt.beams = 2 if (opts.best_quality and opts.speed != "fast") else 1
            log("Decoding: " + ("beam search, 2 candidates per sentence (Best quality – about 2× slower)."
                                if mt.beams == 2 else
                                "fast (one candidate per sentence; damaged sentences are translated again "
                                "with a wider search)."))

        job_dir = job_cache_dir(pdf_path, lang, opts)
        job_dir.mkdir(parents=True, exist_ok=True)
        os.utime(job_dir, None)
        copts = dataclasses.replace(opts, translate_bookmarks=False)
        need_text = opts.out_docx or opts.out_txt
        src_rtl = bool(LANGS.get(opts.src_lang, {}).get("rtl"))
        # the reading direction changes (English -> Persian, Persian -> English): the two columns change places
        swap = bool(opts.swap_columns and bool(info["rtl"]) != src_rtl and (opts.rtl_direction or not info["rtl"]))
        t_start = time.time()
        state = {"tr": 0.0, "lay": 0.0, "paused": 0.0, "cached_pages": 0}
        hist_spp, hist_n = predicted_sec_per_page(opts, lang)
        langs_left = nl - li - 1
        if hist_spp:
            log(f"Estimated time for {total_sel} page(s): ≈ {fmt_dur(hist_spp * total_sel)}  "
                f"(Estimated time based on previous translations – {hist_n} part(s) with the same settings)")
        else:
            log(f"Estimated time: not known yet – no earlier translation with these settings on this computer. "
                f"It is measured during this job and remembered for the next one.")

        page_words: Dict[int, int] = {}                     # words to translate on every analysed page

        def words_at(pos: float) -> float:
            """Words of the pages up to position pos (pages of the job, with a fraction of the page in work)."""
            n_full = int(pos)
            w = sum(page_words.get(selected[j], 0) for j in range(min(n_full, total_sel)))
            if n_full < total_sel:
                w += (pos - n_full) * page_words.get(selected[n_full], 0)
            return w

        def send_eta() -> None:
            """Remaining time.  Pages differ a lot (a page of text, a page of figures), so the estimate counts
            WORDS, not pages: seconds per word measured in this job x words that are still to do.  Pages that are
            not analysed yet count with the average of the analysed ones.  While little is measured, the average
            of earlier translations (per page) is mixed in."""
            done_w = 0.85 * words_at(state["tr"]) + 0.15 * words_at(state["lay"])
            elapsed = time.time() - t_start - state["paused"] - state.get("idle", 0.0)
            known = sum(page_words.values())
            unknown_pages = max(0, total_sel - len(page_words) - state.get("win_cached", 0))
            avg = known / max(1, sum(1 for v in page_words.values() if v)) if known else 0.0
            left_w = max(0.0, known - done_w) + unknown_pages * avg
            pages_left = max(0.0, total_sel - (0.85 * state["tr"] + 0.15 * state["lay"]))
            live = (elapsed / done_w) * left_w if done_w >= 120 and elapsed > 10 else None
            hist = hist_spp * pages_left if hist_spp else None
            if live is not None and hist is not None:
                w = min(1.0, done_w / 900.0)
                est = w * live + (1 - w) * hist
            else:
                est = live if live is not None else hist
            if est is None:
                act("", "eta")
                return
            if langs_left:
                est += langs_left * (hist_spp * total_sel if hist_spp else (elapsed + est))
            act(str(int(est)), "eta")

        def st(phase: str, gi: int = 0, pages_now: Optional[List[int]] = None) -> None:
            """ONE place for page / part / status:  'Page 007 / 034 · Part 4 of 17 · Status: translating …'"""
            state["phase"] = phase
            if gi:
                state["gi"] = gi
            show()

        def show() -> None:
            phase = state.get("phase", "")
            cur = state["lay"] if ("layout" in phase or "review" in phase) else state["tr"]
            page = max(1, min(total_sel, int(cur + 1e-6) + 1))
            if state["lay"] >= total_sel:
                page = total_sel
            part = f"   ·   Part {state['gi']} of {nparts}" if state.get("gi") else ""
            act(f"Page {page:03d} / {total_sel:03d}{part}   ·   Status: {phase}", "s")
            prog(min(1.0, overall()), f"Page {page:03d} of {total_sel:03d}")

        def overall() -> float:
            return (0.85 * state["tr"] + 0.15 * state["lay"]) / total_sel

        def tick(msg: str = "", gi: int = 0) -> None:
            show()
            send_eta()

        # fonts: once per language
        same = body_key == SAME_FONT
        body = heading = None
        fonts_ready = False

        def ensure_fonts() -> None:
            nonlocal body, heading, fonts_ready
            if fonts_ready:
                return
            fonts_ready = True
            if body_key and not same:
                body = resolve_font_safe(body_key, log, body_file, opts.allow_download)
                heading = body if (head_key == body_key and head_file == body_file) else \
                    resolve_font_safe(head_key if head_key != SAME_FONT else body_key, log, head_file,
                                      opts.allow_download)

        part_files: List[str] = []
        all_analysis: Dict[int, List[Para]] = {}
        all_pieces: Dict[int, List[Piece]] = {}
        done_pages: List[int] = []
        gi = 0
        st("starting …")
        # ---- the output files: their names are fixed now; they are written after EVERY part
        spec_tail = "" if whole else opts.pages
        final: Dict[str, str] = {}
        for ext, on in ((".pdf", opts.out_pdf), (".txt", opts.out_txt), (".docx", opts.out_docx)):
            if on:
                f0 = fit_output_path(out_dir, output_name(pdf_path, lang, ext, spec_tail), log)
                if is_locked(f0):
                    alt = str(free_name(f0))
                    log(f"Warning: “{Path(f0).name}” is open in another program and can not be overwritten – "
                        f"this translation is saved as “{Path(alt).name}”.")
                    f0 = alt
                final[ext] = f0
        told = {"locked": False}

        split_on = bool(opts.split_pages and opts.out_pdf and len(windows) > 1)
        seg_parts: List[str] = []                           # finished parts of the 20-page file in work
        seg = {"dst": final.get(".pdf", ""), "no": 0}

        def seg_name(wi: int, pages_w: List[int]) -> str:
            base_ = output_name(pdf_path, lang, ".pdf", "")
            tail = f"_file{wi + 1:02d}of{len(windows):02d}_pages_{pages_w[0] + 1}-{pages_w[-1] + 1}"
            return fit_output_path(out_dir, base_[:-4] + tail + ".pdf", log)

        def publish() -> None:
            """Writes what is finished so far to the output folder (PDF and text)."""
            try:
                ok = True
                files_now = seg_parts if split_on else part_files
                if opts.out_pdf and files_now:
                    m_ = fitz.open()
                    for f in files_now:
                        with fitz.open(f) as d:
                            m_.insert_pdf(d)
                    ok = save_with_fallback(seg["dst"] if split_on else final[".pdf"],
                                            lambda f: m_.save(f, garbage=3, deflate=True), log,
                                            quiet=True) is not None
                    m_.close()
                if opts.out_txt and done_pages:
                    part_an = {i: all_analysis[i] for i in done_pages if i in all_analysis}
                    save_with_fallback(final[".txt"], lambda f: write_txt(f, part_an, all_pieces, lang), log,
                                       quiet=True)
                if ok:
                    told["locked"] = False
                    if opts.out_pdf and files_now:
                        log(f"✔ Output file updated ({int(state['lay'])} of {total_sel} pages): "
                            f"{Path(seg['dst'] if split_on else final['.pdf']).name}")
                elif not told["locked"]:
                    told["locked"] = True
                    log("Note: the output file is open in another program, so it can not be updated now. "
                        "The finished parts are safe in the cache; the file is written at the end.")
            except Cancelled:
                raise
            except Exception as exc:                     # noqa: BLE001 – an update must never stop the job
                log(f"Note: the output file could not be updated now ({type(exc).__name__}: {exc}).")

        pos_of = {i: k for k, i in enumerate(selected)}
        if li == 0:                                         # workload chart: the pages of the job, from page one
            act({"kind": "plan", "pages": [i + 1 for i in selected], "pts": []}, "load")
        if split_on:
            log(f"Long job on a slow computer: the PDF is written as {len(windows)} files of {win} "
                f"pages each (file01 … file{len(windows):02d}); each file is complete as soon as its pages are done.")
        for wi, pages_w in enumerate(windows):
            if cancel.is_set():
                raise Cancelled()
            if split_on:
                if seg_parts and seg["dst"] and seg["dst"] not in outputs:
                    outputs.append(seg["dst"])
                    log(f"Saved: {seg['dst']}")
                seg_parts.clear()
                seg["dst"] = seg_name(wi, pages_w)
            parts = split(pages_w)
            pfile = lambda part: job_dir / f"p{part[0] + 1:05d}-{part[-1] + 1:05d}.pdf"
            done_w = [opts.out_pdf and pfile(part).is_file() for part in parts]
            if opts.out_pdf and not need_text and all(done_w):          # everything of this window is in the cache
                for part in parts:
                    gi += 1
                    part_files.append(str(pfile(part)))
                    state["tr"] += len(part)
                    state["lay"] += len(part)
                    state["cached_pages"] += len(part)
                    state["win_cached"] = state.get("win_cached", 0) + len(part)
                    done_pages.extend(part)
                    seg_parts.append(str(pfile(part)))
                    if li == 0:
                        act({"kind": "real", "flat": [(pos_of[i], 0.0) for i in part]}, "load")
                log(f"✔ Parts up to {gi} of {nparts} were already finished (taken from the cache).")
                st("continuing after the finished parts …", gi)
                tick()
                publish()
                continue

            copts.pages = _pages_spec(pages_w)
            st("reading the page layout …", gi + 1, pages_w)
            doc = fitz.open(xl(pdf_path))
            analysis, obstacles = analyze(doc, copts, log, cancel,
                                          lambda f, m, gi=gi: tick(m, gi + 1))
            opts.backmatter_at = copts.backmatter_at
            zones: Dict[int, list] = {}
            if swap:
                for i in pages_w:
                    try:
                        zones[i] = column_swap_zones(analysis[i], obstacles[i], doc[i], i)
                    except Exception:
                        zones[i] = []
            page_h = {i: max(1.0, doc[i].rect.height) for i in pages_w}
            for i, cached_ in ((i, c) for part_, c in zip(parts, done_w) for i in part_):
                # (pages of a part that comes from the cache need no work: they count as zero words)
                page_words[i] = 0 if (cached_ and not need_text) else \
                    sum(len(p.text.split()) for p in analysis[i] if not p.skip)
            doc.close()
            xpos = lambda p: pos_of[p.page] + min(0.999, max(0.0, (p.bbox[1] + p.bbox[3]) / 2 / page_h[p.page]))
            if li == 0:                                     # workload chart: the amount of text of every page region
                act({"kind": "plan", "pages": [i + 1 for i in selected],
                     "pts": [(xpos(p), len(p.text.split())) for i in pages_w for p in analysis[i] if not p.skip]},
                    "load")
            if proto is None and any(not p.skip for v in analysis.values() for p in v):
                sample = [p.text for v in analysis.values() for p in v if not p.skip][:4000]
                _specs, domain_terms = resolve_specialties(sample, opts, log, cancel)
                proto = Protector(opts, load_user_terms(), domain_terms, instructions)
                proto.set_lang(lang)
                log(f"Terminology guard: {proto.n_terms} terms ({len(domain_terms)} from specialty search)"
                    f"{' + proper names and Capitalized terms' if opts.keep_names else ''}"
                    f"{' + automatic detection of acronyms, units, identifiers and formulas' if opts.auto_terms else ''}.")
            if need_text:
                all_analysis.update(analysis)

            for part, cached in zip(parts, done_w):
                if cancel.is_set():
                    raise Cancelled()
                gi += 1
                t_part, paused0 = time.time(), state["paused"]
                dst_part = pfile(part)
                pages_txt = f"page {part[0] + 1}" if len(part) == 1 else f"pages {part[0] + 1}–{part[-1] + 1}"
                if cached and not need_text:
                    part_files.append(str(dst_part))
                    seg_parts.append(str(dst_part))
                    state["tr"] += len(part)
                    state["lay"] += len(part)
                    state["cached_pages"] += len(part)
                    done_pages.extend(part)
                    if li == 0:
                        act({"kind": "real", "flat": [(pos_of[i], 0.0) for i in part]}, "load")
                    log(f"✔ Part {gi} of {nparts} ({pages_txt}) was already finished (taken from the cache).")
                    st("continuing …", gi)
                    tick()
                    continue
                log(f"━ Part {gi} of {nparts}  ({pages_txt})")
                sub_an = {i: analysis[i] for i in part}
                sub_ob = {i: obstacles[i] for i in part}
                prepared: Dict[int, List[Item]] = {}
                para_by_id: Dict[int, Para] = {}
                for i in part:
                    for p in sub_an[i]:
                        if not p.skip and proto is not None:
                            prepared[id(p)] = prepare_para(p, proto)
                            para_by_id[id(p)] = p
                if not prepared:
                    log("  nothing to translate in this part (all blocks are kept unchanged).")
                all_texts = [t for items in prepared.values() for t in collect_texts(items)]
                tr: Dict[str, str] = {}
                by_page: Dict[int, List[str]] = {}
                for pid, items in prepared.items():
                    by_page.setdefault(para_by_id[pid].page, []).extend(collect_texts(items))
                stats: Dict[str, int] = {}
                tr0 = state["tr"]
                for k, pno in enumerate(part):              # page after page: progress is visible, nothing is lost
                    if cancel.is_set():
                        raise Cancelled()
                    if pno in by_page:
                        t_pg = time.time()
                        state["tr"] = tr0 + k
                        st("translating …", gi, part)

                        def tprog(f: float, m: str, k=k, gi=gi, pno=pno) -> None:
                            state["tr"] = tr0 + k + min(f, 0.999)
                            if li == 0:                     # workload chart: where the work is now
                                act({"kind": "real", "head": pos_of[pno] + min(f, 0.97)}, "load")
                            tick()

                        if li == 0:
                            act({"kind": "real", "head": pos_of[pno] + 0.12}, "load")

                        c0 = (getattr(mt, "n_sent", 0), getattr(mt, "n_retry", 0), getattr(mt, "n_tok", 0))
                        tr.update(translate_all(by_page[pno], lang, mt, opts, log, cancel, tprog, stats))
                        ns, nr, nt = (getattr(mt, "n_sent", 0) - c0[0], getattr(mt, "n_retry", 0) - c0[1],
                                      getattr(mt, "n_tok", 0) - c0[2])
                        sec = max(0.1, time.time() - t_pg)
                        cost = stats.get("cost", {})
                        if li == 0:                         # workload chart: the time every region really took
                            act({"kind": "real", "pts": [
                                (xpos(para_by_id[pid]), sum(cost.get(t, 0.0) for t in collect_texts(items)) + 0.05)
                                for pid, items in prepared.items() if para_by_id[pid].page == pno]}, "load")
                        log(f"✔ Page {pno + 1} translated ({fmt_dur(sec)})" +
                            (f" – {ns} sentences, {nr} translated twice, {nt / sec:.1f} tokens per second"
                             if ns else ""))
                    state["tr"] = tr0 + k + 1 - (0.001 if k == len(part) - 1 else 0)
                    tick()
                # ---- proofreading: automatic checks of every translated block
                st("checking the translation …", gi, part)
                tr = proofread(all_texts, tr, log) if all_texts else tr
                pieces_map = {pid: assemble_para(items, tr, lang, opts) for pid, items in prepared.items()}
                all_pieces.update(pieces_map)

                # ---- typesetting of this part (into the cache)
                want_pdf = opts.out_pdf or (review_on() and opts.speed != "fast")
                lay0 = state["lay"]
                if want_pdf and not cached:
                    ensure_fonts()

                    def render_part() -> None:
                        charset = "".join(pc.text for pcs in pieces_map.values() for pc in pcs) + \
                                  "\u200c\u200d\u200e\u200f\u202a\u202c"
                        orig_names = {piece_font_name(pc, para_by_id[pid]) for pid, pcs in pieces_map.items()
                                      for pc in pcs if pc.latin}
                        if same:
                            orig_names |= {para_by_id[pid].font for pid in pieces_map}
                        orig_names.discard("")
                        renderer = Renderer(lang, opts, body, heading, orig_names, charset, log, same_orig=same)

                        def on_para(pno: int, p: Para) -> None:
                            fa = "".join(c.text for c in pieces_map.get(id(p), [])).strip().replace("\n", " ")
                            act(f"  {'Heading' if p.heading else 'Body'}: {fa[:80]}", "h" if p.heading else "w")

                        def lprog(f: float, m: str) -> None:
                            state["lay"] = lay0 + len(part) * min(f, 0.999)
                            tick()

                        tmp = str(dst_part) + ".tmp"
                        try:
                            pushes: Dict[int, List[tuple]] = {}
                            for sp in spaces:
                                pushes.setdefault(part[int(sp["page"])], []).append(
                                    (float(sp["y"]), float(sp["dy"]), float(sp.get("x0", -1e4)),
                                     float(sp.get("x1", 1e4))))
                            render_pdf(pdf_path, tmp, sub_an, sub_ob, pieces_map, renderer, lang, copts,
                                       lambda t: t, log, cancel, lprog, on_para,
                                       part if len(part) < n_pages else None, pushes)
                        finally:
                            renderer.close()
                        if swap:
                            nsw = swap_columns_pdf(tmp, {k: zones.get(i, []) for k, i in enumerate(part)})
                            if nsw:
                                act(f"  two-column layout mirrored for Persian on {nsw} page(s)", "b")
                        os.replace(tmp, dst_part)

                    st("working on layout …", gi, part)
                    t_lay = time.time()
                    area_ops: List[dict] = []
                    spaces: List[dict] = []                    # review window: room inserted / removed on the pages
                    render_part()
                    if li == 0:
                        act({"kind": "real", "flat": [(pos_of[i], (time.time() - t_lay) / len(part)) for i in part]},
                            "load")
                    # ---- "Translate with review": the user edits this part.  Every change of the window is
                    # typeset at once ("preview"): the part goes back to its original translation and ALL changes of
                    # the window are applied again, so "Undo all" and "Cancel" give exactly the first result.
                    todo = [(i, p) for i in part for p in sub_an[i]
                            if not p.skip and "".join(c.text for c in pieces_map.get(id(p), [])).strip()] \
                        if review_on() else []
                    if todo:
                        import copy as _copy
                        pristine = {id(p): (p.bbox, p.lh_mult, p.dh, p.moved, p.size, p.bold, p.italic, p.heading,
                                            p.align, _copy.deepcopy(pieces_map[id(p)])) for _i, p in todo}

                        def shown_boxes() -> Dict[int, List[float]]:
                            shown: Dict[int, List[float]] = {}
                            for i in part:
                                shown.update(pushed_boxes(sub_an[i], [
                                    (float(sp["y"]), float(sp["dy"]), float(sp.get("x0", -1e4)),
                                     float(sp.get("x1", 1e4))) for sp in spaces if part[int(sp["page"])] == i]))
                            return shown

                        shown = shown_boxes()
                        act({"part": gi, "nparts": nparts, "pdf": str(dst_part), "pages": [i + 1 for i in part],
                             "rtl": bool(info["rtl"]), "spaces": [],
                             "paras": [{"k": k, "page": i + 1, "pi": part.index(i),
                                        "bbox": [round(v, 2) for v in shown.get(id(p), p.bbox)],
                                        "lh": round(p.lh_mult, 2),
                                        "text": "".join(c.text for c in pieces_map[id(p)]),
                                        "size": round(p.size, 1), "bold": bool(p.bold),
                                        "italic": bool(p.italic), "heading": bool(p.heading),
                                        "align": p.align} for k, (i, p) in enumerate(todo)]}, "review")
                        log(f"Review: part {gi}/{nparts} is shown in the review window – every change is shown at "
                            f"once; waiting for “Save and next part” …")
                        st("waiting for your review", gi, part)
                        rendered = json.dumps({"edits": {}, "areas": [], "spaces": []}, sort_keys=True)
                        t_wait = time.time()
                        while True:
                            resp = None
                            while resp is None:
                                if cancel.is_set():
                                    raise Cancelled()
                                try:
                                    resp = ctl["resp"].get(timeout=0.4)
                                except queue.Empty:
                                    if not review_on():           # the tick was removed while the window was open
                                        resp = {"action": "next", "keep": True}
                            action = resp.get("action", "cancel")
                            if resp.get("keep"):                  # keep what the page shows now
                                break
                            want = {"edits": {k: v for k, v in (resp.get("edits") or {}).items() if v},
                                     "areas": [a for a in (resp.get("areas") or []) if isinstance(a, dict)],
                                     "spaces": [a for a in (resp.get("spaces") or []) if isinstance(a, dict)]}
                            if action == "cancel":
                                want = {"edits": {}, "areas": [], "spaces": []}
                            key = json.dumps(want, sort_keys=True)
                            if key != rendered:
                                for _i, p in todo:                # back to the translation as it was made
                                    (p.bbox, p.lh_mult, p.dh, p.moved, p.size, p.bold, p.italic, p.heading,
                                     p.align, pcs0) = pristine[id(p)]
                                    pieces_map[id(p)] = _copy.deepcopy(pcs0)
                                    all_pieces[id(p)] = pieces_map[id(p)]
                                spaces[:] = want["spaces"]
                                shown = shown_boxes()
                                for k, e in want["edits"].items():
                                    if k == "_" or not k.isdigit() or int(k) >= len(todo):
                                        continue
                                    i, p = todo[int(k)]
                                    pieces_map[id(p)] = apply_review_edit(p, pieces_map[id(p)], e)
                                    all_pieces[id(p)] = pieces_map[id(p)]
                                t_r = time.time()
                                render_part()
                                area_ops[:] = want["areas"]
                                if area_ops:
                                    apply_area_ops(str(dst_part), area_ops)
                                rendered = key
                                n_ch = len(want["edits"]) + len(want["areas"]) + len(want["spaces"])
                                log(f"Review: part {gi}/{nparts} typeset again with {n_ch} change(s) "
                                    f"({time.time() - t_r:.1f} s).")
                            if action == "preview":
                                act({"pdf": str(dst_part), "seq": resp.get("seq", 0),
                                     "bbox": [[round(v, 2) for v in shown.get(id(p), pristine[id(p)][0])]
                                              for _i, p in todo]}, "review_upd")
                                st("waiting for your review", gi, part)
                                continue
                            log(f"Review: part {gi}/{nparts} " + ("kept as it was translated." if action == "cancel"
                                                                   else "saved with your changes."))
                            break
                        state["paused"] += time.time() - t_wait
                if opts.out_pdf:
                    part_files.append(str(dst_part))
                    seg_parts.append(str(dst_part))
                state["tr"] = tr0 + len(part)
                state["lay"] = lay0 + len(part)
                done_pages.extend(part)
                log(f"✔ Part {gi} of {nparts} finished ({fmt_dur(time.time() - t_part - (state['paused'] - paused0))}).")
                if stats.get("all") and stats.get("todo", 0) >= 0.7 * stats["all"] and not cached:
                    record_timing(opts, lang, len(part), time.time() - t_part - (state["paused"] - paused0))
                else:
                    state["cached_pages"] += len(part) * (1 - stats.get("todo", 0) / max(1, stats.get("all", 1)))
                st("saving the finished part …", gi, part)
                tick()
                publish()
                if gi < nparts:
                    act("", "part")                         # sound: a part is finished
            analysis = obstacles = None                     # free the memory of this window (kept only for Word / text)

        # ---- merge: one file per format
        if split_on:
            if seg_parts and seg["dst"] and seg["dst"] not in outputs:
                outputs.append(seg["dst"])
                log(f"Saved: {seg['dst']}")
        elif opts.out_pdf and part_files:
            st("writing the final PDF …")
            merged = fitz.open()
            for f in part_files:
                with fitz.open(f) as d:
                    merged.insert_pdf(d)
            if opts.translate_bookmarks and whole:
                try:
                    with fitz.open(xl(pdf_path)) as srcd:
                        toc = srcd.get_toc(simple=True)
                    if toc:
                        merged.set_toc(toc)
                        if proto is None:
                            proto = Protector(opts, load_user_terms(), set(), instructions)
                            proto.set_lang(lang)

                        def titles_fn(titles: List[str]) -> List[str]:
                            d0 = Run("", 10, False, False, "#000000")
                            its = [_build_item([Run(t, 10, False, False, "#000000")], d0, proto, None)
                                   for t in titles]
                            srcs = list(dict.fromkeys(it.src for it in its if it.needs_mt))
                            tr2 = dict(zip(srcs, mt.translate_texts(srcs))) if srcs else {}
                            return ["".join(pc.text for pc in assemble_item(it, tr2, lang, opts)).strip()
                                    for it in its]

                        _translate_bookmarks(merged, titles_fn, opts, log)
                except Exception as exc:
                    log(f"Bookmarks could not be translated: {exc}")
            dst = save_with_fallback(final[".pdf"], lambda f: merged.save(f, garbage=3, deflate=True), log)
            merged.close()
            outputs.append(dst)
            log(f"Saved: {dst}")
        if opts.out_txt:
            dst = save_with_fallback(final[".txt"], lambda f: write_txt(f, all_analysis, all_pieces, lang), log)
            outputs.append(dst)
            log(f"Saved: {dst}")
        if opts.out_docx:
            st("writing the Word file …")
            dst = save_with_fallback(
                final[".docx"], lambda f: write_docx(f, pdf_path, all_analysis, all_pieces, lang, opts, head_name, body_name, log),
                log)
            outputs.append(dst)
            log(f"Saved: {dst}")
            log(f"Note: Word uses the fonts installed on the computer that opens the file "
                f"({head_name} / {body_name}).")
        shutil.rmtree(job_dir, ignore_errors=True)        # the job is complete: its part cache is not needed any more
        st("finished – all files are in the output folder")
    act("0", "eta")
    progress(1.0, "Done")
    try:
        add_history(pdf_path, outputs, langs)
    except Exception:
        pass
    return outputs


# ════════════════════════════════════════════════════════════════════════════
#  Help text
# ════════════════════════════════════════════════════════════════════════════
HELP_TEXT = f"""\
{APP_TITLE}  v{APP_VERSION}
═══════════════════════════════════════════════════════════════

ABOUT THIS APPLICATION
  {APP_TITLE} translates books and long documents (PDF) into another language and keeps the look of the
  original. The translation is done by AI, completely OFFLINE on your own computer, with open-source
  state-of-the-art AI translation models (currently MADLAD-400 and NLLB-200; newer, stronger models will be
  adopted as they appear). No website, no account and no API key are needed – after a one-time download of the
  model, the app works without internet.

  Current version: English  →  Persian  and  English  →  German (choose one target language).
  Coming in future versions: more origin and target languages. The greyed-out entries in the "Languages" area show
  what will be added. For German the fonts of the original document are used by default ("same as original
  document"), quotation marks become „…“, and left-to-right layout is used (RTL / Align Right do not apply).

HOW THE TRANSLATION WORKS
  • The app tries to keep the layout algorithm of the reference document: every translated paragraph is put back
    at the position of the original paragraph; images, figures, tables, lines and page numbers stay where they are.
  • Only the text is translated. Heading / body font sizes, bold, italic, colours, line spacing
    of paragraphs follow the original document.
  • As far as possible, technical terms, proper names, acronyms, units, formulas, identifiers, code and
    citations are NOT translated – they are copied exactly as they are, with the font and size of the
    original document.
  • Equations: a displayed equation stays exactly where it is, untouched. Maths inside a sentence (Greek letters,
    indices, small formulas) is kept as it is and moves with the translated sentence.
  • Machine translation can contain mistakes. Always proof-read before you publish or print.

QUICK START
  1. Files:   choose the input PDF (a book with selectable text) and an output folder.
              Tip: test first with a page range such as 1-10.
  2. Output:  tick one or more output formats – PDF, Text (.txt). (Doc / .docx: coming soon.)
  3. Languages:  tick the origin language of the file and the target language (English, Persian, German,
              French, Spanish – in both directions).
  4. Engine and fonts:  choose the AI model, the Heading font and the Body font, and the font-size factor.
  5. Click "RUN". One file per language and format is written into the folder you chose:
              Translated_to_fa__<original name>.pdf   .docx   .txt
              (a page selection adds  _pages_3-6  to the name)
     If a file with this name is open in another program, the app asks before it starts and saves the result
     with an index (_01, _02 …) – a finished translation is never lost.
     If the folder path is very long, the file name is shortened automatically: Windows programs can not open a
     path of more than 260 characters.

OUTPUT FORMATS
  PDF    The original pages with the translated text typeset at the position of the original text.
  Doc    (coming soon – switched off in this version)  A Word document (.docx): same reading order, same pictures, same relative font sizes and styles.
         Persian paragraphs are Right-To-Left and Align Right. Word shows the fonts that are installed on
         the computer that opens the file – install the chosen fonts there.
         Two-column pages stay two-column (the columns are detected automatically; Persian: right column first).
         Tables, figures and every displayed equation (with its number) are sharp pictures of the original; hard
         maths inside a sentence (Greek letters, integrals, indices …) is a picture put where the translation needs it.
  Text   Plain UTF-8 text, paragraph by paragraph.

LANGUAGES
  Origin Language   English, Persian, German, French or Spanish – the language of the input file.
  Target Language   one of the same five languages (not the same as the origin).
  English → Persian is the pair this app was built and tested for. The other pairs work with the same engine but
  are newer:
    • For an origin other than English the lists of English technical terms, the English heading table and the
      "Capitalized = name" rule are switched off (German writes every noun with a capital letter, Persian has no
      capitals). Formulas, numbers, acronyms and code are still kept.
    • Persian → another language: everything is mirrored the other way round – the text runs left to right, a
      paragraph that started at the right starts at the left, two columns change places, Persian digits become
      0-9. The Persian PDF must contain real text (a PDF whose text can not be copied correctly in a PDF viewer
      can not be translated; PDFs written by this app are of that kind).
    • German, French, Spanish and English targets use the fonts of the original document or a Latin font you
      choose, with automatic hyphenation.

TRANSLATION ENGINES (section 3)
  Built-in · MADLAD / NLLB   The translation models that run inside this app. Offline, nothing to install.
                             They translate sentence by sentence and can not be given instructions.
  Ollama · local LLM         A large language model on this computer (free, offline). Install Ollama from
                             https://ollama.com , then download a model once, for example
                                 ollama pull gemma3:12b      (better Persian, needs about 10 GB of memory)
                                 ollama pull gemma3:4b       (smaller and faster, weaker)
                             "List models" shows the models that are installed. Gemma is usually the stronger
                             choice for Persian; Qwen is strong for English, Chinese and technical text. On a
                             computer without a graphics card a large model is slow.
  Online API                 Any service that speaks the OpenAI chat protocol. Type the server address, the model
                             name and your own API key. Fast and of high quality, but the text of the document
                             is sent to that service and the service may charge for it. The key is stored only
                             in the settings file in the app data folder.
  With Ollama and the online API whole paragraphs are translated in their context, and your Glossary and "My
  instructions" are written into the prompt – so free instructions such as "use a formal tone" work as well.
  Page layout, parts, cache, review and all checks are the same for every engine. "Best quality" belongs to the
  built-in engine only.

FONTS
  Heading, Title, Subtitle Font   used for headings, titles and subtitles.
  Body Text Font                  used for body text, captions, lists and footnotes.
  • Next to each font a sample is shown, so you can see how it looks – like the font box of Microsoft Word.
  • With Persian as target, both fonts are set to B Yaghout automatically.
  • Available fonts include: B Yaghout, B Yagut, Yaghout, B Lotus, B Titr, B Jadid, Jadid, B Mitra, Mitra,
    IranSans, B Nazanin, B Yekan, Vazirmatn, Sahel, Shabnam, Samim, Parastoo, Tanha, Gandom, Nahid, Estedad,
    Lalezar, Amiri, Lateef and more, or "Custom font file…" for any .ttf / .otf file.
  • The "B …" fonts and IranSans are commercial fonts: they must be installed on the computer (or their .ttf
    files copied into the folder  {FONT_DIR}  or a "fonts" folder next to this script). If a chosen font is
    not found, the app uses a free replacement (Vazirmatn or a system font) and tells you in the log.
  • Free fonts (Vazirmatn, Sahel, …) are downloaded once if they are missing and the internet is available.
  • Terms that are not translated keep the font and the size of the original document.

FONT-SIZE FACTOR
  100 % (default): every translated heading, subheading, body line and caption has exactly the size of the
  original text it replaces (for example 18 / 16 / 12 / 10 pt stay 18 / 16 / 12 / 10 pt).
  80 %: all sizes become 80 % of the original, in the same proportion. 120 %: all sizes become 120 %.
  (Not translated terms keep their original size.)

DIRECTION AND ALIGNMENT
  English is written left-to-right, Persian right-to-left, so the layout is mirrored:
  • Right-To-Left Direction   the translated text runs from right to left.
  • Align Right               an "Align Left" paragraph or heading of the original becomes "Align Right".
  • The translated paragraphs start without a first-line indent ("Tab"). Centred and justified paragraphs stay
    centred / justified.
  Both options are ON for Persian.

WHAT IS TRANSLATED – AND WHAT IS NOT
  Translated : running text, headings, captions, list items, footnotes (paragraph by paragraph), bookmarks.
  Kept as is : images, figures and their labels, tables, code blocks, formulas, page numbers, URLs, contents
               lines, and everything from the first "References / Bibliography / Appendix / Glossary / Index"
               heading (searched in the last 60 % of the book) to the end.

★★★  HOW TO TEACH THE APP  ("My instructions")  ★★★
  The app learns from you. Open "My instructions" (top right), write what you want and press Add – in English or
  Persian. Every instruction is remembered and used in ALL later translations:
      Object-specific distance estimation = تخمین فاصله مختص به یک شیء خاص      always translate it like this
      translate backbone as ستون فقرات      /      patch را وصله ترجمه کن             the same, as a sentence
      don't translate LiDAR                 /      LiDAR را ترجمه نکن                 stays in English
      translate image                       /      image را ترجمه کن                  is always translated
  • The app works out by itself whether an instruction is a translation (Persian or German), "keep" or
    "translate". The newest instruction about a word wins. You can edit or delete the stored lines.
  • Before every translation the app looks through the pages for your instructions and applies them.
  • "Review terms before start" (Options): after you click Start, the app shows – with a sound – every technical
    term it found in THIS file and wants to keep in English. Delete a line = translate this word from now on;
    add a line = keep this word in English from now on. "Save and start" stores your changes for later jobs too.
  • The instructions are stored in  {INSTRUCTIONS_FILE}

THE APP DATA FOLDER
  Everything the app remembers is in ONE folder:   {APP_DIR}
      settings.json            the settings of the window (File → Settings)
      history.json             the files you translated (File → History)
      user_instructions.txt    "My instructions"
      glossary.txt             your own terms (Glossary button)
      Bulky_Translotor_Terminology   one term list per field (Chemistry, AI …) – reused by later jobs
      timing_history.json      how long earlier translations took (for the remaining-time estimate)
      cache                    every translated sentence (a sentence is never translated twice)
      jobs                     the finished parts of a job that is running or was interrupted
      fonts, models            downloaded fonts and the translation model
  File → Settings → "Open the app data folder" opens it.

FILE MENU
  New        empties the input, the output folder and the log – all settings stay as they are.
  History    every translation started with version 2.8 or newer, newest first (finished / not finished); show
             the input or the translated file in its folder.
  Settings   save the current settings as defaults, reset them, open the app data folder.
  Exit       closes the app (it always asks first).

PARTS, CACHE AND CONTINUING AN INTERRUPTED JOB
  • The pages are translated and typeset 2 pages at a time (one "part"): 15 pages = 8 parts (7 × 2 pages + 1).
  • The output file is created after the FIRST part and updated after every part, so the pages that are finished
    are already in the output folder if an error happens or the computer goes off. (If you keep that file open in
    a program that locks it, the update waits until the end.)
  • One status line shows where the job is:   Page 007 / 034 · Part 4 of 17 · Status: translating …
  • If the app is closed, the computer is switched off or you cancel: the finished parts stay. When the app is
    opened again it offers to continue; starting the same job again also continues after the last finished part.

TRANSLATE WITH REVIEW
  Tick "Translate with review" next to RUN. After every part (2 pages) the translation stops and the Review window
  shows the pages exactly as they will be saved.
  Tool "Text blocks":
    • Click a text block on the page (or in the list) to choose it. Every block has a thin frame.
    • Change its words in the editor. Only the words you change are typeset again – the other words, the formulas,
      English terms, fonts and sizes stay exactly as they were. New words get the font and size of the text around
      them.
    • "Size %", Bold, Italic, Heading font and Align change the whole block.
    • Drag the block with the mouse to another place, or use ▲ ▼ ◄ ► (3 pt per click) and Width − / +. A green
      frame shows the new place; "Back to its place" undoes the move.
    • "Insert symbol": one click puts a maths symbol, a Greek letter, an arrow or a unit sign at the cursor
      (± × ÷ ≤ ≥ ≠ ≈ ∞ √ ∑ ∫ ∂ ∈ → α β θ λ μ π σ ω Δ Ω ° ² ³ …). Symbols are typeset with the maths font.
  Tool "Area" – for everything that is not a text block (pictures, tables, lines, a row of a table, a caption):
    • Draw a frame around the thing with the mouse, then drag the frame to the new place. The red frame is what is
      cut out, the green frame is where it is pasted.
    • "Erase the framed area" removes what is inside the frame. "Undo last area" takes the last one back.
    • Several areas can be moved one after the other.
  Buttons:  Save = typeset the part again and show the result (you can go on editing) · Next part = store the
  changes and continue · Cancel = keep the part as it is and continue.
  More layout tools:
    • Enter in the editor starts a new line (twice: an empty line), so a paragraph can be cut in two or a long line
      shortened. Several spaces typed between two words stay several spaces.
    • "Selected words": select some words in the editor, then A− / A+ (smaller / bigger), B (bold), I (italic) or
      Normal. Only these words change.
    • "Line spacing %" changes the distance between the lines of the block.
    • "Height − / +" gives the block less or more room; everything below it on the page (text, pictures, formulas)
      moves up or down with it.
    • Tool "Space": click between two lines of the page to insert room there (positive points) or to remove room
      (negative points). Everything below the click moves - in the whole width, or "only this column". A click
      inside a picture inserts the room above the picture. "Undo last space" takes it back.
    • Room and moved blocks are not held back by the page margins.
  Limits: it is a simple editor, not a layout program. A block keeps its rectangular shape and an area is moved as
  a whole.
  Remove the tick at any time: from then on the parts are finished without stopping.

QUICK TRANSLATE
  The green button "Quick translate" at the top opens a small window without a title bar: drag its top strip to
  move it, the corner at the bottom right makes it as small as you like (the two text boxes go one above the
  other in a narrow window). Type, paste or speak a text on the left (up to 5000 characters); the translation
  appears on the right a moment after you stop (Ctrl+Enter translates at once). Persian is typed right-to-left
  like in any Windows program. "Detect language" finds the language by itself; ⇄ swaps languages and texts.
  The built-in engine starts loading as soon as the window opens (10 s to 2 minutes, the first time longer), so
  it is usually ready when you have finished typing; Ollama and the online API answer at once.
  Icons at the top: 📝 saves every translation (original + translation, with the time) in a text file of the
  day in Documents\\DeepTome\\Quick translations · 📂 opens that folder · 📌 keeps the window on top · — hides it
  (open it again with "Quick translate") · 🎬 Live starts Live translation.
  🔊 reads a text aloud, ■ stops, "slow" reads slower, 🗣 chooses the voices. 🎤 types what you say, without a
  time limit, until you click it again (offline speech recognition; without it Windows voice typing, Win+H).

LIVE TRANSLATION (🎬)
  The window becomes two thin strips that stay on top of every window: the upper strip shows what is heard, the
  lower one its translation, sentence by sentence while the film, the video, the lecture or the call goes on.
  Old words slide out of the strip - to the left for English, to the right for Persian. Small buttons: ⤢ back to
  the normal window (to change the languages), ⏸ pause, 🔈/🎤 the sound of this computer or the microphone,
  Σ summary (every sentence as short as possible: fillers, repetitions and side remarks are left out),
  💾 saves original and translation in a text file of the day (Documents\\DeepTome\\Live translations): every
  session starts with a framed title, the date and the start time, every sentence has its time.

SUBTITLE FILES
  Choose an .srt, .vtt, .ass, .ssa, .sbv or .sub file instead of a PDF. The app says that it is a subtitle file,
  switches the output to a subtitle file of the same kind and translates only the spoken text: cue numbers,
  times, styles, positions and tags stay exactly as they are, so the subtitle stays in sync. Sentences that run
  over two or three cues are translated as one sentence and shared out again; two speakers in one cue are
  translated line by line.

SETTINGS (⚙)
  Components: everything the translator can use - engine, models, Ollama, voices, speech recognition, data
  folders - with its status (installed / not installed), size and use. Select a line: Install / Remove with one
  click. Voices: the voice of every language - offline (Piper, no internet), online (Microsoft Edge, the most
  natural) or Windows - with ▶ Test. Speech recognition: model size and one-click installation. System
  information: computer, folders and package versions.

LANGUAGES THAT ARE NOT SUPPORTED YET
  A file in another language (Arabic, Russian, Chinese, Italian …) is recognised and refused with a message: for
  now the app translates from English, Persian, German, French and Spanish only. If the language was recognised
  wrongly, set it with "wrong?".

LANGUAGE OF THE FILE
  The app reads the file and finds its language by itself (Persian by its letters, the other languages by their
  most frequent words); "wrong?" next to it corrects it. If the origin is not English, the technical terms shown
  before the start are the terms of that language: for each you decide whether it stays as it is, is translated
  by the engine, or always gets your own translation in the target language.
  A PDF whose text comes out as wrong characters when it is copied (fonts without a correct character table) is
  marked "text layer damaged": it can not be translated correctly. Persian PDFs written by DeepTome before
  version 3.4 are of this kind - newer ones keep a readable text layer.

TWO-COLUMN PAGES IN PERSIAN
  Persian is read from the right, so on two-column pages the two columns change places: the first column is the
  right one. Titles, figures, tables and equations that span both columns stay where they are. Option "Swap the
  2 columns (Persian)".

WORKLOAD CHART
  The dark chart above the log is drawn while the file is translated, like a heart monitor. From left to right
  are the pages of the job (every page is cut into 8 slices from top to bottom); the height shows how heavy a
  slice is. The dotted blue line is the amount of text that is waiting, the bright green line is the time that
  was really spent. A high peak in the middle of page 8 means: the middle of page 8 is the heavy part.
  Four pages are visible at a time and the chart moves on with the work. Drag it with the mouse (or turn the
  wheel) to look at earlier pages; a double-click makes it follow the work again.

SOUNDS
  After every finished part the Windows sound "NFP Completion" is played, "Alarm06" when the whole file is
  ready, and "Pop-up Blocked" when Cancel is clicked. The loudspeaker button next to Cancel switches the sounds off and on (it also stops a sound that is
  playing). The choice is remembered.

TITLE, NAMES OF PERSONS, MARGIN NOTES
  • The title of the article or book is translated, and the original title is printed under it in a smaller size
    (option "English heading in brackets"). Section headings keep the form  "1 مقدمه (Introduction)".
  • Lines that only list persons (authors, "Edited by Dr. …", "Academic Editors: …") are copied as they are.
    A translation model replaces names it does not know by famous names, so names are never sent to it.
  • Notes in the page margin (citation box, dates, licence text of a journal) are copied as they are.
  • Short lines of a few words are translated with a wider search, and a result that invents words, changes a
    number or repeats itself is thrown away and translated again.

LONG FILES
  • A file of more than {MAX_FILE_PAGES} pages is not accepted. Split it into smaller PDF files first.
  • More than {SPLIT_PAGES} pages on a slow computer (4 processor cores or fewer, or less than 12 GB of memory) with PDF
    output: the app tells you before it starts, and then saves one PDF file for every {SPLIT_PAGES} pages – for example 112
    pages become 6 files (5 × 20 pages and 1 × 12 pages):
        …_file01of06_pages_1-20.pdf ,  …_file02of06_pages_21-40.pdf  …
    Each file is complete as soon as its pages are done, and the next 20 pages start automatically. With the
    online API engine this is not done, because the translation does not run on this computer.

REMAINING TIME
  The remaining time is an estimate. It counts the words that are still to translate (pages differ a lot: a page
  of text, a page of figures) and multiplies them by the seconds per word measured in this job. During the first
  pages, before enough is measured, the average of your earlier translations is used, so the first minutes are
  the least exact. Pages that come from the cache take almost no time.

TICK BOXES AND LANGUAGES
  A tick box is switched on when a blue square is inside it. In section 2 exactly one origin and one target
  language are chosen; the language chosen in one row is greyed out in the other row.

TEXT SPECIALTY (section 5)
  Type the field of the text, for example:  Chemistry, Medical, History, Technical, Deep Learning, AI
  • You can write up to 4 fields, separated by commas ( , ). A space after a comma is removed automatically.
  • The app searches the internet (Hugging Face, Kaggle, Wikipedia) for the specialist names and terms of these
    fields and copies them unchanged – they are not translated.
  • "Also detect the subject of the book automatically": the app reads the book itself, works out what it is about
    (for example artificial intelligence) and downloads the matching terms in the same way.
  • The downloaded term lists are stored in  {TERM_DIR}  (one .txt file per field, refreshed after 30 days), so
    they are available offline afterwards. You may add your own terms there or in the Glossary.
  • Kaggle needs a free API key (file ~/.kaggle/kaggle.json); without it Kaggle is skipped.

TECHNICAL TERMS AND NAMES STAY AS THEY ARE
  • Proper names and specialist words that start with a capital letter inside a sentence (Python, Kaggle,
    Newton) are copied unchanged. Compound names whose words all start with capitals (Hugging Face,
    Convolutional Neural Network) are always treated as specialist terms and are not translated.
  • About 600 built-in technical terms (electronics, control, communications, computing, ML, mechanics,
    thermodynamics, civil engineering …).
  • Kept automatically: acronyms (PID, FFT, CMOS), numbers with units (5 kHz, 10 mA, 3.3 V), identifiers
    (snake_case, camelCase, func()), part numbers (LM741, RS-485, 802.11n), citations [12], URLs, formulas and
    Greek / maths symbols.
  • "Glossary" button: add your own terms (one per line). They are stored in  {GLOSSARY_FILE}.

THE TRANSLATION ENGINE (open source, offline)
  • MADLAD-400 3B (Google, Apache-2.0)   best quality here. One-time download ≈ 12 GB, converted to a fast 8-bit
    format (≈ 3 GB), afterwards 100 % offline. Needs ≈ 16 GB RAM for the one-time conversion.
  • NLLB-200 1.3B / 600M (Meta, CC-BY-NC – non-commercial use)   smaller and faster.
  • "Folder…" lets you use a model folder that is already on your disk – then nothing is downloaded.
  Install once:   pip install pymupdf fonttools python-docx ctranslate2 transformers sentencepiece protobuf accelerate torch
  Speed: a CPU needs minutes per 10 pages with MADLAD-3B; a GPU is much faster. Translations are cached on
  disk ({CACHE_DIR}), so an interrupted job resumes.
  If huggingface.co is blocked, set HF_ENDPOINT to a mirror, or download the model folder in another way and
  select it with "Folder…".

OPTIONS
  Pages                    Limit the job to some pages, e.g. "1-30, 45". Empty = whole book.
  Auto-shrink limit        Only used when a translation is longer than the original text and does not fit:
                           the text is shrunk automatically, but never below this percentage (50 % = at most
                           half size). This is different from the Font size factor, which scales ALL text.
  Terms and headings      Common technical words (image, algorithm, neural network …) are translated with a built-in
                           glossary: the first use is written "فارسی (English)", later uses only in Persian. Standard
                           headings (Abstract, Introduction, Related work, Conclusion, References …) come from a fixed
                           table. Only acronyms, names, formulas, units, identifiers and citations stay in English.
                           Own entries: put lines such as   neural network = شبکهٔ عصبی   into glossary.txt.
  Speed                    The translation model itself is the slow step: on an older laptop CPU it writes only a
                           few words per second, so a dense page needs minutes – the same per page for 2 pages
                           or 200. The app uses one thread per real CPU core and fast decoding by default.
                           "Best quality (2× slower)" switches to beam search. A smaller model (NLLB-200 600M) is
                           several times faster with lower quality. Pages already translated come from the cache.
  Translation mode         Accurate (default): full page layout.  Fast: very quick, only the
                           text is translated and written to a .txt file (no typesetting).
  Remaining time           Shown at the right of the status line and counted down. It is estimated from the
                           average of all previous translations on this computer and from the speed of the
                           running job, and becomes more accurate over time.
  Log                      Every line starts with its time (hh:mm:ss). All text in the log can be selected and
                           copied (Ctrl+C, or right-click → Copy; with nothing selected the whole log is copied).
  English heading in brackets   Sub-headings are written in Persian with the English original in brackets, e.g.
                           "5 نتیجه‌گیری (Conclusion)" (Persian only, for the target language Persian).
  Justify body text        All body paragraphs are justified (headings, titles and captions are not).
  Pages                    "41-44" translates ONLY pages 41 to 44 and the result has exactly these 4 pages.
  Formulas, tables, graphs  Never translated. In the PDF they stay exactly as they are; in the Word file they are
                           pictures of the original (high quality, cut out without their captions, which are
                           translated) at the original place.
  Front matter             Authors, affiliations, e-mails, publisher / copyright data, cover pages and running
                           headers are names and data: they are kept as they are.
  Back-matter keywords     Headings that start the untranslated back matter (comma separated).
  Keep … unchanged         Figure labels and code blocks. Tables and references / appendices are kept as they
                           are unless you tick "Translate inside tables" / "Translate references / appendices".
                           Captions and bookmarks are translated unless you tick "Don't translate …".
  Changing settings        A running job uses the settings it was started with; changing a setting during a job
                           has no effect on it (only "Translate with review" can be switched on / off).
  Persian digits           Use Persian digits (۰۱۲۳) in the translation.

LIMITATIONS
  • The PDF must contain real text. Scanned books need OCR first (e.g. OCRmyPDF).
  • Table, figure and code detection is heuristic. If something is wrongly translated or skipped, use the options
    or the page range and run again. Always review the first chapters.
  • An emphasised stretch longer than {MAX_STYLED_WORDS} words inside a sentence is translated as its own segment.
  • Respect the copyright of the book you translate.

{APP_COPYRIGHT}

Contact me:
{GITHUB}
{LINKEDIN}
{EMAIL}
""".rstrip() + "\n"


# ════════════════════════════════════════════════════════════════════════════
#  GUI
# ════════════════════════════════════════════════════════════════════════════
FONT_SAMPLES_FA: List[str] = ['امروز هوا بسیار خوب است', 'کتاب را روی میز گذاشتم', 'او هر روز صبح می\u200cدود', 'این یک متن آزمایشی است', 'آب و هوای شهر ما معتدل است', 'دانش\u200cآموزان در کلاس هستند', 'من چای داغ دوست دارم', 'پرنده\u200cها بر شاخه\u200cها آواز می\u200cخوانند', 'فردا به کتابخانه می\u200cرویم', 'مهندسی علم ساختن است', 'خورشید از شرق طلوع می\u200cکند', 'دریا آرام و آبی بود', 'این کتاب بسیار مفید است', 'برنامه\u200cنویسی هنر حل مسئله است', 'ما به آینده امیدواریم', 'باران آرام می\u200cبارید', 'او پزشک مهربانی است', 'قطار ساعت هشت حرکت می\u200cکند', 'یادگیری هرگز دیر نیست', 'کوه\u200cها پوشیده از برف\u200cاند', 'صبحانه نان و پنیر خوردم', 'هوش مصنوعی همه\u200cجا هست', 'لطفاً در را ببندید', 'شب\u200cهای تابستان کوتاه\u200cاند', 'من یک کتاب تازه خریدم', 'علم، کلید پیشرفت است', 'گل\u200cها در باغ شکفتند', 'او نامه\u200cای نوشت', 'کودکان در پارک بازی می\u200cکنند', 'پل روی رودخانه ساخته شد', 'ترجمه یعنی انتقال معنا', 'استاد درس را توضیح داد', 'شهر در شب زیبا بود', 'موتور به آرامی کار می\u200cکند', 'این مدار ولتاژ را کم می\u200cکند', 'داده\u200cها دقیق بررسی شدند', 'هر فصل با یک مثال شروع می\u200cشود', 'ما نتیجه را مقایسه کردیم', 'آزمایش با موفقیت انجام شد', 'پنجره را باز کن', 'درخت\u200cهای کهن سایه می\u200cاندازند', 'زندگی زیباست', 'سفر ما دو ساعت طول کشید', 'او با دقت گوش داد', 'فهرست مطالب در ابتدای کتاب است', 'نقشه را به دقت ببین', 'صدای موسیقی از دور می\u200cآمد', 'همه چیز آماده است', 'ساعت دقیقاً سه است', 'کار تیمی موفقیت می\u200cآورد']
FONT_SAMPLES_EN: List[str] = ['The weather is very nice today', 'I put the book on the table', 'She runs every morning', 'This is a test sentence', 'The quick brown fox jumps', 'Students are in the classroom', 'I like hot tea in winter', 'Birds sing on the branches', 'We go to the library tomorrow', 'Engineering is the art of building', 'The sun rises in the east', 'The sea was calm and blue', 'This book is very useful', 'Programming is problem solving', 'We are hopeful for the future', 'The rain fell softly', 'He is a kind doctor', 'The train leaves at eight', 'It is never too late to learn', 'The mountains are covered in snow', 'I had bread and cheese', 'Artificial intelligence is everywhere', 'Please close the door', 'Summer nights are short', 'I bought a brand new book', 'Science is the key to progress', 'Flowers bloomed in the garden', 'She wrote a long letter', 'Children play in the park', 'A bridge was built over the river', 'Translation carries meaning', 'The teacher explained the lesson', 'The city looks lovely at night', 'The engine runs smoothly', 'This circuit reduces the voltage', 'The data were checked carefully', 'Each chapter starts with an example', 'We compared the results', 'The experiment was successful', 'Open the window please', 'Old trees cast long shadows', 'Life is beautiful', 'Our trip took two hours', 'He listened with care', 'The contents are at the front', 'Look at the map carefully', 'Music came from far away', 'Everything is ready now', "It is exactly three o'clock", 'Teamwork brings success']


FONT_SAMPLES_DE: List[str] = ["Das Wetter ist heute sehr schön", "Ich lege das Buch auf den Tisch", "Sie läuft jeden Morgen",
                              "Dies ist ein Testsatz", "Die Schüler sind im Klassenzimmer", "Ich trinke gern heißen Tee",
                              "Die Vögel singen auf den Ästen", "Morgen gehen wir in die Bibliothek",
                              "Technik ist die Kunst des Bauens", "Die Sonne geht im Osten auf",
                              "Das Meer war ruhig und blau", "Dieses Buch ist sehr nützlich",
                              "Wir sind voller Hoffnung", "Es regnete leise", "Der Zug fährt um acht Uhr ab",
                              "Lernen ist nie zu spät", "Große Brücken über Flüsse", "Übung macht den Meister",
                              "Die Straße führt zum Bürogebäude", "Äpfel, Öl und Süßigkeiten"]


# ════════════════════════════════════════════════════════════════════════════
#  Illustrated quick guide (Help window) – English, Persian, German, French, Spanish
# ════════════════════════════════════════════════════════════════════════════
GUIDE_LANGS = {"en": "English", "fa": "فارسی", "de": "Deutsch", "fr": "Français", "es": "Español"}
GUIDE_UI = {
    "en": ("Quick guide (with pictures)", "Full reference (English)", "Language of the guide:"),
    "fa": ("راهنمای سریع (تصویری)", "مرجع کامل (انگلیسی)", "زبان راهنما:"),
    "de": ("Kurzanleitung (mit Bildern)", "Vollständige Referenz (Englisch)", "Sprache der Anleitung:"),
    "fr": ("Guide rapide (illustré)", "Référence complète (anglais)", "Langue du guide :"),
    "es": ("Guía rápida (ilustrada)", "Referencia completa (inglés)", "Idioma de la guía:"),
}
# every step: key of its picture, then {language: (title, text)}
GUIDE_STEPS: List[Tuple[str, Dict[str, Tuple[str, str]]]] = [
    ("files", {
        "en": ("1 · Choose the file",
               "Click “Browse…” and choose the PDF. Then choose the folder for the result. The app reads the file "
               "and shows its language, the number of pages and about how many tokens it has. You may translate "
               "only some pages, for example 1-10. Files of more than 700 pages are not accepted."),
        "fa": ("۱ · انتخاب فایل",
               "روی «Browse…» کلیک کنید و فایل PDF را انتخاب کنید. سپس پوشهٔ ذخیرهٔ خروجی را مشخص کنید. برنامه فایل "
               "را می‌خواند و زبان آن، تعداد صفحات و تعداد تقریبی توکن‌ها را نشان می‌دهد. می‌توانید فقط بعضی صفحات "
               "را ترجمه کنید، مثلاً 1-10. فایل‌های بیش از ۷۰۰ صفحه پذیرفته نمی‌شوند."),
        "de": ("1 · Datei wählen",
               "Klicken Sie auf „Browse…“ und wählen Sie die PDF-Datei, danach den Ordner für das Ergebnis. Die App "
               "liest die Datei und zeigt ihre Sprache, die Seitenzahl und die ungefähre Anzahl der Tokens. Sie "
               "können auch nur einige Seiten übersetzen, z. B. 1-10. Dateien mit mehr als 700 Seiten werden "
               "nicht angenommen."),
        "fr": ("1 · Choisir le fichier",
               "Cliquez sur « Browse… » et choisissez le PDF, puis le dossier du résultat. L’application lit le "
               "fichier et affiche sa langue, le nombre de pages et le nombre approximatif de tokens. Vous pouvez "
               "ne traduire que certaines pages, par exemple 1-10. Les fichiers de plus de 700 pages sont refusés."),
        "es": ("1 · Elegir el archivo",
               "Haga clic en «Browse…» y elija el PDF; después, la carpeta del resultado. La aplicación lee el "
               "archivo y muestra su idioma, el número de páginas y la cantidad aproximada de tokens. Puede "
               "traducir solo algunas páginas, por ejemplo 1-10. No se aceptan archivos de más de 700 páginas."),
    }),
    ("langs", {
        "en": ("2 · Choose the target language",
               "The origin language is found automatically. Tick the language you want: Persian, German, French, "
               "Spanish or English. The language of the file itself is greyed out. If the app guessed the origin "
               "wrongly, click “wrong?” next to it."),
        "fa": ("۲ · انتخاب زبان مقصد",
               "زبان مبدأ خودکار تشخیص داده می‌شود. زبان دلخواه را تیک بزنید: فارسی، آلمانی، فرانسوی، اسپانیایی یا "
               "انگلیسی. زبانِ خودِ فایل خاکستری و غیرقابل انتخاب است. اگر برنامه زبان مبدأ را اشتباه تشخیص داد، روی "
               "«wrong?» در کنار آن کلیک کنید."),
        "de": ("2 · Zielsprache wählen",
               "Die Ausgangssprache wird automatisch erkannt. Markieren Sie die gewünschte Sprache: Persisch, "
               "Deutsch, Französisch, Spanisch oder Englisch. Die Sprache der Datei selbst ist ausgegraut. Wurde "
               "die Ausgangssprache falsch erkannt, klicken Sie daneben auf „wrong?“."),
        "fr": ("2 · Choisir la langue cible",
               "La langue d’origine est détectée automatiquement. Cochez la langue voulue : persan, allemand, "
               "français, espagnol ou anglais. La langue du fichier est grisée. Si la langue d’origine est mal "
               "détectée, cliquez sur « wrong? » à côté."),
        "es": ("2 · Elegir el idioma de destino",
               "El idioma de origen se detecta automáticamente. Marque el idioma deseado: persa, alemán, francés, "
               "español o inglés. El idioma del propio archivo aparece en gris. Si el origen se detectó mal, haga "
               "clic en «wrong?» a su lado."),
    }),
    ("engine", {
        "en": ("3 · Engine and fonts",
               "Built-in: works offline, nothing to set. Ollama: a language model on your computer – choose the "
               "model with “List models”. Online API: type the address, the model name and your own key; fast, "
               "but the text is sent to that service. Below, choose the heading font, the body font and the font "
               "size factor."),
        "fa": ("۳ · موتور ترجمه و فونت‌ها",
               "Built-in: آفلاین کار می‌کند و تنظیمی لازم ندارد. Ollama: یک مدل زبانی روی کامپیوتر خودتان – مدل را "
               "با «List models» انتخاب کنید. Online API: آدرس سرور، نام مدل و کلید خودتان را وارد کنید؛ سریع است، "
               "اما متن به آن سرویس فرستاده می‌شود. پایین‌تر فونت تیتر، فونت متن و ضریب اندازهٔ فونت را انتخاب کنید."),
        "de": ("3 · Übersetzungs-Engine und Schriften",
               "Built-in: arbeitet offline, nichts einzustellen. Ollama: ein Sprachmodell auf Ihrem Computer – "
               "wählen Sie das Modell mit „List models“. Online API: Adresse, Modellname und eigener Schlüssel; "
               "schnell, aber der Text wird an diesen Dienst gesendet. Darunter: Überschriften-Schrift, "
               "Textschrift und Schriftgrößenfaktor."),
        "fr": ("3 · Moteur et polices",
               "Built-in : fonctionne hors ligne, rien à régler. Ollama : un modèle de langue sur votre "
               "ordinateur – choisissez-le avec « List models ». Online API : adresse, nom du modèle et votre "
               "propre clé ; rapide, mais le texte est envoyé à ce service. En dessous : police des titres, police "
               "du texte et facteur de taille."),
        "es": ("3 · Motor y fuentes",
               "Built-in: funciona sin conexión, nada que ajustar. Ollama: un modelo de lenguaje en su equipo; "
               "elíjalo con «List models». Online API: dirección, nombre del modelo y su propia clave; rápido, "
               "pero el texto se envía a ese servicio. Debajo: fuente de títulos, fuente del texto y factor de "
               "tamaño."),
    }),
    ("options", {
        "en": ("4 · Options",
               "A box with a blue square is switched on. The defaults are good for a scientific article: technical "
               "terms, names, formulas, figure labels and code stay as they are; tables and references are not "
               "translated. Section 5 (Text specialty) is optional: type the field of the text, e.g. Chemistry, AI."),
        "fa": ("۴ · گزینه‌ها",
               "خانه‌ای که مربع آبی دارد روشن است. پیش‌فرض‌ها برای مقالهٔ علمی مناسب‌اند: اصطلاحات فنی، نام‌ها، "
               "فرمول‌ها، برچسب شکل‌ها و کدها دست‌نخورده می‌مانند؛ جدول‌ها و مراجع ترجمه نمی‌شوند. بخش ۵ (تخصص متن) "
               "اختیاری است: رشتهٔ متن را بنویسید، مثلاً Chemistry, AI."),
        "de": ("4 · Optionen",
               "Ein Kästchen mit blauem Quadrat ist eingeschaltet. Die Vorgaben passen für einen wissenschaftlichen "
               "Artikel: Fachbegriffe, Namen, Formeln, Abbildungsbeschriftungen und Code bleiben unverändert; "
               "Tabellen und Literaturverzeichnis werden nicht übersetzt. Abschnitt 5 (Fachgebiet) ist optional, "
               "z. B. Chemistry, AI."),
        "fr": ("4 · Options",
               "Une case avec un carré bleu est activée. Les réglages par défaut conviennent à un article "
               "scientifique : termes techniques, noms, formules, légendes de figures et code restent tels quels ; "
               "tableaux et références ne sont pas traduits. La section 5 (spécialité) est facultative, "
               "p. ex. Chemistry, AI."),
        "es": ("4 · Opciones",
               "Una casilla con un cuadrado azul está activada. Los valores por defecto sirven para un artículo "
               "científico: términos técnicos, nombres, fórmulas, rótulos de figuras y código quedan como están; "
               "tablas y referencias no se traducen. La sección 5 (especialidad) es opcional, p. ej. Chemistry, AI."),
    }),
    ("run", {
        "en": ("5 · Start",
               "Press the green RUN button. “Best quality” is about two times slower (built-in engine). “Review "
               "terms before start” shows the technical terms the app found, so you can decide which ones stay in "
               "the original language. The loudspeaker button switches the sounds off. Cancel stops the job; the "
               "finished parts stay in the cache."),
        "fa": ("۵ · شروع",
               "دکمهٔ سبز RUN را بزنید. «Best quality» حدود دو برابر کندتر است (موتور داخلی). «Review terms before "
               "start» اصطلاحات فنی پیداشده را نشان می‌دهد تا تصمیم بگیرید کدام‌ها به زبان اصلی بمانند. دکمهٔ "
               "بلندگو صداها را قطع می‌کند. Cancel کار را متوقف می‌کند؛ بخش‌های تمام‌شده در حافظهٔ موقت می‌مانند."),
        "de": ("5 · Starten",
               "Drücken Sie die grüne Taste RUN. „Best quality“ ist etwa doppelt so langsam (eingebaute Engine). "
               "„Review terms before start“ zeigt die gefundenen Fachbegriffe, damit Sie entscheiden, welche in "
               "der Originalsprache bleiben. Die Lautsprecher-Taste schaltet die Töne aus. Cancel bricht ab; "
               "fertige Teile bleiben im Cache."),
        "fr": ("5 · Démarrer",
               "Appuyez sur le bouton vert RUN. « Best quality » est environ deux fois plus lent (moteur intégré). "
               "« Review terms before start » montre les termes techniques trouvés, pour décider lesquels restent "
               "dans la langue d’origine. Le bouton haut-parleur coupe les sons. Cancel arrête le travail ; les "
               "parties terminées restent en cache."),
        "es": ("5 · Iniciar",
               "Pulse el botón verde RUN. «Best quality» es aproximadamente dos veces más lento (motor "
               "integrado). «Review terms before start» muestra los términos técnicos encontrados para decidir "
               "cuáles quedan en el idioma original. El botón del altavoz apaga los sonidos. Cancel detiene el "
               "trabajo; las partes terminadas quedan en la caché."),
    }),
    ("watch", {
        "en": ("6 · While it works",
               "The status line shows the page, the part and the remaining time (an estimate). The Workload chart "
               "shows four pages at a time: the dotted line is the text that is waiting, the green line the time "
               "spent – a high peak is a heavy part of the page. Drag the chart to look back. A sound is played "
               "after every part and at the end."),
        "fa": ("۶ · هنگام کار",
               "خط وضعیت، صفحه، بخش و زمان باقی‌مانده (تخمینی) را نشان می‌دهد. نمودار Workload هر بار چهار صفحه را "
               "نشان می‌دهد: خط‌چین متنِ در انتظار و خط سبز زمانِ صرف‌شده است – قلهٔ بلند یعنی قسمت سنگین صفحه. برای "
               "دیدن صفحات قبل نمودار را با ماوس بکشید. پس از هر بخش و در پایان صدایی پخش می‌شود."),
        "de": ("6 · Während der Arbeit",
               "Die Statuszeile zeigt Seite, Teil und Restzeit (eine Schätzung). Das Workload-Diagramm zeigt "
               "jeweils vier Seiten: gepunktet der wartende Text, grün die verbrauchte Zeit – eine hohe Spitze ist "
               "ein schwerer Teil der Seite. Ziehen Sie das Diagramm, um zurückzublicken. Nach jedem Teil und am "
               "Ende ertönt ein Signal."),
        "fr": ("6 · Pendant le travail",
               "La ligne d’état montre la page, la partie et le temps restant (une estimation). Le graphique "
               "Workload montre quatre pages à la fois : en pointillé le texte en attente, en vert le temps "
               "passé – un pic élevé est une partie lourde de la page. Faites glisser le graphique pour revenir "
               "en arrière. Un son retentit après chaque partie et à la fin."),
        "es": ("6 · Mientras trabaja",
               "La línea de estado muestra la página, la parte y el tiempo restante (una estimación). El gráfico "
               "Workload muestra cuatro páginas a la vez: punteado el texto en espera, en verde el tiempo "
               "empleado; un pico alto es una parte pesada de la página. Arrastre el gráfico para mirar atrás. "
               "Suena un aviso tras cada parte y al final."),
    }),
    ("review", {
        "en": ("7 · Review and edit (optional)",
               "Tick “Translate with review”: after every two pages the Review window opens. Tool “Text blocks”: "
               "click a block, change its words, drag it to another place, change its size. Tool “Area”: draw a "
               "frame around a picture, a table or a line and drag it, or erase it. “Insert symbol” adds maths "
               "signs. Save shows the result, Next part continues."),
        "fa": ("۷ · بازبینی و ویرایش (اختیاری)",
               "تیک «Translate with review» را بزنید: پس از هر دو صفحه پنجرهٔ بازبینی باز می‌شود. ابزار «Text "
               "blocks»: روی یک بلوک کلیک کنید، کلماتش را تغییر دهید، آن را با ماوس جابه‌جا کنید یا اندازه‌اش را عوض "
               "کنید. ابزار «Area»: دور تصویر، جدول یا خط کادر بکشید و آن را جابه‌جا یا پاک کنید. «Insert symbol» "
               "نمادهای ریاضی اضافه می‌کند. Save نتیجه را نشان می‌دهد و Next part ادامه می‌دهد."),
        "de": ("7 · Prüfen und bearbeiten (optional)",
               "Aktivieren Sie „Translate with review“: nach je zwei Seiten öffnet sich das Prüffenster. Werkzeug "
               "„Text blocks“: Block anklicken, Wörter ändern, an eine andere Stelle ziehen, Größe ändern. "
               "Werkzeug „Area“: Rahmen um ein Bild, eine Tabelle oder eine Linie ziehen und verschieben oder "
               "löschen. „Insert symbol“ fügt Formelzeichen ein. Save zeigt das Ergebnis, Next part fährt fort."),
        "fr": ("7 · Relire et modifier (facultatif)",
               "Cochez « Translate with review » : toutes les deux pages, la fenêtre de relecture s’ouvre. Outil "
               "« Text blocks » : cliquez un bloc, changez ses mots, faites-le glisser ailleurs, changez sa "
               "taille. Outil « Area » : tracez un cadre autour d’une image, d’un tableau ou d’une ligne, puis "
               "déplacez-le ou effacez-le. « Insert symbol » ajoute des signes mathématiques. Save montre le "
               "résultat, Next part continue."),
        "es": ("7 · Revisar y editar (opcional)",
               "Marque «Translate with review»: cada dos páginas se abre la ventana de revisión. Herramienta "
               "«Text blocks»: haga clic en un bloque, cambie sus palabras, arrástrelo a otro lugar, cambie su "
               "tamaño. Herramienta «Area»: dibuje un marco alrededor de una imagen, una tabla o una línea y "
               "muévalo o bórrelo. «Insert symbol» añade signos matemáticos. Save muestra el resultado, Next "
               "part continúa."),
    }),
    ("result", {
        "en": ("8 · The result",
               "At the end a window shows where the file was saved, with buttons to open it. The name is "
               "Translated_to_<language>__<original name>.pdf. The file is updated after every part, so finished "
               "pages are never lost. A long job on a slow computer is saved as numbered files of 20 pages "
               "(file01, file02 …)."),
        "fa": ("۸ · نتیجه",
               "در پایان پنجره‌ای محل ذخیرهٔ فایل را با دکمهٔ بازکردن نشان می‌دهد. نام فایل به شکل "
               "Translated_to_<زبان>__<نام اصلی>.pdf است. فایل پس از هر بخش به‌روز می‌شود، پس صفحات تمام‌شده هرگز از "
               "دست نمی‌روند. کار طولانی روی کامپیوتر کند به صورت فایل‌های شماره‌دارِ ۲۰ صفحه‌ای ذخیره می‌شود "
               "(file01، file02 …)."),
        "de": ("8 · Das Ergebnis",
               "Am Ende zeigt ein Fenster, wo die Datei gespeichert wurde, mit Tasten zum Öffnen. Der Name lautet "
               "Translated_to_<Sprache>__<Originalname>.pdf. Die Datei wird nach jedem Teil aktualisiert, fertige "
               "Seiten gehen nie verloren. Ein langer Auftrag auf einem langsamen Computer wird in nummerierten "
               "Dateien zu je 20 Seiten gespeichert (file01, file02 …)."),
        "fr": ("8 · Le résultat",
               "À la fin, une fenêtre indique où le fichier a été enregistré, avec des boutons pour l’ouvrir. Son "
               "nom est Translated_to_<langue>__<nom d’origine>.pdf. Le fichier est mis à jour après chaque "
               "partie : les pages terminées ne sont jamais perdues. Un long travail sur un ordinateur lent est "
               "enregistré en fichiers numérotés de 20 pages (file01, file02 …)."),
        "es": ("8 · El resultado",
               "Al final, una ventana indica dónde se guardó el archivo, con botones para abrirlo. El nombre es "
               "Translated_to_<idioma>__<nombre original>.pdf. El archivo se actualiza tras cada parte: las "
               "páginas terminadas nunca se pierden. Un trabajo largo en un equipo lento se guarda en archivos "
               "numerados de 20 páginas (file01, file02 …)."),
    }),
    ("teach", {
        "en": ("9 · Teach the app",
               "“Glossary”: terms that must stay untranslated, or fixed translations. “My instructions”: write "
               "what you want in a sentence, for example  Translate “loss” as «زیان» . With Ollama and the online "
               "API these texts go into the prompt, so free instructions such as “use a formal tone” work too. "
               "“File → History” lists your translations."),
        "fa": ("۹ · آموزش به برنامه",
               "«Glossary»: اصطلاحاتی که نباید ترجمه شوند یا ترجمهٔ ثابت دارند. «My instructions»: خواستهٔ خود را در "
               "یک جمله بنویسید، مثلاً  Translate “loss” as «زیان» . با Ollama و Online API این متن‌ها مستقیم در پرامپت "
               "می‌روند، پس دستورهای آزاد مانند «لحن رسمی داشته باش» هم کار می‌کند. «File → History» فهرست "
               "ترجمه‌های شماست."),
        "de": ("9 · Der App etwas beibringen",
               "„Glossary“: Begriffe, die unübersetzt bleiben, oder feste Übersetzungen. „My instructions“: "
               "Schreiben Sie Ihren Wunsch als Satz, z. B.  Translate “loss” as „Verlust“ . Mit Ollama und der "
               "Online-API gehen diese Texte in den Prompt, so wirken auch freie Anweisungen wie „formeller Stil“. "
               "„File → History“ listet Ihre Übersetzungen."),
        "fr": ("9 · Apprendre à l’application",
               "« Glossary » : termes à ne pas traduire, ou traductions fixes. « My instructions » : écrivez votre "
               "souhait en une phrase, p. ex.  Translate “loss” as « perte » . Avec Ollama et l’API en ligne, ces "
               "textes vont dans le prompt : des consignes libres comme « ton formel » fonctionnent aussi. "
               "« File → History » liste vos traductions."),
        "es": ("9 · Enseñar a la aplicación",
               "«Glossary»: términos que no se traducen, o traducciones fijas. «My instructions»: escriba lo que "
               "desea en una frase, p. ej.  Translate “loss” as «pérdida» . Con Ollama y la API en línea estos "
               "textos van al prompt, así que también funcionan instrucciones libres como «tono formal». "
               "«File → History» lista sus traducciones."),
    }),
]


def render_rtl_text(title: str, body: str, width_px: int = 600) -> Optional[bytes]:
    """Persian text of the guide as a picture: Tk draws right-to-left paragraphs with the punctuation and the
    English words at the wrong side, the PDF engine of this app does it correctly."""
    try:
        fonts = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts"
        if not (fonts / "tahoma.ttf").is_file():
            return None
        w_pt = width_px * 72 / 96
        doc = fitz.open()
        page = doc.new_page(width=w_pt, height=900)
        css = ("@font-face{font-family:t;src:url(tahoma.ttf);} "
               "@font-face{font-family:t;font-weight:bold;src:url(tahomabd.ttf);}")
        markup = (f'<div style="font-family:t;direction:rtl;text-align:right;">'
                  f'<p style="margin:0 0 5pt 0;font-size:10.5pt;font-weight:bold;color:#4F46E5">{html.escape(title)}</p>'
                  f'<p style="margin:0;font-size:9pt;line-height:1.6;color:#0F172A">{html.escape(body)}</p></div>')
        spare, _sc = page.insert_htmlbox(fitz.Rect(2, 2, w_pt - 2, 898), markup, css=css,
                                         archive=fitz.Archive(str(fonts)))
        used = 900 - max(0.0, spare) + 4
        png = page.get_pixmap(dpi=96, clip=fitz.Rect(0, 0, w_pt, min(900, used)), alpha=False).tobytes("png")
        doc.close()
        return png
    except Exception:
        return None


def draw_guide_picture(c, key: str) -> None:
    """A small drawing of the window (320 x 190) with the part that the step talks about in colour."""
    HDR_, CARD_, HI, LINE_ = "#0F2A5C", "#FFFFFF", "#3D98FF", "#CBD5E1"
    c.create_rectangle(1, 1, 319, 189, fill="#F1F5F9", outline="#94A3B8")
    c.create_rectangle(1, 1, 319, 22, fill=HDR_, outline=HDR_)
    c.create_text(10, 12, anchor="w", text="DEEPTOME", fill="white", font=("Segoe UI", 8, "bold"))

    def badge(x: float, y: float, n: str) -> None:
        c.create_oval(x - 9, y - 9, x + 9, y + 9, fill="#F97316", outline="white", width=2)
        c.create_text(x, y, text=n, fill="white", font=("Segoe UI", 8, "bold"))

    if key == "review":                                   # the Review window
        c.create_rectangle(8, 28, 150, 184, fill="white", outline=LINE_)
        for k, (y0, y1) in enumerate(((36, 50), (58, 92), (100, 128), (140, 176))):
            c.create_rectangle(16, y0, 142, y1, outline=HI if k == 1 else LINE_, width=2 if k == 1 else 1,
                               dash=() if k == 1 else (2, 2))
            for yy in range(y0 + 4, y1 - 2, 6):
                c.create_line(20, yy, 138, yy, fill="#CBD5E1")
        c.create_rectangle(30, 142, 90, 174, outline="#DC2626", dash=(3, 2), width=2)
        c.create_rectangle(60, 150, 120, 182, outline="#16A34A", width=2)
        c.create_rectangle(158, 28, 312, 70, fill="white", outline=LINE_)
        c.create_rectangle(158, 78, 312, 132, fill="white", outline=HI, width=2)
        for yy in (88, 98, 108):
            c.create_line(166, yy, 300, yy, fill="#94A3B8")
        for k in range(10):
            c.create_rectangle(160 + k * 15, 138, 172 + k * 15, 150, fill="white", outline=LINE_)
            c.create_text(166 + k * 15, 144, text="±≤∑√∞αβθπΩ"[k], font=("Segoe UI Symbol", 7))
        c.create_rectangle(232, 162, 272, 180, fill="#1BF576", outline="")
        c.create_text(252, 171, text="Save", font=("Segoe UI", 7, "bold"))
        badge(150, 75, "1"); badge(312, 105, "2"); badge(120, 150, "3")
        return
    if key == "result":
        for k in range(3):
            x = 40 + k * 90
            c.create_polygon(x, 50, x + 44, 50, x + 60, 66, x + 60, 130, x, 130, fill="white", outline="#64748B")
            c.create_rectangle(x + 6, 100, x + 54, 122, fill="#DC2626", outline="")
            c.create_text(x + 30, 111, text="PDF", fill="white", font=("Segoe UI", 8, "bold"))
            c.create_text(x + 30, 144, text=f"file0{k + 1}", font=("Segoe UI", 8))
        c.create_text(160, 168, text="Translated_to_fa__name.pdf", font=("Consolas", 8), fill="#334155")
        return
    # the main window: left column = 5 numbered cards, right column = run / chart / log
    cards = {"files": (8, 28, 190, 58), "langs": (8, 62, 190, 84), "engine": (8, 88, 190, 126),
             "options": (8, 130, 190, 164), "spec": (8, 168, 190, 184)}
    right = {"run": (198, 28, 312, 62), "chart": (198, 66, 312, 104), "log": (198, 108, 312, 184)}
    hi = {"files": ["files"], "langs": ["langs"], "engine": ["engine"], "options": ["options", "spec"],
          "run": ["run"], "watch": ["run", "chart", "log"], "teach": []}.get(key, [])
    for n, (name, r) in enumerate(cards.items()):
        on = name in hi
        c.create_rectangle(*r, fill="#EAF3FF" if on else CARD_, outline=HI if on else LINE_, width=2 if on else 1)
        c.create_text(r[0] + 6, r[1] + 7, anchor="w", text=str(n + 1), fill=HI if on else "#94A3B8",
                      font=("Segoe UI", 7, "bold"))
        for yy in range(r[1] + 14, r[3] - 3, 7):
            c.create_line(r[0] + 8, yy, r[2] - 30, yy, fill="#CBD5E1")
    for name, r in right.items():
        on = name in hi
        dark = name in ("chart", "log")
        c.create_rectangle(*r, fill="#0F172A" if dark else CARD_, outline=HI if on else LINE_, width=2 if on else 1)
    c.create_rectangle(204, 34, 240, 48, fill="#1BF576", outline="")
    c.create_text(222, 41, text="RUN", font=("Segoe UI", 7, "bold"))
    c.create_rectangle(204, 53, 306, 57, fill="#E2E8F0", outline="")
    c.create_rectangle(204, 53, 250, 57, fill="#4F46E5", outline="")
    pts = [204, 98, 214, 80, 224, 94, 234, 74, 246, 96, 258, 84, 268, 97, 280, 97, 292, 97, 306, 97]
    c.create_line(*pts[:14], fill="#1BF576", width=2, smooth=True)
    c.create_line(*pts[12:], fill="#38BDF8", dash=(2, 2))
    for yy in range(116, 180, 8):
        c.create_line(204, yy, 204 + 60 + (yy * 7) % 40, yy, fill="#475569")
    if key == "teach":
        for k, t in enumerate(("File", "Glossary", "My instr.", "Help")):
            x = 150 + k * 42
            c.create_rectangle(x, 5, x + 38, 18, fill=HI if k in (1, 2) else "#6366F1", outline="")
            c.create_text(x + 19, 12, text=t, fill="white", font=("Segoe UI", 6))
        badge(170, 26, "1"); badge(254, 26, "2")
    elif key == "files":
        c.create_rectangle(150, 34, 184, 44, fill="#E2E8F0", outline="")
        c.create_text(167, 39, text="Browse", font=("Segoe UI", 6))
        badge(186, 34, "1")
    elif key == "watch":
        badge(198, 45, "1"); badge(198, 85, "2"); badge(198, 146, "3")
    elif hi:
        r = {**cards, **right}[hi[0]]
        badge(r[2], r[1] + 4, "✓")



def random_font_sample(lang: str = "fa") -> Tuple[str, bool]:
    """Combined sample text.  Persian (read from the right): Persian sentence, Persian 123, English sentence,
    English 123.  Latin languages (left to right): sentence in the language, 123, English sentence, 123."""
    import random
    if lang == "de":
        return f"{random.choice(FONT_SAMPLES_DE)}  12345  {random.choice(FONT_SAMPLES_EN)}  12345", False
    if lang in FONT_SAMPLES_LATIN:
        return f"{random.choice(FONT_SAMPLES_LATIN[lang])}  12345  {random.choice(FONT_SAMPLES_EN)}  12345", False
    if lang in LATIN_LANGS:
        return f"{random.choice(FONT_SAMPLES_EN)}  12345  {random.choice(FONT_SAMPLES_EN)}", False
    return random_font_sample_fa()


FONT_SAMPLES_LATIN: Dict[str, List[str]] = {
    "fr": ["Le temps est très beau aujourd’hui", "J’ai posé le livre sur la table", "La science est la clé du progrès",
           "Chaque chapitre commence par un exemple", "L’expérience a été réussie", "Où est la bibliothèque ?"],
    "es": ["Hoy hace muy buen tiempo", "Puse el libro sobre la mesa", "La ciencia es la clave del progreso",
           "Cada capítulo empieza con un ejemplo", "El experimento fue un éxito", "¿Dónde está la biblioteca?"],
}


def random_font_sample_fa() -> Tuple[str, bool]:
    """One combined text, read from the right: Persian sentence, Persian 123, English sentence, English 123.
    It is longer than the sample box, which scrolls sideways with the mouse wheel."""
    import random
    return (f"{random.choice(FONT_SAMPLES_FA)}  ۱۲۳۴۵  {random.choice(FONT_SAMPLES_EN)}  12345"), True


# ════════════════════════════════════════════════════════════════════════════
#  Speech (pronunciation) with the voices of Windows
# ════════════════════════════════════════════════════════════════════════════
_TTS_SCRIPT = r"""
param([string]$Mode, [string]$TextFile, [string]$Lang, [double]$Rate, [string]$Out)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); [void]$t.Wait(-1); $t.Result }
[void][Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
$all = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices
if ($Mode -eq 'list') { $all | ForEach-Object { $_.Language + '|' + $_.DisplayName }; exit 0 }
$v = $all | Where-Object { $_.Language -like ($Lang + '*') } | Select-Object -First 1
if (-not $v) { Write-Output 'NOVOICE'; exit 3 }
$s = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$s.Voice = $v
try { $s.Options.SpeakingRate = $Rate } catch {}
$text = [IO.File]::ReadAllText($TextFile, [Text.Encoding]::UTF8)
$stream = Await ($s.SynthesizeTextToStreamAsync($text)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
$in = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($stream)
$fs = [IO.File]::Create($Out); $in.CopyTo($fs); $fs.Close()
Write-Output 'OK'
"""
_TTS_CULTURE = {"en": "en", "fa": "fa", "de": "de", "fr": "fr", "es": "es"}


def _tts_run(args: List[str], timeout: float = 60) -> Tuple[int, str]:
    """Runs the speech script of Windows PowerShell (no window).  -> (exit code, output)."""
    import subprocess
    script = Path(tempfile.gettempdir()) / "deeptome_tts.ps1"
    try:
        if not script.is_file() or script.read_text("utf-8-sig") != _TTS_SCRIPT:
            script.write_text(_TTS_SCRIPT, "utf-8-sig")
    except Exception:
        script.write_text(_TTS_SCRIPT, "utf-8-sig")
    cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)] + args
    r = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
    return r.returncode, out.strip()


def tts_voices() -> Dict[str, List[str]]:
    """Installed Windows voices by language: {'en': ['Microsoft Zira', …], 'de': […]}."""
    try:
        code, out = _tts_run(["-Mode", "list"], 30)
    except Exception:
        return {}
    voices: Dict[str, List[str]] = {}
    for line in out.splitlines():
        if "|" in line:
            lang, name = line.split("|", 1)
            voices.setdefault(lang.split("-")[0].lower(), []).append(name.strip())
    return voices


def tts_to_wav(text: str, lang: str, out: Path, rate: float = 1.0) -> str:
    """Speech of the text in a WAV file.  -> 'OK', 'NOVOICE' or an error message."""
    tf = Path(tempfile.gettempdir()) / "deeptome_tts.txt"
    tf.write_text(text[:4000], "utf-8")
    try:
        code, res = _tts_run(["-Mode", "speak", "-TextFile", str(tf), "-Lang", _TTS_CULTURE.get(lang, lang),
                              "-Rate", f"{rate:.2f}", "-Out", str(out)], 120)
    except Exception as exc:                                  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"
    if "NOVOICE" in res:
        return "NOVOICE"
    return "OK" if out.is_file() and out.stat().st_size > 100 else (res[-300:] or f"exit code {code}")


# ════════════════════════════════════════════════════════════════════════════
#  Components: voices (offline Piper, online Edge, Windows), speech recognition (offline Whisper), audio capture,
#  daily text logs of Quick translate and Live translation
# ════════════════════════════════════════════════════════════════════════════
VOICE_DIR = APP_DIR / "voices"                       # offline Piper voices (.onnx + .onnx.json)
WHISPER_DIR = APP_DIR / "whisper"                    # offline speech recognition models (faster-whisper)
DOCS_DIR = Path.home() / "Documents" / "DeepTome"
QUICK_LOG_DIR = DOCS_DIR / "Quick translations"
LIVE_LOG_DIR = DOCS_DIR / "Live translations"
PIPER_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
# good offline voices for the five languages (the first one of every language is installed by default)
PIPER_VOICES: Dict[str, List[Tuple[str, str]]] = {
    "en": [("en_US-lessac-medium", "Lessac · US English, female"), ("en_US-ryan-medium", "Ryan · US English, male"),
           ("en_US-amy-medium", "Amy · US English, female"), ("en_GB-alan-medium", "Alan · British English, male")],
    "fa": [("fa_IR-amir-medium", "Amir · Persian, male"), ("fa_IR-gyro-medium", "Gyro · Persian, male")],
    "de": [("de_DE-thorsten-medium", "Thorsten · German, male"), ("de_DE-thorsten-high", "Thorsten HQ · German, male"),
           ("de_DE-kerstin-low", "Kerstin · German, female")],
    "fr": [("fr_FR-siwis-medium", "Siwis · French, female"), ("fr_FR-upmc-medium", "UPMC · French, female / male"),
           ("fr_FR-tom-medium", "Tom · French, male")],
    "es": [("es_ES-davefx-medium", "DaveFX · Spanish (Spain), male"),
           ("es_ES-sharvard-medium", "Sharvard · Spanish (Spain), female / male"),
           ("es_MX-claude-high", "Claude · Spanish (Mexico), female")],
}
# natural online voices of Microsoft Edge (free, need the internet; the text is sent to Microsoft)
EDGE_VOICES: Dict[str, List[Tuple[str, str]]] = {
    "en": [("en-US-JennyNeural", "Jenny · US, female"), ("en-US-GuyNeural", "Guy · US, male"),
           ("en-US-AriaNeural", "Aria · US, female"), ("en-GB-SoniaNeural", "Sonia · British, female"),
           ("en-GB-RyanNeural", "Ryan · British, male")],
    "fa": [("fa-IR-DilaraNeural", "Dilara · Persian, female"), ("fa-IR-FaridNeural", "Farid · Persian, male")],
    "de": [("de-DE-KatjaNeural", "Katja · female"), ("de-DE-ConradNeural", "Conrad · male"),
           ("de-DE-AmalaNeural", "Amala · female")],
    "fr": [("fr-FR-DeniseNeural", "Denise · female"), ("fr-FR-HenriNeural", "Henri · male"),
           ("fr-FR-EloiseNeural", "Eloise · female")],
    "es": [("es-ES-ElviraNeural", "Elvira · Spain, female"), ("es-ES-AlvaroNeural", "Álvaro · Spain, male"),
           ("es-MX-DaliaNeural", "Dalia · Mexico, female")],
}
WHISPER_SIZES: Dict[str, Tuple[str, str]] = {        # size -> (download, quality note)
    "tiny": ("75 MB", "fastest, weak for Persian"), "base": ("145 MB", "fast, fair"),
    "small": ("485 MB", "recommended – good for all five languages"),
    "medium": ("1.5 GB", "best quality, needs a fast computer")}
SPEECH_PACKAGES = {"piper": ("piper-tts", "piper"), "edge": ("edge-tts", "edge_tts"),
                   "whisper": ("faster-whisper", "faster_whisper"), "audio": ("soundcard", "soundcard")}


def pkg_version(dist: str, module: str = "") -> str:
    """Installed version of a Python package, '' if it is not installed."""
    import importlib.metadata as md
    import importlib.util
    try:
        return md.version(dist)
    except Exception:
        pass
    try:
        if module and importlib.util.find_spec(module) is not None:
            return "installed"
    except Exception:
        pass
    return ""


def pip_python() -> str:
    """The python.exe of this app (pythonw.exe of the shortcut can not show the output of pip)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").is_file():
        return str(exe.parent / "python.exe")
    return str(exe)


def run_pip(args: List[str], log: Callable[[str], None], cancel: Optional[threading.Event] = None) -> int:
    """pip install / uninstall in the Python of the app; every line of pip goes to `log`."""
    import subprocess
    cmd = [pip_python(), "-m", "pip"] + args + ["--disable-pip-version-check"]
    if args and args[0] == "install":
        cmd.append("--no-warn-script-location")
    log("> pip " + " ".join(args))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                         errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for line in p.stdout:                                       # type: ignore[union-attr]
        if line.strip():
            log("  " + line.rstrip()[:200])
        if cancel is not None and cancel.is_set():
            p.kill()
            return -1
    code = p.wait()
    import importlib
    importlib.invalidate_caches()                               # the new package can be imported at once
    return code


def fetch_file(url: str, dest: Path, log: Callable[[str], None],
               progress: Optional[Callable[[float], None]] = None, min_size: int = 1000) -> Path:
    """Download with progress; a broken download leaves nothing behind."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_TITLE}/{APP_VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while True:
                block = r.read(1 << 16)
                if not block:
                    break
                f.write(block)
                got += len(block)
                if progress and total:
                    progress(got / total)
        if tmp.stat().st_size < min_size:
            raise RuntimeError("the downloaded file is too small")
        tmp.replace(dest)
        return dest
    finally:
        tmp.unlink(missing_ok=True)


def dir_size(p: Path) -> int:
    try:
        if p.is_file():
            return p.stat().st_size
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    except Exception:
        return 0


def fmt_size(n: float) -> str:
    return f"{n / 1e9:.2f} GB" if n >= 1e9 else (f"{n / 1e6:.0f} MB" if n >= 1e6 else f"{n / 1e3:.0f} KB")


# ---- offline voices (Piper)
def piper_voice_file(vid: str) -> Path:
    return VOICE_DIR / f"{vid}.onnx"


def piper_voice_installed(vid: str) -> bool:
    f = piper_voice_file(vid)
    return f.is_file() and Path(str(f) + ".json").is_file()


def install_piper_voice(vid: str, log: Callable[[str], None],
                        progress: Optional[Callable[[float], None]] = None) -> None:
    locale, name, quality = vid.split("-")
    base = f"{PIPER_URL}{locale.split('_')[0]}/{locale}/{name}/{quality}/{vid}"
    log(f"Downloading the offline voice {vid} …")
    fetch_file(base + ".onnx.json", Path(str(piper_voice_file(vid)) + ".json"), log, None, 200)
    fetch_file(base + ".onnx", piper_voice_file(vid), log, progress, 1_000_000)
    log(f"Voice ready: {vid} ({fmt_size(piper_voice_file(vid).stat().st_size)})")


def remove_piper_voice(vid: str) -> None:
    for f in (piper_voice_file(vid), Path(str(piper_voice_file(vid)) + ".json")):
        f.unlink(missing_ok=True)


def install_default_voices(log: Callable[[str], None] = print) -> int:
    """One good offline voice for each of the five languages (called by the Setup and by Settings)."""
    n = 0
    for lang, vs in PIPER_VOICES.items():
        vid = vs[0][0]
        if not piper_voice_installed(vid):
            try:
                install_piper_voice(vid, log)
                n += 1
            except Exception as exc:                        # noqa: BLE001
                log(f"Warning: voice {vid} could not be downloaded ({type(exc).__name__}: {exc})")
    return n


_PIPER_CACHE: Dict[str, object] = {}


def piper_say(text: str, vid: str, out: Path, rate: float = 1.0) -> None:
    import wave
    from piper import PiperVoice                              # type: ignore
    voice = _PIPER_CACHE.get(vid)
    if voice is None:
        voice = PiperVoice.load(str(piper_voice_file(vid)))
        _PIPER_CACHE[vid] = voice
    with wave.open(str(out), "wb") as wf:
        if hasattr(voice, "synthesize_wav"):                  # piper-tts 1.3 and newer
            cfg = None
            try:
                from piper import SynthesisConfig            # type: ignore
                cfg = SynthesisConfig(length_scale=1.0 / max(0.3, rate))
            except Exception:
                cfg = None
            if cfg is not None:
                voice.synthesize_wav(text, wf, syn_config=cfg)
            else:
                voice.synthesize_wav(text, wf)
        else:                                                 # piper-tts 1.2
            voice.synthesize(text, wf, length_scale=1.0 / max(0.3, rate))


def edge_say(text: str, voice: str, out: Path, rate: float = 1.0) -> None:
    import asyncio
    import edge_tts                                           # type: ignore
    pct = int(round((rate - 1.0) * 100))

    async def go() -> None:
        await edge_tts.Communicate(text, voice, rate=f"{pct:+d}%").save(str(out))
    asyncio.run(go())


def voice_choice(lang: str, settings: Optional[dict] = None) -> Tuple[str, str]:
    """(engine, voice) chosen in Settings for a language; else the best one that is installed:
    offline Piper voice -> Windows voice -> online Edge voice."""
    d = settings if settings is not None else (load_json(SETTINGS_FILE, {}) or {})
    ch = ((d.get("voices") or {}) if isinstance(d, dict) else {}).get(lang) or {}
    if ch.get("engine") in ("piper", "edge", "windows"):
        return ch["engine"], ch.get("voice", "")
    if pkg_version("piper-tts", "piper"):
        for vid, _l in PIPER_VOICES.get(lang, []):
            if piper_voice_installed(vid):
                return "piper", vid
    if lang == "en":
        return "windows", ""
    return "piper", PIPER_VOICES.get(lang, PIPER_VOICES["en"])[0][0]


def speak_to_file(text: str, lang: str, rate: float = 1.0, settings: Optional[dict] = None) -> Tuple[str, str]:
    """Speech of a text in a sound file with the chosen voice.  -> ('OK', file) or (message, '')."""
    engine, voice = voice_choice(lang, settings)
    stamp = int(time.time() * 1000)
    tmpd = Path(tempfile.gettempdir())
    text = text[:4000]
    try:
        if engine == "piper":
            if not pkg_version("piper-tts", "piper"):
                if lang != "fa":
                    out = tmpd / f"deeptome_tts_{stamp}.wav"
                    if tts_to_wav(text, lang, out, rate) == "OK":
                        return "OK", str(out)
                return "The offline voices are not installed yet (Settings → Voices → Install).", ""
            if not voice or not piper_voice_installed(voice):
                voice = next((v for v, _l in PIPER_VOICES.get(lang, []) if piper_voice_installed(v)), "")
            if not voice:
                if lang != "fa":                                  # a Windows voice may be there meanwhile
                    out = tmpd / f"deeptome_tts_{stamp}.wav"
                    if tts_to_wav(text, lang, out, rate) == "OK":
                        return "OK", str(out)
                return (f"No offline {LANGS.get(lang, {}).get('name', lang)} voice is installed yet "
                        "(Settings → Voices).", "")
            out = tmpd / f"deeptome_tts_{stamp}.wav"
            piper_say(text, voice, out, rate)
            return "OK", str(out)
        if engine == "edge":
            if not pkg_version("edge-tts", "edge_tts"):
                return "The online voices are not installed yet (Settings → Voices → Install).", ""
            out = tmpd / f"deeptome_tts_{stamp}.mp3"
            edge_say(text, voice or EDGE_VOICES.get(lang, EDGE_VOICES["en"])[0][0], out, rate)
            return "OK", str(out)
        out = tmpd / f"deeptome_tts_{stamp}.wav"
        res = tts_to_wav(text, lang, out, rate)
        if res == "NOVOICE":
            return (f"Windows has no {LANGS.get(lang, {}).get('name', lang)} voice – install an offline voice in "
                    "Settings → Voices.", "")
        return (res, str(out)) if res == "OK" else (res, "")
    except Exception as exc:                                  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}", ""


_MCI_ALIAS = "deeptome_snd"


def play_audio(path: str) -> None:
    """Plays a WAV or MP3 file (Windows MCI: no extra package, can be stopped at any time)."""
    stop_audio()
    if os.name != "nt":
        open_path(path)
        return
    import ctypes
    mci = ctypes.windll.winmm.mciSendStringW
    mci(f'open "{path}" type mpegvideo alias {_MCI_ALIAS}', None, 0, None)
    mci(f"play {_MCI_ALIAS}", None, 0, None)


def stop_audio() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        mci = ctypes.windll.winmm.mciSendStringW
        mci(f"stop {_MCI_ALIAS}", None, 0, None)
        mci(f"close {_MCI_ALIAS}", None, 0, None)
    except Exception:
        pass


def audio_playing() -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(64)
        ctypes.windll.winmm.mciSendStringW(f"status {_MCI_ALIAS} mode", buf, 64, None)
        return buf.value == "playing"
    except Exception:
        return False


# ---- offline speech recognition (faster-whisper) + sound of the microphone or of the computer
def whisper_installed(size: str) -> bool:
    return (WHISPER_DIR / size / "model.bin").is_file()


def install_whisper(size: str, log: Callable[[str], None]) -> None:
    from huggingface_hub import snapshot_download
    log(f"Downloading the speech recognition model “{size}” ({WHISPER_SIZES[size][0]}) …")
    snapshot_download(f"Systran/faster-whisper-{size}", local_dir=str(WHISPER_DIR / size))
    log(f"Speech recognition model ready: {size}")


_WHISPER_CACHE: Dict[str, object] = {}


def load_whisper(size: str):
    if size not in _WHISPER_CACHE:
        from faster_whisper import WhisperModel             # type: ignore
        _WHISPER_CACHE.clear()
        _WHISPER_CACHE[size] = WhisperModel(str(WHISPER_DIR / size), device="cpu", compute_type="int8",
                                            cpu_threads=max(1, physical_cores()))
    return _WHISPER_CACHE[size]


def speech_ready() -> str:
    """'' when the microphone / live translation can work, else what is missing."""
    miss = []
    if not pkg_version("faster-whisper", "faster_whisper"):
        miss.append("speech recognition (faster-whisper)")
    if not pkg_version("soundcard", "soundcard"):
        miss.append("sound capture (soundcard)")
    if not any(whisper_installed(s) for s in WHISPER_SIZES):
        miss.append("a speech recognition model")
    return ", ".join(miss)


def whisper_size(settings: Optional[dict] = None) -> str:
    d = settings if settings is not None else (load_json(SETTINGS_FILE, {}) or {})
    want = (d.get("whisper") if isinstance(d, dict) else "") or "small"
    if whisper_installed(want):
        return want
    return next((s for s in ("small", "base", "medium", "tiny") if whisper_installed(s)), want)


class SpeechListener:
    """Listens to the microphone or to the sound of the computer (a film, a video call, a lecture in the browser)
    without end, cuts the sound into sentences at the pauses and turns every sentence into text with Whisper.
    on_text(text, lang) for every finished sentence, on_partial(text) while a sentence is still spoken,
    on_status(kind, message) for 'listening', 'level', 'error'."""

    def __init__(self, source: str, lang: str, on_text, on_partial=None, on_status=None, size: str = ""):
        self.source, self.lang = source, (lang if lang in LANGS else None)
        self.on_text, self.on_partial, self.on_status = on_text, on_partial, on_status or (lambda k, m: None)
        self.size = size or whisper_size()
        self.stop_ev = threading.Event()
        self.segments: "queue.Queue" = queue.Queue()
        self.lock = threading.Lock()
        self.current: List = []                       # blocks of the sentence that is spoken now
        self.paused = False

    def start(self) -> None:
        threading.Thread(target=self._capture, daemon=True).start()
        threading.Thread(target=self._recognise, daemon=True).start()

    def stop(self) -> None:
        self.stop_ev.set()

    def _capture(self) -> None:
        try:
            import warnings
            import numpy as np
            import soundcard as sc                    # type: ignore
            warnings.filterwarnings("ignore", module="soundcard")
            if self.source == "system":
                spk = sc.default_speaker()
                mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
            else:
                mic = sc.default_microphone()
        except Exception as exc:                       # noqa: BLE001
            self.on_status("error", f"Sound capture is not available: {type(exc).__name__}: {exc}")
            self.stop_ev.set()
            return
        sr, block = 16000, 1600                          # 0.1 s blocks
        noise, speaking, silent = 0.004, False, 0
        try:
            with mic.recorder(samplerate=sr, channels=1, blocksize=block) as rec:
                self.on_status("listening", "")
                while not self.stop_ev.is_set():
                    data = rec.record(numframes=block)
                    x = data[:, 0] if getattr(data, "ndim", 1) > 1 else data
                    x = x.astype("float32")
                    rms = float(np.sqrt(np.mean(x * x)) + 1e-9)
                    self.on_status("level", f"{rms:.4f}")
                    if self.paused:
                        continue
                    thr = max(0.008, noise * 3.0)
                    if rms > thr:
                        speaking, silent = True, 0
                    else:
                        silent += 1
                        if not speaking:
                            noise = 0.97 * noise + 0.03 * rms
                    if speaking:
                        with self.lock:
                            self.current.append(x.copy())
                            dur = len(self.current) * 0.1
                        if (silent >= 6 and dur > 0.8) or dur >= 14.0:   # a pause of 0.6 s or 14 s of speech
                            with self.lock:
                                audio = np.concatenate(self.current)
                                self.current = []
                            speaking, silent = False, 0
                            if dur - 0.6 > 0.4:
                                self.segments.put(audio)
        except Exception as exc:                         # noqa: BLE001
            self.on_status("error", f"Sound capture stopped: {type(exc).__name__}: {exc}")
            self.stop_ev.set()

    def _recognise(self) -> None:
        try:
            import numpy as np
            model = load_whisper(self.size)
        except Exception as exc:                         # noqa: BLE001
            self.on_status("error", f"Speech recognition is not available: {type(exc).__name__}: {exc}")
            self.stop_ev.set()
            return
        last_partial = 0.0
        while not self.stop_ev.is_set():
            try:
                audio = self.segments.get(timeout=0.3)
            except queue.Empty:
                audio = None
            if audio is None:                            # nothing finished: show the sentence that is spoken now
                if self.on_partial and time.time() - last_partial > 1.2:
                    with self.lock:
                        cur = np.concatenate(self.current) if len(self.current) >= 12 else None
                    if cur is not None:
                        last_partial = time.time()
                        txt, _lg = self._text(model, cur)
                        if txt and not self.stop_ev.is_set():
                            self.on_partial(txt)
                continue
            txt, lg = self._text(model, audio)
            if txt and not self.stop_ev.is_set():
                self.on_text(txt, lg)

    def _text(self, model, audio) -> Tuple[str, str]:
        try:
            segs, info = model.transcribe(audio, language=self.lang, beam_size=1, vad_filter=False,
                                          condition_on_previous_text=False, without_timestamps=True)
            txt = " ".join(s.text.strip() for s in segs if getattr(s, "no_speech_prob", 0) < 0.7).strip()
            if re.fullmatch(r"[\W_]*|(?i:thank you\.?|thanks for watching!?|you)", txt):
                return "", ""                            # Whisper's usual words on silence
            return txt, (self.lang or getattr(info, "language", "") or "")
        except Exception as exc:                         # noqa: BLE001
            self.on_status("error", f"Speech recognition error: {type(exc).__name__}: {exc}")
            return "", ""


# ---- shorter sentences for Live translation ("Summary" switch)
_FILLERS = {
    "en": r"\b(?:um+|uh+|erm|er|ah|hmm|you know|i mean|kind of|sort of|basically|actually|literally|"
          r"so yeah|okay so)\b,?",
    "de": r"\b(?:äh+m?|ähm|halt|eigentlich|sozusagen|quasi|naja|irgendwie|ja also)\b,?",
    "fr": r"\b(?:euh+|ben|bah|en fait|du coup|tu vois|genre|bon|voilà|quoi)\b,?",
    "es": r"\b(?:eh+|este|o sea|pues|bueno|digamos|tipo|vale|en plan)\b,?",
    "fa": r"(?:(?<=\s)|^)(?:خب|خوب دیگه|یعنی|ببین|ببینید|اِم|اوم|چیزه|راستش|در واقع|به هر حال)(?=\s|$)[،,]?",
}


def compress_sentence(text: str, lang: str) -> str:
    """The same message in fewer words: fillers, repeated words, side remarks in brackets and dashes go away."""
    t = " " + text.strip() + " "
    t = re.sub(r"\([^)]{0,80}\)|\[[^\]]{0,80}\]|\s[–—-]\s[^–—]{0,60}\s[–—-]\s", " ", t)
    pat = _FILLERS.get(lang)
    if pat:
        t = re.sub(pat, " ", t, flags=re.I)
    t = re.sub(r"\b(\w+)(?:\s+\1\b)+", r"\1", t, flags=re.I)        # "the the", "I I I"
    t = re.sub(r"\s+([,.;:!?،؛؟])", r"\1", t)
    t = re.sub(r"([,،])\s*(?=[,.،])", "", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" ,،")
    return t[:1].upper() + t[1:] if lang in LATIN_LANGS and t else t


# ---- daily text files
_RULE = "═" * 72


def quick_log_write(src_lang: str, tgt_lang: str, src: str, out: str) -> Path:
    """Quick translate: one file per day, every translation with the time, the original and its translation."""
    QUICK_LOG_DIR.mkdir(parents=True, exist_ok=True)
    f = QUICK_LOG_DIR / f"Quick_translations_{time.strftime('%Y-%m-%d')}.txt"
    new = not f.is_file()
    with open(f, "a", encoding="utf-8") as fh:
        if new:
            fh.write(f"{_RULE}\n  DeepTome Translator · Quick translations of {time.strftime('%A %d %B %Y')}\n"
                     f"{_RULE}\n\n")
        fh.write(f"── {time.strftime('%H:%M:%S')} · {LANGS.get(src_lang, {}).get('name', src_lang)} → "
                 f"{LANGS.get(tgt_lang, {}).get('name', tgt_lang)} " + "─" * 30 + "\n")
        fh.write(f"Original:\n{src.strip()}\n\nTranslation:\n{out.strip()}\n\n")
    return f


class LiveLog:
    """Live translation: one file per day; every session starts with a framed title, date and start time,
    every sentence is written with its time, the original and the translation under it."""

    def __init__(self) -> None:
        self.file: Optional[Path] = None

    def start(self, src: str, tgt: str, source: str, summary: bool) -> Path:
        LIVE_LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.file = LIVE_LOG_DIR / f"Live_translation_{time.strftime('%Y-%m-%d')}.txt"
        n = 1
        if self.file.is_file():
            n = self.file.read_text("utf-8", "replace").count("Live translation · session") + 1
        with open(self.file, "a", encoding="utf-8") as fh:
            fh.write(f"\n{_RULE}\n  DeepTome · Live translation · session {n}\n"
                     f"  Started : {time.strftime('%A %d %B %Y, %H:%M:%S')}\n"
                     f"  Languages: {LANGS.get(src, {}).get('name', 'detected automatically')} → "
                     f"{LANGS.get(tgt, {}).get('name', tgt)}\n"
                     f"  Sound   : {'the sound of this computer' if source == 'system' else 'the microphone'}"
                     f"{'   ·   short translations (summary)' if summary else ''}\n{_RULE}\n\n")
        return self.file

    def add(self, src_lang: str, tgt_lang: str, original: str, translation: str) -> None:
        if not self.file:
            return
        with open(self.file, "a", encoding="utf-8") as fh:
            fh.write(f"[{time.strftime('%H:%M:%S')}]  {src_lang.upper() or '??'}  {original.strip()}\n"
                     f"            {tgt_lang.upper()}  {translation.strip()}\n\n")

    def end(self) -> None:
        if self.file and self.file.is_file():
            with open(self.file, "a", encoding="utf-8") as fh:
                fh.write(f"  ── session ended {time.strftime('%H:%M:%S')} " + "─" * 40 + "\n")
        self.file = None


QUICK_LANGS = [("auto", "Detect language"), ("en", "English"), ("fa", "Persian"), ("de", "German"),
               ("fr", "French"), ("es", "Spanish")]


SOUND_FILES = {"part": "Windows Proximity Notification.wav",     # Windows sound scheme: "NFP Completion"
               "done": "Alarm06.wav", "cancel": "Windows Pop-up Blocked.wav"}
ENGINE_LABELS = {"local": "Built-in · MADLAD / NLLB (offline, no installation)",
                 "ollama": "Ollama · local LLM such as Gemma or Qwen (offline)",
                 "api": "Online API · OpenAI-compatible (your own key)"}


def open_path(path: str) -> None:
    """Open a file / folder with the program of the system."""
    try:
        if os.name == "nt":
            os.startfile(shell_path(path))               # noqa: S606
        else:
            import subprocess
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])
    except Exception:
        try:
            webbrowser.open(Path(path).as_uri())
        except Exception:
            pass


def reveal_path(path: str) -> None:
    """Show the file in its folder (Windows: selected in the Explorer)."""
    try:
        if os.name == "nt" and exists(path):
            import subprocess
            subprocess.Popen(["explorer", "/select,", shell_path(path)])
            return
    except Exception:
        pass
    open_path(str(Path(path).parent if not Path(path).is_dir() else path))


# ════════════════════════════════════════════════════════════════════════════
#  Subtitle files (SRT, WebVTT, ASS / SSA, YouTube SBV, MicroDVD)
#  Only the spoken text is translated.  Numbers, times, styles, positions, tags and the file format stay exactly
#  as they are; the output is a subtitle file of the same kind, line by line in the same order.
# ════════════════════════════════════════════════════════════════════════════
SUB_EXTS: Dict[str, str] = {".srt": "SubRip (.srt)", ".vtt": "WebVTT (.vtt)", ".ass": "Advanced SubStation (.ass)",
                            ".ssa": "SubStation Alpha (.ssa)", ".sbv": "YouTube subtitles (.sbv)",
                            ".sub": "MicroDVD (.sub)"}
_SUB_TIME = re.compile(r"^\s*(?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3}\s*-->\s*(?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3}")
_SBV_TIME = re.compile(r"^\s*\d+:\d{2}:\d{2}\.\d{1,3},\d+:\d{2}:\d{2}\.\d{1,3}\s*$")
_MDVD = re.compile(r"^(\{\d+\}\{\d*\})(.*)$")
_SUB_TAG = re.compile(r"<[^<>\n]{1,80}>|\{[^{}\n]{0,200}\}")
_SENT_END = re.compile(r"[.!?…:;؟!\"»”')\]♪]\s*$")


def is_subtitle(path) -> bool:
    return Path(str(path)).suffix.lower() in SUB_EXTS


def _read_subtitle_text(path: str) -> Tuple[str, str, str]:
    """(text with \\n line ends, encoding, original line end).  UTF-8 / UTF-16 first; old Persian subtitles are
    often Windows-1256, Western ones Windows-1252."""
    raw = Path(xl(path)).read_bytes()
    text, enc = None, "utf-8"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text, enc = raw.decode("utf-16"), "utf-16"
    else:
        for e in ("utf-8-sig",):
            try:
                text, enc = raw.decode(e), e
            except UnicodeDecodeError:
                text = None
        if text is None:
            a, b = raw.decode("cp1256", "replace"), raw.decode("cp1252", "replace")
            ar = len(_ARABIC_SCRIPT.findall(a))
            text, enc = (a, "cp1256") if ar > 0.3 * max(1, sum(ch.isalpha() for ch in a)) else (b, "cp1252")
    nl = "\r\n" if "\r\n" in text else "\n"
    return text.replace("\r\n", "\n").replace("\r", "\n"), enc, nl


def subtitle_slots(text: str, ext: str) -> Tuple[List[str], List[dict]]:
    """The lines of the file and the places of its spoken text.  A slot is either a run of whole lines (SRT, VTT,
    SBV) or the text part of one line (ASS / SSA 'Dialogue:', MicroDVD) with its own line separator."""
    lines = text.split("\n")
    slots: List[dict] = []
    ext = ext.lower()
    if ext in (".ass", ".ssa"):
        n_fields, in_events = 10, False
        for i, ln in enumerate(lines):
            s = ln.strip()
            if s.startswith("["):
                in_events = s.lower() == "[events]"
            elif in_events and s.lower().startswith("format:"):
                n_fields = max(2, len(s[7:].split(",")))
            elif in_events and re.match(r"^\s*dialogue\s*:", ln, re.I):
                head, _sep, rest = ln.partition(":")
                parts = rest.split(",", n_fields - 1)
                if len(parts) == n_fields:
                    pre = head + ":" + ",".join(parts[:-1]) + ","
                    slots.append({"kind": "inline", "line": i, "prefix": pre, "sep": "\\N",
                                  "lines": re.split(r"\\[Nn]", parts[-1])})
        return lines, slots
    if ext == ".sub":
        for i, ln in enumerate(lines):
            m = _MDVD.match(ln)
            if m and m.group(2).strip():
                slots.append({"kind": "inline", "line": i, "prefix": m.group(1), "sep": "|",
                              "lines": m.group(2).split("|")})
        return lines, slots
    timing = _SBV_TIME if ext == ".sbv" else _SUB_TIME
    i = 0
    while i < len(lines):
        if timing.match(lines[i]):
            j = i + 1
            while j < len(lines) and lines[j].strip():
                j += 1
            if j > i + 1:
                slots.append({"kind": "lines", "idx": list(range(i + 1, j)), "lines": lines[i + 1:j]})
            i = j
        else:
            i += 1
    return lines, slots


def _split_lines(text: str, n: int) -> List[str]:
    """A translated cue back into (at most) as many lines as the original had, cut at spaces near the middle."""
    words = text.split()
    if n <= 1 or len(text) < 24 or len(words) < 2:
        return [text]
    out: List[str] = []
    rest = words
    for k in range(n, 1, -1):
        total = len(" ".join(rest))
        goal, acc, cut = total / k, 0, 1
        for c, w in enumerate(rest[:-1]):
            acc += len(w) + (1 if c else 0)
            if acc >= goal:
                cut = c + 1 if abs(acc - goal) <= abs(acc - len(w) - 1 - goal) or c == 0 else c
                break
        out.append(" ".join(rest[:cut]))
        rest = rest[cut:]
        if not rest:
            break
    if rest:
        out.append(" ".join(rest))
    return [x for x in out if x]


def _cue_plain(lines: List[str]) -> Tuple[str, str, str, List[str]]:
    """(leading tags, text with inner tags as placeholders, trailing tags, inner tags) of one cue."""
    joined = " ".join(ln.strip() for ln in lines if ln.strip()).replace("\\h", " ")
    lead = re.match(r"^(?:\s*(?:<[^<>\n]{1,80}>|\{[^{}\n]{0,200}\}))+", joined)
    lead_s = lead.group(0) if lead else ""
    body = joined[len(lead_s):]
    trail = re.search(r"(?:(?:<[^<>\n]{1,80}>|\{[^{}\n]{0,200}\})\s*)+$", body)
    trail_s = trail.group(0) if trail else ""
    body = body[:len(body) - len(trail_s)] if trail_s else body
    tags: List[str] = []
    # bold / italic / underline / colour of a few words inside a line: the words are translated without them
    # (the engine would often keep such a line untranslated); every other tag is kept as a placeholder
    body = re.sub(r"</?(?:b|i|u|s)>|<font\b[^<>]*>|</font>", "", body, flags=re.I)

    def keep(m) -> str:
        tags.append(m.group(0))
        return f" {ph_token(len(tags))} "
    body = re.sub(r"\s{2,}", " ", _SUB_TAG.sub(keep, body)).strip()
    return lead_s.strip(), body, trail_s.strip(), tags


def _restore_tags(text: str, tags: List[str]) -> str:
    want = set(range(1, len(tags) + 1))
    got = {int(x.translate(DIGIT_NORM)) for x in PH_RE.findall(text)}
    if got != want:                                     # a tag was lost: drop the inner tags, keep the words
        return re.sub(r"\s{2,}", " ", PH_RE.sub(" ", text)).strip()
    t = PH_RE.sub(lambda m: tags[int(m.group(1).translate(DIGIT_NORM)) - 1], text)
    t = re.sub(r"(<[^/<>][^<>]*>|\{[^{}]*\})\s+", r"\1", t)            # <b> word  ->  <b>word
    t = re.sub(r"\s+(</[^<>]+>)", r"\1", t)                              # word </b> ->  word</b>
    t = re.sub(r"(</[^<>]+>)\s+(?=[.,!?;:؟،…])", r"\1", t)               # </b> !    ->  </b>!
    return re.sub(r"\s{2,}", " ", t).strip()


def subtitle_stats(path: str) -> dict:
    """What the main window shows for a subtitle file: kind, cues, words, language."""
    text, enc, _nl = _read_subtitle_text(path)
    _lines, slots = subtitle_slots(text, Path(path).suffix)
    spoken = " ".join(_cue_plain(s["lines"])[1] for s in slots)
    spoken = PH_RE.sub(" ", spoken)
    words = len(spoken.split())
    tok = local_tokenizer()
    ratio = 2.0
    if tok is not None and spoken.strip():
        try:
            ratio = len(tok.encode(spoken[:60000])) / max(1, len(spoken[:60000].split()))
        except Exception:
            pass
    return {"subtitle": SUB_EXTS.get(Path(path).suffix.lower(), "subtitle"), "cues": len(slots), "pages": 0,
            "words": words, "tokens": int(words * ratio), "tok_exact": tok is not None, "encoding": enc,
            "lang": detect_language(spoken), "other": detect_other_language(spoken), "text": bool(slots),
            "damaged": False}


def run_subtitle_job(path: str, out_dir: str, langs: List[str], opts: "Options", log: Callable[[str], None],
                     progress: Callable[[float, str], None], cancel: threading.Event) -> List[str]:
    """Translates a subtitle file.  Cues that belong to one sentence (no full stop at the end, at most 3 cues) are
    translated together, so that the engine sees the whole sentence, and the translation is shared out over the
    cues again by the length of their original text.  Two speakers in one cue ('- Hi' / '- Hello') are translated
    line by line.  Lines without letters (♪ ♪) stay as they are."""
    ext = Path(path).suffix.lower()
    text, enc, nl = _read_subtitle_text(path)
    lines, slots = subtitle_slots(text, ext)
    log(f"Subtitle file: {SUB_EXTS.get(ext, ext)} · {len(slots)} cues · encoding {enc} · line ends "
        f"{'CRLF' if nl == chr(13) + chr(10) else 'LF'}")
    if not slots:
        raise RuntimeError("No subtitle text was found in this file.")
    outputs: List[str] = []
    for lang in langs:
        if cancel.is_set():
            raise Cancelled()
        rtl = bool(LANGS[lang]["rtl"])
        log(f"━━ {LANGS.get(opts.src_lang, LANGS['en'])['name']} → {LANGS[lang]['name']} ━━")
        progress(0.01, "Loading the translation engine …")
        mt = make_engine(opts, lang, log)
        if opts.engine == "local":
            mt.beams = 2 if opts.best_quality else 1
        # ---- units to translate: (slot indexes, text, tags, lead, trail, dialogue line or -1)
        units: List[dict] = []
        k = 0
        while k < len(slots):
            s = slots[k]
            raw = [ln for ln in s["lines"] if ln.strip()]
            if len(raw) >= 2 and all(re.match(r"^\s*(?:<[^>]+>|\{[^}]*\})*\s*[-–—]", ln) for ln in raw):
                for li, ln in enumerate(raw):             # two speakers: every line on its own, dash kept
                    lead, body, trail, tags = _cue_plain([ln])
                    m = re.match(r"^([-–—]\s*)", body)
                    dash = m.group(1) if m else ""
                    units.append({"slots": [k], "text": body[len(dash):], "tags": tags, "lead": lead + dash,
                                  "trail": trail, "line": li})
                k += 1
                continue
            group = [k]
            while (len(group) < 3 and group[-1] + 1 < len(slots)
                   and not _SENT_END.search(_cue_plain(slots[group[-1]]["lines"])[1])
                   and _cue_plain(slots[group[-1]]["lines"])[1]
                   and not _cue_plain(slots[group[-1] + 1]["lines"])[0]
                   and not re.match(r"^\s*[-–—]", " ".join(slots[group[-1] + 1]["lines"]))
                   and sum(len(_cue_plain(slots[g]["lines"])[1].split()) for g in group) < 30):
                group.append(group[-1] + 1)
            if len(group) == 1:
                lead, body, trail, tags = _cue_plain(s["lines"])
                units.append({"slots": [k], "text": body, "tags": tags, "lead": lead, "trail": trail, "line": -1})
            else:
                parts = [_cue_plain(slots[g]["lines"]) for g in group]
                units.append({"slots": group, "text": " ".join(p[1] for p in parts), "tags": [], "lead": parts[0][0],
                              "trail": parts[-1][2], "line": -1, "parts": parts})
            k = group[-1] + 1
        todo = [u for u in units if re.search(r"[^\W\d_]", PH_RE.sub("", u["text"]))]
        log(f"{len(todo)} pieces of spoken text to translate ({sum(1 for u in units if len(u['slots']) > 1)} "
            f"sentences run over 2 or 3 cues).")
        t0 = time.time()
        batch = 24
        for b0 in range(0, len(todo), batch):
            if cancel.is_set():
                raise Cancelled()
            chunk = todo[b0:b0 + batch]
            res = mt.translate_texts([u["text"] for u in chunk])
            for u, r in zip(chunk, res):
                u["out"] = _post(r, lang, opts)
            done = min(len(todo), b0 + batch)
            el = time.time() - t0
            left = el / done * (len(todo) - done) if done else 0
            progress(0.03 + 0.95 * done / max(1, len(todo)),
                     f"Subtitles: {done} / {len(todo)} translated" + (f" · about {fmt_dur(left)} left" if left > 60
                                                                       else ""))
            act(f"  {chunk[-1]['text'][:70]}  →  {chunk[-1].get('out', '')[:70]}", "w")
        # ---- the translations back into the slots
        new_text: Dict[int, List[str]] = {}
        dialog: Dict[int, Dict[int, str]] = {}
        for u in units:
            out = u.get("out")
            if out is None:                                   # nothing to translate (♪, numbers): unchanged
                continue
            if u["line"] >= 0:
                t = _restore_tags(out, u["tags"])
                dialog.setdefault(u["slots"][0], {})[u["line"]] = (u["lead"] + t + (" " + u["trail"] if u["trail"]
                                                                                   else "")).strip()
                continue
            if len(u["slots"]) == 1:
                t = _restore_tags(out, u["tags"])
                pieces = [t]
            else:                                             # share the sentence out by the original lengths
                words = PH_RE.sub(" ", out).split()
                lens = [max(1, len(p[1])) for p in u["parts"]]
                tot, pieces, w0 = sum(lens), [], 0
                for gi, ln_ in enumerate(lens):
                    w1 = len(words) if gi == len(lens) - 1 else max(w0 + 1, round(len(words) * sum(lens[:gi + 1]) / tot))
                    w1 = min(w1, len(words) - (len(lens) - gi - 1))
                    pieces.append(" ".join(words[w0:w1]) or "…")
                    w0 = max(w0, w1)
            for gi, sl in enumerate(u["slots"]):
                n_lines = max(1, len([ln for ln in slots[sl]["lines"] if ln.strip()]))
                cue = _split_lines(pieces[gi] if gi < len(pieces) else "", n_lines)
                lead = u["lead"] if gi == 0 else (u["parts"][gi][0] if len(u["slots"]) > 1 else "")
                trail = u["trail"] if gi == len(u["slots"]) - 1 else (u["parts"][gi][2] if len(u["slots"]) > 1 else "")
                if lead:
                    cue[0] = lead + cue[0]
                if trail:
                    cue[-1] = cue[-1] + trail
                new_text[sl] = cue
        for sl, lines_ in dialog.items():
            raw = [ln for ln in slots[sl]["lines"] if ln.strip()]
            new_text[sl] = [lines_.get(li, raw[li]) for li in range(len(raw))]
        mark = (lambda t: "‏" + t + "‏") if rtl else (lambda t: t)   # punctuation at the right side
        out_lines: List[str] = []
        slot_at = {}
        for si, s in enumerate(slots):
            slot_at[s["idx"][0] if s["kind"] == "lines" else s["line"]] = si
        skip: Set[int] = set()
        for i, ln in enumerate(lines):
            if i in skip:
                continue
            si = slot_at.get(i)
            if si is None or si not in new_text:
                out_lines.append(ln)
                continue
            s = slots[si]
            cue = [mark(c) for c in new_text[si]]
            if s["kind"] == "lines":
                out_lines.extend(cue)
                skip.update(s["idx"])
            else:
                out_lines.append(s["prefix"] + s["sep"].join(cue))
        dst = fit_output_path(out_dir, output_name(path, lang, ext), log)
        Path(xl(out_dir)).mkdir(parents=True, exist_ok=True)
        enc_out = "utf-8" if ext == ".vtt" else "utf-8-sig"
        data = nl.join(out_lines)

        def write(p: str) -> None:
            with open(xl(p), "w", encoding=enc_out, newline="") as f:
                f.write(data)
        dst = save_with_fallback(dst, write, log)
        log(f"Saved: {dst}  ({len(new_text)} cues translated, times and format unchanged)")
        outputs.append(dst)
    progress(1.0, "Finished")
    try:
        add_history(path, outputs, langs)
    except Exception:
        pass
    return outputs


# ════════════════════════════════════════════════════════════════════════════
#  Languages that are recognised but can not be translated yet
# ════════════════════════════════════════════════════════════════════════════
_OTHER_WORDS = {
    "Italian": "il di che la per non una sono della del gli anche questo come più alla nel",
    "Portuguese": "não uma para com os mais como seu sua pelo está são também foi dos das",
    "Dutch": "het een van en niet zijn ook maar wordt wel deze voor naar bij met dat",
    "Turkish": "bir ve bu için ile da de olarak gibi daha çok olan ama değil kadar",
    "Polish": "nie się jest że na do jak ale tak przez tylko od być dla które",
    "Swedish": "och att det som en på är för med av till den inte har om",
    "Indonesian": "yang dan di dengan untuk ini dari dalam tidak akan pada adalah itu",
    "Czech": "je se že na jsou jako ale pro není jeho také byl podle který",
}


def detect_other_language(text: str) -> str:
    """A language that is NOT one of the five languages of the app (name), or ''.  By script (Arabic without
    Persian letters, Cyrillic, Greek, Hebrew, Chinese, Japanese, Korean, Devanagari, Thai …) or by its most
    frequent words."""
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 30:
        return ""
    n = len(letters)

    def share(lo: str, hi: str) -> float:
        return sum(1 for c in letters if lo <= c <= hi) / n
    arab = [c for c in letters if _ARABIC_SCRIPT.match(c)]
    if len(arab) > 0.4 * n:
        norm = unicodedata.normalize("NFKC", "".join(arab))
        fa = sum(1 for c in norm if c in _FA_ONLY)
        ar = sum(1 for c in norm if c in "ةىيك")
        urdu = sum(1 for c in norm if c in "ٹڈڑےں")
        if urdu > 0.01 * len(norm):
            return "Urdu"
        if fa < 0.004 * len(norm) and ar > 0.02 * len(norm):
            return "Arabic"
        return ""
    for name, lo, hi in (("Russian / Cyrillic", "Ѐ", "ӿ"), ("Greek", "Ͱ", "Ͽ"),
                         ("Hebrew", "֐", "׿"), ("Hindi / Devanagari", "ऀ", "ॿ"),
                         ("Thai", "฀", "๿"), ("Korean", "가", "힯"),
                         ("Japanese", "぀", "ヿ"), ("Chinese", "一", "鿿"),
                         ("Armenian", "԰", "֏"), ("Georgian", "Ⴀ", "ჿ")):
        if share(lo, hi) > 0.3:
            return name
    words = re.findall(r"[a-zà-ÿąćęłńóśźżçğışöüčěřšťůž]+", text.lower())
    real = [w for w in words if len(w) >= 2]
    if len(real) < 20:
        return ""
    ours = max(sum(real.count(w) for w in set(ws.split())) for ws in _LANG_WORDS.values())
    best, score = "", 0
    for name, ws in _OTHER_WORDS.items():
        sc = sum(real.count(w) for w in set(ws.split()))
        if sc > score:
            best, score = name, sc
    if score >= 0.08 * len(real) and score > 1.6 * ours:
        return best
    return ""


def _job_entry(args: tuple, q, cancel, ctl=None) -> None:
    """Runs a translation job in its OWN process, so that 'Cancel' can stop it at once even if the engine hangs."""
    set_activity(lambda text, tag="w": q.put(("act", text, tag)))
    try:
        outs = run_job(*args, log=lambda m: q.put(("log", m)),
                       progress=lambda f, m: q.put(("progress", f, m)), cancel=cancel, ctl=ctl)
        q.put(("done", outs))
    except Cancelled:
        q.put(("cancelled",))
    except BaseException as exc:                      # noqa: BLE001 – report everything to the window
        q.put(("error", f"{type(exc).__name__}: {exc}"))


def run_gui(_test=None) -> None:
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import filedialog, messagebox, ttk
    from tkinter.scrolledtext import ScrolledText

    BG, CARD, INK, MUTE = "#F3F5FA", "#FFFFFF", "#1E293B", "#64748B"
    ACC, ACC2, LINE, SOFT = "#4F46E5", "#4338CA", "#E2E8F0", "#EEF2FF"
    HDR = "#063360"                       # header colour (matches the logo picture)
    GREY = "#9CA3AF"                      # font colour of the options that are not available yet

    # ------------------------------------------------------------------ a text box that can write Persian
    # Tk 8.6 has no bidirectional text: in its Text / Entry widgets a Persian line is cut into pieces at the cursor
    # and every piece is mirrored on its own, so letters jump and the cursor goes to the wrong end.  On Windows the
    # text boxes below are a native RichEdit control (the one of WordPad) inside a Tk frame: Persian, English and
    # mixed text are typed, selected and moved through with the arrow keys exactly like in any Windows program.
    import ctypes
    from ctypes import wintypes as wt
    _W = os.name == "nt"
    if _W:
        _u32 = ctypes.WinDLL("user32", use_last_error=True)
        _LRES = ctypes.c_ssize_t
        _u32.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        _u32.SendMessageW.restype = _LRES
        _u32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                         ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
        _u32.CreateWindowExW.restype = wt.HWND
        _u32.MoveWindow.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.BOOL]
        _u32.SetFocus.argtypes = [wt.HWND]
        _u32.GetFocus.restype = wt.HWND
        _u32.GetKeyState.argtypes = [ctypes.c_int]
        _u32.GetKeyState.restype = ctypes.c_short
        _u32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_void_p]
        _u32.SetWindowLongPtrW.restype = ctypes.c_void_p
        _u32.CallWindowProcW.argtypes = [ctypes.c_void_p, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        _u32.CallWindowProcW.restype = _LRES
        _u32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
        _WNDPROC = ctypes.WINFUNCTYPE(_LRES, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

        class _CHARRANGE(ctypes.Structure):
            _fields_ = [("cpMin", ctypes.c_long), ("cpMax", ctypes.c_long)]

        class _CF2(ctypes.Structure):
            _fields_ = [("cbSize", wt.UINT), ("dwMask", wt.DWORD), ("dwEffects", wt.DWORD), ("yHeight", ctypes.c_long),
                        ("yOffset", ctypes.c_long), ("crTextColor", wt.DWORD), ("bCharSet", ctypes.c_ubyte),
                        ("bPitchAndFamily", ctypes.c_ubyte), ("szFaceName", ctypes.c_wchar * 32),
                        ("wWeight", wt.WORD), ("sSpacing", ctypes.c_short), ("crBackColor", wt.DWORD),
                        ("lcid", wt.DWORD), ("dwReserved", wt.DWORD), ("sStyle", ctypes.c_short),
                        ("wKerning", wt.WORD), ("bUnderlineType", ctypes.c_ubyte), ("bAnimation", ctypes.c_ubyte),
                        ("bRevAuthor", ctypes.c_ubyte), ("bUnderlineColor", ctypes.c_ubyte)]

        class _PF2(ctypes.Structure):
            _fields_ = [("cbSize", wt.UINT), ("dwMask", wt.DWORD), ("wNumbering", wt.WORD), ("wEffects", wt.WORD),
                        ("dxStartIndent", ctypes.c_long), ("dxRightIndent", ctypes.c_long),
                        ("dxOffset", ctypes.c_long), ("wAlignment", wt.WORD), ("cTabCount", ctypes.c_short),
                        ("rgxTabs", ctypes.c_long * 32), ("dySpaceBefore", ctypes.c_long),
                        ("dySpaceAfter", ctypes.c_long), ("dyLineSpacing", ctypes.c_long), ("sStyle", ctypes.c_short),
                        ("bLineSpacingRule", ctypes.c_ubyte), ("bOutlineLevel", ctypes.c_ubyte),
                        ("wShadingWeight", wt.WORD), ("wShadingStyle", wt.WORD), ("wNumberingStart", wt.WORD),
                        ("wNumberingStyle", wt.WORD), ("wNumberingTab", wt.WORD), ("wBorderSpace", wt.WORD),
                        ("wBorderWidth", wt.WORD), ("wBorders", wt.WORD)]

        class _GTEX(ctypes.Structure):
            _fields_ = [("cb", wt.DWORD), ("flags", wt.DWORD), ("codepage", wt.UINT),
                        ("lpDefaultChar", ctypes.c_void_p), ("lpUsedDefChar", ctypes.c_void_p)]

        class _GTLEX(ctypes.Structure):
            _fields_ = [("flags", wt.DWORD), ("codepage", wt.UINT)]

        class _POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        try:
            ctypes.WinDLL("Msftedit.dll")
        except Exception:
            _W = False

    def _rgb(col: str) -> int:
        if not re.match(r"^#[0-9A-Fa-f]{6}$", str(col)):
            try:                                              # a colour name such as "white"
                r, g, b = (v // 257 for v in tk._default_root.winfo_rgb(col))
                return r | (g << 8) | (b << 16)
            except Exception:
                return 0xFFFFFF
        col = col.lstrip("#")
        r, g, b = int(col[0:2], 16), int(col[2:4], 16), int(col[4:6], 16)
        return r | (g << 8) | (b << 16)

    _WMU = 0x400
    EM_EXGETSEL, EM_EXSETSEL, EM_GETCHARFORMAT, EM_SETBKGNDCOLOR = _WMU + 52, _WMU + 55, _WMU + 58, _WMU + 67
    EM_SETCHARFORMAT, EM_SETPARAFORMAT, EM_SETTEXTMODE, EM_GETTEXTEX = _WMU + 68, _WMU + 71, _WMU + 89, _WMU + 94
    EM_GETTEXTLENGTHEX, EM_GETSCROLLPOS, EM_SETSCROLLPOS = _WMU + 95, _WMU + 221, _WMU + 222
    EM_SETLANGOPTIONS, EM_GETLANGOPTIONS = _WMU + 120, _WMU + 121
    CFM_BOLD, CFM_ITALIC, CFM_SIZE, CFM_COLOR, CFM_FACE = 0x1, 0x2, 0x80000000, 0x40000000, 0x20000000

    class BidiText(tk.Frame):
        """A text box for every language.  Methods: get(), set(text), insert(text), clear(), selection(),
        select(a, b), focus(), set_rtl(bool), set_readonly(bool), set_format(a, b, bold, italic, size),
        formats() (rich boxes), on_change / on_key callbacks.  Offsets count every line end as one character."""

        def __init__(self, master, font=("Tahoma", 12), bg="white", fg="#1E293B", rich=False, multiline=True,
                     readonly=False, auto_dir=True, pad=(10, 8), on_change=None, on_key=None, height=0, width=0,
                     border="#E2E8F0"):
            super().__init__(master, bg=bg, highlightthickness=1, highlightbackground=border, highlightcolor="#3D98FF",
                             height=height or (34 if not multiline else 120), width=width or 200)
            self.font, self.bg, self.fg, self.rich, self.multi = font, bg, fg, rich, multiline
            self.auto_dir, self.pad = auto_dir, pad
            self.on_change, self.on_key = on_change, on_key
            self.hwnd = None
            self.tkt = None
            self._rtl = None
            self._last = ""
            self._swallow = False
            if _W:
                try:
                    self._native(readonly)
                except Exception:
                    self.hwnd = None
            if not self.hwnd:                                   # other systems: the Tk text box
                self.tkt = tk.Text(self, wrap="word" if multiline else "none", font=font, bg=bg, fg=fg,
                                   relief="flat", height=1 if not multiline else 5, undo=True, padx=pad[0],
                                   pady=pad[1] if multiline else 3)
                self.tkt.pack(fill="both", expand=True)
                self.tkt.tag_configure("r", justify="right")
                if readonly:
                    self.tkt.config(state="disabled")
            self.bind("<Configure>", self._resize)
            self.after(150, self._poll)

        # ---- native control
        def _native(self, readonly: bool) -> None:
            style = 0x40000000 | 0x10000000 | 0x00010000 | 0x100          # CHILD VISIBLE TABSTOP NOHIDESEL
            style |= (0x4 | 0x40 | 0x1000 | 0x00200000) if self.multi else 0x80   # MULTILINE AUTOVSCROLL WANTRETURN VSCROLL
            self.update_idletasks()
            parent = wt.HWND(self.winfo_id())
            self.hwnd = _u32.CreateWindowExW(0, "RICHEDIT50W", "", style, 0, 0, 100, 30, parent, None, None, None)
            if not self.hwnd:
                raise OSError("RichEdit")
            h = self.hwnd
            send = self._send
            if not self.rich:
                send(EM_SETTEXTMODE, 1 | 4 | 32, 0)            # plain text, multi-level undo, any code page
            opt = send(EM_GETLANGOPTIONS, 0, 0)
            send(EM_SETLANGOPTIONS, 0, opt & ~0x2 & ~0x80)     # no automatic font switching
            send(EM_SETBKGNDCOLOR, 0, _rgb(self.bg))
            cf = self._cf(CFM_FACE | CFM_SIZE | CFM_COLOR, size=self.font[1], color=self.fg)
            cf.szFaceName = self.font[0]
            send(EM_SETCHARFORMAT, 4, ctypes.addressof(cf))      # SCF_ALL
            send(EM_SETCHARFORMAT, 0, ctypes.addressof(cf))      # default for new text
            if readonly:
                send(0x00CF, 1, 0)
            self._proc = _WNDPROC(self._wndproc)                # keys and the right-click menu
            self._old = _u32.SetWindowLongPtrW(h, -4, ctypes.cast(self._proc, ctypes.c_void_p))
            self._menu = tk.Menu(self, tearoff=0)
            for lab, msg in (("Cut", 0x300), ("Copy", 0x301), ("Paste", 0x302)):
                self._menu.add_command(label=lab, command=lambda m=msg: (self._send(m, 0, 0), self._poll(False)))
            self._menu.add_separator()
            self._menu.add_command(label="Select all", command=lambda: self.select(0, -1))

        def _send(self, msg: int, wp: int = 0, lp: int = 0) -> int:
            return _u32.SendMessageW(self.hwnd, msg, wp, lp) if self.hwnd else 0

        def _wndproc(self, hwnd, msg, wp, lp):
            try:
                if msg == 0x0100 and self.on_key:                # WM_KEYDOWN
                    ctrl = _u32.GetKeyState(0x11) < 0
                    shift = _u32.GetKeyState(0x10) < 0
                    if self.on_key(int(wp), ctrl, shift):
                        self._swallow = True
                        return 0
                if msg == 0x0102 and self._swallow:              # WM_CHAR of a key that was used
                    self._swallow = False
                    return 0
                if msg == 0x007B:                                # WM_CONTEXTMENU
                    x, y = self.winfo_pointerx(), self.winfo_pointery()
                    self.after(1, lambda: self._menu.tk_popup(x, y))
                    return 0
            except Exception:
                pass
            return _u32.CallWindowProcW(self._old, hwnd, msg, wp, lp)

        def _cf(self, mask: int, bold=None, italic=None, size=None, color=None):
            cf = _CF2()
            cf.cbSize = ctypes.sizeof(_CF2)
            cf.dwMask = mask
            eff = 0
            if bold:
                eff |= 1
            if italic:
                eff |= 2
            cf.dwEffects = eff
            if size:
                cf.yHeight = int(round(float(size) * 20))
            if color:
                cf.crTextColor = _rgb(color)
            return cf

        def _resize(self, _e=None) -> None:
            if self.hwnd:
                w, h = self.winfo_width(), self.winfo_height()
                px, py = self.pad if self.multi else (self.pad[0], 4)
                _u32.MoveWindow(self.hwnd, px, py, max(10, w - 2 * px - 2), max(10, h - 2 * py - 2), True)

        def destroy(self) -> None:
            if self.hwnd and getattr(self, "_old", None):
                try:
                    _u32.SetWindowLongPtrW(self.hwnd, -4, self._old)
                except Exception:
                    pass
            self.hwnd = None
            super().destroy()

        def _poll(self, again: bool = True) -> None:
            try:
                if not self.winfo_exists():
                    return
            except Exception:
                return
            t = self.get()
            if t != self._last:
                self._last = t
                if self.auto_dir:
                    self.set_rtl(_first_strong_rtl(t), _force=False)
                if self.on_change:
                    try:
                        self.on_change()
                    except Exception:
                        pass
            if again:
                self.after(120, self._poll)

        # ---- text
        def get(self) -> str:
            if self.tkt is not None:
                return self.tkt.get("1.0", "end-1c")
            gl = _GTLEX(8 | 2, 1200)                             # GTL_NUMCHARS | GTL_PRECISE
            n = self._send(EM_GETTEXTLENGTHEX, ctypes.addressof(gl), 0)
            buf = ctypes.create_unicode_buffer(n + 2)
            gt = _GTEX((n + 2) * 2, 0, 1200, None, None)
            self._send(EM_GETTEXTEX, ctypes.addressof(gt), ctypes.addressof(buf))
            return buf.value.replace("\r", "\n").replace("\v", "\n")

        def set(self, text: str) -> None:
            text = text or ""
            if self.tkt is not None:
                ro = self.tkt.cget("state") == "disabled"
                self.tkt.config(state="normal")
                self.tkt.delete("1.0", "end")
                self.tkt.insert("1.0", text)
                if ro:
                    self.tkt.config(state="disabled")
            else:
                buf = ctypes.create_unicode_buffer(text.replace("\r\n", "\n").replace("\n", "\r"))
                _u32.SendMessageW(self.hwnd, 0x000C, 0, ctypes.addressof(buf))
                if self.rich:                                  # back to the plain font of the box
                    cf = self._cf(CFM_FACE | CFM_SIZE | CFM_COLOR | CFM_BOLD | CFM_ITALIC, size=self.font[1],
                                  color=self.fg)
                    cf.szFaceName = self.font[0]
                    self._send(EM_SETCHARFORMAT, 4, ctypes.addressof(cf))
            self._last = self.get()
            self._rtl = None
            if self.auto_dir:
                self.set_rtl(_first_strong_rtl(text))

        def clear(self) -> None:
            self.set("")

        def insert(self, text: str) -> None:
            """At the cursor (replaces the selection), with undo."""
            if self.tkt is not None:
                self.tkt.insert("insert", text)
                return
            buf = ctypes.create_unicode_buffer(text.replace("\r\n", "\n").replace("\n", "\r"))
            _u32.SendMessageW(self.hwnd, 0x00C2, 1, ctypes.addressof(buf))
            self._poll(False)

        def append(self, text: str) -> None:
            n = len(self.get())
            self.select(n, n)
            self.insert(text)
            self.see_end()

        def see_end(self) -> None:
            if self.tkt is not None:
                self.tkt.see("end")
            else:
                n = len(self.get())
                self.select(n, n)
                self._send(0x00B7, 0, 0)                         # EM_SCROLLCARET

        def selection(self) -> Tuple[int, int]:
            if self.tkt is not None:
                try:
                    a = len(self.tkt.get("1.0", "sel.first"))
                    b = len(self.tkt.get("1.0", "sel.last"))
                    return a, b
                except tk.TclError:
                    i = len(self.tkt.get("1.0", "insert"))
                    return i, i
            cr = _CHARRANGE()
            self._send(EM_EXGETSEL, 0, ctypes.addressof(cr))
            return int(cr.cpMin), int(cr.cpMax)

        def select(self, a: int, b: int) -> None:
            if self.tkt is not None:
                self.tkt.tag_remove("sel", "1.0", "end")
                self.tkt.tag_add("sel", f"1.0+{a}c", "end-1c" if b < 0 else f"1.0+{b}c")
                return
            cr = _CHARRANGE(a, b)
            self._send(EM_EXSETSEL, 0, ctypes.addressof(cr))

        def focus(self) -> None:
            if self.tkt is not None:
                self.tkt.focus_set()
            elif self.hwnd:
                _u32.SetFocus(self.hwnd)

        def has_focus(self) -> bool:
            if self.tkt is not None:
                return self.focus_get() is self.tkt
            return bool(self.hwnd) and _u32.GetFocus() == self.hwnd

        def set_readonly(self, ro: bool) -> None:
            if self.tkt is not None:
                self.tkt.config(state="disabled" if ro else "normal")
            else:
                self._send(0x00CF, 1 if ro else 0, 0)

        def set_rtl(self, rtl: bool, _force: bool = True) -> None:
            """Right-to-left paragraphs aligned right (Persian) or left-to-right aligned left."""
            rtl = bool(rtl)
            if rtl == self._rtl:
                return
            self._rtl = rtl
            if self.tkt is not None:
                (self.tkt.tag_add if rtl else self.tkt.tag_remove)("r", "1.0", "end")
                return
            keep = self.selection()
            pt = _POINT()
            self._send(EM_GETSCROLLPOS, 0, ctypes.addressof(pt))
            self._send(0x000B, 0, 0)                             # no drawing meanwhile
            self.select(0, -1)
            pf = _PF2()
            pf.cbSize = ctypes.sizeof(_PF2)
            pf.dwMask = 0x8 | 0x00010000                          # PFM_ALIGNMENT | PFM_RTLPARA
            pf.wEffects = 1 if rtl else 0
            pf.wAlignment = 2 if rtl else 1
            self._send(EM_SETPARAFORMAT, 0, ctypes.addressof(pf))
            self.select(*keep)
            self._send(EM_SETSCROLLPOS, 0, ctypes.addressof(pt))
            self._send(0x000B, 1, 0)
            ctypes.windll.user32.InvalidateRect(self.hwnd, None, True)

        # ---- formats of some words (rich boxes: the review editor)
        def set_format(self, a: int, b: int, bold=None, italic=None, size=None, color=None) -> None:
            if not self.hwnd or b <= a:
                return
            keep = self.selection()
            mask, cf_kw = 0, {}
            if bold is not None:
                mask |= CFM_BOLD
                cf_kw["bold"] = bold
            if italic is not None:
                mask |= CFM_ITALIC
                cf_kw["italic"] = italic
            if size is not None:
                mask |= CFM_SIZE
                cf_kw["size"] = size
            if color is not None:
                mask |= CFM_COLOR
                cf_kw["color"] = color
            cf = self._cf(mask, **cf_kw)
            self.select(a, b)
            self._send(EM_SETCHARFORMAT, 1, ctypes.addressof(cf))  # SCF_SELECTION
            self.select(*keep)

        def char_format(self, i: int) -> Tuple[float, bool, bool]:
            cf = _CF2()
            cf.cbSize = ctypes.sizeof(_CF2)
            self.select(i, i + 1)
            self._send(EM_GETCHARFORMAT, 1, ctypes.addressof(cf))
            return cf.yHeight / 20.0, bool(cf.dwEffects & 1), bool(cf.dwEffects & 2)

        def formats(self) -> List[Tuple[float, bool, bool]]:
            """(size in pt, bold, italic) of every character."""
            n = len(self.get())
            if not self.hwnd or not self.rich:
                return [(float(self.font[1]), False, False)] * n
            keep = self.selection()
            pt = _POINT()
            self._send(EM_GETSCROLLPOS, 0, ctypes.addressof(pt))
            self._send(0x000B, 0, 0)
            out = [self.char_format(i) for i in range(n)]
            self.select(*keep)
            self._send(EM_SETSCROLLPOS, 0, ctypes.addressof(pt))
            self._send(0x000B, 1, 0)
            ctypes.windll.user32.InvalidateRect(self.hwnd, None, True)
            return out

        def reset_undo(self) -> None:
            if self.tkt is not None:
                self.tkt.edit_reset()
            else:
                self._send(0x00CD, 0, 0)                        # EM_EMPTYUNDOBUFFER

        def bg_color(self, col: str) -> None:
            self.bg = col
            self.configure(bg=col)
            if self.tkt is not None:
                self.tkt.config(bg=col)
            else:
                self._send(EM_SETBKGNDCOLOR, 0, _rgb(col))

    def _first_strong_rtl(text: str) -> bool:
        for ch in text:
            if ch.isalpha():
                return bool(_ARABIC_SCRIPT.match(ch)) or "֐" <= ch <= "׿"
        return False
    run_gui.BidiText = BidiText                              # (used by the tests)

    class App(tk.Tk):
        def __init__(self) -> None:
            super().__init__()
            self.title(f"{APP_TITLE} {APP_VERSION}")
            self.geometry(f"1280x{max(640, min(840, self.winfo_screenheight() - 64))}")
            try:                                          # window / taskbar icon (written by the Setup builder)
                ico = LOGO_FILE.parent / "deeptome.ico"
                if ico.is_file():
                    self.iconbitmap(default=str(ico))
            except Exception:
                pass
            self.minsize(1000, 600)
            self.configure(bg=BG)
            self.q: "queue.Queue[tuple]" = queue.Queue()        # fonts / previews (threads)
            self.job_q = None                                   # messages of the translation process
            self.proc = None
            self.t0: Optional[float] = None                       # start of the running job
            self.running = False
            self.err_count = 0
            self.spin_i = 0
            self.dead_ticks = 0
            self.cancel_ev = None
            self.review_ev = None                               # "Translate with review" (shared with the job)
            self.resp_q = None                                  # answers of the review window
            self.review_win = None
            self.eta_left: Optional[float] = None               # remaining seconds (as told by the job)
            self.eta_at = 0.0
            self.logo_frames: List[object] = []
            self.logo_i = 0
            self.protocol("WM_DELETE_WINDOW", self._close)
            self.custom_font: Dict[str, Optional[str]] = {"head": None, "body": None}
            self.pv_token: Dict[str, int] = {"head": 0, "body": 0}
            self.pv_img: Dict[str, object] = {}
            self.pv_lbl: Dict[str, object] = {}
            self._theme()
            self._build()
            self._engine_changed(load=True)
            self._langs_changed(fonts=False)
            self.defaults = self._settings_dict()
            self._apply_settings(load_json(SETTINGS_FILE, {}))
            self.after(700, self._check_pending)
            self.after(100, self._poll)
            self.after(80, self._tick)
            self.after(400, lambda: (self._update_preview("head"), self._update_preview("body")))

        # ------------------------------------------------------------ theme
        def _theme(self) -> None:
            base = tkfont.nametofont("TkDefaultFont")
            base.configure(size=9)
            fam = base.actual("family")
            self.f_title = tkfont.Font(family=fam, size=19, weight="bold")
            self.f_h = tkfont.Font(family=fam, size=10, weight="bold")
            self.f_b = tkfont.Font(family=fam, size=9, weight="bold")
            self.f_s = tkfont.Font(family=fam, size=8)
            st = ttk.Style(self)
            st.theme_use("clam")
            st.configure(".", background=BG, foreground=INK, font=base, bordercolor=LINE, focuscolor=BG)
            st.configure("TFrame", background=BG)
            st.configure("Card.TFrame", background=CARD)
            st.configure("Header.TFrame", background=HDR)
            st.configure("Header.TLabel", background=HDR, foreground="white", font=self.f_title)
            st.configure("HeaderSub.TLabel", background=HDR, foreground="#C7D2FE", font=self.f_s)
            st.configure("Card.TLabel", background=CARD, foreground=INK)
            st.configure("CardBold.TLabel", background=CARD, foreground=INK, font=self.f_b)
            st.configure("CardTitle.TLabel", background=CARD, foreground=ACC, font=self.f_h)
            st.configure("Muted.TLabel", background=CARD, foreground=MUTE, font=self.f_s)
            st.configure("Status.TLabel", background=CARD, foreground=INK, font=self.f_b)
            # every tick box of the app: an empty square, or a square with a filled blue (#3D98FF) square inside
            def _box(inner: str, edge: str) -> "tk.PhotoImage":
                im = tk.PhotoImage(width=20, height=15)        # 5 px of air between the box and its label
                im.put(CARD, to=(0, 0, 20, 15))
                im.put(edge, to=(1, 1, 14, 14))
                im.put("white", to=(2, 2, 13, 13))
                if inner:
                    im.put(inner, to=(4, 4, 11, 11))
                return im
            self._tick_imgs = [_box("", "#64748B"), _box("#3D98FF", "#3D98FF"), _box("", "#CBD5E1"),
                               _box("#A9CFFB", "#CBD5E1")]
            try:
                st.element_create("Tick.indicator", "image", self._tick_imgs[0],
                                  ("disabled", "selected", self._tick_imgs[3]), ("disabled", self._tick_imgs[2]),
                                  ("selected", self._tick_imgs[1]), border=0, sticky="w")
                lay = [("Checkbutton.padding", {"sticky": "nswe", "children": [
                    ("Tick.indicator", {"side": "left", "sticky": ""}),
                    ("Checkbutton.focus", {"side": "left", "sticky": "", "children": [
                        ("Checkbutton.label", {"sticky": "nswe"})]})]})]
                for name in ("TCheckbutton", "Card.TCheckbutton", "Soon.TCheckbutton"):
                    st.layout(name, lay)
                st.configure("TCheckbutton", padding=(1, 1))
            except Exception:
                pass
            st.configure("Card.TCheckbutton", background=CARD, foreground=INK)
            st.map("Card.TCheckbutton", background=[("active", CARD)])
            st.configure("Soon.TCheckbutton", background=CARD, foreground=GREY)
            st.map("Soon.TCheckbutton", background=[("active", CARD), ("disabled", CARD)],
                   foreground=[("disabled", GREY)])
            st.configure("TSeparator", background="#CBD5E1")
            st.configure("TButton", padding=(10, 3), background="#E2E8F0", foreground=INK, borderwidth=0,
                         focusthickness=0)
            st.configure("Eta.TLabel", background=CARD, foreground=ACC, font=self.f_b)
            st.configure("Link.TMenubutton", padding=(4, 0), background=CARD, foreground=MUTE, borderwidth=0,
                         font=self.f_s, arrowcolor=MUTE)
            st.map("Link.TMenubutton", background=[("active", CARD)], foreground=[("active", ACC)])
            st.configure("Icon.TButton", padding=(4, 0), font=("Segoe UI Symbol", 13))
            st.configure("TMenubutton", padding=(9, 6), background="#6366F1", foreground="white", borderwidth=0,
                         font=self.f_s, arrowcolor="white")
            st.map("TMenubutton", background=[("active", "#818CF8")])
            st.configure("Card.TRadiobutton", background=CARD, foreground=INK)
            st.map("Card.TRadiobutton", background=[("active", CARD)])
            st.map("TButton", background=[("active", "#CBD5E1"), ("disabled", "#F1F5F9")],
                   foreground=[("disabled", "#94A3B8")])
            st.configure("Ghost.TButton", padding=(7, 6), background="#6366F1", foreground="white", borderwidth=0,
                         font=self.f_s)
            st.map("Ghost.TButton", background=[("active", "#818CF8")])
            st.configure("Accent.TButton", padding=(18, 7), background="#1BF576", foreground="#052E16",
                         font=self.f_b, borderwidth=0)
            st.map("Accent.TButton", background=[("active", "#5CFA9E"), ("disabled", "#B6F5D0")],
                   foreground=[("disabled", "#64748B")])
            st.configure("TEntry", fieldbackground="white", padding=3)
            st.configure("TCombobox", fieldbackground="white", background="white", padding=2, arrowsize=13)
            st.configure("TSpinbox", fieldbackground="white", padding=2)
            st.configure("Accent.Horizontal.TProgressbar", troughcolor=LINE, background=ACC, bordercolor=LINE,
                         lightcolor=ACC, darkcolor=ACC, thickness=12)
            self.option_add("*TCombobox*Listbox.font", base)

        def _load_logo(self) -> None:
            try:
                if LOGO_FILE.is_file():
                    self.logo_frames = [tk.PhotoImage(file=str(LOGO_FILE))]
            except Exception:
                self.logo_frames = []

        def _card(self, parent, title: str, hint: str = "", expand: bool = False):
            outer = tk.Frame(parent, bg=LINE)
            outer.pack(fill="both" if expand else "x", expand=expand, pady=(0, 1 if parent is self._colL else 4))
            inner = ttk.Frame(outer, style="Card.TFrame", padding=(12, 3, 12, 5))
            inner.pack(fill="both", expand=True, padx=1, pady=1)
            if title or hint:
                head = ttk.Frame(inner, style="Card.TFrame")
                head.pack(fill="x", pady=(0, 3))
                ttk.Label(head, text=title, style="CardTitle.TLabel").pack(side="left")
                if hint:
                    ttk.Label(head, text=hint, style="Muted.TLabel").pack(side="right")
            body = ttk.Frame(inner, style="Card.TFrame")
            body.pack(fill="both", expand=True)
            return body

        def _link(self, parent, url: str, bg: str = BG, fg: str = ACC) -> "tk.Label":
            lab = tk.Label(parent, text=url, fg=fg, bg=bg, cursor="hand2",
                           font=tkfont.Font(family=self.f_s.actual("family"), size=9, underline=True))
            lab.bind("<Button-1>", lambda _e: webbrowser.open(url))
            return lab

        # ----------------------------------------------------------- layout
        def _build(self) -> None:
            hdr = ttk.Frame(self, style="Header.TFrame", padding=(16, 4))
            hdr.pack(fill="x")
            left = ttk.Frame(hdr, style="Header.TFrame")
            left.pack(side="left")
            self._load_logo()
            if self.logo_frames:                      # the animated logo replaces the big title
                self.logo_lbl = tk.Label(left, image=self.logo_frames[0], bg=HDR, borderwidth=0)
                self.logo_lbl.pack(side="left")
            else:
                ttk.Label(left, text=APP_TITLE, style="Header.TLabel").pack(side="left")
            ttk.Label(left, text=APP_SUBTITLE, style="HeaderSub.TLabel", wraplength=230,
                      justify="left").pack(side="left", padx=14)
            right = ttk.Frame(hdr, style="Header.TFrame")
            right.pack(side="right")
            qb = tk.Button(right, text="文A  Quick translate", command=self._quick, relief="flat", bg="#1BF576",
                           fg="#052E16", activebackground="#5CFA9E", font=self.f_b, cursor="hand2", padx=9, pady=4,
                           borderwidth=0)
            qb.pack(side="left", padx=(4, 8))
            mb = ttk.Menubutton(right, text="File")
            fm = tk.Menu(mb, tearoff=0)
            fm.add_command(label="New", command=self._new)
            fm.add_command(label="History …", command=self._history)
            sm = tk.Menu(fm, tearoff=0)
            sm.add_command(label="Components, voices, speech recognition, system …", command=self._settings)
            sm.add_separator()
            sm.add_command(label="Save the current settings as my defaults", command=lambda: self._save_settings(True))
            sm.add_command(label="Reset all settings", command=self._reset_settings)
            sm.add_separator()
            sm.add_command(label="Open the app data folder", command=lambda: (APP_DIR.mkdir(parents=True, exist_ok=True),
                                                                               open_path(str(APP_DIR))))
            fm.add_cascade(label="Settings", menu=sm)
            fm.add_separator()
            fm.add_command(label="Exit", command=self._close)
            mb["menu"] = fm
            mb.pack(side="left", padx=4)
            ttk.Button(right, text="⚙ Settings", style="Ghost.TButton", command=self._settings).pack(side="left", padx=3)
            ttk.Button(right, text="Glossary", style="Ghost.TButton", command=self._glossary).pack(side="left", padx=3)
            ttk.Button(right, text="My instructions", style="Ghost.TButton",
                       command=self._instructions).pack(side="left", padx=3)
            ttk.Button(right, text="Help", style="Ghost.TButton", command=self._help).pack(side="left", padx=3)
            ttk.Button(right, text="About", style="Ghost.TButton", command=self._about).pack(side="left", padx=3)

            # footer: one centred line, nothing else
            foot = ttk.Frame(self)
            foot.pack(side="bottom", fill="x", pady=(0, 4))
            foot_in = ttk.Frame(foot)
            foot_in.pack()
            tk.Label(foot_in, text=f"© {APP_YEAR}  All rights reserved.  |  ", fg=MUTE, bg=BG,
                     font=self.f_s).pack(side="left")
            self._link(foot_in, GITHUB).pack(side="left")

            body = ttk.Frame(self, padding=(14, 3, 14, 0))
            body.pack(fill="both", expand=True)
            body.columnconfigure(0, weight=5, uniform="c")
            body.columnconfigure(1, weight=4, uniform="c")
            body.rowconfigure(0, weight=1)
            wrapL = ttk.Frame(body)
            wrapL.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
            cv = tk.Canvas(wrapL, bg=BG, highlightthickness=0, borderwidth=0)
            sb = ttk.Scrollbar(wrapL, orient="vertical", command=cv.yview)
            colL = ttk.Frame(cv)
            win_id = cv.create_window((0, 0), window=colL, anchor="nw")
            colL.bind("<Configure>", lambda _e: cv.configure(scrollregion=cv.bbox("all")))
            cv.bind("<Configure>", lambda e: cv.itemconfigure(win_id, width=e.width))
            cv.configure(yscrollcommand=sb.set)
            cv.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")

            def _wheel(e) -> None:
                w = self.winfo_containing(e.x_root, e.y_root)
                while w is not None and w is not wrapL:
                    w = getattr(w, "master", None)
                if w is None:
                    return
                d = -1 if (e.num == 4 or getattr(e, "delta", 0) > 0) else 1
                cv.yview_scroll(d, "units")
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.bind_all(seq, _wheel)
            self._colL = colL
            colR = ttk.Frame(body)
            colR.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

            # ---- 1. files + output format
            c1 = self._card(colL, "1 · Files")
            c1.columnconfigure(1, weight=1)
            self.pdf_var, self.out_var, self.pages_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
            ttk.Label(c1, text="Input file", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=1)
            ttk.Entry(c1, textvariable=self.pdf_var).grid(row=0, column=1, sticky="ew", padx=8, pady=1)
            ttk.Button(c1, text="Browse…", command=self._pick_pdf).grid(row=0, column=2, pady=1)
            ttk.Label(c1, text="Save output in", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=1)
            ttk.Entry(c1, textvariable=self.out_var).grid(row=1, column=1, sticky="ew", padx=8, pady=1)
            ttk.Button(c1, text="Browse…", command=self._pick_out).grid(row=1, column=2, pady=1)
            ttk.Label(c1, text="Pages (optional)", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=1)
            fmt = ttk.Frame(c1, style="Card.TFrame")
            fmt.grid(row=2, column=1, columnspan=2, sticky="ew", padx=8, pady=1)
            ttk.Entry(fmt, textvariable=self.pages_var, width=14).pack(side="left")
            ttk.Label(fmt, text='e.g. 1-30, 45 · empty = all', style="Muted.TLabel").pack(side="left", padx=(6, 0))
            self.out_docx = tk.BooleanVar(value=False)
            self.out_txt = tk.BooleanVar(value=False)
            self.out_pdf = tk.BooleanVar(value=True)
            self.cb_pdf = ttk.Checkbutton(fmt, text="PDF", variable=self.out_pdf, style="Card.TCheckbutton")
            self.cb_pdf.pack(side="right")
            self.cb_txt = ttk.Checkbutton(fmt, text="Text (.txt)", variable=self.out_txt, style="Card.TCheckbutton")
            self.cb_txt.pack(side="right", padx=(0, 10))
            self.sub_mode = False                            # a subtitle file is chosen: text output of the same kind
            self.sub_told: Set[str] = set()
            self.pages_entry = fmt.winfo_children()[0]
            docf = ttk.Frame(fmt, style="Card.TFrame")
            docf.pack(side="right", padx=(0, 10))
            ttk.Checkbutton(docf, text="Doc (.docx)", variable=self.out_docx, style="Soon.TCheckbutton",
                            state="disabled").pack(anchor="w")
            ttk.Label(docf, text="coming soon", style="Muted.TLabel",
                      font=(self.f_s.actual("family"), 7)).pack(anchor="e")
            ttk.Label(fmt, text="Output:", style="Card.TLabel").pack(side="right", padx=(0, 8))

            # ---- 2. languages: one row for the origin, one row for the target
            c2 = self._card(colL, "2 · Languages")
            self.lang_vars: Dict[str, "tk.BooleanVar"] = {}
            self.origin_vars: Dict[str, "tk.BooleanVar"] = {}

            def lang_box(parent, store, code: str, name: str, enabled: bool, row: int, col: int,
                         target: bool = False) -> None:
                v = tk.BooleanVar(value=(code == ("fa" if target else "en")))
                store[code] = v                      # exactly one language is ticked in each row (a click selects it)
                cb = ttk.Checkbutton(parent, text=name, variable=v, style="Card.TCheckbutton",
                                     command=(lambda c=code: self._pick_target(c)) if target
                                     else (lambda c=code: self._pick_origin(c)))
                cb.grid(row=row, column=col, sticky="w", padx=(0, 14), pady=1)
                (self.lang_cbs if target else self.origin_cbs)[code] = cb

            self.lang_cbs: Dict[str, object] = {}
            self.origin_cbs: Dict[str, object] = {}
            ttk.Label(c2, text="Origin language:", style="CardBold.TLabel").grid(row=0, column=0, sticky="w",
                                                                                 padx=(0, 12))
            for code, _name, _on in ORIGIN_LANGS:              # found by the app itself after a file was chosen
                self.origin_vars[code] = tk.BooleanVar(value=(code == "en"))
            orow = ttk.Frame(c2, style="Card.TFrame")
            orow.grid(row=0, column=1, columnspan=6, sticky="ew", pady=1)
            self.origin_lbl = ttk.Label(orow, text="choose a PDF or a subtitle file – the app finds its language itself",
                                        style="Muted.TLabel")
            self.origin_lbl.pack(side="left")
            self.origin_fix = ttk.Menubutton(orow, text="wrong?", style="Link.TMenubutton")
            om = tk.Menu(self.origin_fix, tearoff=0)
            for code, name, _on in ORIGIN_LANGS:
                om.add_command(label=f"The file is {name}", command=lambda c=code: self._origin_by_hand(c))
            self.origin_fix["menu"] = om
            self.file_info: dict = {}
            self._stats_job = None
            self._stats_seq = 0
            self.pdf_var.trace_add("write", lambda *_a: self._stats_later())
            ttk.Label(c2, text="Target language:", style="CardBold.TLabel").grid(row=1, column=0, sticky="w",
                                                                                 padx=(0, 12))
            for i, (code, name, on) in enumerate(TARGET_LANGS):
                lang_box(c2, self.lang_vars, code, name, on, 1, i + 1, True)
            self.lang_note = ttk.Label(c2, text="", style="Muted.TLabel")
            self.lang_note.grid(row=2, column=0, columnspan=6, sticky="w")

            # ---- 3. engine + fonts
            c3 = self._card(colL, "3 · Engine and fonts")
            c3.columnconfigure(1, weight=1)
            ttk.Label(c3, text="Translation engine", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=1)
            self.engine_var = tk.StringVar(value=ENGINE_LABELS["local"])
            ecb = ttk.Combobox(c3, textvariable=self.engine_var, values=list(ENGINE_LABELS.values()),
                               state="readonly")
            ecb.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=1)
            ecb.bind("<<ComboboxSelected>>", lambda _e: self._engine_changed())
            # -- built-in engine
            self.eng_rows: Dict[str, list] = {"local": [], "llm": [], "key": []}
            w = ttk.Label(c3, text="AI model", style="Card.TLabel")
            w.grid(row=1, column=0, sticky="w", pady=1)
            self.model_var = tk.StringVar(value=list(MODELS)[0])
            w2 = ttk.Combobox(c3, textvariable=self.model_var, values=list(MODELS), width=52)
            w2.grid(row=1, column=1, sticky="ew", padx=8)
            w3 = ttk.Button(c3, text="Folder…", command=self._pick_model)
            w3.grid(row=1, column=2)
            self.eng_rows["local"] += [w, w2, w3]
            # -- Ollama / online API
            self.llm_model_var, self.llm_url_var, self.llm_key_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
            self.llm_store = {"ollama": {"model": OLLAMA_SUGGESTED[0], "url": "http://localhost:11434", "key": ""},
                              "api": {"model": "", "url": LLM_DEFAULT_URL["api"], "key": ""}}
            w = ttk.Label(c3, text="LLM model", style="Card.TLabel")
            w.grid(row=2, column=0, sticky="w", pady=1)
            self.llm_cb = ttk.Combobox(c3, textvariable=self.llm_model_var, values=OLLAMA_SUGGESTED)
            self.llm_cb.grid(row=2, column=1, sticky="ew", padx=8)
            w3 = ttk.Button(c3, text="List models", command=lambda: self._llm_refresh(True))
            w3.grid(row=2, column=2)
            self.eng_rows["llm"] += [w, self.llm_cb, w3]
            w = ttk.Label(c3, text="Server address", style="Card.TLabel")
            w.grid(row=3, column=0, sticky="w", pady=1)
            w2 = ttk.Entry(c3, textvariable=self.llm_url_var)
            w2.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(8, 0))
            self.eng_rows["llm"] += [w, w2]
            w = ttk.Label(c3, text="API key", style="Card.TLabel")
            w.grid(row=4, column=0, sticky="w", pady=1)
            w2 = ttk.Entry(c3, textvariable=self.llm_key_var, show="•")
            w2.grid(row=4, column=1, columnspan=2, sticky="ew", padx=(8, 0))
            self.eng_rows["key"] += [w, w2]
            self.llm_note = ttk.Label(c3, text="", style="Muted.TLabel", wraplength=640, justify="left")
            self.llm_note.grid(row=5, column=0, columnspan=3, sticky="w")
            self.eng_rows["llm"].append(self.llm_note)

            self.head_var = tk.StringVar(value=DEFAULT_FA_FONT)        # Persian target -> B Yaghout for both
            self.body_var = tk.StringVar(value=DEFAULT_FA_FONT)
            values = PERSIAN_FONTS + [CUSTOM_FONT_LABEL]
            self.font_cbs: Dict[str, object] = {}
            for r0, (which, label, var) in enumerate((("head", "Heading font", self.head_var),
                                                      ("body", "Body text font", self.body_var))):
                ttk.Label(c3, text=label, style="Card.TLabel").grid(row=6 + r0, column=0, sticky="w", pady=0)
                line = ttk.Frame(c3, style="Card.TFrame")
                line.grid(row=6 + r0, column=1, columnspan=2, sticky="ew", padx=8, pady=0)
                cb = ttk.Combobox(line, textvariable=var, values=values, state="readonly", width=20)
                cb.pack(side="left")
                self.font_cbs[which] = cb
                cb.bind("<<ComboboxSelected>>", lambda _e, w=which: self._font_changed(w))
                cvs = tk.Canvas(line, width=300, height=27, bg="white", highlightthickness=1,
                                highlightbackground=LINE, xscrollincrement=24)
                cvs.pack(side="left", padx=(8, 0), fill="x", expand=True)
                for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):     # wheel = scroll left / right
                    cvs.bind(seq, lambda e, c=cvs: self._sample_wheel(e, c))
                self.pv_lbl[which] = cvs
            self.font_note = ttk.Label(c3, text="", style="Muted.TLabel")
            ttk.Label(c3, text="Font size factor", style="Card.TLabel").grid(row=8, column=0, sticky="w", pady=1)
            sc = ttk.Frame(c3, style="Card.TFrame")
            sc.grid(row=8, column=1, columnspan=2, sticky="ew", padx=8, pady=1)
            self.fscale_var = tk.IntVar(value=100)
            ttk.Spinbox(sc, from_=30, to=300, increment=5, textvariable=self.fscale_var, width=5).pack(side="left")
            ttk.Label(sc, text="%", style="Muted.TLabel").pack(side="left", padx=(3, 14))
            self.speed_var = tk.StringVar(value="accurate")     # the old "Mode" switch is gone: Best quality replaces it
            ttk.Button(sc, text="Check fonts", command=self._fetch_fonts).pack(side="right")
            self.o: Dict[str, tk.BooleanVar] = {"dl": tk.BooleanVar(value=True)}
            self.o_cb: Dict[str, object] = {}
            self.o_cb["dl"] = ttk.Checkbutton(sc, text="Allow downloads", variable=self.o["dl"],
                                              style="Card.TCheckbutton")
            self.o_cb["dl"].pack(side="right", padx=(0, 10))

            # ---- 4. options
            c4 = self._card(colL, "4 · Options")
            for col in range(3):
                c4.columnconfigure(col, weight=1, uniform="opt")
            checks = [("terms", "Keep technical terms unchanged", True),
                      ("names", "Keep names & Capitalized terms", True),
                      ("auto", "Keep acronyms, units, formulas", True),
                      ("figs", "Keep figure labels unchanged", True),
                      ("code", "Keep code blocks unchanged", True),
                      ("tables", "Translate inside tables", False),
                      ("back", "Translate references / appendices", False),
                      ("caps", "Don't translate captions", False),
                      ("bm", "Don't translate bookmarks", False),
                      ("justify", "Justify body text", True),
                      ("bilingual", "English heading in brackets", True),
                      ("digits", "Persian digits (۰۱۲۳)", True),
                      ("rtl", "Right-To-Left direction", True), ("align", "Align Right", True),
                      ("swap", "Swap the 2 columns (RTL ↔ LTR)", True)]
            for i, (k, t, d) in enumerate(checks):
                self.o[k] = tk.BooleanVar(value=d)
                cb = ttk.Checkbutton(c4, text=t, variable=self.o[k], style="Card.TCheckbutton")
                cb.grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 6), pady=0)
                self.o_cb[k] = cb
            r = (len(checks) + 2) // 3
            last = ttk.Frame(c4, style="Card.TFrame")
            last.grid(row=r, column=0, columnspan=3, sticky="ew", pady=(1, 0))
            ttk.Label(last, text="Auto-shrink limit (%)", style="Card.TLabel").pack(side="left")
            self.scale_var = tk.IntVar(value=50)
            ttk.Spinbox(last, from_=20, to=100, increment=5, textvariable=self.scale_var, width=5).pack(
                side="left", padx=(6, 14))
            ttk.Label(last, text="Back-matter keywords", style="Card.TLabel").pack(side="left")
            self.kw_var = tk.StringVar(value=Options().backmatter_keywords)
            ttk.Entry(last, textvariable=self.kw_var).pack(side="left", fill="x", expand=True, padx=(6, 0))

            # ---- 5. specialty of the text (left column, under the options)
            c8 = self._card(colL, "")
            c8.columnconfigure(1, weight=1)
            ttk.Label(c8, text="5 · Text specialty", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
            self.spec_var = tk.StringVar(value="")
            ent = ttk.Entry(c8, textvariable=self.spec_var)
            ent.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(10, 0))
            ent.bind("<KeyRelease>", lambda _e: self._spec_changed())
            self.auto_spec = tk.BooleanVar(value=True)
            ttk.Checkbutton(c8, text="Also detect the subject", variable=self.auto_spec,
                            style="Card.TCheckbutton").grid(row=1, column=0, sticky="w", pady=(2, 0))
            self.spec_info = ttk.Label(c8, text="up to 4 fields, comma separated – e.g.  Chemistry, AI",
                                       style="Muted.TLabel")
            self.spec_info.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=(2, 0))
            ttk.Button(c8, text="Terminology folder", command=self._open_terms).grid(row=1, column=2, sticky="e",
                                                                                     pady=(2, 0))

            # ---- run + workload chart + log (right)
            c5 = self._card(colR, "")
            self.start_btn = ttk.Button(c5, text="▶  RUN", style="Accent.TButton", command=self._start)
            self.start_btn.pack(side="left")
            self.review_var = tk.BooleanVar(value=False)
            self.o["quality"] = tk.BooleanVar(value=False)
            ticks = ttk.Frame(c5, style="Card.TFrame")
            ticks.pack(side="left", padx=(12, 0))
            self.o_cb["quality"] = ttk.Checkbutton(ticks, text="Best quality (2× slower)", variable=self.o["quality"],
                                                   style="Card.TCheckbutton")
            self.o_cb["quality"].pack(anchor="w")
            self.o["review_terms"] = tk.BooleanVar(value=True)
            self.o_cb["review_terms"] = ttk.Checkbutton(ticks, text="Review terms before start",
                                                        variable=self.o["review_terms"], style="Card.TCheckbutton")
            self.o_cb["review_terms"].pack(anchor="w")
            ttk.Checkbutton(ticks, text="Translate with review (edit every part)",
                            variable=self.review_var, style="Card.TCheckbutton",
                            command=self._review_toggled).pack(anchor="w")
            self.cancel_btn = ttk.Button(c5, text="Cancel", command=self._cancel, state="disabled")
            self.cancel_btn.pack(side="right")
            self.sound_on = tk.BooleanVar(value=True)
            self.sound_btn = ttk.Button(c5, text="🔊", width=3, style="Icon.TButton", command=self._toggle_sound)
            self.sound_btn.pack(side="right", padx=(0, 6))
            c5b = ttk.Frame(c5.master, style="Card.TFrame")
            c5b.pack(fill="x", pady=(6, 0))
            line1 = ttk.Frame(c5b, style="Card.TFrame")
            line1.pack(fill="x")
            self.eta_lbl = ttk.Label(line1, text="", style="Eta.TLabel")
            self.eta_lbl.pack(side="right")                       # glued to the right margin
            self.status = ttk.Label(line1, text="Ready", style="Status.TLabel")
            self.status.pack(side="left")
            self.eta_note = ttk.Label(c5b, text="", style="Muted.TLabel")
            self.eta_note.pack(anchor="w")
            self.pb = ttk.Progressbar(c5b, maximum=1000, style="Accent.Horizontal.TProgressbar")
            self.pb.pack(fill="x", pady=(4, 0))

            # ---- live workload chart: which part of the file needs the most work (like a heart monitor)
            c9 = self._card(colR, "Workload", "translation complexity of each page")
            self.load_cv = tk.Canvas(c9, height=92, bg="#0F172A", highlightthickness=1,
                                     highlightbackground="#334155")
            self.load_cv.pack(fill="x")
            self.load_cv.bind("<Configure>", lambda _e: self._draw_load())
            self.load_cv.bind("<ButtonPress-1>", lambda e: self._load_drag(e, True))
            self.load_cv.bind("<B1-Motion>", self._load_drag)
            self.load_cv.bind("<Double-Button-1>", self._load_resume)
            self.load_cv.bind("<MouseWheel>", self._load_wheel)
            self.load_cv.config(cursor="sb_h_double_arrow")
            self._load_reset()

            c6 = self._card(colR, "Log", expand=True)
            # fixed bar at the top of the log: it stays visible while the log below scrolls
            bar = tk.Frame(c6, bg="#0F172A", highlightbackground="#334155", highlightthickness=1)
            bar.pack(fill="x", pady=(0, 6))
            row1 = tk.Frame(bar, bg="#0F172A")
            row1.pack(fill="x", padx=10, pady=(6, 0))
            self.spin = tk.Canvas(row1, width=92, height=22, bg="#0F172A", highlightthickness=0)
            self.spin.pack(side="left")
            tk.Label(row1, text="Progressing", bg="#0F172A", fg="#F8FAFC", font=self.f_b).pack(side="left", padx=(6, 0))
            self.elapsed_lbl = tk.Label(row1, text="00:00:00  Elapsed time", bg="#0F172A", fg="#86EFAC",
                                        font=self.f_b)
            self.elapsed_lbl.pack(side="right")                         # glued to the right edge
            row2 = tk.Frame(bar, bg="#0F172A")
            row2.pack(fill="x", padx=10, pady=(2, 6))
            self.err_lbl = tk.Label(row2, text="Errors / warnings: 0", bg="#0F172A", fg="#7DD3FC", font=self.f_s)
            self.err_lbl.pack(anchor="w")
            self.phase_lbl = tk.Label(row2, text="Waiting for a file …", bg="#0F172A", fg="#F8FAFC", font=self.f_s,
                                      anchor="w", justify="left", wraplength=520)
            self.phase_lbl.pack(anchor="w", fill="x")
            self.log_box = ScrolledText(c6, state="disabled", wrap="word", relief="flat", borderwidth=0,
                                        bg="#0F172A", fg="#E2E8F0", insertbackground="white",
                                        font="TkFixedFont", padx=10, pady=8)
            self.log_box.pack(fill="both", expand=True)
            self.log_box.tag_config("err", foreground="#FCA5A5")
            self.log_box.tag_config("ok", foreground="#86EFAC")
            self.log_box.tag_config("hd", foreground="#A5B4FC")
            self.log_box.tag_config("act_h", foreground="#86EFAC")      # headings / titles (green)
            self.log_box.tag_config("act_b", foreground="#7DD3FC")      # actions, moves (blue)
            self.log_box.tag_config("act_w", foreground="#F8FAFC")      # body text (white)
            self._make_log_copyable()
            self._log(f"{APP_TITLE} {APP_VERSION} (build {APP_BUILD}) ready. Tip: test with pages 1-10 first.")

        def _make_log_copyable(self) -> None:
            """The log is read-only but everything in it can be selected and copied (mouse, Ctrl+C, Ctrl+A, menu)."""
            box = self.log_box

            def copy(_e=None):
                try:
                    txt = box.get("sel.first", "sel.last")
                except tk.TclError:
                    txt = box.get("1.0", "end-1c")           # nothing selected: copy the whole log
                self.clipboard_clear()
                self.clipboard_append(txt)
                return "break"

            def select_all(_e=None):
                box.tag_add("sel", "1.0", "end-1c")
                return "break"

            menu = tk.Menu(box, tearoff=0)
            menu.add_command(label="Copy", command=copy)
            menu.add_command(label="Select all", command=select_all)
            box.bind("<Button-1>", lambda _e: box.focus_set(), add="+")      # a disabled Text needs focus for Ctrl+C
            for seq in ("<Control-c>", "<Control-C>", "<Command-c>", "<Control-Insert>"):
                box.bind(seq, copy)
            for seq in ("<Control-a>", "<Control-A>", "<Command-a>"):
                box.bind(seq, select_all)
            box.bind("<Button-3>", lambda e: (box.focus_set(), menu.tk_popup(e.x_root, e.y_root)))
            box.bind("<Button-2>", lambda e: (box.focus_set(), menu.tk_popup(e.x_root, e.y_root)))
            for lbl in (self.phase_lbl, self.err_lbl):          # the status texts above the log can be copied too
                lbl.bind("<Button-3>", lambda e, w=lbl: (self.clipboard_clear(), self.clipboard_append(w.cget("text"))))

        # --------------------------------------------------------- actions
        def _about(self) -> None:
            if self._single("about"):
                return
            win = tk.Toplevel(self)
            self._keep("about", win)
            win.title("About")
            win.configure(bg=BG)
            win.resizable(False, False)
            box = tk.Frame(win, bg=BG, padx=36, pady=24)
            box.pack()
            tk.Label(box, text=APP_TITLE, bg=BG, fg=ACC, font=self.f_title).pack()
            tk.Label(box, text=f"Version {APP_VERSION}   ·   build {APP_BUILD}", bg=BG, fg=INK,
                     font=self.f_h).pack(pady=(6, 0))
            tk.Label(box, text="This software may not be copied, changed or sold without the written permission of\n"
                               "its creator. Third-party components keep their own licences (see LICENSE.txt and\n"
                               "THIRD_PARTY_NOTICES.txt in the program folder).", bg=BG, fg=MUTE, font=self.f_s,
                     justify="center").pack(pady=(10, 0))
            tk.Frame(box, bg=LINE, height=1, width=360).pack(pady=(14, 8))
            tk.Label(box, text=APP_COPYRIGHT, bg=BG, fg=INK,                 # smaller, under the text
                     font=(self.f_s.actual("family"), 8, "bold")).pack(pady=(0, 3))
            self._link(box, GITHUB).pack()
            ttk.Button(box, text="Close", command=win.destroy).pack(pady=(16, 0))

        def _help(self) -> None:
            if self._single("help"):
                return
            win = tk.Toplevel(self)
            self._keep("help", win)
            win.title("Help")
            h = max(420, min(720, int(self.winfo_screenheight() * 0.8)))
            win.geometry(f"1040x{h}")
            win.minsize(700, 340)
            win.configure(bg=BG)
            glang = tk.StringVar(value=load_json(SETTINGS_FILE, {}).get("help_lang", "en")
                                 if isinstance(load_json(SETTINGS_FILE, {}), dict) else "en")
            if glang.get() not in GUIDE_LANGS:
                glang.set("en")
            topbar = ttk.Frame(win, padding=(12, 8, 12, 0))
            topbar.pack(fill="x")
            lang_lbl = ttk.Label(topbar, text="", font=self.f_b)
            lang_lbl.pack(side="left")
            for code, name in GUIDE_LANGS.items():
                ttk.Radiobutton(topbar, text=name, value=code, variable=glang,
                                command=lambda: fill_guide()).pack(side="left", padx=(10, 0))
            nb = ttk.Notebook(win)
            nb.pack(fill="both", expand=True, padx=10, pady=10)
            tab_g, tab_r = ttk.Frame(nb), ttk.Frame(nb)
            nb.add(tab_g, text="Quick guide")
            nb.add(tab_r, text="Full reference")
            gcv = tk.Canvas(tab_g, bg="white", highlightthickness=0)
            gsb = ttk.Scrollbar(tab_g, orient="vertical", command=gcv.yview)
            gcv.configure(yscrollcommand=gsb.set)
            gsb.pack(side="right", fill="y")
            gcv.pack(fill="both", expand=True)
            ginner = tk.Frame(gcv, bg="white")
            gwin = gcv.create_window((0, 0), window=ginner, anchor="nw")
            ginner.bind("<Configure>", lambda _e: gcv.configure(scrollregion=gcv.bbox("all")))
            gcv.bind("<Configure>", lambda e: (gcv.itemconfigure(gwin, width=e.width), wrap_guide(e.width)))
            glabels: List = []
            gimgs: List = []                              # pictures of the Persian text (kept alive)

            def wrap_guide(wd: int) -> None:
                for lab in glabels:
                    lab.config(wraplength=max(240, wd - 400))

            def gwheel(e) -> str:
                gcv.yview_scroll(-1 if e.delta > 0 else 1, "units")
                return "break"

            def fill_guide() -> None:
                lg = glang.get()
                ui = GUIDE_UI[lg]
                nb.tab(0, text=ui[0])
                nb.tab(1, text=ui[1])
                lang_lbl.config(text=ui[2])
                rtl_ = lg == "fa"
                for ch in ginner.winfo_children():
                    ch.destroy()
                glabels.clear()
                gimgs.clear()
                win.update_idletasks()
                fam_ = "Tahoma" if rtl_ else self.f_s.actual("family")
                for key, texts in GUIDE_STEPS:
                    title, body = texts.get(lg) or texts["en"]
                    row = tk.Frame(ginner, bg="white")
                    row.pack(fill="x", padx=16, pady=(14, 4))
                    pic = tk.Canvas(row, width=320, height=190, bg="white", highlightthickness=0)
                    draw_guide_picture(pic, key)
                    pic.pack(side="right" if not rtl_ else "left", padx=(16, 0) if not rtl_ else (0, 16))
                    txt = tk.Frame(row, bg="white")
                    txt.pack(side="left" if not rtl_ else "right", fill="both", expand=True)
                    png = render_rtl_text(title, body, max(420, (gcv.winfo_width() if gcv.winfo_width() > 200 else 1000) - 400)) if rtl_ else None
                    if png:
                        im = tk.PhotoImage(data=base64.b64encode(png).decode("ascii"))
                        gimgs.append(im)
                        il = tk.Label(txt, image=im, bg="white", anchor="ne")
                        il.pack(fill="x")
                        tk.Frame(ginner, bg="#E2E8F0", height=1).pack(fill="x", padx=16)
                        for w_ in (row, pic, txt, il):
                            w_.bind("<MouseWheel>", gwheel)
                        continue
                    tk.Label(txt, text=title, bg="white", fg=ACC, font=(fam_, 13, "bold"),
                             anchor="e" if rtl_ else "w", justify="right" if rtl_ else "left").pack(fill="x")
                    lab = tk.Label(txt, text=body, bg="white", fg=INK, font=(fam_, 11), wraplength=560,
                                   anchor="ne" if rtl_ else "nw", justify="right" if rtl_ else "left")
                    lab.pack(fill="x", pady=(6, 0))
                    glabels.append(lab)
                    tk.Frame(ginner, bg="#E2E8F0", height=1).pack(fill="x", padx=16)
                    for w_ in (row, pic, txt, lab):
                        w_.bind("<MouseWheel>", gwheel)
                wrap_guide(gcv.winfo_width())
                gcv.yview_moveto(0)
                try:
                    d_ = load_json(SETTINGS_FILE, {})
                    if isinstance(d_, dict) and d_.get("help_lang") != lg:
                        d_["help_lang"] = lg
                        save_json(SETTINGS_FILE, d_)
                except Exception:
                    pass

            gcv.bind("<MouseWheel>", gwheel)
            fill_guide()
            box = ScrolledText(tab_r, wrap="word", relief="flat", padx=14, pady=12, font="TkFixedFont")
            box.pack(fill="both", expand=True)
            head, _sep, tail = HELP_TEXT.partition("Contact me:")
            box.insert("1.0", head)
            fam = tkfont.nametofont("TkFixedFont").actual("family")
            box.tag_config("rule", foreground=INK)
            box.tag_config("contact", font=tkfont.Font(family=fam, size=15, weight="bold"), foreground=INK)
            box.tag_config("link", foreground=ACC, underline=True,
                           font=tkfont.Font(family=fam, size=12, weight="bold"))
            box.insert("end", "━" * 70 + "\n", "rule")                      # a line before "Contact me"
            box.insert("end", "Contact me:\n", "contact")
            box.insert("end", tail.lstrip("\n"))
            for m in re.finditer(r"https?://\S+|[\w.+-]+@[\w-]+\.[\w.]+", tail):   # clickable addresses
                start = box.search(m.group(), "end-1c", backwards=True, stopindex="1.0")
                if start:
                    box.tag_add("link", start, f"{start}+{len(m.group())}c")

            def open_link(e) -> None:
                idx = box.index(f"@{e.x},{e.y}")
                rng = box.tag_prevrange("link", idx + "+1c")
                if rng:
                    target = box.get(*rng)
                    webbrowser.open(target if "://" in target else "mailto:" + target)
            box.tag_bind("link", "<Button-1>", open_link)
            box.tag_bind("link", "<Enter>", lambda _e: box.config(cursor="hand2"))
            box.tag_bind("link", "<Leave>", lambda _e: box.config(cursor=""))
            box.configure(state="disabled")

        def _list_dates(self, which: str) -> dict:
            d = load_json(APP_DIR / "list_dates.json", {})
            return d.get(which, {}) if isinstance(d, dict) else {}

        def _set_list_dates(self, which: str, dates: dict) -> None:
            d = load_json(APP_DIR / "list_dates.json", {})
            d = d if isinstance(d, dict) else {}
            d[which] = dates
            save_json(APP_DIR / "list_dates.json", d)

        def _glossary(self) -> None:
            """Your own terms that always stay in the original language.  Every term is a line of the list: click it
            to see it, change it or delete it.  Every change is saved at once."""
            if self._single("glossary"):
                return
            win = tk.Toplevel(self)
            self._keep("glossary", win)
            win.title("Glossary – terms kept as they are")
            win.geometry("760x600")
            win.minsize(560, 420)
            win.configure(bg=BG)
            ttk.Label(win, text="Your own terms that are never translated (they stay as they are written). The ≈600 "
                                "built-in technical terms and the automatic detection are always active as well.",
                      foreground=MUTE, background=BG, wraplength=720, justify="left").pack(anchor="w", padx=14,
                                                                                           pady=(12, 6))
            top = ttk.Frame(win)
            top.pack(fill="x", padx=14)
            ttk.Label(top, text="New term:").pack(side="left")
            ent = BidiText(top, multiline=False, font=("Tahoma", 11), height=30,
                           on_key=lambda vk, c, s: (vk == 0x0D and (win.after(1, add) or True)))
            ent.pack(side="left", fill="x", expand=True, padx=8)
            ttk.Button(top, text="Add", style="Accent.TButton", command=lambda: add()).pack(side="left")
            raw = load_user_terms()
            comments = [ln for ln in raw.splitlines() if ln.strip().startswith("#")]
            terms: List[str] = []
            for ln in raw.splitlines():
                if ln.strip() and not ln.strip().startswith("#"):
                    for t_ in ln.split(","):
                        if t_.strip() and t_.strip() not in terms:
                            terms.append(t_.strip())
            dates = self._list_dates("glossary")
            lf = ttk.Frame(win)
            lf.pack(fill="both", expand=True, padx=14, pady=8)
            tv = ttk.Treeview(lf, columns=("term", "date"), show="headings", selectmode="extended")
            tv.heading("term", text=f"Your terms")
            tv.heading("date", text="Added")
            tv.column("term", width=520)
            tv.column("date", width=130, stretch=False)
            sb_ = ttk.Scrollbar(lf, orient="vertical", command=tv.yview)
            tv.configure(yscrollcommand=sb_.set)
            sb_.pack(side="right", fill="y")
            tv.pack(fill="both", expand=True)
            edit = ttk.Frame(win)
            edit.pack(fill="x", padx=14)
            ttk.Label(edit, text="Selected:").pack(side="left")
            ed = BidiText(edit, multiline=False, font=("Tahoma", 11), height=30,
                          on_key=lambda vk, c, s: (vk == 0x0D and (win.after(1, update) or True)))
            ed.pack(side="left", fill="x", expand=True, padx=8)
            ttk.Button(edit, text="Save change", command=lambda: update()).pack(side="left")
            ttk.Button(edit, text="Delete", command=lambda: delete()).pack(side="left", padx=(6, 0))
            row = ttk.Frame(win)
            row.pack(fill="x", padx=14, pady=(8, 12))
            note = ttk.Label(row, text="", foreground=MUTE)
            note.pack(side="left")

            def fill(sel: Optional[str] = None) -> None:
                tv.delete(*tv.get_children())
                for i, t_ in enumerate(terms):
                    tv.insert("", "end", iid=str(i), values=(t_, dates.get(t_, "")))
                tv.heading("term", text=f"Your terms ({len(terms)})")
                if sel is not None and sel in terms:
                    k = str(terms.index(sel))
                    tv.selection_set(k)
                    tv.see(k)

            def store(msg: str) -> None:
                save_user_terms("\n".join(comments + terms) + "\n")
                self._set_list_dates("glossary", {t_: dates[t_] for t_ in terms if t_ in dates})
                note.config(text=msg + "   ·   saved ✓")

            def add() -> None:
                new = [t_.strip() for t_ in ent.get().replace("\n", ",").split(",") if t_.strip()]
                added = [t_ for t_ in new if t_ not in terms]
                for t_ in added:
                    terms.append(t_)
                    dates[t_] = time.strftime("%Y-%m-%d %H:%M")
                ent.clear()
                fill(added[-1] if added else (new[-1] if new else None))
                store(f"{len(added)} term(s) added" if added else "Already in the list")
                ent.focus()

            def current() -> List[int]:
                return sorted(int(s_) for s_ in tv.selection())

            def on_select(_e=None) -> None:
                c_ = current()
                ed.set(terms[c_[0]] if len(c_) == 1 else "")

            def update() -> None:
                c_ = current()
                new = ed.get().strip()
                if len(c_) != 1 or not new:
                    note.config(text="Select one term in the list first.")
                    return
                old = terms[c_[0]]
                terms[c_[0]] = new
                dates[new] = dates.pop(old, time.strftime("%Y-%m-%d %H:%M"))
                fill(new)
                store("Term changed")

            def delete() -> None:
                c_ = current()
                if not c_:
                    note.config(text="Select one or more terms in the list first.")
                    return
                for i in reversed(c_):
                    dates.pop(terms[i], None)
                    del terms[i]
                ed.clear()
                fill()
                store(f"{len(c_)} term(s) deleted")

            def delete_all() -> None:
                if terms and messagebox.askyesno("Glossary", f"Delete all {len(terms)} terms?", parent=win,
                                                 default="no"):
                    terms.clear()
                    dates.clear()
                    fill()
                    store("All terms deleted")

            def show_builtin() -> None:
                if self._single("builtin_terms"):
                    return
                b = tk.Toplevel(win)
                self._keep("builtin_terms", b)
                b.title("Built-in terms")
                b.geometry("620x520")
                bx = ScrolledText(b, wrap="word", padx=10, pady=8)
                bx.pack(fill="both", expand=True)
                bx.insert("1.0", BUILTIN_TERMS.strip())
                bx.configure(state="disabled")

            tv.bind("<<TreeviewSelect>>", on_select)
            tv.bind("<Delete>", lambda _e: delete())
            ttk.Button(row, text="Close", command=win.destroy).pack(side="right")
            ttk.Button(row, text="Delete all", command=delete_all).pack(side="right", padx=6)
            ttk.Button(row, text="Show built-in terms", command=show_builtin).pack(side="right")
            fill()
            win.after(100, ent.focus)

        # ------------------------------------------------- one window of each kind
        def _single(self, name: str):
            """The window of this kind if it is open already (brought to the front), else None."""
            if not hasattr(self, "_wins"):
                self._wins = {}
            w = self._wins.get(name)
            if w is not None:
                try:
                    if w.winfo_exists():
                        w.deiconify()
                        w.lift()
                        w.focus_force()
                        return w
                except Exception:
                    pass
                self._wins.pop(name, None)
            return None

        def _keep(self, name: str, win) -> None:
            if not hasattr(self, "_wins"):
                self._wins = {}
            self._wins[name] = win

        # ------------------------------------------------- Settings: everything that is installed
        def _settings(self, tab: str = "components") -> None:
            """What is installed and what is not (engines, models, voices, speech recognition), install or remove
            every part with one click, choose the voices, and the facts of this computer."""
            old = self._single("settings")
            if old is not None:
                try:
                    old._nb.select(old._tabs.get(tab, 0))
                except Exception:
                    pass
                return
            win = tk.Toplevel(self)
            self._keep("settings", win)
            win.title("Settings – components, voices, speech recognition, system")
            win.geometry(f"1060x{max(560, min(720, self.winfo_screenheight() - 120))}")
            win.minsize(820, 480)
            win.configure(bg=BG)
            nb = ttk.Notebook(win)
            nb.pack(fill="both", expand=True, padx=10, pady=(10, 4))
            win._nb = nb
            t_comp, t_voice, t_speech, t_sys = (ttk.Frame(nb, padding=8) for _ in range(4))
            nb.add(t_comp, text="  Components (installed / not installed)  ")
            nb.add(t_voice, text="  Voices  ")
            nb.add(t_speech, text="  Speech recognition (microphone, live)  ")
            nb.add(t_sys, text="  System information  ")
            win._tabs = {"components": 0, "voices": 1, "speech": 2, "system": 3}
            # ---- the work area at the bottom: what is being installed
            work = ttk.Frame(win, padding=(10, 0, 10, 8))
            work.pack(fill="x")
            wl = ttk.Frame(work)
            wl.pack(fill="x")
            work_lbl = ttk.Label(wl, text="", font=self.f_b)
            work_lbl.pack(side="left")
            ttk.Button(wl, text="Close", command=win.destroy).pack(side="right")
            pb = ttk.Progressbar(work, maximum=1000, style="Accent.Horizontal.TProgressbar")
            pb.pack(fill="x", pady=(4, 2))
            logb = ScrolledText(work, height=5, font="TkFixedFont", relief="flat", bg="#0F172A", fg="#E2E8F0",
                                state="disabled")
            logb.pack(fill="x")
            busy = {"on": False}

            def wlog(msg: str) -> None:
                logb.config(state="normal")
                logb.insert("end", msg + "\n")
                logb.see("end")
                logb.config(state="disabled")

            def task(title: str, fn, after=None) -> None:
                """Runs an installation in the background; the window stays usable."""
                if busy["on"]:
                    messagebox.showinfo("Settings", "Another installation is running – please wait until it has "
                                                    "finished.", parent=win)
                    return
                busy["on"] = True
                work_lbl.config(text="⏳ " + title + " …")
                pb.config(mode="indeterminate")
                pb.start(12)
                wlog("━━ " + title)

                def run() -> None:
                    err = ""
                    try:
                        fn(lambda m: self.q.put(("comp", "log", m)),
                           lambda f: self.q.put(("comp", "progress", f)))
                    except Exception as exc:                  # noqa: BLE001
                        err = f"{type(exc).__name__}: {exc}"
                    self.q.put(("comp", "done", title, err, after))
                threading.Thread(target=run, daemon=True).start()

            def event(kind: str, *a) -> None:
                try:
                    if not win.winfo_exists():
                        return
                except Exception:
                    return
                if kind == "log":
                    wlog(a[0])
                elif kind == "progress":
                    pb.stop()
                    pb.config(mode="determinate", value=int(a[0] * 1000))
                elif kind == "done":
                    title, err, after = a
                    busy["on"] = False
                    pb.stop()
                    pb.config(mode="determinate", value=0 if err else 1000)
                    work_lbl.config(text=("✖ " + title + " – failed: " + err[:120]) if err else ("✔ " + title + " – done"))
                    wlog(("ERROR: " + err) if err else "Done.")
                    refresh()
                    if after:
                        after()
                elif kind == "winvoices":
                    st_["winvoices"] = a[0]
                    refresh()
            self._settings_event = event

            # ================================================= Components
            ttk.Label(t_comp, text="Everything the translator can use. Select a line and press Install or Remove. "
                                   "Downloads go to the app data folder; nothing needs administrator rights.",
                      foreground=MUTE).pack(anchor="w", pady=(0, 6))
            cols = ("status", "size", "use")
            tv = ttk.Treeview(t_comp, columns=cols, show="tree headings", selectmode="browse")
            tv.heading("#0", text="Component")
            tv.heading("status", text="Status")
            tv.heading("size", text="Size")
            tv.heading("use", text="Used for")
            tv.column("#0", width=300, stretch=False)
            tv.column("status", width=170, stretch=False)
            tv.column("size", width=80, stretch=False, anchor="e")
            tv.column("use", width=420)
            tv.tag_configure("ok", foreground="#15803D")
            tv.tag_configure("no", foreground="#B91C1C")
            tv.tag_configure("grp", font=self.f_b)
            ysb = ttk.Scrollbar(t_comp, orient="vertical", command=tv.yview)
            tv.configure(yscrollcommand=ysb.set)
            btns = ttk.Frame(t_comp)
            btns.pack(side="bottom", fill="x", pady=(6, 0))
            ysb.pack(side="right", fill="y")
            tv.pack(fill="both", expand=True)
            st_ = {"rows": {}, "winvoices": None}

            def ollama_exe() -> str:
                p_ = shutil.which("ollama")
                if p_:
                    return p_
                cand = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
                return str(cand) if cand.is_file() else ""

            def rows() -> List[tuple]:
                """(group, key, name, installed, status, size, use)"""
                out: List[tuple] = []
                core = [("pymupdf", "fitz"), ("fonttools", "fontTools"), ("python-docx", "docx"), ("pyphen", "pyphen")]
                vers = [pkg_version(d, m) for d, m in core]
                out.append(("Program", "pkg:core", "Program packages (PDF, fonts, Word)", all(vers),
                            ", ".join(f"{d} {v}" for (d, _m), v in zip(core, vers) if v) or "missing", "",
                            "reading and writing PDF / Word files, fonts, hyphenation"))
                v1, v2 = pkg_version("ctranslate2", "ctranslate2"), pkg_version("sentencepiece", "sentencepiece")
                out.append(("Built-in translation engine", "pkg:ct2", "Engine runtime (CTranslate2 + SentencePiece)",
                            bool(v1 and v2), f"CTranslate2 {v1}" if v1 else "not installed", "",
                            "runs the offline AI model on the processor"))
                v3, v4 = pkg_version("transformers", "transformers"), pkg_version("torch", "torch")
                out.append(("Built-in translation engine", "pkg:conv", "Model converter (transformers + PyTorch)",
                            bool(v3 and v4), f"installed ({v4.split('+')[0]})" if v3 and v4 else "not installed",
                            "", "only needed ONCE to convert a new model – can be "
                            "removed afterwards to free space (NLLB models still need it)"))
                found = False
                if MODEL_DIR.is_dir():
                    for d in sorted(MODEL_DIR.iterdir()):
                        if d.is_dir() and d.name.endswith("-ct2-int8") and (d / "model.bin").is_file():
                            found = True
                            out.append(("Built-in translation engine", "model:" + d.name,
                                        d.name.replace("-ct2-int8", "").replace("__", "/") + "  (int8)", True,
                                        "installed ✓", fmt_size(dir_size(d)), "the offline translation model"))
                        elif d.is_dir() and d.name.endswith("-src"):
                            out.append(("Built-in translation engine", "src:" + d.name,
                                        "Downloaded original files: " + d.name.replace("-src", ""), True,
                                        "can be deleted", fmt_size(dir_size(d)),
                                        "not needed after the conversion – delete to free space"))
                if not found:
                    out.append(("Built-in translation engine", "model:new", "MADLAD-400 3B (offline model)", False,
                                "not installed", "≈ 2.8 GB", "download ≈ 12 GB once, then converted (15–40 min)"))
                ol = ollama_exe()
                out.append(("Ollama (local LLM)", "ollama", "Ollama", bool(ol), "installed ✓" if ol else "not installed",
                            "", "optional engine for Gemma / Qwen models – Install opens ollama.com"))
                if ol:
                    for m in llm_models("ollama", "", "", timeout=1.5):
                        out.append(("Ollama (local LLM)", "olm:" + m, "model " + m, True, "installed ✓", "",
                                    "an Ollama model"))
                pv = pkg_version("piper-tts", "piper")
                out.append(("Voices (pronunciation)", "pkg:piper", "Offline voice engine (Piper)", bool(pv),
                            f"installed {pv}" if pv else "not installed", "", "natural voices without internet"))
                for lang, vs in PIPER_VOICES.items():
                    for vid, label in vs:
                        ok = piper_voice_installed(vid)
                        out.append(("Voices (pronunciation)", "voice:" + vid, f"{LANGS[lang]['name']}: {label}", ok,
                                    "installed ✓" if ok else "not installed",
                                    fmt_size(piper_voice_file(vid).stat().st_size) if ok else "≈ 60 MB",
                                    "offline voice"))
                ev = pkg_version("edge-tts", "edge_tts")
                out.append(("Voices (pronunciation)", "pkg:edge", "Online voices (Microsoft Edge, neural)", bool(ev),
                            f"installed {ev}" if ev else "not installed", "", "very natural voices for all five "
                            "languages, need the internet (the text is sent to Microsoft)"))
                wv = st_["winvoices"]
                out.append(("Voices (pronunciation)", "winvoices", "Windows voices", bool(wv),
                            ("installed: " + ", ".join(sorted(LANGS[c]["name"] for c in wv if c in LANGS)))
                            if wv else ("looking …" if wv is None else "none"), "",
                            "add more in Windows Settings → Time & language → Speech"))
                fw, sc_ = pkg_version("faster-whisper", "faster_whisper"), pkg_version("soundcard", "soundcard")
                out.append(("Speech recognition", "pkg:whisper", "Speech recognition (faster-whisper)", bool(fw),
                            f"installed {fw}" if fw else "not installed", "", "microphone typing and Live translation, "
                            "offline"))
                out.append(("Speech recognition", "pkg:audio", "Sound capture (soundcard)", bool(sc_),
                            f"installed {sc_}" if sc_ else "not installed", "", "microphone and the sound of the "
                            "computer (films, videos, calls)"))
                for size, (dl, note) in WHISPER_SIZES.items():
                    ok = whisper_installed(size)
                    out.append(("Speech recognition", "whisper:" + size, f"Whisper model “{size}”", ok,
                                "installed ✓" if ok else "not installed",
                                fmt_size(dir_size(WHISPER_DIR / size)) if ok else dl, note))
                for key, name, p_, use in (("dir:fonts", "Downloaded fonts", FONT_DIR, "fonts of the translations"),
                                           ("dir:jobs", "Job cache (finished parts)", JOBS_DIR,
                                            "lets an interrupted job continue – safe to empty"),
                                           ("dir:cache", "Translation cache", CACHE_DIR, "safe to empty"),
                                           ("dir:terms", "Terminology downloads", TERM_DIR, "term lists of the fields")):
                    sz = dir_size(p_) if p_.exists() else 0
                    out.append(("Data folders", key, name, sz > 0, str(p_), fmt_size(sz) if sz else "empty", use))
                return out

            def refresh() -> None:
                sel = tv.selection()
                tv.delete(*tv.get_children())
                groups: Dict[str, str] = {}
                st_["rows"] = {}
                for g, key, name, ok, status, size, use in rows():
                    if g not in groups:
                        groups[g] = tv.insert("", "end", text=g, open=True, tags=("grp",))
                    tv.insert(groups[g], "end", iid=key, text=("✔  " if ok else "○  ") + name,
                              values=(status, size, use), tags=("ok" if ok else "no",))
                    st_["rows"][key] = (ok, name)
                if sel and tv.exists(sel[0]):
                    tv.selection_set(sel[0])
                    tv.see(sel[0])
                fill_voices()
                fill_speech()
                fill_system()

            def pip_task(title: str, args: List[str]) -> None:
                def fn(log, _prog):
                    if run_pip(args, log) != 0:
                        raise RuntimeError("pip reported an error (see the lines above). Is the internet on?")
                task(title, fn)

            def selected() -> Optional[str]:
                s_ = tv.selection()
                return s_[0] if s_ and s_[0] in st_["rows"] else None

            def install() -> None:
                k = selected()
                if not k:
                    return
                if k == "pkg:core":
                    pip_task("Installing the program packages", ["install", "pymupdf", "fonttools", "python-docx",
                                                                 "pyphen"])
                elif k == "pkg:ct2":
                    pip_task("Installing the engine runtime", ["install", "ctranslate2", "sentencepiece"])
                elif k == "pkg:conv":
                    pip_task("Installing the model converter (large download)", ["install", "transformers", "torch",
                                                                                 "accelerate", "protobuf"])
                elif k.startswith("model:"):
                    if not messagebox.askyesno("Built-in model", "The MADLAD-400 3B model is downloaded (about 12 GB) "
                                               "and converted once (15–40 minutes, needs 16 GB of memory).\n\n"
                                               "Start now?", parent=win):
                        return
                    task("Downloading and converting MADLAD-400", lambda log, _p: prepare_model(DEFAULT_MODEL, log, True))
                elif k.startswith("src:"):
                    messagebox.showinfo("Settings", "These files are already downloaded – use Remove to free the "
                                                    "space.", parent=win)
                elif k == "ollama" or k.startswith("olm:"):
                    webbrowser.open("https://ollama.com/download")
                elif k == "pkg:piper":
                    def fn(log, prog):
                        if run_pip(["install", "piper-tts"], log) != 0:
                            raise RuntimeError("pip reported an error (see above)")
                        install_default_voices(log)
                    task("Installing the offline voices (engine + one voice for each language)", fn)
                elif k.startswith("voice:"):
                    vid = k[6:]
                    task(f"Downloading the voice {vid}", lambda log, prog: install_piper_voice(vid, log, prog))
                elif k == "pkg:edge":
                    pip_task("Installing the online voices", ["install", "edge-tts"])
                elif k == "winvoices":
                    open_path("ms-settings:speech")
                elif k in ("pkg:whisper", "pkg:audio"):
                    install_speech()
                elif k.startswith("whisper:"):
                    size = k[8:]
                    task(f"Downloading the speech model “{size}”", lambda log, _p: install_whisper(size, log))
                elif k.startswith("dir:"):
                    open_path(str({"dir:fonts": FONT_DIR, "dir:jobs": JOBS_DIR, "dir:cache": CACHE_DIR,
                                   "dir:terms": TERM_DIR}[k]))

            def remove() -> None:
                k = selected()
                if not k:
                    return
                ok, name = st_["rows"][k]
                if not ok:
                    messagebox.showinfo("Settings", f"“{name}” is not installed.", parent=win)
                    return
                if k in ("pkg:core", "pkg:ct2"):
                    messagebox.showinfo("Settings", "This part is needed by the program itself and can not be "
                                                    "removed here.", parent=win)
                    return
                if not messagebox.askyesno("Remove", f"Remove “{name}”?\n\nIt can be installed again later with one "
                                                     "click.", parent=win, default="no"):
                    return
                if k == "pkg:conv":
                    pip_task("Removing the model converter", ["uninstall", "-y", "torch", "transformers", "accelerate"])
                elif k.startswith(("model:", "src:")):
                    d_ = MODEL_DIR / k.split(":", 1)[1]
                    task(f"Deleting {d_.name}", lambda log, _p: (shutil.rmtree(d_), _MT_CACHE.clear(),
                                                                 setattr(self, "_qt_engine", None)))
                elif k == "ollama":
                    messagebox.showinfo("Settings", "Ollama is a program of its own: remove it in Windows Settings → "
                                                    "Apps.", parent=win)
                elif k.startswith("olm:"):
                    m = k[4:]
                    task(f"Removing the Ollama model {m}", lambda log, _p: log(__import__("subprocess").run(
                        [ollama_exe(), "rm", m], capture_output=True, text=True,
                        creationflags=getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0)).stdout))
                elif k == "pkg:piper":
                    pip_task("Removing the offline voice engine", ["uninstall", "-y", "piper-tts"])
                elif k.startswith("voice:"):
                    remove_piper_voice(k[6:])
                    _PIPER_CACHE.pop(k[6:], None)
                    refresh()
                elif k == "pkg:edge":
                    pip_task("Removing the online voices", ["uninstall", "-y", "edge-tts"])
                elif k == "winvoices":
                    open_path("ms-settings:speech")
                elif k == "pkg:whisper":
                    pip_task("Removing speech recognition", ["uninstall", "-y", "faster-whisper"])
                elif k == "pkg:audio":
                    pip_task("Removing sound capture", ["uninstall", "-y", "soundcard"])
                elif k.startswith("whisper:"):
                    _WHISPER_CACHE.clear()
                    task("Deleting the speech model", lambda log, _p: shutil.rmtree(WHISPER_DIR / k[8:]))
                elif k.startswith("dir:"):
                    d_ = {"dir:fonts": FONT_DIR, "dir:jobs": JOBS_DIR, "dir:cache": CACHE_DIR, "dir:terms": TERM_DIR}[k]
                    task(f"Emptying {d_}", lambda log, _p: shutil.rmtree(d_, ignore_errors=True))

            def install_speech() -> None:
                size = v_wsize.get()

                def fn(log, prog):
                    need = [p_ for p_, m in (("faster-whisper", "faster_whisper"), ("soundcard", "soundcard"))
                            if not pkg_version(p_, m)]
                    if need and run_pip(["install"] + need, log) != 0:
                        raise RuntimeError("pip reported an error (see above)")
                    if not whisper_installed(size):
                        install_whisper(size, log)
                    d_ = load_json(SETTINGS_FILE, {})
                    if isinstance(d_, dict):
                        d_["whisper"] = size
                        save_json(SETTINGS_FILE, d_)
                task(f"Installing speech recognition (model “{size}”)", fn)

            ttk.Button(btns, text="⬇  Install / open", style="Accent.TButton", command=install).pack(side="left")
            ttk.Button(btns, text="🗑  Remove", command=remove).pack(side="left", padx=8)
            ttk.Button(btns, text="↻  Refresh", command=lambda: refresh()).pack(side="left")
            ttk.Button(btns, text="Install all default voices",
                       command=lambda: task("Installing one offline voice for each language",
                                            lambda log, _p: (run_pip(["install", "piper-tts"], log)
                                                             if not pkg_version("piper-tts", "piper") else 0,
                                                             install_default_voices(log)))).pack(side="right")
            ttk.Button(btns, text="Open the app data folder",
                       command=lambda: (APP_DIR.mkdir(parents=True, exist_ok=True), open_path(str(APP_DIR)))).pack(
                side="right", padx=8)
            tv.bind("<Double-1>", lambda _e: install())

            # ================================================= Voices
            ttk.Label(t_voice, text="The voice of every language for 🔊 in Quick translate. Offline voices work without "
                                    "the internet; online voices are the most natural but send the text to Microsoft; "
                                    "Windows voices are the ones of your Windows.", foreground=MUTE,
                      wraplength=980, justify="left").pack(anchor="w", pady=(0, 8))
            vgrid = ttk.Frame(t_voice)
            vgrid.pack(fill="x")
            ENG = {"piper": "Offline (Piper)", "edge": "Online (Microsoft Edge)", "windows": "Windows voice"}
            ENG_R = {v: k for k, v in ENG.items()}
            vrows: Dict[str, tuple] = {}
            for r_, lang in enumerate(("en", "fa", "de", "fr", "es")):
                ttk.Label(vgrid, text=LANGS[lang]["name"], font=self.f_b).grid(row=r_, column=0, sticky="w", pady=4)
                ve, vv = tk.StringVar(), tk.StringVar()
                cbe = ttk.Combobox(vgrid, textvariable=ve, values=list(ENG.values()), state="readonly", width=24)
                cbe.grid(row=r_, column=1, padx=8)
                cbv = ttk.Combobox(vgrid, textvariable=vv, state="readonly", width=48)
                cbv.grid(row=r_, column=2, padx=8)
                lbl = ttk.Label(vgrid, text="", foreground=MUTE)
                ttk.Button(vgrid, text="▶ Test", command=lambda lg=lang: test_voice(lg)).grid(row=r_, column=3)
                lbl.grid(row=r_, column=4, sticky="w", padx=8)
                vrows[lang] = (ve, vv, cbe, cbv, lbl)
                cbe.bind("<<ComboboxSelected>>", lambda _e, lg=lang: (voice_values(lg), save_voice(lg)))
                cbv.bind("<<ComboboxSelected>>", lambda _e, lg=lang: save_voice(lg))
            SAMPLES = {"en": "Hello! This is how I sound when I read your translation.",
                       "fa": "سلام! این صدای من هنگام خواندن ترجمهٔ شماست.",
                       "de": "Hallo! So klinge ich, wenn ich Ihre Übersetzung vorlese.",
                       "fr": "Bonjour ! Voici ma voix quand je lis votre traduction.",
                       "es": "¡Hola! Así sueno cuando leo su traducción."}

            def voice_list(lang: str, eng: str) -> List[Tuple[str, str]]:
                if eng == "piper":
                    return [(v, f"{l}{'   ✓ installed' if piper_voice_installed(v) else '   (downloaded when chosen)'}")
                            for v, l in PIPER_VOICES[lang]]
                if eng == "edge":
                    return EDGE_VOICES[lang]
                wv = st_["winvoices"] or {}
                return [(n, n) for n in wv.get(lang, [])] or [("", "no Windows voice for this language")]

            def voice_values(lang: str) -> None:
                ve, vv, _cbe, cbv, _lbl = vrows[lang]
                eng = ENG_R.get(ve.get(), "piper")
                lst = voice_list(lang, eng)
                cbv.config(values=[l for _v, l in lst])
                if vv.get() not in [l for _v, l in lst]:
                    vv.set(lst[0][1] if lst else "")

            def fill_voices() -> None:
                d_ = load_json(SETTINGS_FILE, {}) or {}
                for lang, (ve, vv, _cbe, _cbv, lbl) in vrows.items():
                    eng, vid = voice_choice(lang, d_)
                    ve.set(ENG[eng])
                    lst = voice_list(lang, eng)
                    vv.set(next((l for v, l in lst if v == vid), lst[0][1] if lst else ""))
                    voice_values(lang)
                    ready = (eng == "piper" and pkg_version("piper-tts", "piper") and piper_voice_installed(vid)) or \
                            (eng == "edge" and pkg_version("edge-tts", "edge_tts")) or \
                            (eng == "windows" and bool((st_["winvoices"] or {}).get(lang)))
                    lbl.config(text="ready ✓" if ready else "not installed – choose it and press ▶ Test to install",
                               foreground="#15803D" if ready else "#B45309")

            def save_voice(lang: str) -> None:
                ve, vv, *_r = vrows[lang]
                eng = ENG_R.get(ve.get(), "piper")
                vid = next((v for v, l in voice_list(lang, eng) if l == vv.get()), "")
                d_ = load_json(SETTINGS_FILE, {})
                d_ = d_ if isinstance(d_, dict) else {}
                d_.setdefault("voices", {})[lang] = {"engine": eng, "voice": vid}
                save_json(SETTINGS_FILE, d_)

            def test_voice(lang: str) -> None:
                save_voice(lang)
                eng, vid = voice_choice(lang)
                if eng == "piper" and not (pkg_version("piper-tts", "piper") and piper_voice_installed(vid)):
                    def fn(log, prog):
                        if not pkg_version("piper-tts", "piper") and run_pip(["install", "piper-tts"], log) != 0:
                            raise RuntimeError("pip reported an error (see above)")
                        if vid and not piper_voice_installed(vid):
                            install_piper_voice(vid, log, prog)
                    task(f"Installing the offline voice {vid}", fn, after=lambda: test_voice(lang))
                    return
                if eng == "edge" and not pkg_version("edge-tts", "edge_tts"):
                    task("Installing the online voices", lambda log, _p: run_pip(["install", "edge-tts"], log),
                         after=lambda: test_voice(lang))
                    return
                vrows[lang][4].config(text="speaking …", foreground=MUTE)

                def work() -> None:
                    res, path = speak_to_file(SAMPLES[lang], lang)
                    self.q.put(("comp", "voice_done", lang, res, path))
                threading.Thread(target=work, daemon=True).start()

            ev0 = event

            def event2(kind: str, *a) -> None:
                if kind == "voice_done":
                    lang, res, path = a
                    if res == "OK":
                        play_audio(path)
                        vrows[lang][4].config(text="ready ✓", foreground="#15803D")
                    else:
                        vrows[lang][4].config(text=res[:110], foreground="#B91C1C")
                    return
                ev0(kind, *a)
            self._settings_event = event2

            # ================================================= Speech recognition
            ttk.Label(t_speech, text="Speech recognition turns spoken words into text without the internet (OpenAI "
                                     "Whisper, run by faster-whisper). It is used by 🎤 in Quick translate (talk "
                                     "instead of typing, without time limit) and by 🎬 Live translation (the sound of "
                                     "a film, a video or a meeting is translated while it plays).", foreground=MUTE,
                      wraplength=980, justify="left").pack(anchor="w", pady=(0, 8))
            sp_lbl = ttk.Label(t_speech, text="", font=self.f_b)
            sp_lbl.pack(anchor="w", pady=(0, 8))
            szf = ttk.LabelFrame(t_speech, text=" Model size ", padding=8)
            szf.pack(fill="x")
            v_wsize = tk.StringVar(value=whisper_size())
            for size, (dl, note) in WHISPER_SIZES.items():
                ttk.Radiobutton(szf, text=f"{size:<7}  {dl:>7}   ·   {note}", value=size, variable=v_wsize,
                                command=lambda: (save_size(), fill_speech())).pack(anchor="w")
            spb = ttk.Frame(t_speech)
            spb.pack(fill="x", pady=8)
            ttk.Button(spb, text="⬇  Install speech recognition (packages + chosen model)", style="Accent.TButton",
                       command=install_speech).pack(side="left")
            ttk.Button(spb, text="Open the folder of the Live translations",
                       command=lambda: (LIVE_LOG_DIR.mkdir(parents=True, exist_ok=True),
                                        open_path(str(LIVE_LOG_DIR)))).pack(side="right")

            def save_size() -> None:
                d_ = load_json(SETTINGS_FILE, {})
                if isinstance(d_, dict):
                    d_["whisper"] = v_wsize.get()
                    save_json(SETTINGS_FILE, d_)

            def fill_speech() -> None:
                miss = speech_ready()
                sp_lbl.config(text=("✔ Ready – model “" + whisper_size() + "” is used.") if not miss else
                              ("○ Not ready – missing: " + miss), foreground="#15803D" if not miss else "#B45309")

            # ================================================= System
            sysbox = ScrolledText(t_sys, font="TkFixedFont", relief="flat", padx=10, pady=8)
            sysbox.pack(fill="both", expand=True)
            sb2 = ttk.Frame(t_sys)
            sb2.pack(fill="x", pady=(6, 0))
            ttk.Button(sb2, text="Copy", command=lambda: (self.clipboard_clear(),
                                                          self.clipboard_append(sysbox.get("1.0", "end-1c")))).pack(
                side="left")

            def fill_system() -> None:
                import platform
                cores, gb = system_info()
                try:
                    du = shutil.disk_usage(str(APP_DIR if APP_DIR.exists() else Path.home()))
                    disk = f"{du.free / 1e9:.0f} GB free of {du.total / 1e9:.0f} GB"
                except Exception:
                    disk = "?"
                try:
                    import ctranslate2
                    gpu = ctranslate2.get_cuda_device_count()
                except Exception:
                    gpu = 0
                lines = [f"{APP_TITLE} {APP_VERSION}   (build {APP_BUILD})", "",
                         f"Windows / system : {platform.platform()}",
                         f"Processor        : {platform.processor() or '?'}",
                         f"Cores            : {cores} real cores, {os.cpu_count()} threads",
                         f"Memory           : {gb:.1f} GB",
                         f"Graphics (CUDA)  : {gpu} NVIDIA GPU(s) usable" if gpu else
                         "Graphics (CUDA)  : none – the engine runs on the processor",
                         f"Disk             : {disk}", "",
                         f"Python           : {platform.python_version()}   ({sys.executable})",
                         f"Tk               : {tk.TkVersion}", "",
                         "Folders", f"  app data        : {APP_DIR}", f"  models          : {MODEL_DIR}",
                         f"  voices          : {VOICE_DIR}", f"  speech models   : {WHISPER_DIR}",
                         f"  Quick log       : {QUICK_LOG_DIR}", f"  Live log        : {LIVE_LOG_DIR}", "",
                         "Python packages"]
                for d_, m_ in (("pymupdf", "fitz"), ("fonttools", "fontTools"), ("python-docx", "docx"),
                               ("pyphen", "pyphen"), ("ctranslate2", "ctranslate2"), ("sentencepiece", "sentencepiece"),
                               ("transformers", "transformers"), ("torch", "torch"), ("huggingface_hub", "huggingface_hub"),
                               ("numpy", "numpy"), ("onnxruntime", "onnxruntime"), ("piper-tts", "piper"),
                               ("edge-tts", "edge_tts"), ("faster-whisper", "faster_whisper"), ("soundcard", "soundcard")):
                    lines.append(f"  {d_:<16}: {pkg_version(d_, m_) or '— not installed'}")
                sysbox.config(state="normal")
                sysbox.delete("1.0", "end")
                sysbox.insert("1.0", "\n".join(lines))
                sysbox.config(state="disabled")

            def wv_job() -> None:
                self.q.put(("comp", "winvoices", tts_voices()))
            threading.Thread(target=wv_job, daemon=True).start()
            refresh()
            nb.select(win._tabs.get(tab, 0))

        def _pick_pdf(self) -> None:
            p = filedialog.askopenfilename(
                title="Choose a PDF book or a subtitle file",
                filetypes=[("PDF or subtitles", "*.pdf *.srt *.vtt *.ass *.ssa *.sbv *.sub"), ("PDF", "*.pdf"),
                           ("Subtitles", "*.srt *.vtt *.ass *.ssa *.sbv *.sub"), ("All files", "*.*")])
            if p:
                p = long_path(p)
                self._reset_view()
                self.pdf_var.set(p)
                if not self.out_var.get():
                    self.out_var.set(str(Path(p).parent / "translated"))

        def _pick_out(self) -> None:
            """The user decides where the translated files are saved."""
            start = self.out_var.get() or (str(Path(self.pdf_var.get()).parent) if self.pdf_var.get() else "")
            p = filedialog.askdirectory(title="Choose the folder for the translated files",
                                        initialdir=start if start and Path(start).exists() else None)
            if p:
                self.out_var.set(long_path(p))

        # ------------------------------------------------------- File menu
        def _new(self) -> None:
            """A fresh start: input, output and log are emptied – every setting stays as it is."""
            if self.running:
                messagebox.showinfo("New", "A translation is running. Cancel it first.")
                return
            self.pdf_var.set("")
            self.out_var.set("")
            self._reset_view()
            self.phase_lbl.config(text="Waiting for a file …")

        def _history(self) -> None:
            if self._single("history"):
                return
            win = tk.Toplevel(self)
            self._keep("history", win)
            win.title("History – translated files (newest first)")
            win.geometry("980x420")
            win.configure(bg=BG)
            hist = [h for h in load_json(HISTORY_FILE, []) if isinstance(h, dict)]
            cols = ("time", "lang", "status", "input")
            tv = ttk.Treeview(win, columns=cols, show="headings", selectmode="browse")
            for c, t, w in (("time", "Date", 120), ("lang", "Language", 70), ("status", "Status", 90),
                            ("input", "Input file", 660)):
                tv.heading(c, text=t)
                tv.column(c, width=w, anchor="w", stretch=(c == "input"))
            for i, h in enumerate(hist):
                tv.insert("", "end", iid=str(i), values=(h.get("time", ""), ", ".join(h.get("langs", [])),
                                                          "finished" if h.get("outputs") else "not finished",
                                                          h.get("input", "")))
            tv.pack(fill="both", expand=True, padx=10, pady=(10, 4))
            info = ttk.Label(win, text="No translation has been started with this version yet." if not hist else
                             "Double-click a line to show the input file in its folder.", foreground=MUTE,
                             background=BG)
            info.pack(anchor="w", padx=12)

            def sel() -> Optional[dict]:
                s_ = tv.selection()
                return hist[int(s_[0])] if s_ else None

            def show_input(_e=None) -> None:
                h = sel()
                if h:
                    if exists(h.get("input", "")):
                        reveal_path(h["input"])
                    else:
                        messagebox.showinfo("History", "This file is not at its old place any more:\n" +
                                            h.get("input", ""), parent=win)

            def show_output() -> None:
                h = sel()
                outs = [o for o in (h or {}).get("outputs", []) if exists(o)]
                if outs:
                    reveal_path(outs[0])
                elif h:
                    messagebox.showinfo("History", "The translated file is not at its old place any more.",
                                        parent=win)

            def use() -> None:
                h = sel()
                if h and exists(h.get("input", "")) and not self.running:
                    self._reset_view()
                    self.pdf_var.set(h["input"])
                    outs = h.get("outputs") or []
                    self.out_var.set(str(Path(outs[0]).parent) if outs else str(Path(h["input"]).parent / "translated"))
                    win.destroy()

            tv.bind("<Double-1>", show_input)
            row = ttk.Frame(win)
            row.pack(fill="x", padx=10, pady=8)
            ttk.Button(row, text="Show input file", command=show_input).pack(side="left")
            ttk.Button(row, text="Show translated file", command=show_output).pack(side="left", padx=6)
            ttk.Button(row, text="Use as input again", command=use).pack(side="left")
            ttk.Button(row, text="Close", command=win.destroy).pack(side="right")

        def _settings_dict(self) -> dict:
            return {"o": {k: bool(v.get()) for k, v in self.o.items()}, "model": self.model_var.get(),
                    "target": self._target(), "head": self.head_var.get(), "body": self.body_var.get(),
                    "custom_font": dict(self.custom_font), "fscale": self._int(self.fscale_var, 100),
                    "scale": self._int(self.scale_var, 50), "kw": self.kw_var.get(),
                    "origin": self._origin(), "engine": self._engine(), "llm": self._llm_snapshot(),
                    "help_lang": (load_json(SETTINGS_FILE, {}) or {}).get("help_lang", "en"),
                    "spec": self.spec_var.get(), "auto_spec": bool(self.auto_spec.get()),
                    "out_docx": bool(self.out_docx.get()), "out_txt": bool(self.out_txt.get()),
                    "out_pdf": bool(self.out_pdf.get()), "review": bool(self.review_var.get()),
                    "sound": bool(self.sound_on.get())}

        @staticmethod
        def _int(var, default: int) -> int:
            try:
                return int(var.get())
            except Exception:
                return default

        def _apply_settings(self, d: dict) -> None:
            if not isinstance(d, dict) or not d:
                return
            try:
                if d.get("target") in self.lang_vars and d["target"] != self._target():
                    self._pick_target(d["target"])
                for k, v in (d.get("o") or {}).items():
                    if k in self.o:
                        self.o[k].set(bool(v))
                rtl = LANGS[self._target()]["rtl"]
                if not rtl:
                    self.o["rtl"].set(False)
                    self.o["align"].set(False)
                if d.get("origin") in self.origin_vars:
                    for c, v in self.origin_vars.items():
                        v.set(c == d["origin"])
                if isinstance(d.get("llm"), dict):
                    for e in ("ollama", "api"):
                        if isinstance(d["llm"].get(e), dict):
                            self.llm_store[e].update({k: str(v) for k, v in d["llm"][e].items()
                                                      if k in ("model", "url", "key")})
                if d.get("engine") in ENGINE_LABELS:
                    self._cur_engine = None
                    self.engine_var.set(ENGINE_LABELS[d["engine"]])
                self._engine_changed(load=True)
                self.out_docx.set(False)
                self._langs_changed(fonts=False)
                for key, var in (("model", self.model_var), ("kw", self.kw_var),
                                 ("spec", self.spec_var), ("fscale", self.fscale_var), ("scale", self.scale_var),
                                 ("auto_spec", self.auto_spec),
                                 ("out_txt", self.out_txt), ("out_pdf", self.out_pdf), ("review", self.review_var),
                                 ("sound", self.sound_on)):
                    if key in d:
                        var.set(d[key])
                self.sound_btn.config(text="🔊" if self.sound_on.get() else "🔇")
                cf = d.get("custom_font") or {}
                for which, var in (("head", self.head_var), ("body", self.body_var)):
                    name = d.get(which)
                    if name == CUSTOM_FONT_LABEL and cf.get(which) and Path(cf[which]).is_file():
                        self.custom_font[which] = cf[which]
                        var.set(name)
                    elif name and name in list(self.font_cbs[which].cget("values")) and name != CUSTOM_FONT_LABEL:
                        var.set(name)
            except Exception:
                pass

        def _save_settings(self, tell: bool = False) -> None:
            save_json(SETTINGS_FILE, self._settings_dict())
            if tell:
                messagebox.showinfo("Settings", f"The current settings are saved and used the next time the app "
                                                f"starts.\n\n{SETTINGS_FILE}")

        def _reset_settings(self) -> None:
            if messagebox.askyesno("Settings", "Set every setting back to its default value?"):
                self._apply_settings(self.defaults)
                self._save_settings()
                self._update_preview("head")
                self._update_preview("body")

        # ------------------------------------------------- sounds
        def _toggle_sound(self) -> None:
            self.sound_on.set(not self.sound_on.get())
            self.sound_btn.config(text="🔊" if self.sound_on.get() else "🔇")
            if not self.sound_on.get():
                try:
                    import winsound
                    winsound.PlaySound(None, winsound.SND_PURGE)         # stop what is playing now
                except Exception:
                    pass
            self._save_settings()

        def _play(self, which: str) -> None:
            """'part' = Windows "NFP Completion" after every finished part, 'done' = Alarm06 when the file is ready, 'cancel' = Pop-up Blocked."""
            if not self.sound_on.get():
                return
            try:
                import winsound
                media = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Media"
                f = media / SOUND_FILES[which]
                if f.is_file():
                    winsound.PlaySound(str(f), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
                else:
                    winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                try:
                    self.bell()
                except Exception:
                    pass

        # ------------------------------------------------- live workload chart
        LOAD_BINS = 8                                        # slices per page

        def _load_reset(self) -> None:
            self.load_n = 0                                  # pages of the job
            self.load_plan: Dict[int, float] = {}            # slice -> words to translate (known after the analysis)
            self.load_real: Dict[int, float] = {}            # slice -> seconds really spent
            self.load_head = -1                              # last slice that was worked on
            self.load_first = 1                              # number of the first page (label)
            self.load_pages: List[int] = []
            self.load_view, self.load_follow = 0.0, True
            self._draw_load()

        def _load_msg(self, d: dict) -> None:
            nb = self.LOAD_BINS
            if "head" in d and self.load_n:
                self.load_head = max(self.load_head, min(self.load_n * nb - 1, int(float(d["head"]) * nb)))
            if d.get("pages"):
                self.load_pages = list(d["pages"])
                self.load_n = len(self.load_pages)
            store = self.load_plan if d.get("kind") == "plan" else self.load_real
            for x, w in d.get("pts", []):
                b = max(0, min(self.load_n * nb - 1, int(x * nb)))
                store[b] = store.get(b, 0.0) + float(w)
                if store is self.load_real:
                    self.load_head = max(self.load_head, b)
            for pg, sec in d.get("flat", []):                # typesetting time of a page: spread over its slices
                for b in range(pg * nb, pg * nb + nb):
                    if sec and (self.load_plan.get(b) or self.load_real.get(b)):
                        self.load_real[b] = self.load_real.get(b, 0.0) + float(sec) / nb
                self.load_head = max(self.load_head, pg * nb + nb - 1)
            self._draw_load()

        LOAD_SPAN = 4.0                                      # pages that are visible at once

        def _load_drag(self, e, start: bool = False) -> None:
            n = self.load_n
            if n <= self.LOAD_SPAN:
                return
            w = max(120, self.load_cv.winfo_width()) - 16
            if start:
                self._drag0 = (e.x, self.load_view)
                self.load_follow = False                     # the user looks back: stop following the work
                return
            x0, v0 = getattr(self, "_drag0", (e.x, self.load_view))
            self.load_view = max(0.0, min(n - self.LOAD_SPAN, v0 - (e.x - x0) * self.LOAD_SPAN / w))
            self._draw_load()

        def _load_wheel(self, e) -> str:
            n = self.load_n
            if n > self.LOAD_SPAN:
                self.load_follow = False
                d = -0.5 if getattr(e, "delta", 0) > 0 else 0.5
                self.load_view = max(0.0, min(n - self.LOAD_SPAN, self.load_view + d))
                self._draw_load()
            return "break"

        def _load_resume(self, _e=None) -> None:
            self.load_follow = True
            self._draw_load()

        def _draw_load(self) -> None:
            c = getattr(self, "load_cv", None)
            if c is None or not hasattr(self, "load_plan"):
                return
            c.delete("all")
            w, h = max(120, c.winfo_width()), max(60, c.winfo_height())
            x0, x1, y0, y1 = 8, w - 8, 8, h - 16
            for k in range(1, 4):                            # faint grid, like monitor paper
                yy = y1 - (y1 - y0) * k / 4
                c.create_line(x0, yy, x1, yy, fill="#1E293B")
            c.create_line(x0, y1, x1, y1, fill="#334155")
            n = self.load_n
            if not n:
                c.create_text(w / 2, (y0 + y1) / 2, fill="#64748B", font=self.f_s,
                              text="The live workload curve of the file appears here while it is translated.")
                return
            nb = self.LOAD_BINS
            span = min(float(n), self.LOAD_SPAN)
            head_pg = (self.load_head + 1) / nb              # pages (and slices) that are done
            if getattr(self, "load_follow", True):           # the newest work stays in view, a little room ahead
                self.load_view = max(0.0, min(n - span, head_pg - span + 0.6))
            v0 = max(0.0, min(n - span, getattr(self, "load_view", 0.0)))
            X = lambda pg: x0 + (x1 - x0) * (pg - v0) / span      # page position -> pixel
            for k in range(int(v0), min(n, int(v0 + span) + 1)):   # page borders and page numbers
                xa, xb = max(x0, X(k)), min(x1, X(k + 1))
                if xb - xa < 4:
                    continue
                if X(k) > x0 + 1:
                    c.create_line(X(k), y0, X(k), y1, fill="#1E293B")
                if xb - xa > 26:
                    c.create_text((xa + xb) / 2, h - 7, fill="#94A3B8", font=self.f_s,
                                  text=f"page {self.load_pages[k] if k < len(self.load_pages) else k + 1}")
            b_lo, b_hi = max(0, int(v0 * nb) - 1), min(n * nb - 1, int((v0 + span) * nb) + 1)

            def curve(store: Dict[int, float], upto: int, top: float) -> List[float]:
                pts: List[float] = []
                for b in range(b_lo, min(b_hi, upto) + 1):
                    v = (store.get(b, 0.0) / top) if top > 0 else 0.0
                    pts += [min(x1, max(x0, X((b + 0.5) / nb))), y1 - (y1 - y0 - 4) * min(1.0, v)]
                return pts

            if self.load_plan:                               # what is waiting: amount of text of every page region
                pts = curve(self.load_plan, max(self.load_plan), max(self.load_plan.values()))
                if len(pts) >= 4:
                    c.create_line(*pts, fill="#38BDF8", width=1, smooth=True, dash=(2, 3))
            if self.load_head >= 0:                          # what was done: time spent, the bright line
                top = max(self.load_real.values(), default=0.0)
                pts = curve(self.load_real, self.load_head, top)
                if len(pts) >= 4:
                    c.create_line(*pts, fill="#064E3B", width=5, smooth=True)
                    c.create_line(*pts, fill="#1BF576", width=2, smooth=True)
                if pts and b_lo <= self.load_head <= b_hi:
                    hx, hy = pts[-2], pts[-1]
                    r = 3.5 + (1.8 * (0.5 + 0.5 * __import__("math").sin(self.spin_i * 0.3)) if self.running else 0)
                    c.create_oval(hx - r, hy - r, hx + r, hy + r, fill="#ECFDF5", outline="#1BF576")
                if top > 0:
                    c.create_text(x1 - 2, y0 + 5, anchor="e", fill="#86EFAC", font=self.f_s,
                                  text=f"heaviest region: {fmt_dur(top) if top >= 60 else str(int(top + 0.5)) + ' s'}")
            hint = "┈ text waiting    ━ time spent"
            if n > span:
                hint += "    ·    drag ◄ ► to look back" + ("" if getattr(self, "load_follow", True)
                                                             else "  (double-click: follow again)")
                # a thin bar under the curve: which part of the file is shown
                c.create_line(x0, h - 1, x1, h - 1, fill="#1E293B", width=2)
                c.create_line(x0 + (x1 - x0) * v0 / n, h - 1, x0 + (x1 - x0) * (v0 + span) / n, h - 1,
                              fill="#38BDF8", width=2)
            c.create_text(x0 + 2, y0 + 5, anchor="w", fill="#64748B", font=self.f_s, text=hint)

        def _review_toggled(self) -> None:
            """The tick can be changed while a job runs: from now on parts are (not) shown for review."""
            ev = self.review_ev
            if ev is not None:
                try:
                    ev.set() if self.review_var.get() else ev.clear()
                except Exception:
                    pass
            if not self.review_var.get() and self.review_win is not None:
                self._review_answer({"action": "cancel"})
            if self.running:
                self._log("Translate with review: " + ("ON – the next finished part is shown for editing."
                                                       if self.review_var.get() else
                                                       "OFF – the remaining parts are finished without stopping."), "hd")

        # ------------------------------------------------- My instructions
        def _instructions(self) -> None:
            """How the user wants terms translated.  Every instruction is a line of the list with its date: click it
            to see it, change it or delete it.  Every change is saved at once."""
            if self._single("instructions"):
                return
            win = tk.Toplevel(self)
            self._keep("instructions", win)
            win.title("My instructions – teach the app how to translate")
            win.geometry("900x640")
            win.minsize(700, 480)
            win.configure(bg=BG)
            ttk.Label(win, justify="left", foreground=MUTE, background=BG, wraplength=860,
                      text="Write an instruction in English or Persian and press Enter (or Add). Examples:   "
                           "backbone = ستون فقرات      translate patch as وصله      don't translate LiDAR      "
                           "LiDAR را ترجمه نکن      translate image\nEvery instruction is used in all later "
                           "translations.").pack(anchor="w", padx=14, pady=(12, 6))
            top = ttk.Frame(win)
            top.pack(fill="x", padx=14)
            ttk.Label(top, text="New instruction:").pack(side="left")
            ent = BidiText(top, multiline=False, font=("Tahoma", 11), height=30, auto_dir=True,
                           on_key=lambda vk, c, s: (vk == 0x0D and (win.after(1, add) or True)))
            ent.pack(side="left", fill="x", expand=True, padx=8)
            ttk.Button(top, text="Add", style="Accent.TButton", command=lambda: add()).pack(side="left")
            KIND = {"fa": "Translate as (Persian)", "de": "Translate as (German)", "fr": "Translate as (French)",
                    "es": "Translate as (Spanish)", "en": "Translate as (English)", "keep": "Keep unchanged",
                    "translate": "Always translate"}
            KIND_R = {v: k for k, v in KIND.items()}
            items: List[Tuple[str, str, str]] = load_instructions()
            dates = self._list_dates("instructions")
            lf = ttk.Frame(win)
            lf.pack(fill="both", expand=True, padx=14, pady=8)
            tv = ttk.Treeview(lf, columns=("kind", "term", "tr", "date"), show="headings", selectmode="extended")
            for c_, t_, w_ in (("kind", "Instruction", 170), ("term", "Term", 250), ("tr", "Translation", 250),
                               ("date", "Added", 120)):
                tv.heading(c_, text=t_)
                tv.column(c_, width=w_, stretch=c_ in ("term", "tr"))
            sb_ = ttk.Scrollbar(lf, orient="vertical", command=tv.yview)
            tv.configure(yscrollcommand=sb_.set)
            sb_.pack(side="right", fill="y")
            tv.pack(fill="both", expand=True)
            edit = ttk.LabelFrame(win, text=" Selected instruction ", padding=8)
            edit.pack(fill="x", padx=14)
            v_kind = tk.StringVar(value=KIND["fa"])
            ttk.Combobox(edit, textvariable=v_kind, values=list(KIND.values()), state="readonly",
                         width=22).grid(row=0, column=0, padx=(0, 8))
            e_term = BidiText(edit, multiline=False, font=("Tahoma", 11), height=30, width=260)
            e_term.grid(row=0, column=1, sticky="ew")
            ttk.Label(edit, text=" = ").grid(row=0, column=2)
            e_tr = BidiText(edit, multiline=False, font=("Tahoma", 11), height=30, width=260)
            e_tr.grid(row=0, column=3, sticky="ew")
            edit.columnconfigure(1, weight=1)
            edit.columnconfigure(3, weight=1)
            ttk.Button(edit, text="Save change", command=lambda: update()).grid(row=0, column=4, padx=(8, 0))
            ttk.Button(edit, text="Delete", command=lambda: delete()).grid(row=0, column=5, padx=(6, 0))
            row = ttk.Frame(win)
            row.pack(fill="x", padx=14, pady=(8, 12))
            note = ttk.Label(row, text="", foreground=MUTE)
            note.pack(side="left")

            def key(ins) -> str:
                return format_instruction(ins)

            def fill(sel: Optional[str] = None) -> None:
                tv.delete(*tv.get_children())
                for i, ins in enumerate(items):
                    tv.insert("", "end", iid=str(i), values=(KIND.get(ins[0], ins[0]), ins[1], ins[2] or "—",
                                                             dates.get(key(ins), "")))
                tv.heading("kind", text=f"Instruction ({len(items)})")
                if sel is not None:
                    for i, ins in enumerate(items):
                        if key(ins) == sel:
                            tv.selection_set(str(i))
                            tv.see(str(i))

            def store(msg: str) -> None:
                save_instructions_text("\n".join(dict.fromkeys(key(i) for i in items)))
                self._set_list_dates("instructions", {key(i): dates[key(i)] for i in items if key(i) in dates})
                note.config(text=msg + "   ·   saved ✓")

            def add() -> None:
                ins = parse_instruction(ent.get())
                if ins is None:
                    messagebox.showwarning("My instructions", "I could not understand this instruction.\n\n"
                                           "Write it like one of the examples, e.g.\n   backbone = ستون فقرات\n"
                                           "   don't translate LiDAR", parent=win)
                    return
                for i in [i for i, old in enumerate(items) if old[1].lower() == ins[1].lower()
                          and (old[0] == ins[0] or ins[0] in ("keep", "translate") or old[0] in ("keep", "translate"))]:
                    dates.pop(key(items[i]), None)
                    items[i] = None                               # the newest instruction about a term wins
                items[:] = [i for i in items if i is not None] + [ins]
                dates[key(ins)] = time.strftime("%Y-%m-%d %H:%M")
                ent.clear()
                fill(key(ins))
                store("Instruction added")
                ent.focus()

            def current() -> List[int]:
                return sorted(int(s_) for s_ in tv.selection())

            def on_select(_e=None) -> None:
                c_ = current()
                if len(c_) == 1:
                    ins = items[c_[0]]
                    v_kind.set(KIND.get(ins[0], ins[0]))
                    e_term.set(ins[1])
                    e_tr.set(ins[2])

            def update() -> None:
                c_ = current()
                if len(c_) != 1:
                    note.config(text="Select one instruction in the list first.")
                    return
                kind = KIND_R.get(v_kind.get(), "fa")
                term, tr = e_term.get().strip(), e_tr.get().strip()
                if not term or (kind in GLOSS_KINDS and not tr):
                    note.config(text="The term and its translation are needed.")
                    return
                old = items[c_[0]]
                new = (kind, term, tr if kind in GLOSS_KINDS else "")
                items[c_[0]] = new
                dates[key(new)] = dates.pop(key(old), time.strftime("%Y-%m-%d %H:%M"))
                fill(key(new))
                store("Instruction changed")

            def delete() -> None:
                c_ = current()
                if not c_:
                    note.config(text="Select one or more instructions in the list first.")
                    return
                for i in reversed(c_):
                    dates.pop(key(items[i]), None)
                    del items[i]
                e_term.clear()
                e_tr.clear()
                fill()
                store(f"{len(c_)} instruction(s) deleted")

            def delete_all() -> None:
                if items and messagebox.askyesno("My instructions", f"Delete all {len(items)} instructions?",
                                                 parent=win, default="no"):
                    items.clear()
                    dates.clear()
                    fill()
                    store("All instructions deleted")

            tv.bind("<<TreeviewSelect>>", on_select)
            tv.bind("<Delete>", lambda _e: delete())
            ttk.Button(row, text="Close", command=win.destroy).pack(side="right")
            ttk.Button(row, text="Delete all", command=delete_all).pack(side="right", padx=6)
            ttk.Button(row, text="Open the file", command=lambda: (store("Saved"),
                                                                   open_path(str(INSTRUCTIONS_FILE)))).pack(side="right")
            fill()
            win.after(100, ent.focus)

        def _pick_model(self) -> None:
            p = filedialog.askdirectory(title="Choose a model folder (Hugging Face or CTranslate2 format)")
            if p:
                self.model_var.set(p)

        def _target(self) -> str:
            return next((c for c, v in self.lang_vars.items() if v.get()), "fa")

        def _origin(self) -> str:
            return next((c for c, v in self.origin_vars.items() if v.get()), "en")

        # ------------------------------------------------- the chosen file: language, pages, tokens
        def _stats_later(self) -> None:
            """The file name changed (Browse, typing, a continued job): look at the file half a second later."""
            if self._stats_job is not None:
                try:
                    self.after_cancel(self._stats_job)
                except Exception:
                    pass
            self._stats_job = self.after(500, self._stats_start)

        def _stats_start(self) -> None:
            self._stats_job = None
            path = self.pdf_var.get().strip()
            self._stats_seq += 1
            seq = self._stats_seq
            if not path or not is_file(path):
                self.file_info = {}
                self._subtitle_mode(False, path)
                self._origin_show()
                return
            self.origin_lbl.config(text="reading the file …")

            def work() -> None:
                try:
                    info = subtitle_stats(path) if is_subtitle(path) else file_stats(path, lambda: seq != self._stats_seq)
                except Exception as exc:                 # noqa: BLE001
                    info = {"error": f"{type(exc).__name__}: {exc}"}
                self.q.put(("stats", seq, path, info))
            threading.Thread(target=work, daemon=True).start()

        def _stats_done(self, seq: int, path: str, info: dict) -> None:
            if seq != self._stats_seq:
                return                                   # another file was chosen meanwhile
            self.file_info = dict(info, path=path)
            self._subtitle_mode(bool(info.get("subtitle")), path)
            if info.get("lang") and not self.running:
                for c, v in self.origin_vars.items():
                    v.set(c == info["lang"])
                self._langs_changed(fonts=False)
            self._origin_show()

        def _subtitle_mode(self, on: bool, path: str = "") -> None:
            """A subtitle file switches the output to a subtitle file of the same kind (PDF / Word are off, pages
            are not used).  The first time a file is chosen a short message says what will happen."""
            if on and not self.sub_mode:
                self._fmt_before = (self.out_pdf.get(), self.out_txt.get())
            if on:
                ext = Path(path).suffix.lower()
                self.out_pdf.set(False)
                self.out_txt.set(True)
                self.cb_pdf.config(state="disabled")
                self.cb_txt.config(text=f"Subtitle ({ext})", state="disabled")
                self.pages_entry.config(state="disabled")
                if path not in self.sub_told:
                    self.sub_told.add(path)
                    info = self.file_info or {}
                    messagebox.showinfo(
                        "Subtitle file",
                        f"This is a subtitle file: {SUB_EXTS.get(ext, ext)}"
                        + (f" with {info.get('cues', 0):,} cues" if info.get("cues") else "") + ".\n\n"
                        "Only the spoken text is translated. The cue numbers, the times, styles, positions and "
                        "tags stay exactly as they are, so the subtitle stays in sync with the film.\n\n"
                        f"The output is a text file of the same format ({ext}). The PDF output is switched off for "
                        "this file.", parent=self)
            elif self.sub_mode:
                pdf_, txt_ = getattr(self, "_fmt_before", (True, False))
                self.out_pdf.set(pdf_)
                self.out_txt.set(txt_)
                self.cb_pdf.config(state="normal")
                self.cb_txt.config(text="Text (.txt)", state="normal")
                self.pages_entry.config(state="normal")
            self.sub_mode = on

        def _origin_by_hand(self, code: str) -> None:
            self.file_info = dict(self.file_info, lang=code, by_hand=True)
            self._pick_origin(code)
            self._origin_show()

        def _origin_show(self) -> None:
            info = self.file_info
            if not info:
                self.origin_lbl.config(text="choose a PDF or a subtitle file – the app finds its language itself", style="Muted.TLabel")
                self.origin_fix.pack_forget()
                return
            if info.get("error"):
                self.origin_lbl.config(text="the file can not be read: " + info["error"][:70], style="Muted.TLabel")
                return
            if info.get("other") and not info.get("by_hand"):
                self.origin_lbl.config(text=f"⚠ {info['other']} – not supported yet (only English, Persian, German, "
                                            f"French and Spanish)", style="Card.TLabel")
                self.origin_fix.pack(side="left", padx=(8, 0))
                return
            name = LANGS[self._origin()]["name"]
            how = "set by you" if info.get("by_hand") else ("detected" if info.get("lang") else "not recognised – "
                                                            "assumed")
            txt = (f"{name}  ({how})   ·   {info.get('pages', 0):,} pages   ·   ≈ {info.get('tokens', 0):,} tokens"
                   f"  ({info.get('words', 0):,} words)" + ("" if info.get("tok_exact") else "  (estimate)"))
            if info.get("subtitle"):
                txt = (f"{name}  ({how})   ·   {info['subtitle']}   ·   {info.get('cues', 0):,} cues   ·   "
                       f"{info.get('words', 0):,} words")
            if not info.get("text", True):
                txt += "   ·   almost no text: a scanned PDF?"
            elif info.get("damaged"):
                txt += "   ·   ⚠ text layer damaged"
            self.origin_lbl.config(text=txt, style="Card.TLabel")
            self.origin_fix.pack(side="left", padx=(8, 0))

        def _pick_origin(self, code: str) -> None:
            for c, v in self.origin_vars.items():
                v.set(c == code)
            self._langs_changed(fonts=False)

        def _pick_target(self, code: str) -> None:
            for c, v in self.lang_vars.items():
                v.set(c == code)
            self._langs_changed(fonts=True)

        def _target_changed(self) -> None:
            self._langs_changed(fonts=True)

        def _langs_changed(self, fonts: bool = True) -> None:
            """Fonts, direction options and samples that belong to the chosen pair of languages.  Everything that
            is done for English -> Persian is done the other way round for Persian -> English."""
            lang, src = self._target(), self._origin()
            if lang == src:                                    # never the same language twice
                alt = next(c for c, _n, _on in (TARGET_LANGS if not fonts else ORIGIN_LANGS) if c != lang)
                if fonts:
                    for c, v in self.origin_vars.items():
                        v.set(c == alt)
                    src = alt
                else:
                    for c, v in self.lang_vars.items():
                        v.set(c == alt)
                    lang, fonts = alt, True
            for c, cb in self.lang_cbs.items():                # the origin language is greyed out as target …
                cb.config(state="disabled" if c == src else "normal")
            for c, cb in self.origin_cbs.items():              # … and the target language as origin
                cb.config(state="disabled" if c == lang else "normal")
            rtl, src_rtl = bool(LANGS[lang]["rtl"]), bool(LANGS[src]["rtl"])
            values = (PERSIAN_FONTS if rtl else LATIN_FONTS[1:] if src_rtl else LATIN_FONTS) + [CUSTOM_FONT_LABEL]
            default = DEFAULT_FA_FONT if lang == "fa" else ("Times New Roman" if src_rtl else SAME_FONT)
            for which in ("head", "body"):
                self.font_cbs[which].config(values=values)
                if fonts or self._font_var(which).get() not in values:
                    self._font_var(which).set(default)
                    self.custom_font[which] = None
            for k in ("rtl", "align", "digits"):
                self.o_cb[k].config(state="normal" if rtl else "disabled")
            self.o_cb["swap"].config(state="normal" if rtl != src_rtl else "disabled")
            self.o_cb["bilingual"].config(state="normal" if (lang == "fa" and src == "en") else "disabled")
            for k in ("terms", "names"):                       # lists of English terms / Capitalized names
                self.o_cb[k].config(state="normal" if src == "en" else "disabled")
            self.o["rtl"].set(rtl)
            self.o["align"].set(rtl)
            note = ""
            if lang == src:
                note = "Origin and target are the same language – choose two different ones."
            elif src != "en":
                note = (f"{LANGS[src]['name']} → {LANGS[lang]['name']}: new and less tested than English → Persian. "
                        "English term lists are not used" +
                        (", the page is mirrored to left-to-right." if src_rtl and not rtl else "."))
            self.lang_note.config(text=note)
            if fonts:
                self._log(f"Languages: {LANGS[src]['name']} → {LANGS[lang]['name']} – fonts and options adjusted.",
                          "hd")
            self._update_preview("head")
            self._update_preview("body")

        # ------------------------------------------------- translation engines
        def _engine(self) -> str:
            return next((k for k, v in ENGINE_LABELS.items() if v == self.engine_var.get()), "local")

        def _llm_snapshot(self) -> dict:
            e = getattr(self, "_cur_engine", None)
            if e in self.llm_store:
                self.llm_store[e] = {"model": self.llm_model_var.get().strip(), "url": self.llm_url_var.get().strip(),
                                     "key": self.llm_key_var.get().strip()}
            return {k: dict(v) for k, v in self.llm_store.items()}

        def _engine_changed(self, load: bool = False) -> None:
            """Shows the fields of the chosen engine; every engine remembers its own model, address and key."""
            if not load:
                self._llm_snapshot()
            e = self._engine()
            self._cur_engine = e
            show = {"local": e == "local", "llm": e != "local", "key": e == "api"}
            for grp, widgets in self.eng_rows.items():
                for w in widgets:
                    w.grid() if show[grp] else w.grid_remove()
            if e != "local":
                st = self.llm_store[e]
                self.llm_model_var.set(st["model"])
                self.llm_url_var.set(st["url"])
                self.llm_key_var.set(st["key"])
                self.llm_cb.config(values=OLLAMA_SUGGESTED if e == "ollama" else [])
                self.llm_note.config(text=(
                    "Ollama runs a language model on this computer (free, offline). Install it from ollama.com, "
                    "then run e.g.  ollama pull gemma3:12b . “List models” shows what is installed."
                    if e == "ollama" else
                    "Any service that speaks the OpenAI chat protocol (OpenAI, OpenRouter, Groq, a company server …). "
                    "Type its address, the model name and your own key. The text of the document is sent to "
                    "that service; the key is stored only in the settings file on this computer."))
            self.o_cb["quality"].config(state="normal" if e == "local" else "disabled")

        def _llm_refresh(self, tell: bool = False) -> None:
            e = self._engine()
            if e == "local":
                return
            names = llm_models(e, self.llm_url_var.get(), self.llm_key_var.get())
            if names:
                self.llm_cb.config(values=names)
                if not self.llm_model_var.get().strip():
                    self.llm_model_var.set(names[0])
            if tell:
                messagebox.showinfo("Models", ("Models of this server:\n\n  " + "\n  ".join(names[:40])) if names else
                                    ("No answer from " + llm_base_url(e, self.llm_url_var.get()) + ".\n\n" +
                                     ("Is Ollama installed and running?" if e == "ollama"
                                      else "Check the address and the API key.")))

        def _spec_changed(self) -> None:
            specs, extra = parse_specialties(self.spec_var.get())
            if not specs:
                self.spec_info.config(text="up to 4 fields, comma separated – e.g.  Chemistry, AI")
            else:
                msg = f"{len(specs)} of {MAX_SPECIALTIES} fields"
                if extra:
                    msg += f" – {extra} more ignored"
                self.spec_info.config(text=msg)

        def _open_terms(self) -> None:
            TERM_DIR.mkdir(parents=True, exist_ok=True)
            webbrowser.open(TERM_DIR.as_uri())

        def _font_var(self, which: str) -> "tk.StringVar":
            return self.head_var if which == "head" else self.body_var

        def _font_changed(self, which: str) -> None:
            var = self._font_var(which)
            if var.get() == CUSTOM_FONT_LABEL:
                p = filedialog.askopenfilename(title="Choose a font file", filetypes=[("Fonts", "*.ttf *.otf")])
                if p:
                    self.custom_font[which] = p
                else:
                    var.set(DEFAULT_FA_FONT)
                    self.custom_font[which] = None
            else:
                self.custom_font[which] = None
            self._update_preview(which)

        def _sample_wheel(self, e, cvs) -> str:
            d = -1 if (e.num == 4 or getattr(e, "delta", 0) > 0) else 1
            cvs.xview_scroll(d * 3, "units")
            return "break"                                # do not also scroll the whole page

        def _update_preview(self, which: str) -> None:
            """Show a random sentence in the chosen font (like the font box of Word). The old sample stays visible
            until the new one is ready, so nothing flickers."""
            key = self._font_var(which).get()
            custom = self.custom_font[which] if key == CUSTOM_FONT_LABEL else None
            self.pv_token[which] += 1
            token = self.pv_token[which]
            allow = bool(self.o["dl"].get())
            text, is_fa = random_font_sample(self._target())

            def job() -> None:
                try:
                    if key == SAME_FONT:
                        self.q.put(("preview", which, token, None, "Same fonts as the original document", False))
                        return
                    fonts = resolve_font(key, lambda _m: None, custom, allow)
                    png = render_font_sample(fonts["regular"], text, rtl=is_fa, height=21, size=13.5)
                    self.q.put(("preview", which, token, png, "", is_fa))
                except Exception as exc:
                    first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
                    self.q.put(("preview", which, token, None,
                                f"{first}  (a free replacement font will be used)", False))
            threading.Thread(target=job, daemon=True).start()

        def _fetch_fonts(self) -> None:
            pairs = [(self.head_var.get(), self.custom_font["head"]), (self.body_var.get(), self.custom_font["body"])]
            names = [k for k, _c in pairs if k != CUSTOM_FONT_LABEL]
            names += [LANGS[c]["font"] for c, v in self.lang_vars.items() if v.get() and c != "fa" and LANGS[c]["font"]]
            allow = bool(self.o["dl"].get())

            def job() -> None:
                for n in dict.fromkeys(names):
                    try:
                        got = resolve_font(n, lambda m: self.q.put(("log", m)), None, allow)
                        self.q.put(("log", f"Font ready: {n}  ({got['regular'].name}"
                                           f"{', bold ✓' if got.get('bold') else ', no bold'})"))
                    except Exception as exc:
                        self.q.put(("log", f"ERROR font {n}: {exc}"))
            threading.Thread(target=job, daemon=True).start()

        # ------------------------------------------------- quick translation of a text (like an online translator)
        def _quick(self) -> None:
            """A small window to translate typed, pasted or spoken text at once, with pronunciation.  No title bar:
            it can be made very small and put in a corner.  Live mode turns it into two thin strips that stay on top
            of every window and show what is heard (a film, a video, a meeting) and its translation."""
            if getattr(self, "quick_win", None) is not None:
                try:
                    self.quick_win.deiconify()
                    self.quick_win.lift()
                    return
                except Exception:
                    self.quick_win = None
            win = tk.Toplevel(self)
            self.quick_win = win
            win.title("Quick translate")
            win.overrideredirect(True)                    # no title bar: the window can be small and sit anywhere
            sx, sy = self.winfo_rootx() + 160, self.winfo_rooty() + 90
            win.geometry(f"780x400+{sx}+{sy}")
            win.minsize(340, 200)
            win.configure(bg=LINE)
            names = dict(QUICK_LANGS)
            codes = {v: k for k, v in names.items()}
            d0 = load_json(SETTINGS_FILE, {}) if isinstance(load_json(SETTINGS_FILE, {}), dict) else {}
            prev = d0.get("quick", {}) or {}
            v_src = tk.StringVar(value=names.get(prev.get("src", "auto"), "Detect language"))
            v_tgt = tk.StringVar(value=names.get(prev.get("tgt", "fa"), "Persian"))
            v_slow = tk.BooleanVar(value=False)
            v_log = tk.BooleanVar(value=bool(prev.get("log", False)))
            v_top = tk.BooleanVar(value=bool(prev.get("top", False)))
            v_sum = tk.BooleanVar(value=bool(prev.get("summary", False)))
            v_save_live = tk.BooleanVar(value=bool(prev.get("save_live", True)))
            v_source = tk.StringVar(value=prev.get("source", "system"))
            st = {"seq": 0, "job": None, "detected": "", "busy": False, "pending_log": None, "log_job": None,
                  "mode": "normal", "listener": None, "live_src": [], "live_tr": [], "partial": "",
                  "normal_geom": "", "load_t0": None, "dictate": None, "anim": {}}
            live_log = LiveLog()
            F_S = (self.f_s.actual("family"), 8)
            F_I = ("Segoe UI Symbol", 10)

            outer = tk.Frame(win, bg="white")
            outer.pack(fill="both", expand=True, padx=1, pady=1)
            # ---- slim header: drag here to move the window
            head = tk.Frame(outer, bg="#F1F5F9", height=26)
            head.pack(fill="x")
            grip = tk.Label(head, text=" ⠿  Quick translate", bg="#F1F5F9", fg=MUTE, font=F_S, cursor="fleur")
            grip.pack(side="left")

            def hbtn(text, cmd, tip="", toggle=None):
                b = tk.Label(head, text=text, bg="#F1F5F9", fg=INK, font=F_I, padx=6, cursor="hand2")
                b.pack(side="right")
                b.bind("<Button-1>", lambda _e: cmd())
                b.bind("<Enter>", lambda _e: (b.config(bg="#E2E8F0"), status_tip(tip)))
                b.bind("<Leave>", lambda _e: (b.config(bg=b._on_bg if getattr(b, "_on", False) else "#F1F5F9"),
                                              status_tip("")))
                b._on_bg = "#C7D2FE"
                return b
            b_close = hbtn("✕", lambda: close(), "Close")
            b_min = hbtn("—", lambda: (win.withdraw(), self._log("Quick translate is hidden – open it again with "
                                                                  "“Quick translate”.")), "Hide the window")
            b_top = hbtn("📌", lambda: toggle_top(), "Always on top of other windows")
            b_folder = hbtn("📂", lambda: (QUICK_LOG_DIR.mkdir(parents=True, exist_ok=True),
                                           open_path(str(QUICK_LOG_DIR))), "Open the folder of the saved translations")
            b_log = hbtn("📝", lambda: toggle_log(), "Save every translation (original + translation) in a text "
                                                     "file of the day")
            b_live = hbtn("🎬 Live", lambda: go_live(), "Live translation of what is heard: films, videos, meetings")
            for w_ in (head, grip):
                w_.bind("<ButtonPress-1>", lambda e: start_move(e))
                w_.bind("<B1-Motion>", lambda e: do_move(e))

            # ---- languages
            normal = tk.Frame(outer, bg="white")
            normal.pack(fill="both", expand=True)
            langbar = tk.Frame(normal, bg="white")
            langbar.pack(fill="x", padx=8, pady=(6, 4))
            src_cb = ttk.Combobox(langbar, textvariable=v_src, values=[n for _c, n in QUICK_LANGS], state="readonly",
                                  width=15, font=self.f_s)
            src_cb.pack(side="left")
            det_lbl = tk.Label(langbar, text="", bg="white", fg=MUTE, font=F_S)
            det_lbl.pack(side="left", padx=(4, 0))
            tk.Button(langbar, text="⇄", command=lambda: swap(), relief="flat", bg="#EEF2FF",
                      activebackground="#C7D2FE", font=F_I, cursor="hand2", padx=8, pady=0,
                      borderwidth=0).pack(side="left", padx=10)
            tgt_cb = ttk.Combobox(langbar, textvariable=v_tgt, values=[n for c, n in QUICK_LANGS if c != "auto"],
                                  state="readonly", width=15, font=self.f_s)
            tgt_cb.pack(side="left")
            eng_lbl = tk.Label(langbar, text="", bg="white", fg=MUTE, font=F_S, anchor="e")
            eng_lbl.pack(side="right", fill="x", expand=True)

            body = tk.Frame(normal, bg="white")
            body.pack(fill="both", expand=True, padx=8)
            fnt = ("Tahoma", 12)
            panes = {}
            for key, bgc in (("src", "white"), ("out", "#F8FAFC")):
                fr = tk.Frame(body, bg=LINE)
                box = BidiText(fr, font=fnt, bg=bgc, readonly=(key == "out"), pad=(8, 6), border=bgc,
                               on_change=(lambda: changed()) if key == "src" else None,
                               on_key=(lambda vk, c, s: key_src(vk, c, s)) if key == "src" else None)
                box.pack(fill="both", expand=True, padx=1, pady=(1, 0))
                bar = tk.Frame(fr, bg=bgc)
                bar.pack(fill="x", padx=1, pady=(0, 1))
                panes[key] = (fr, box, bar)
            src_t, out_t = panes["src"][1], panes["out"][1]
            src_bar, out_bar = panes["src"][2], panes["out"][2]

            def mkbtn(parent, text, cmd, tip=""):
                b = tk.Label(parent, text=text, bg=parent.cget("bg"), fg=INK, font=F_I, padx=5, pady=1,
                             cursor="hand2")
                b.pack(side="left")
                b.bind("<Button-1>", lambda _e: cmd())
                base_bg = parent.cget("bg")
                b.bind("<Enter>", lambda _e: (b.config(bg="#E2E8F0"), status_tip(tip)))
                b.bind("<Leave>", lambda _e: (b.config(bg="#FECACA" if getattr(b, "_on", False) else base_bg),
                                              status_tip("")))
                return b
            mic_b = mkbtn(src_bar, "🎤", lambda: dictate(), "Speak – your words are typed here (no time limit)")
            mkbtn(src_bar, "🔊", lambda: speak("src"), "Listen to the original")
            mkbtn(src_bar, "📋", lambda: paste(), "Paste")
            mkbtn(src_bar, "✕", lambda: (flush_log(), src_t.clear(), changed()), "Clear")
            cnt_lbl = tk.Label(src_bar, text="0 / 5000", bg="white", fg=MUTE, font=F_S)
            cnt_lbl.pack(side="right", padx=6)
            mkbtn(out_bar, "🔊", lambda: speak("out"), "Listen to the translation")
            mkbtn(out_bar, "■", lambda: stop_audio(), "Stop the sound")
            mkbtn(out_bar, "📋", lambda: copy(), "Copy the translation")
            tk.Checkbutton(out_bar, text="slow", variable=v_slow, bg="#F8FAFC", font=F_S, activebackground="#F8FAFC",
                           borderwidth=0, highlightthickness=0).pack(side="left", padx=4)
            mkbtn(out_bar, "🗣", lambda: self._settings("voices"), "Choose the voices")

            foot = tk.Frame(outer, bg="white")
            foot.pack(fill="x", side="bottom")
            status = tk.Label(foot, text="", bg="white", fg=MUTE, font=F_S, anchor="w", justify="left")
            status.pack(side="left", fill="x", expand=True, padx=8, pady=(2, 3))
            ttk.Sizegrip(foot).pack(side="right", anchor="se")
            st["msg"] = "Type, paste or speak a text – the translation appears at once."
            status.config(text=st["msg"])

            def status_tip(tip: str) -> None:
                status.config(text=tip or st["msg"], fg=MUTE)

            def say(msg: str, col: str = MUTE) -> None:
                st["msg"] = msg
                status.config(text=msg, fg=col)

            def layout(_e=None) -> None:
                """Side by side when there is room, one above the other in a narrow window."""
                if st["mode"] != "normal":
                    return
                wide = body.winfo_width() >= 560
                if st.get("wide") == wide:
                    return
                st["wide"] = wide
                for k, (fr, _b, _bar) in panes.items():
                    fr.grid_forget()
                for c in range(2):
                    body.columnconfigure(c, weight=0, uniform="")
                    body.rowconfigure(c, weight=0, uniform="")
                if wide:
                    body.columnconfigure(0, weight=1, uniform="q")
                    body.columnconfigure(1, weight=1, uniform="q")
                    body.rowconfigure(0, weight=1)
                    panes["src"][0].grid(row=0, column=0, sticky="nsew", padx=(0, 4))
                    panes["out"][0].grid(row=0, column=1, sticky="nsew", padx=(4, 0))
                else:
                    body.columnconfigure(0, weight=1)
                    body.rowconfigure(0, weight=1, uniform="q")
                    body.rowconfigure(1, weight=1, uniform="q")
                    panes["src"][0].grid(row=0, column=0, sticky="nsew", pady=(0, 3))
                    panes["out"][0].grid(row=1, column=0, sticky="nsew", pady=(3, 0))
                eng_lbl.config(text=engine_text() if body.winfo_width() > 640 else "")
            body.bind("<Configure>", layout)

            # ---- moving the window without a title bar
            def start_move(e) -> None:
                st["mv"] = (e.x_root, e.y_root, win.winfo_x(), win.winfo_y())

            def do_move(e) -> None:
                x0, y0, wx, wy = st.get("mv", (e.x_root, e.y_root, win.winfo_x(), win.winfo_y()))
                win.geometry(f"+{wx + e.x_root - x0}+{wy + e.y_root - y0}")

            def set_on(b, on: bool, col: str = "#C7D2FE") -> None:
                b._on, b._on_bg = on, col
                b.config(bg=col if on else b.master.cget("bg"))

            def toggle_top() -> None:
                v_top.set(not v_top.get())
                win.attributes("-topmost", bool(v_top.get()) or st["mode"] == "live")
                set_on(b_top, v_top.get())
                say("Always on top: " + ("on" if v_top.get() else "off"))

            def toggle_log() -> None:
                v_log.set(not v_log.get())
                set_on(b_log, v_log.get())
                say(("Saving is ON – every translation goes into " +
                     str(QUICK_LOG_DIR / f"Quick_translations_{time.strftime('%Y-%m-%d')}.txt"))
                    if v_log.get() else "Saving is off.")
                if not v_log.get():
                    st["pending_log"] = None

            set_on(b_log, v_log.get())
            set_on(b_top, v_top.get())
            win.attributes("-topmost", bool(v_top.get()))

            def lang_of(which: str) -> str:
                if which == "out":
                    return codes.get(v_tgt.get(), "fa")
                c = codes.get(v_src.get(), "auto")
                return (st["detected"] or "en") if c == "auto" else c

            def engine_text() -> str:
                o = self._collect_options()
                if o.engine == "local":
                    return "built-in AI · " + o.model.split("/")[-1]
                return f"{'Ollama' if o.engine == 'ollama' else 'online API'} · {o.llm_model or '?'}"

            def key_src(vk: int, ctrl: bool, shift: bool) -> bool:
                if vk == 0x0D and ctrl:                       # Ctrl+Enter: translate now
                    win.after(1, request)
                    return True
                return False

            def changed() -> None:
                text = src_t.get()
                n = len(text)
                cnt_lbl.config(text=f"{n} / 5000", fg="#DC2626" if n > 5000 else MUTE)
                if codes.get(v_src.get()) == "auto":
                    lg = detect_language(text)
                    if not lg and _ARABIC_SCRIPT.search(text):
                        lg = "fa"
                    st["detected"] = lg or ("en" if re.search("[A-Za-z]", text) else "")
                    det_lbl.config(text=LANGS[st["detected"]]["name"] if st["detected"] else "")
                else:
                    det_lbl.config(text="")
                if st["job"] is not None:
                    win.after_cancel(st["job"])
                st["job"] = win.after(600, request)

            def request() -> None:
                st["job"] = None
                text = src_t.get()[:5000]
                src, tgt = lang_of("src"), codes.get(v_tgt.get(), "fa")
                if not text.strip():
                    out_t.set("")
                    return
                if src == tgt:
                    out_t.set(text)
                    say("The text is already in this language.")
                    return
                st["seq"] += 1
                opts = self._collect_options()
                if opts.engine == "local" and not self._quick_ready(opts):
                    say("The offline AI model is starting on your computer – the first time this can take a minute "
                        "or two. The translation appears by itself as soon as it is ready …", "#B45309")
                else:
                    say("Translating …")
                self._quick_request(st["seq"], text, src, tgt, opts)

            def result(seq: int, text: str, err: str, secs: float) -> None:
                if seq == -1:                                 # the model was loaded in advance
                    if err:
                        say("The model could not be loaded: " + err, "#DC2626")
                    elif st["load_t0"] is not None:
                        say(f"Ready – the offline model was loaded in {time.time() - st['load_t0']:.0f} s. "
                            "Translations now take a few seconds.")
                        st["load_t0"] = None
                    return
                if seq != st["seq"]:
                    return                                   # an older request: the text has changed since
                if err:
                    say("Error: " + err, "#DC2626")
                    return
                say(f"Translated in {secs:.1f} s" + ("   ·   📝 saving on" if v_log.get() else ""))
                out_t.set(text)
                if v_log.get():                               # saved when the text has stayed the same for 4 s
                    st["pending_log"] = (lang_of("src"), codes.get(v_tgt.get(), "fa"), src_t.get(), text)
                    if st["log_job"]:
                        win.after_cancel(st["log_job"])
                    st["log_job"] = win.after(4000, flush_log)

            def flush_log() -> None:
                st["log_job"] = None
                p_ = st.get("pending_log")
                st["pending_log"] = None
                if p_ and v_log.get() and p_[2].strip() and p_[3].strip():
                    try:
                        quick_log_write(*p_)
                    except Exception as exc:                  # noqa: BLE001
                        say(f"Could not save: {exc}", "#DC2626")

            self._quick_result = result

            def swap() -> None:
                flush_log()
                s_code, t_code = lang_of("src"), codes.get(v_tgt.get(), "fa")
                out = out_t.get()
                v_src.set(names.get(t_code, "English"))
                v_tgt.set(names.get(s_code, "Persian"))
                src_t.set(out)
                changed()

            def paste() -> None:
                try:
                    src_t.insert(win.clipboard_get())
                except Exception:
                    pass
                src_t.focus()

            def copy() -> None:
                win.clipboard_clear()
                win.clipboard_append(out_t.get())
                say("Translation copied.")

            def speak(which: str, text: Optional[str] = None, lang: Optional[str] = None) -> None:
                text = (text if text is not None else (src_t if which == "src" else out_t).get()).strip()
                lang = lang or lang_of(which)
                if not text:
                    return
                say("Preparing the voice …")
                rate = 0.75 if v_slow.get() else 1.0

                def work() -> None:
                    res, path = speak_to_file(text, lang, rate)
                    self.q.put(("qt_speak", res, path))
                threading.Thread(target=work, daemon=True).start()

            def spoken(res: str, path: str) -> None:
                if res == "OK":
                    try:
                        play_audio(path)
                        say("Speaking …   (■ stops)")
                    except Exception as exc:                  # noqa: BLE001
                        say(f"The sound can not be played: {exc}", "#DC2626")
                else:
                    say(res, "#B45309")
                    if "not installed" in res or "has no" in res:
                        if messagebox.askyesno("Voices", res + "\n\nOpen Settings → Voices to install a voice with one "
                                               "click (▶ Test installs it)?", parent=win):
                            self._settings("voices")

            self._quick_spoken = spoken

            # ---- speaking instead of typing (no time limit) -------------------------------------------
            def need_speech() -> bool:
                miss = speech_ready()
                if not miss:
                    return True
                if messagebox.askyesno(
                        "Speech recognition", "Offline speech recognition is not installed yet.\n\nMissing: " + miss +
                        ".\n\nOpen Settings to install it with one click (about 600 MB)?", parent=win):
                    self._settings("speech")
                return False

            def dictate() -> None:
                if st["dictate"] is not None:
                    st["dictate"].stop()
                    st["dictate"] = None
                    set_on(mic_b, False, "#FECACA")
                    say("Microphone off.")
                    return
                miss = speech_ready()
                if miss:
                    if os.name == "nt" and messagebox.askyesno(
                            "Speech recognition", "Offline speech recognition is not installed yet (missing: " + miss +
                            ").\n\nYes = use the voice typing of Windows (Win + H) now – English, German, French, "
                            "Spanish; needs the internet.\nNo = open Settings and install the offline recognition "
                            "for all five languages with one click.", parent=win):
                        src_t.focus()
                        try:
                            kb = ctypes.windll.user32.keybd_event
                            kb(0x5B, 0, 0, 0), kb(0x48, 0, 0, 0), kb(0x48, 0, 2, 0), kb(0x5B, 0, 2, 0)
                        except Exception:
                            pass
                    else:
                        self._settings("speech")
                    return
                lg = codes.get(v_src.get(), "auto")
                lst = SpeechListener("mic", lg, on_text=lambda t, l_: self.q.put(("qt_dict", t, l_)),
                                     on_partial=lambda t: self.q.put(("qt_dict_part", t)),
                                     on_status=lambda k, m: self.q.put(("qt_dict_st", k, m)) if k != "level" else None)
                st["dictate"] = lst
                lst.start()
                set_on(mic_b, True, "#FECACA")
                say("🎤 Loading speech recognition … then speak; click 🎤 again to stop.", "#B45309")

            def dict_event(kind: str, a="", b="") -> None:
                if kind == "qt_dict":
                    cur = src_t.get()
                    sep = "" if not cur or cur.endswith((" ", "\n")) else " "
                    src_t.append(sep + a)
                    if codes.get(v_src.get()) == "auto" and b in LANGS:
                        st["detected"] = b
                    say("🎤 listening …   (click 🎤 to stop)", "#B45309")
                elif kind == "qt_dict_part":
                    say("🎤 … " + a[-110:], "#B45309")
                elif kind == "qt_dict_st":
                    if a == "listening":
                        say("🎤 listening – speak now …   (click 🎤 to stop)", "#B45309")
                    elif a == "error":
                        say(b, "#DC2626")
                        if st["dictate"] is not None:
                            st["dictate"].stop()
                            st["dictate"] = None
                            set_on(mic_b, False)
            self._quick_dict = dict_event

            # ---- Live translation: two thin strips on top of every window --------------------------------
            live = tk.Frame(outer, bg="#0F172A")
            strips = tk.Frame(live, bg="#0F172A")
            strips.pack(side="left", fill="both", expand=True)
            cv_src = tk.Canvas(strips, bg="#0F172A", highlightthickness=0, height=30)
            cv_tr = tk.Canvas(strips, bg="#111827", highlightthickness=0, height=34)
            cv_src.pack(fill="both", expand=True)
            tk.Frame(strips, bg="#334155", height=1).pack(fill="x")
            cv_tr.pack(fill="both", expand=True)
            ctl = tk.Frame(live, bg="#0F172A")
            ctl.pack(side="right", fill="y")

            def lbtn(parent, text, cmd, tip):
                b = tk.Label(parent, text=text, bg="#0F172A", fg="#E2E8F0", font=("Segoe UI Symbol", 9), padx=3,
                             cursor="hand2")
                b.bind("<Button-1>", lambda _e: cmd())
                b.bind("<Enter>", lambda _e: (b.config(fg="#86EFAC"), live_tip(tip)))
                b.bind("<Leave>", lambda _e: (b.config(fg="#E2E8F0"), live_tip("")))
                return b
            row_a, row_b = tk.Frame(ctl, bg="#0F172A"), tk.Frame(ctl, bg="#0F172A")
            row_a.pack(anchor="e")
            row_b.pack(anchor="e")
            lb_back = lbtn(row_a, "⤢", lambda: leave_live(), "Back to the normal window (change languages …)")
            lb_pause = lbtn(row_a, "⏸", lambda: pause_live(), "Pause / go on")
            lb_close = lbtn(row_a, "✕", lambda: close(), "Close")
            lb_src = lbtn(row_b, "🔈", lambda: switch_source(), "Sound: this computer (film, video) ↔ microphone")
            lb_sum = lbtn(row_b, "Σ", lambda: toggle_sum(), "Summary: translate every sentence as short as possible")
            lb_save = lbtn(row_b, "💾", lambda: toggle_save(), "Save original + translation in a text file of the day")
            for b_ in (lb_back, lb_pause, lb_close):
                b_.pack(side="left")
            for b_ in (lb_src, lb_sum, lb_save):
                b_.pack(side="left")
            lgrip = ttk.Sizegrip(ctl)
            lgrip.pack(side="bottom", anchor="se")
            for w_ in (live, strips, cv_src, cv_tr, ctl):
                w_.bind("<ButtonPress-1>", lambda e: start_move(e))
                w_.bind("<B1-Motion>", lambda e: do_move(e))

            def live_tip(tip: str) -> None:
                if tip:
                    show_strip(cv_src, tip, "#FDE68A", False, tag="tip")
                else:
                    redraw_live()

            def live_marks() -> None:
                lb_src.config(text="🔈" if v_source.get() == "system" else "🎤")
                lb_sum.config(fg="#86EFAC" if v_sum.get() else "#E2E8F0", font=("Segoe UI Symbol", 9,
                                                                               "bold" if v_sum.get() else "normal"))
                lb_save.config(fg="#86EFAC" if v_save_live.get() else "#64748B")

            def show_strip(cv, text: str, col: str, rtl: bool, bold: bool = False, tag: str = "t") -> None:
                """One line of text; when it is longer than the strip the newest words stay in view and the old
                ones slide out – to the left for English, to the right for Persian."""
                cv.delete("all")
                w, h = max(40, cv.winfo_width()), max(20, cv.winfo_height())
                size = max(9, min(15, int(h * 0.45)))
                shown = ("‫" + text + "‬") if rtl else text
                it = cv.create_text(0, h / 2, text=shown, fill=col, anchor="w",
                                    font=("Tahoma", size, "bold" if bold else "normal"))
                bb = cv.bbox(it)
                tw = (bb[2] - bb[0]) if bb else 0
                if tw <= w - 16:
                    x = (w - 8 - tw) if rtl else 8
                else:
                    x = 8 if rtl else (w - 8 - tw)
                key = str(cv) + tag
                old = st["anim"].get(key)
                st["anim"][key] = x
                if old is None or abs(old - x) < 2 or abs(old - x) > w:
                    cv.coords(it, x, h / 2)
                    return
                steps = 8
                for k in range(1, steps + 1):                 # a short slide instead of a jump
                    xx = old + (x - old) * k / steps
                    cv.after(k * 22, lambda xx=xx, it=it: cv.coords(it, xx, h / 2) if cv.find_all() else None)
                cv.coords(it, old, h / 2)

            def redraw_live() -> None:
                if st["mode"] != "live":
                    return
                src_txt = " ".join(st["live_src"][-2:] + ([st["partial"]] if st["partial"] else []))[-400:]
                tr_txt = " ".join(st["live_tr"][-2:])[-400:]
                s_rtl = _first_strong_rtl(src_txt)
                t_rtl = bool(LANGS.get(codes.get(v_tgt.get(), "fa"), {}).get("rtl"))
                if not src_txt:
                    src_txt = ("Listening to " + ("the sound of this computer" if v_source.get() == "system"
                                                  else "the microphone") + " …") if st["listener"] else \
                        "Paused – ⏸ to go on"
                show_strip(cv_src, src_txt, "#CBD5E1", s_rtl)
                show_strip(cv_tr, tr_txt or "…", "#FFFFFF", t_rtl, bold=True)

            cv_src.bind("<Configure>", lambda _e: redraw_live())
            cv_tr.bind("<Configure>", lambda _e: redraw_live())

            def go_live() -> None:
                if not need_speech():
                    return
                flush_log()
                st["mode"] = "live"
                st["normal_geom"] = win.geometry()
                normal.pack_forget()
                foot.pack_forget()
                head.pack_forget()
                live.pack(fill="both", expand=True)
                g = prev.get("live_geom") or f"760x86+{win.winfo_x()}+{max(0, win.winfo_y())}"
                win.minsize(240, 56)
                win.geometry(g)
                win.attributes("-topmost", True)
                try:
                    win.attributes("-alpha", 0.94)
                except Exception:
                    pass
                st["live_src"], st["live_tr"], st["partial"] = [], [], ""
                live_marks()
                start_listen()

            def start_listen() -> None:
                if st["listener"] is not None:
                    st["listener"].stop()
                lg = codes.get(v_src.get(), "auto")
                lst = SpeechListener(v_source.get(), lg, on_text=lambda t, l_: self.q.put(("live_text", t, l_)),
                                     on_partial=lambda t: self.q.put(("live_part", t, "")),
                                     on_status=lambda k, m: self.q.put(("live_st", k, m)) if k != "level" else None)
                st["listener"] = lst
                lst.start()
                if v_save_live.get():
                    live_log.start(lg, codes.get(v_tgt.get(), "fa"), v_source.get(), v_sum.get())
                lb_pause.config(text="⏸")
                show_strip(cv_src, "Loading speech recognition …", "#FDE68A", False)
                show_strip(cv_tr, "", "#FFFFFF", False)

            def stop_listen() -> None:
                if st["listener"] is not None:
                    st["listener"].stop()
                    st["listener"] = None
                live_log.end()

            def pause_live() -> None:
                if st["listener"] is not None:
                    stop_listen()
                    lb_pause.config(text="▶")
                    st["partial"] = ""
                    redraw_live()
                else:
                    start_listen()

            def switch_source() -> None:
                v_source.set("mic" if v_source.get() == "system" else "system")
                live_marks()
                if st["listener"] is not None:
                    start_listen()

            def toggle_sum() -> None:
                v_sum.set(not v_sum.get())
                live_marks()

            def toggle_save() -> None:
                v_save_live.set(not v_save_live.get())
                live_marks()
                if v_save_live.get() and st["listener"] is not None:
                    live_log.start(codes.get(v_src.get(), "auto"), codes.get(v_tgt.get(), "fa"), v_source.get(),
                                   v_sum.get())
                elif not v_save_live.get():
                    live_log.end()

            def leave_live() -> None:
                stop_listen()
                prev["live_geom"] = win.geometry()
                st["mode"] = "normal"
                live.pack_forget()
                head.pack(fill="x")
                foot.pack(fill="x", side="bottom")
                normal.pack(fill="both", expand=True)
                win.minsize(340, 200)
                win.geometry(st["normal_geom"] or "780x400")
                win.attributes("-topmost", bool(v_top.get()))
                try:
                    win.attributes("-alpha", 1.0)
                except Exception:
                    pass
                st["wide"] = None
                win.after(50, layout)
                if st["live_src"]:                            # the last sentences can be read and copied here
                    src_t.set("\n".join(st["live_src"][-20:]))
                    out_t.set("\n".join(st["live_tr"][-20:]))

            def live_event(kind: str, a: str = "", b: str = "") -> None:
                if kind == "live_part":
                    st["partial"] = a
                    redraw_live()
                elif kind == "live_text":
                    st["partial"] = ""
                    st["live_src"].append(a)
                    st["live_src"] = st["live_src"][-50:]
                    redraw_live()
                    src = b if b in LANGS else lang_of("src")
                    tgt = codes.get(v_tgt.get(), "fa")
                    text = compress_sentence(a, src) if v_sum.get() else a
                    if src == tgt:
                        live_event("live_tr", text, a + "\x00" + src)
                        return
                    self._quick_request(-2, text, src, tgt, self._collect_options(), live=(a, src))
                elif kind == "live_tr":
                    original, _sep, src = b.partition("\x00")
                    st["live_tr"].append(a)
                    st["live_tr"] = st["live_tr"][-50:]
                    redraw_live()
                    if v_save_live.get():
                        try:
                            live_log.add(src, codes.get(v_tgt.get(), "fa"), original, a)
                        except Exception:
                            pass
                elif kind == "live_st":
                    if a == "listening":
                        redraw_live()
                    elif a == "error":
                        show_strip(cv_src, b[:160], "#FCA5A5", False)
                        stop_listen()
                        lb_pause.config(text="▶")
            self._quick_live = live_event

            src_t.on_change = changed
            src_cb.bind("<<ComboboxSelected>>", lambda _e: changed())
            tgt_cb.bind("<<ComboboxSelected>>", lambda _e: (changed(), preload()))

            def close() -> None:
                flush_log()
                stop_listen()
                if st["dictate"] is not None:
                    st["dictate"].stop()
                try:
                    d_ = load_json(SETTINGS_FILE, {})
                    if isinstance(d_, dict):
                        d_["quick"] = {"src": codes.get(v_src.get(), "auto"), "tgt": codes.get(v_tgt.get(), "fa"),
                                       "log": bool(v_log.get()), "top": bool(v_top.get()),
                                       "summary": bool(v_sum.get()), "save_live": bool(v_save_live.get()),
                                       "source": v_source.get(),
                                       "live_geom": win.geometry() if st["mode"] == "live" else prev.get("live_geom")}
                        save_json(SETTINGS_FILE, d_)
                except Exception:
                    pass
                stop_audio()
                self.quick_win = None
                win.destroy()

            def preload() -> None:
                """The offline model is loaded as soon as the window opens, while the user is still typing."""
                o = self._collect_options()
                if o.engine == "local" and not self._quick_ready(o):
                    st["load_t0"] = time.time()
                    say("The offline AI model is starting on your computer – the first time this can take a minute "
                        "or two (later only seconds). You can already type.", "#B45309")
                    self._quick_request(-1, "", lang_of("src") if codes.get(v_src.get()) != "auto" else "en",
                                        codes.get(v_tgt.get(), "fa"), o)

            win.protocol("WM_DELETE_WINDOW", close)
            win.bind("<Escape>", lambda _e: leave_live() if st["mode"] == "live" else None)
            win.after(80, lambda: (layout(), src_t.focus()))
            win.after(200, preload)
            self._quick_api = {"src": src_t, "out": out_t, "changed": changed, "request": request, "speak": speak,
                               "status": status, "v_src": v_src, "v_tgt": v_tgt, "swap": swap, "go_live": go_live,
                               "leave_live": leave_live, "live_event": live_event, "st": st, "toggle_log": toggle_log,
                               "flush_log": flush_log, "v_log": v_log, "dictate": dictate, "close": close,
                               "show_strip": show_strip, "redraw_live": redraw_live}

        def _quick_ready(self, opts: Options) -> bool:
            eng = getattr(self, "_qt_engine", None)
            return bool(eng and eng.get("model") == opts.model and opts.engine == "local")

        def _quick_request(self, seq: int, text: str, src: str, tgt: str, opts: Options,
                           live: Optional[tuple] = None) -> None:
            """Translations of the Quick window run in ONE thread of their own.  A typed text replaces the one that
            is still waiting (only the newest counts); sentences of Live translation are all translated, in order.
            seq -1 = only load the engine.  The engine stays loaded for the next requests."""
            if not hasattr(self, "_qt_jobs"):
                self._qt_jobs = collections.deque()
                self._qt_lock = threading.Lock()
            with self._qt_lock:
                if live is None:                                  # drop the older typed text that still waits
                    for j in [j for j in self._qt_jobs if j[5] is None]:
                        self._qt_jobs.remove(j)
                self._qt_jobs.append((seq, text, src, tgt, opts, live))
            if getattr(self, "_qt_thread", None) is not None and self._qt_thread.is_alive():
                return

            def loop() -> None:
                import dataclasses
                while True:
                    with self._qt_lock:
                        if not self._qt_jobs:
                            return
                        seq_, text_, src_, tgt_, o, live_ = self._qt_jobs.popleft()
                    t0 = time.time()
                    try:
                        o = dataclasses.replace(o, src_lang=src_)
                        key = (o.engine, o.model, o.llm_model, o.llm_url, src_, tgt_)
                        eng = getattr(self, "_qt_engine", None) or {}
                        if eng.get("key") != key:
                            mt = make_engine(o, tgt_, lambda m: None)
                            if o.engine == "local":
                                mt.beams = 1
                            eng = {"key": key, "mt": mt, "model": o.model if o.engine == "local" else ""}
                            self._qt_engine = eng
                        mt = eng["mt"]
                        if seq_ == -1:
                            self.q.put(("qt", -1, "", "", time.time() - t0))
                            continue
                        paras = text_.split("\n")
                        idx = [i for i, p_ in enumerate(paras) if p_.strip()]
                        res = mt.translate_texts([paras[i].strip() for i in idx]) if idx else []
                        out = list(paras)
                        for i, r in zip(idx, res):
                            out[i] = _post(r, tgt_, o) if tgt_ != "fa" else persian_typography(r, False)
                        joined = "\n".join(out)
                        if live_ is not None:
                            self.q.put(("live_tr", joined, live_[0] + "\x00" + live_[1]))
                        else:
                            self.q.put(("qt", seq_, joined, "", time.time() - t0))
                    except Exception as exc:              # noqa: BLE001
                        if live_ is None:
                            self.q.put(("qt", seq_, "", f"{type(exc).__name__}: {exc}", time.time() - t0))
                        else:
                            self.q.put(("live_st", "error", f"Translation error: {type(exc).__name__}: {exc}"))

            self._qt_thread = threading.Thread(target=loop, daemon=True)
            self._qt_thread.start()

        def _collect_options(self) -> Options:
            o = self.o
            label = self.model_var.get().strip()
            try:
                factor = max(0.3, min(3.0, int(self.fscale_var.get()) / 100))
            except (ValueError, tk.TclError):
                factor = 1.0
            try:
                min_scale = max(0.2, min(1.0, int(self.scale_var.get()) / 100))
            except (ValueError, tk.TclError):
                min_scale = 0.5
            return Options(skip_tables=not o["tables"].get(), skip_figures=o["figs"].get(),
                           skip_code=o["code"].get(),
                           skip_backmatter=not o["back"].get(), backmatter_keywords=self.kw_var.get(),
                           translate_captions=not o["caps"].get(), translate_bookmarks=not o["bm"].get(),
                           swap_columns=o["swap"].get(), best_quality=o["quality"].get(),
                           keep_terms=o["terms"].get(), auto_terms=o["auto"].get(),
                           keep_names=o["names"].get(), justify_body=o["justify"].get(),
                           bilingual_headings=o["bilingual"].get(),
                           specialties=parse_specialties(self.spec_var.get())[0],
                           auto_specialty=self.auto_spec.get(),
                           persian_digits=o["digits"].get(), rtl_direction=o["rtl"].get(),
                           align_right=o["align"].get(),
                           heading_font=self.head_var.get(), body_font=self.body_var.get(),
                           heading_font_file=self.custom_font["head"], body_font_file=self.custom_font["body"],
                           font_scale=factor,
                           out_pdf=self.out_pdf.get(), out_docx=self.out_docx.get(), out_txt=self.out_txt.get(),
                           min_scale=min_scale, pages=self.pages_var.get(),
                           model=MODELS.get(label, label), allow_download=o["dl"].get(),
                           speed="accurate", src_lang=self._origin(), engine=self._engine(),
                           llm_model=self.llm_model_var.get().strip(), llm_url=self.llm_url_var.get().strip(),
                           llm_key=self.llm_key_var.get().strip())

        def _start(self) -> None:
            if self.running:
                return
            langs = [c for c, v in self.lang_vars.items() if v.get()]
            if not self.pdf_var.get() or not self.out_var.get():
                messagebox.showwarning("Missing input", "Please choose the input file and the folder for the output.")
                return
            if not is_file(self.pdf_var.get()):
                messagebox.showwarning("Missing input", "The input file was not found:\n" + self.pdf_var.get())
                return
            sub = is_subtitle(self.pdf_var.get())
            if not sub and not (self.out_pdf.get() or self.out_docx.get() or self.out_txt.get()):
                messagebox.showwarning("No output format", "Tick at least one output format: Doc, Text or PDF.")
                return
            fi = self.file_info or {}
            if fi.get("other") and not fi.get("by_hand") and fi.get("path") == self.pdf_var.get():
                messagebox.showwarning(
                    "Language not supported yet",
                    f"This file seems to be written in {fi['other']}.\n\nFor now DeepTome translates only from "
                    "English, Persian, German, French and Spanish. If the language was recognised wrongly, choose "
                    "the right one with “wrong?” next to “Origin language”.")
                return
            if not langs:
                messagebox.showwarning("No language", "Select at least one target language.")
                return
            self.pdf_var.set(long_path(self.pdf_var.get()))
            self.out_var.set(long_path(self.out_var.get()))
            opts = self._collect_options()               # a snapshot: later changes in the window do not touch this job
            if parse_specialties(self.spec_var.get())[1]:
                self._log(f"Warning: only the first {MAX_SPECIALTIES} specialties are used.")
            # ---- a file with the output name is open in another program: ask now, not after the whole translation
            try:
                with fitz.open(xl(self.pdf_var.get())) as d0:
                    n0 = d0.page_count
                n_sel = len(parse_pages(opts.pages, n0))
                tail = "" if n_sel == n0 else opts.pages
            except Exception:
                n0 = n_sel = 0
                tail = opts.pages
            if (self.file_info or {}).get("damaged") and self.file_info.get("path") == self.pdf_var.get():
                if not messagebox.askyesno(
                        "Text of the PDF can not be read",
                        "The text inside this PDF is damaged: when it is copied out, many letters come out as wrong "
                        "characters (the fonts of the file have no correct character table). Such text can not be "
                        "translated correctly.\n\nPersian PDFs made by DeepTome before version 3.4 are of this kind –"
                        " translate their original instead.\n\nStart anyway?", default="no"):
                    return
            if n0 > MAX_FILE_PAGES:
                messagebox.showwarning("File too large", f"This file has {n0} pages.\n\nFiles of more than "
                                       f"{MAX_FILE_PAGES} pages are not accepted. Split the PDF into smaller files "
                                       f"and translate them one after the other.")
                return
            if n_sel > SPLIT_PAGES and opts.out_pdf and opts.engine != "api" and system_is_weak():
                cores, gb = system_info()
                n_files = -(-n_sel // SPLIT_PAGES)
                last = n_sel - SPLIT_PAGES * (n_files - 1)
                opts.split_pages = SPLIT_PAGES
                messagebox.showinfo(
                    "Long translation", f"{n_sel} pages are selected and this computer is slow for such a job "
                    f"({cores} processor cores, {gb:.0f} GB of memory).\n\nThe translation is therefore saved in "
                    f"{n_files} PDF files: every {SPLIT_PAGES} pages are translated, saved as a file of their own, "
                    f"and the next {SPLIT_PAGES} pages start automatically"
                    + (f" ({n_files - 1} files of {SPLIT_PAGES} pages and one of {last})" if last != SPLIT_PAGES
                       else "") + ".\n\nThe files are numbered in order:  …_file01of"
                    f"{n_files:02d}_pages_1-{SPLIT_PAGES}.pdf ,  …_file02of{n_files:02d}… and so on.")
            fast = opts.speed == "fast"
            exts = [e for e, on in ((".pdf", opts.out_pdf and not fast), (".docx", opts.out_docx and not fast),
                                    (".txt", opts.out_txt or fast)) if on]
            if sub:
                exts, tail = [Path(self.pdf_var.get()).suffix.lower()], ""
            locked = [Path(f).name for f in (fit_output_path(self.out_var.get(),
                                                             output_name(self.pdf_var.get(), lg, e, tail))
                                             for lg in langs for e in exts) if is_locked(f)]
            if locked:
                if not messagebox.askyesno(
                        "File is open", "A file with the output name is open in another program and can not be "
                        "overwritten:\n\n   " + "\n   ".join(locked) + "\n\nDo you want to save the translation "
                        "with another name in the same folder (an index such as _01 is added)?\n\n"
                        "Yes = save with an index      No = do not start (close the file first)"):
                    return
            self._save_settings()
            if self.o["review_terms"].get() and (opts.keep_terms or opts.src_lang != "en") and not fast and not sub:
                self._scan_then_start(langs, opts)
            else:
                self._launch(langs, opts)

        def _scan_then_start(self, langs: List[str], opts: Options) -> None:
            """Before the translation: find the technical terms of this file and let the user check them."""
            self.start_btn.config(state="disabled")
            self.status.config(text="Looking for technical terms in the file …")
            self._clear_log()
            self._log("Looking for the technical terms of this file …", "hd")
            pdf = self.pdf_var.get()

            def job() -> None:
                try:
                    found, used = scan_terms(pdf, opts, lambda m: self.q.put(("log", m)), threading.Event())
                    self.q.put(("terms", langs, opts, found, used))
                except Exception as exc:                     # noqa: BLE001
                    self.q.put(("log", f"Warning: the terms could not be collected ({type(exc).__name__}: {exc})."))
                    self.q.put(("terms", langs, opts, [], []))
            threading.Thread(target=job, daemon=True).start()

        def _terms_dialog(self, langs: List[str], opts: Options, found: list, used: List[str]) -> None:
            self.start_btn.config(state="normal")
            self.status.config(text="Ready")
            if found and len(found[0]) == 3:
                self._terms_dialog_foreign(langs, opts, found, used)
                return
            if not found:
                self._log("No technical terms from the term lists were found in this file.")
                self._launch(langs, opts, keep_log=True)
                return
            try:
                self.bell()
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass
            win = tk.Toplevel(self)
            win.title("Technical terms of this file")
            win.geometry("640x600")
            win.configure(bg=BG)
            win.transient(self)
            ttk.Label(win, justify="left", background=BG, foreground=INK, wraplength=610,
                      text=f"{len(found)} technical terms were found in this file. They are NOT translated – they "
                           f"stay in English.\n\n• Delete a line  → this word will be translated (also in later "
                           f"translations).\n• Add a line  → this word stays in English (also in later translations)."
                           f"\n\nThen click “Save and start”.").pack(anchor="w", padx=14, pady=(12, 4))
            if used:
                ttk.Label(win, background=BG, foreground=ACC, wraplength=610, justify="left",
                          text=f"{len(used)} of your instructions apply to this file:  " +
                               "   ·   ".join(u.split("|", 1)[1].strip() for u in used[:6]) +
                               (" …" if len(used) > 6 else "")).pack(anchor="w", padx=14)
            txt = ScrolledText(win, wrap="none", relief="flat", padx=10, pady=8, font="TkFixedFont")
            txt.pack(fill="both", expand=True, padx=14, pady=6)
            original = [t for t, _c in found]
            txt.insert("1.0", "\n".join(original) + "\n")
            row = ttk.Frame(win)
            row.pack(fill="x", padx=14, pady=(0, 12))
            done = {"v": False}

            def go(save: bool) -> None:
                if done["v"]:
                    return
                done["v"] = True
                if save:
                    now = [x.strip() for x in txt.get("1.0", "end").splitlines() if x.strip()]
                    low_now, low_old = {x.lower() for x in now}, {x.lower() for x in original}
                    removed = [x for x in original if x.lower() not in low_now]
                    added = [x for x in now if x.lower() not in low_old]
                    add_instructions([("translate", x, "") for x in removed] + [("keep", x, "") for x in added])
                    self._log(f"Terms checked: {len(removed)} will be translated from now on, {len(added)} new "
                              f"term(s) stay in English. Saved in {INSTRUCTIONS_FILE.name}.", "ok")
                win.destroy()
                self._launch(langs, opts, keep_log=True)

            def cancel() -> None:
                done["v"] = True
                win.destroy()
                self._log("Not started.")

            ttk.Button(row, text="Save and start", style="Accent.TButton", command=lambda: go(True)).pack(side="left")
            ttk.Button(row, text="Start without changes", command=lambda: go(False)).pack(side="left", padx=8)
            ttk.Button(row, text="Cancel", command=cancel).pack(side="right")
            win.protocol("WM_DELETE_WINDOW", cancel)

        def _terms_dialog_foreign(self, langs: List[str], opts: Options, found: list, used: List[str]) -> None:
            """Terms of a file that is NOT English (e.g. Persian -> German): the words of the origin language that
            recur, and the English words in it.  For each the user decides: it stays as it is, the engine translates
            it, or it gets a fixed translation in the target language.  Stored in "My instructions"."""
            src, tgt = opts.src_lang, langs[0]
            s_name, t_name = LANGS[src]["name"], LANGS[tgt]["name"]
            rtl = bool(LANGS[src]["rtl"])
            ins = load_instructions()
            key = lambda t: " ".join(_TOKEN_RE.findall(t.lower()))
            fixed = {key(e): tr for k, e, tr in ins if k == tgt}
            keep_set = {key(e) for k, e, _t in ins if k == "keep"}
            trans_set = {key(e) for k, e, _t in ins if k == "translate"}
            try:
                self.bell()
            except Exception:
                pass
            win = tk.Toplevel(self)
            win.title(f"Technical terms of this file – {s_name} → {t_name}")
            win.geometry("760x640")
            win.configure(bg=BG)
            win.transient(self)
            ttk.Label(win, justify="left", background=BG, foreground=INK, wraplength=730,
                      text=f"{len(found)} terms were found in this {s_name} file. Choose for each what happens in the "
                           f"{t_name} translation:\n• Keep as it is – the word is copied unchanged (English words, "
                           f"names, acronyms).\n• Engine translates – the translation engine translates it.\n"
                           f"• My translation – your fixed {t_name} word is always used.\nYour choices are kept "
                           f"for later translations (“My instructions”).").pack(anchor="w", padx=14, pady=(12, 6))
            if used:
                ttk.Label(win, background=BG, foreground=ACC, wraplength=730, justify="left",
                          text=f"{len(used)} of your instructions apply to this file already.").pack(anchor="w",
                                                                                                    padx=14)
            fr = ttk.Frame(win)
            fr.pack(fill="both", expand=True, padx=14, pady=6)
            tv = ttk.Treeview(fr, columns=("term", "count", "what"), show="headings", selectmode="browse")
            tv.heading("term", text=f"Term ({s_name})")
            tv.heading("count", text="Count")
            tv.heading("what", text=f"In the {t_name} translation")
            tv.column("term", width=290, anchor="e" if rtl else "w")
            tv.column("count", width=60, anchor="center")
            tv.column("what", width=330, anchor="w")
            sb = ttk.Scrollbar(fr, orient="vertical", command=tv.yview)
            tv.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            tv.pack(fill="both", expand=True)
            state: Dict[str, list] = {}                 # row id -> [term, start action, action, fixed text]

            def label(act: str, txt: str) -> str:
                return {"keep": "keep as it is", "engine": "engine translates"}.get(act, f"→ {txt}")

            for term, cnt, kd in found:
                k = key(term)
                if k in fixed:
                    act, txt = "fixed", fixed[k]
                elif k in keep_set or (kd == "keep" and k not in trans_set):
                    act, txt = "keep", ""
                else:
                    act, txt = "engine", ""
                iid = tv.insert("", "end", values=(term, cnt, label(act, txt)))
                state[iid] = [term, act, act, txt]
            ed = ttk.Frame(win)
            ed.pack(fill="x", padx=14)
            ttk.Label(ed, text=f"{t_name} translation of the chosen term:").pack(side="left")
            v_tr = tk.StringVar()
            ent = ttk.Entry(ed, textvariable=v_tr, width=34)
            ent.pack(side="left", padx=6)
            btns = ttk.Frame(win)
            btns.pack(fill="x", padx=14, pady=(6, 0))

            def chosen() -> Optional[str]:
                sel = tv.selection()
                return sel[0] if sel else None

            def set_act(act: str) -> None:
                iid = chosen()
                if not iid:
                    return
                st = state[iid]
                if act == "fixed":
                    if not v_tr.get().strip():
                        ent.focus_set()
                        return
                    st[3] = v_tr.get().strip()
                st[2] = act
                tv.set(iid, "what", label(act, st[3]))

            def on_sel(_e=None) -> None:
                iid = chosen()
                if iid:
                    v_tr.set(state[iid][3])

            tv.bind("<<TreeviewSelect>>", on_sel)
            ent.bind("<Return>", lambda _e: set_act("fixed"))
            ttk.Button(btns, text="Use my translation", command=lambda: set_act("fixed")).pack(side="left")
            ttk.Button(btns, text="Engine translates", command=lambda: set_act("engine")).pack(side="left", padx=6)
            ttk.Button(btns, text="Keep as it is", command=lambda: set_act("keep")).pack(side="left")
            addf = ttk.Frame(win)
            addf.pack(fill="x", padx=14, pady=(6, 0))
            ttk.Label(addf, text="Add a term:").pack(side="left")
            v_new = tk.StringVar()
            ttk.Entry(addf, textvariable=v_new, width=30).pack(side="left", padx=6)

            def add_term() -> None:
                t = v_new.get().strip()
                if not t:
                    return
                iid = tv.insert("", 0, values=(t, "–", label("engine", "")))
                state[iid] = [t, "new", "engine", ""]
                v_new.set("")
                tv.selection_set(iid)
                tv.see(iid)
            ttk.Button(addf, text="Add", command=add_term).pack(side="left")
            row = ttk.Frame(win)
            row.pack(fill="x", padx=14, pady=(10, 12))
            done = {"v": False}

            def go(save: bool) -> None:
                if done["v"]:
                    return
                done["v"] = True
                if save:
                    new: List[Tuple[str, str, str]] = []
                    for term, start, act, txt in state.values():
                        if act == start and not (act == "fixed" and txt != fixed.get(key(term))):
                            continue
                        if act == "keep":
                            new.append(("keep", term, ""))
                        elif act == "fixed":
                            new.append((tgt, term, txt))
                        else:
                            new.append(("translate", term, ""))
                    add_instructions(new)
                    self._log(f"Terms checked ({s_name} → {t_name}): {len(new)} change(s) saved in "
                              f"{INSTRUCTIONS_FILE.name}.", "ok")
                win.destroy()
                self._launch(langs, opts, keep_log=True)

            def cancel() -> None:
                done["v"] = True
                win.destroy()
                self._log("Not started.")

            ttk.Button(row, text="Save and start", style="Accent.TButton", command=lambda: go(True)).pack(side="left")
            ttk.Button(row, text="Start without changes", command=lambda: go(False)).pack(side="left", padx=8)
            ttk.Button(row, text="Cancel", command=cancel).pack(side="right")
            win.protocol("WM_DELETE_WINDOW", cancel)
            self._terms_api = {"tv": tv, "state": state, "set_act": set_act, "v_tr": v_tr, "go": go}

        def _clear_log(self) -> None:
            self.log_box.config(state="normal")
            self.log_box.delete("1.0", "end")
            self.log_box.config(state="disabled")
            self.err_count = 0
            self.err_lbl.config(text="Errors / warnings: 0")
            self.update_idletasks()

        def _launch(self, langs: List[str], opts: Options, keep_log: bool = False) -> None:
            if not keep_log:
                self._clear_log()                        # a new job: the old log disappears at once
            import multiprocessing as mp
            ctx = mp.get_context("spawn")
            self.job_q = ctx.Queue()
            self.cancel_ev = ctx.Event()
            self.review_ev = ctx.Event()
            self.resp_q = ctx.Queue()
            if self.review_var.get():
                self.review_ev.set()
            pdf, out = self.pdf_var.get(), self.out_var.get()
            self.proc = ctx.Process(target=_job_entry,
                                    args=((pdf, out, langs, opts), self.job_q, self.cancel_ev,
                                          {"review": self.review_ev, "resp": self.resp_q}), daemon=True)
            self.pb["value"] = 0
            self.status.config(text="Starting …")
            self.eta_left = None
            self.eta_lbl.config(text="")
            self.eta_note.config(text="")
            self.elapsed_lbl.config(text="00:00:00  Elapsed time")
            self.phase_lbl.config(text="Starting …")
            self.t0, self.running = time.time(), True
            self._load_reset()
            self.start_btn.config(state="disabled")
            self.cancel_btn.config(state="normal")
            self._log(f"Starting – {len(langs)} language(s), translation engine: "
                      f"{opts.model if opts.engine == 'local' else opts.engine + ' / ' + opts.llm_model}", "hd")
            save_json(PENDING_FILE, {"pdf": pdf, "out": out, "pages": self.pages_var.get(),
                                     "settings": self._settings_dict(), "time": time.strftime("%Y-%m-%d %H:%M")})
            self.update_idletasks()
            self.proc.start()

        def _check_pending(self) -> None:
            """The app was closed (or the computer went off) in the middle of a job: offer to continue it."""
            d = load_json(PENDING_FILE, None)
            if not isinstance(d, dict) or self.running:
                return
            if not is_file(d.get("pdf", "")):
                PENDING_FILE.unlink(missing_ok=True)
                return
            if not messagebox.askyesno(
                    "Unfinished translation", "The last translation was not finished:\n\n   " + d["pdf"] +
                    f"\n   started {d.get('time', '')}\n\nDo you want to continue it now? The parts that were "
                    "already finished are taken from the cache."):
                PENDING_FILE.unlink(missing_ok=True)
                return
            self._apply_settings(d.get("settings") or {})
            self.pdf_var.set(d["pdf"])
            self.out_var.set(d.get("out") or str(Path(d["pdf"]).parent / "translated"))
            self.pages_var.set(d.get("pages", ""))
            langs = [c for c, v in self.lang_vars.items() if v.get()]
            self._launch(langs, self._collect_options())

        def _cancel(self) -> None:
            """Stops the translation at once: ask politely, then end the worker process (it may be hanging)."""
            if self.proc is None:
                return
            self._play("cancel")
            if not messagebox.askyesno("Cancel", "Are you sure you want to cancel the translation?\n\n"
                                       "(The finished parts stay in the cache: starting the same job again "
                                       "continues after them.)", default="no"):
                return
            if self.proc is None:
                return
            self.cancel_btn.config(state="disabled")
            self.status.config(text="Cancelling …")
            try:
                self.cancel_ev.set()
            except Exception:
                pass
            self.after(600, self._kill_job)

        def _kill_job(self) -> None:
            proc = self.proc
            if proc is not None and proc.is_alive():
                proc.terminate()
                proc.join(2)
            self._job_finished("cancelled", None)

        def _job_finished(self, kind: str, payload) -> None:
            if self.proc is None:
                return                                   # already handled
            self.proc = None
            self.job_q = None
            self.review_ev = None
            self.resp_q = None
            self.running = False
            self.eta_left = None
            self.eta_lbl.config(text="")
            self.eta_note.config(text="")
            if self.review_win is not None:
                try:
                    self.review_win.destroy()
                except Exception:
                    pass
                self.review_win = None
            try:
                PENDING_FILE.unlink(missing_ok=True)
            except Exception:
                pass
            self.start_btn.config(state="normal")
            self.cancel_btn.config(state="disabled")
            if kind == "done":
                self.pb["value"] = 1000
                self.status.config(text="Finished ✓")
                self._log("All done:\n  " + "\n  ".join(payload), "ok")
                self._finished_dialog(list(payload or []))
                return
            self.pb["value"] = 0                         # back to zero at once
            if kind == "cancelled":
                self.status.config(text="Cancelled")
                self._log("Cancelled.")
            else:
                self.status.config(text="Error")
                self._log("ERROR: " + str(payload), "err")
                messagebox.showerror("Error", str(payload) + "\n\nThe finished parts stay in the cache: click "
                                     "“RUN” again to continue after them.")

        def _finished_dialog(self, files: List[str]) -> None:
            """'Finished' message: where every file was saved, with Open buttons."""
            self._play("done")
            win = tk.Toplevel(self)
            win.title("Finished")
            win.configure(bg=BG)
            win.transient(self)
            box = tk.Frame(win, bg=BG, padx=20, pady=16)
            box.pack(fill="both", expand=True)
            tk.Label(box, text="Translation finished ✓", bg=BG, fg=ACC, font=self.f_h).grid(
                row=0, column=0, columnspan=3, sticky="w")
            if files:
                tk.Label(box, text="Saved in:  " + str(Path(files[0]).parent), bg=BG, fg=INK, wraplength=760,
                         justify="left").grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 8))
            for i, f in enumerate(files):
                tk.Label(box, text=Path(f).name, bg=BG, fg=INK, font=self.f_b, wraplength=520,
                         justify="left").grid(row=2 + i, column=0, sticky="w", pady=2)
                ttk.Button(box, text="Open", command=lambda f=f: open_path(f)).grid(row=2 + i, column=1, padx=(12, 4))
                ttk.Button(box, text="Show in folder", command=lambda f=f: reveal_path(f)).grid(row=2 + i, column=2)
            ttk.Button(box, text="Close", command=win.destroy).grid(row=3 + len(files), column=0, columnspan=3,
                                                                    sticky="e", pady=(14, 0))

        def _close(self) -> None:
            msg = "Are you sure you want to close the app?"
            if self.running:
                msg = ("A translation is running. Are you sure you want to close the app?\n\nThe finished parts "
                       "are kept: when you open the app again it offers to continue this translation.")
            if not messagebox.askyesno("Close", msg, default="no"):
                return
            self._save_settings()
            try:
                if self.proc is not None and self.proc.is_alive():
                    self.proc.terminate()
            except Exception:
                pass
            self.destroy()

        # --------------------------------------------------- review window
        def _review_answer(self, resp: dict, close: bool = True) -> None:
            q_ = self.resp_q
            if q_ is not None:
                try:
                    q_.put(resp)
                except Exception:
                    pass
            if close and self.review_win is not None:
                try:
                    self.review_win.destroy()
                except Exception:
                    pass
                self.review_win = None

        def _review(self, d: dict) -> None:
            """"Translate with review": the finished part as it will be saved.  ONE thing is selected at a time – a
            text block or a framed area – and Esc clears the selection.  Click a block to edit its text, drag it with
            the mouse, move it with the arrow keys or type its exact place (from the top-left corner of the page).
            Drag on an empty place (or use the Frame tool) to frame anything – names, a picture, a table – and move
            it the same way.  Every change is shown at once and the page is typeset again by itself after a moment;
            “Save and next part” keeps all changes, “Undo all” goes back to the first result."""
            if self.review_win is not None:
                try:
                    self.review_win.destroy()
                except Exception:
                    pass
            self.eta_left = None
            self.eta_lbl.config(text="Paused – waiting for your review")
            try:
                self.bell()
            except Exception:
                pass
            win = tk.Toplevel(self)
            self.review_win = win
            pages = d.get("pages", [])
            win.title(f"Review – part {d['part']} of {d['nparts']}")
            win.geometry(f"1340x{max(600, min(880, self.winfo_screenheight() - 90))}")
            win.minsize(1000, 540)
            win.configure(bg=BG)
            rtl = bool(d.get("rtl"))
            paras: List[dict] = d.get("paras", [])
            edits: Dict[str, dict] = {}
            areas: List[dict] = []
            spaces: List[dict] = []
            cur = {"sel": None, "zoom": 1.0, "imgs": [], "geom": [], "drag": None, "hover": None, "patches": [],
                   "rendered": {"edits": {}, "areas": {}, "spaces": 0}, "seq": 0, "inflight": None, "dirty": False,
                   "live_job": None, "rid": 0, "pdf": d["pdf"], "store_job": None, "k": None}
            mode = tk.StringVar(value="block")

            top = ttk.Frame(win, padding=(10, 6))
            top.pack(fill="x")
            ttk.Label(top, text=f"Part {d['part']} of {d['nparts']}  ·  page(s) "
                                f"{', '.join(str(x) for x in pages)}", font=self.f_b).pack(side="left")
            ttk.Label(top, text="   Tool:").pack(side="left")
            for val, txt in (("block", "Select / move"), ("area", "Frame an area"), ("space", "Space between lines")):
                ttk.Radiobutton(top, text=txt, value=val, variable=mode, command=lambda: set_mode()).pack(
                    side="left", padx=(6, 0))
            v_space = tk.IntVar(value=12)
            ttk.Spinbox(top, from_=-200, to=200, increment=2, textvariable=v_space, width=5).pack(side="left",
                                                                                               padx=(4, 0))
            ttk.Label(top, text="pt").pack(side="left")
            v_col = tk.BooleanVar(value=False)
            ttk.Checkbutton(top, text="only this column", variable=v_col).pack(side="left", padx=(6, 0))
            ttk.Button(top, text="Zoom +", command=lambda: zoom(1.25)).pack(side="right")
            ttk.Button(top, text="Zoom −", command=lambda: zoom(0.8)).pack(side="right", padx=4)
            ttk.Button(top, text="Fit width", command=lambda: zoom(0)).pack(side="right")

            bottom = ttk.Frame(win, padding=(10, 8))
            bottom.pack(side="bottom", fill="x")
            note = ttk.Label(bottom, text="", foreground=MUTE)
            note.pack(side="left", padx=(0, 12))
            live_lbl = ttk.Label(bottom, text="", foreground="#B45309")
            live_lbl.pack(side="left")

            pane = ttk.Panedwindow(win, orient="horizontal")
            pane.pack(fill="both", expand=True, padx=10)
            left = ttk.Frame(pane)
            right = ttk.Frame(pane, padding=(8, 0, 0, 0))
            pane.add(left, weight=3)
            pane.add(right, weight=2)
            cv = tk.Canvas(left, bg="#64748B", highlightthickness=0, takefocus=1)
            vs = ttk.Scrollbar(left, orient="vertical", command=cv.yview)
            hs = ttk.Scrollbar(left, orient="horizontal", command=cv.xview)
            cv.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
            vs.pack(side="right", fill="y")
            hs.pack(side="bottom", fill="x")
            cv.pack(fill="both", expand=True)
            cv.bind("<MouseWheel>", lambda e: (cv.yview_scroll(-1 if e.delta > 0 else 1, "units"), "break")[1])

            # ---- geometry helpers
            def to_cv(pi: int, x: float, y: float) -> Tuple[float, float]:
                y0, sc_ = cur["geom"][pi]
                return 10 + x * sc_, y0 + y * sc_

            def to_page(cx: float, cy: float) -> Optional[Tuple[int, float, float]]:
                for pi, (y0, sc_) in enumerate(cur["geom"]):
                    h = cur["imgs"][pi].height()
                    if y0 <= cy <= y0 + h:
                        return pi, (cx - 10) / sc_, (cy - y0) / sc_
                return None

            def moved_box(k: int, e: Optional[dict] = None) -> Tuple[float, float, float, float]:
                x0, y0, x1, y1 = paras[k].get("bbox") or (0, 0, 0, 0)
                e = edits.get(str(k), {}) if e is None else e
                dx, dy = e.get("dx", 0.0), e.get("dy", 0.0)
                return x0 + dx, y0 + dy, x1 + dx + e.get("dw", 0.0), y1 + dy + e.get("dh", 0.0)

            def area_box(ar: dict) -> Tuple[float, float, float, float]:
                r = ar["rect"]
                return r[0] + ar.get("dx", 0.0), r[1] + ar.get("dy", 0.0), r[2] + ar.get("dx", 0.0), r[3] + ar.get(
                    "dy", 0.0)

            def page_w(pi: int) -> float:
                try:
                    return cur["imgs"][pi].width() / cur["geom"][pi][1]
                except Exception:
                    return 600.0

            def sel_block() -> Optional[int]:
                s_ = cur["sel"]
                return s_[1] if s_ and s_[0] == "block" else None

            def sel_area() -> Optional[dict]:
                s_ = cur["sel"]
                return s_[1] if s_ and s_[0] == "area" else None

            # ---- what the page shows at once (before it is typeset again): moved pieces of the picture
            def patch(pi: int, box: tuple, dx: float, dy: float, erase_only: bool = False) -> None:
                if pi >= len(cur["imgs"]):
                    return
                img = cur["imgs"][pi]
                sc_ = cur["geom"][pi][1]
                x0, y0 = max(0, int(box[0] * sc_)), max(0, int(box[1] * sc_))
                x1, y1 = min(img.width(), int(box[2] * sc_) + 1), min(img.height(), int(box[3] * sc_) + 1)
                if x1 - x0 < 2 or y1 - y0 < 2:
                    return
                a = to_cv(pi, x0 / sc_, y0 / sc_)
                cv.create_rectangle(a[0], a[1], a[0] + x1 - x0, a[1] + y1 - y0, fill="white", outline="",
                                    tags=("ov", "patch"))
                if erase_only:
                    return
                pim = tk.PhotoImage(width=x1 - x0, height=y1 - y0)
                pim.tk.call(pim, "copy", img, "-from", x0, y0, x1, y1, "-to", 0, 0)
                cur["patches"].append(pim)
                cv.create_image(a[0] + dx * sc_, a[1] + dy * sc_, anchor="nw", image=pim, tags=("ov", "patch"))

            def overlay() -> None:
                """Frames over the page: the selected thing (blue), the block under the mouse (thin), moved things
                (green), framed areas (red dashes)."""
                cv.delete("ov")
                cur["patches"] = []
                if not cur["geom"]:
                    return
                ren = cur["rendered"]
                for k in range(len(paras)):                   # moves that are not typeset yet
                    e, r_ = edits.get(str(k), {}), ren["edits"].get(str(k), {})
                    dx, dy = e.get("dx", 0.0) - r_.get("dx", 0.0), e.get("dy", 0.0) - r_.get("dy", 0.0)
                    if abs(dx) > 0.05 or abs(dy) > 0.05:
                        patch(paras[k].get("pi", 0), moved_box(k, r_), dx, dy)
                for ar in areas:
                    r_ = ren["areas"].get(ar["rid"])
                    if ar.get("delete"):
                        if not (r_ and r_[2]):
                            patch(ar["page"], area_box(ar), 0, 0, True)
                        continue
                    rdx, rdy = (r_[0], r_[1]) if r_ else (0.0, 0.0)
                    if abs(ar.get("dx", 0) - rdx) > 0.05 or abs(ar.get("dy", 0) - rdy) > 0.05:
                        r = ar["rect"]
                        patch(ar["page"], (r[0] + rdx, r[1] + rdy, r[2] + rdx, r[3] + rdy), ar["dx"] - rdx,
                              ar["dy"] - rdy)
                k_sel, hv = sel_block(), cur["hover"]
                for k, it in enumerate(paras):
                    if not it.get("bbox") or it.get("pi", 0) >= len(cur["geom"]):
                        continue
                    if k != k_sel and k != hv:
                        continue
                    pi = it["pi"]
                    b = moved_box(k)
                    a = to_cv(pi, b[0], b[1]) + to_cv(pi, b[2], b[3])
                    cv.create_rectangle(a[0] - 2, a[1] - 2, a[2] + 2, a[3] + 2, outline="#3D98FF" if k == k_sel
                                        else "#94A3B8", width=2 if k == k_sel else 1, dash=() if k == k_sel else (3, 3),
                                        tags="ov")
                    if k == k_sel:                            # little handles: it can be dragged
                        for hx, hy in ((a[0], a[1]), (a[2], a[1]), (a[0], a[3]), (a[2], a[3])):
                            cv.create_rectangle(hx - 4, hy - 4, hx + 4, hy + 4, fill="#3D98FF", outline="white",
                                                tags="ov")
                for k in range(len(paras)):                   # where moved blocks came from
                    e = edits.get(str(k), {})
                    if (e.get("dx") or e.get("dy")) and k == k_sel:
                        it = paras[k]
                        o = to_cv(it["pi"], it["bbox"][0], it["bbox"][1])
                        b = moved_box(k)
                        n_ = to_cv(it["pi"], b[0], b[1])
                        cv.create_line(*o, *n_, fill="#16A34A", arrow="last", dash=(4, 3), tags="ov")
                for sp in spaces:                             # room inserted (green) / removed (red)
                    pi = int(sp["page"])
                    if pi >= len(cur["geom"]):
                        continue
                    pw = page_w(pi)
                    xa, xb = max(0.0, sp.get("x0", 0)), min(pw, sp.get("x1", pw))
                    a = to_cv(pi, xa, sp["y"]) + to_cv(pi, xb, sp["y"])
                    col_ = "#16A34A" if sp["dy"] > 0 else "#DC2626"
                    cv.create_line(*a, fill=col_, width=2, dash=(4, 3), tags="ov")
                    cv.create_text(a[2] - 4, a[1] - 7, anchor="e", fill=col_, tags="ov",
                                   text=f"{'+' if sp['dy'] > 0 else ''}{sp['dy']:.0f} pt", font=("Segoe UI", 9, "bold"))
                a_sel = sel_area()
                for ar in areas:
                    if ar["page"] >= len(cur["geom"]):
                        continue
                    b = area_box(ar)
                    a = to_cv(ar["page"], b[0], b[1]) + to_cv(ar["page"], b[2], b[3])
                    on = ar is a_sel
                    if ar.get("delete"):
                        cv.create_rectangle(*a, outline="#DC2626", width=1, dash=(2, 3), tags="ov")
                        continue
                    if on or mode.get() == "area":
                        cv.create_rectangle(*a, outline="#DC2626" if on else "#F87171", width=2 if on else 1,
                                            dash=(5, 3), tags="ov")
                    if on:
                        for hx, hy in ((a[0], a[1]), (a[2], a[1]), (a[0], a[3]), (a[2], a[3])):
                            cv.create_rectangle(hx - 4, hy - 4, hx + 4, hy + 4, fill="#DC2626", outline="white",
                                                tags="ov")
                show_pos()

            def draw(keep_view: bool = False) -> None:
                yv, xv = cv.yview()[0], cv.xview()[0]
                cv.delete("all")
                cur["imgs"], cur["geom"] = [], []
                try:
                    doc = fitz.open(xl(cur["pdf"]))
                except Exception as exc:                 # noqa: BLE001
                    cv.create_text(20, 20, anchor="nw", fill="white", text=f"Preview not available: {exc}")
                    return
                y = 10
                wmax = 0
                for pg in doc:
                    z = cur["zoom"] * 1.4
                    pix = pg.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
                    img = tk.PhotoImage(data=base64.b64encode(pix.tobytes("png")).decode("ascii"))
                    cur["imgs"].append(img)
                    cur["geom"].append((y, z))
                    cv.create_image(10, y, anchor="nw", image=img, tags="page")
                    y += img.height() + 12
                    wmax = max(wmax, img.width())
                doc.close()
                cv.configure(scrollregion=(0, 0, wmax + 20, y))
                if keep_view:
                    cv.yview_moveto(yv)
                    cv.xview_moveto(xv)
                overlay()

            def zoom(f: float) -> None:
                if f == 0:
                    try:
                        with fitz.open(xl(cur["pdf"])) as doc:
                            wpt = max(pg.rect.width for pg in doc)
                        cur["zoom"] = max(0.3, (cv.winfo_width() - 30) / (wpt * 1.4))
                    except Exception:
                        cur["zoom"] = 1.0
                else:
                    cur["zoom"] = max(0.3, min(4.0, cur["zoom"] * f))
                draw()

            # ---- right: list of text blocks, place of the selection, editor
            ttk.Label(right, text="Text blocks of this part (click one here or on the page):",
                      font=self.f_b).pack(anchor="w")
            lf = ttk.Frame(right)
            lf.pack(fill="both", expand=True)
            lb = tk.Listbox(lf, activestyle="none", exportselection=False, font=("Tahoma", 9), height=6)
            lsb = ttk.Scrollbar(lf, orient="vertical", command=lb.yview)
            lb.configure(yscrollcommand=lsb.set)
            lsb.pack(side="right", fill="y")
            lb.pack(fill="both", expand=True)
            for it in paras:
                lb.insert("end", f"p.{it['page']}  {'[H] ' if it['heading'] else ''}"
                                 f"{it['text'][:70].replace(chr(10), ' ⏎ ')}")
            # -- the place of the selected block / frame, in pt or mm from the top-left corner of the page
            posf = ttk.LabelFrame(right, text=" Place of the selection (from the top-left corner of the page) ",
                                  padding=(8, 4))
            posf.pack(fill="x", pady=(6, 2))
            v_x, v_y, v_w, v_h = (tk.StringVar() for _ in range(4))
            v_unit = tk.StringVar(value="pt")
            v_step = tk.StringVar(value="1")
            ents = {}
            for c_, (lab, var) in enumerate((("X", v_x), ("Y", v_y), ("Width", v_w), ("Height", v_h))):
                ttk.Label(posf, text=lab).grid(row=0, column=2 * c_, sticky="e", padx=(6 if c_ else 0, 2))
                en = ttk.Entry(posf, textvariable=var, width=7)
                en.grid(row=0, column=2 * c_ + 1)
                en.bind("<Return>", lambda _e: apply_pos())
                en.bind("<KP_Enter>", lambda _e: apply_pos())
                ents[lab] = en
            ttk.Combobox(posf, textvariable=v_unit, values=["pt", "mm"], width=4, state="readonly").grid(
                row=0, column=8, padx=(8, 0))
            ttk.Button(posf, text="Apply", command=lambda: apply_pos()).grid(row=0, column=9, padx=(6, 0))
            mvr = ttk.Frame(posf)
            mvr.grid(row=1, column=0, columnspan=10, sticky="w", pady=(4, 0))
            ttk.Label(mvr, text="Move by").pack(side="left")
            ttk.Spinbox(mvr, from_=0.5, to=50, increment=0.5, textvariable=v_step, width=4).pack(side="left", padx=3)
            ttk.Label(mvr, text="pt:").pack(side="left")
            for txt, a in (("◄", (-1, 0)), ("▲", (0, -1)), ("▼", (0, 1)), ("►", (1, 0))):
                ttk.Button(mvr, text=txt, width=3, command=lambda a=a: nudge(*a)).pack(side="left", padx=1)
            ttk.Label(mvr, text="  Width").pack(side="left")
            ttk.Button(mvr, text="−", width=3, command=lambda: widen(-6)).pack(side="left", padx=1)
            ttk.Button(mvr, text="+", width=3, command=lambda: widen(6)).pack(side="left", padx=1)
            ttk.Label(mvr, text="  Height").pack(side="left")
            ttk.Button(mvr, text="−", width=3, command=lambda: grow(-6)).pack(side="left", padx=1)
            ttk.Button(mvr, text="+", width=3, command=lambda: grow(6)).pack(side="left", padx=1)
            ttk.Button(mvr, text="Back to its place", command=lambda: unmove()).pack(side="left", padx=(8, 0))
            ttk.Label(posf, text="Arrow keys move the selection (Shift = 10×) · Esc = select nothing · Delete = erase "
                                 "a frame", foreground=MUTE).grid(row=2, column=0, columnspan=10, sticky="w")
            # -- formats of the block
            tools = ttk.Frame(right)
            tools.pack(fill="x", pady=(6, 2))
            v_scale = tk.IntVar(value=100)
            v_bold, v_ital, v_head = tk.BooleanVar(), tk.BooleanVar(), tk.BooleanVar()
            v_align = tk.StringVar(value="")
            v_lh = tk.IntVar(value=100)
            ttk.Label(tools, text="Size %").pack(side="left")
            ttk.Spinbox(tools, from_=40, to=250, increment=5, textvariable=v_scale, width=5,
                        command=lambda: changed_fmt()).pack(side="left", padx=(4, 8))
            for txt, var in (("Bold", v_bold), ("Italic", v_ital), ("Heading font", v_head)):
                ttk.Checkbutton(tools, text=txt, variable=var, command=lambda: changed_fmt()).pack(side="left",
                                                                                                padx=(0, 6))
            ttk.Label(tools, text="Align").pack(side="left", padx=(4, 4))
            cb_al = ttk.Combobox(tools, textvariable=v_align, values=["left", "right", "center", "justify"], width=7,
                                 state="readonly")
            cb_al.pack(side="left")
            cb_al.bind("<<ComboboxSelected>>", lambda _e: changed_fmt())
            ttk.Label(tools, text="Line spacing %").pack(side="left", padx=(8, 4))
            ttk.Spinbox(tools, from_=60, to=300, increment=10, textvariable=v_lh, width=5,
                        command=lambda: changed_fmt()).pack(side="left")
            fmtf = ttk.Frame(right)
            fmtf.pack(fill="x", pady=(2, 2))
            ttk.Label(fmtf, text="Selected words:").pack(side="left")
            ttk.Button(fmtf, text="A−", width=4, command=lambda: sel_size(0.9)).pack(side="left", padx=1)
            ttk.Button(fmtf, text="A+", width=4, command=lambda: sel_size(1.1)).pack(side="left", padx=1)
            ttk.Button(fmtf, text="B", width=3, command=lambda: sel_flag("b")).pack(side="left", padx=1)
            ttk.Button(fmtf, text="I", width=3, command=lambda: sel_flag("i")).pack(side="left", padx=1)
            ttk.Button(fmtf, text="Normal", command=lambda: sel_clear()).pack(side="left", padx=(4, 0))
            ttk.Label(fmtf, text="  Enter = new line · several spaces stay", foreground=MUTE).pack(side="left")

            ED_PT = 12
            ed = BidiText(right, font=("Tahoma", ED_PT), rich=True, auto_dir=False, height=150,
                          on_change=lambda: text_changed(),
                          on_key=lambda vk, c, s: ed_key(vk, c, s))
            ed.pack(fill="both", expand=True, pady=(2, 4))
            ed.set_rtl(rtl)
            symf = ttk.Frame(right)
            symf.pack(fill="x")
            ttk.Label(symf, text="Insert symbol:", font=self.f_s).grid(row=0, column=0, columnspan=30, sticky="w")
            for n_, ch in enumerate(REVIEW_SYMBOLS):
                tk.Button(symf, text=ch, width=2, relief="flat", bg="white", font=("Segoe UI Symbol", 10),
                          command=lambda ch=ch: (ed.focus(), ed.insert(ch))).grid(row=1 + n_ // 22, column=n_ % 22)
            arf = ttk.Frame(right)
            arf.pack(fill="x", pady=(6, 0))
            area_lbl = ttk.Label(arf, text="", foreground=MUTE)
            area_lbl.pack(side="left")
            ttk.Button(arf, text="Erase the selected frame", command=lambda: erase_area()).pack(side="right")
            ttk.Button(arf, text="Undo last space", command=lambda: (spaces and spaces.pop(), after_change(0))).pack(
                side="right", padx=6)

            # ---- the page is typeset again by itself shortly after every change
            def state_now() -> dict:
                return json.loads(json.dumps({
                    "edits": {k: v for k, v in edits.items() if v},
                    "areas": [{"rid": a["rid"], "page": a["page"], "rect": [round(v, 2) for v in a["rect"]],
                               "dx": round(a.get("dx", 0.0), 2), "dy": round(a.get("dy", 0.0), 2),
                               "delete": bool(a.get("delete"))} for a in areas
                              if a.get("delete") or a.get("dx") or a.get("dy")],
                    "spaces": [{k_: v_ for k_, v_ in sp.items() if k_ != "block"} for sp in spaces]}))

            def schedule_live(ms: int = 700) -> None:
                if cur["live_job"] is not None:
                    win.after_cancel(cur["live_job"])
                cur["live_job"] = win.after(ms, send_live)

            def send_live() -> None:
                cur["live_job"] = None
                if cur["inflight"] is not None:
                    cur["dirty"] = True
                    return
                s_ = state_now()
                if json.dumps(s_, sort_keys=True) == cur.get("rendered_key", json.dumps(
                        {"edits": {}, "areas": [], "spaces": []}, sort_keys=True)):
                    live_lbl.config(text="")
                    return
                cur["seq"] += 1
                cur["inflight"] = (cur["seq"], s_)
                cur["dirty"] = False
                live_lbl.config(text="⟳ updating the page …")
                self._review_answer(dict(s_, action="preview", seq=cur["seq"]), close=False)

            def update(u: dict) -> None:
                """The job has typeset the page with the changes: show the new page, keep everything else."""
                inf = cur["inflight"]
                if not inf or u.get("seq") != inf[0]:
                    return
                s_ = inf[1]
                cur["inflight"] = None
                cur["rendered_key"] = json.dumps(s_, sort_keys=True)
                cur["rendered"] = {"edits": s_["edits"], "spaces": len(s_["spaces"]),
                                   "areas": {a["rid"]: (a["dx"], a["dy"], a["delete"]) for a in s_["areas"]}}
                for k, bb in enumerate(u.get("bbox") or []):
                    if k < len(paras):
                        paras[k]["bbox"] = bb
                cur["pdf"] = u.get("pdf", cur["pdf"])
                draw(keep_view=True)
                live_lbl.config(text="✓ page up to date")
                if cur["dirty"]:
                    schedule_live(50)
            self._review_update = update

            def after_change(ms: Optional[int] = 700) -> None:
                k = sel_block()
                if k is not None and str(k) in edits and not {kk: vv for kk, vv in edits[str(k)].items() if vv}:
                    edits.pop(str(k), None)
                for k2 in range(len(paras)):
                    lb.itemconfig(k2, foreground=ACC if str(k2) in edits else INK)
                done = [a for a in areas if a.get("delete") or a.get("dx") or a.get("dy")]
                area_lbl.config(text=f"Frames: {len(done)} moved / erased" if done else "")
                n_ch = len(edits) + len(done) + len(spaces)
                note.config(text=f"{n_ch} change(s) – shown at once; “Save and next part” keeps them" if n_ch else
                            "No changes yet")
                overlay()
                if ms is not None:
                    schedule_live(ms)

            # ---- selection: one block or one frame, Esc = nothing
            def clear_sel(_e=None) -> str:
                store()
                cur["sel"] = None
                lb.selection_clear(0, "end")
                ed.set("")
                ed.set_readonly(True)
                for a in [a for a in areas if not (a.get("delete") or a.get("dx") or a.get("dy"))]:
                    areas.remove(a)                           # an unused frame disappears
                after_change(None)
                note.config(text="Nothing selected.")
                return "break"

            def select(k: int, from_list: bool = False) -> None:
                store()
                cur["sel"] = ("block", k)
                cur["k"] = k
                for a in [a for a in areas if not (a.get("delete") or a.get("dx") or a.get("dy"))]:
                    areas.remove(a)
                if not from_list:
                    lb.selection_clear(0, "end")
                    lb.selection_set(k)
                    lb.see(k)
                it, e = paras[k], edits.get(str(k), {})
                ed.set_readonly(False)
                ed.set(e.get("text", it["text"]))
                ed.set_rtl(rtl)
                for (a_, b_, sc_, bo_, it_) in e.get("fmt", []):
                    ed.set_format(a_, b_, bold=True if bo_ == 1 else None, italic=True if it_ == 1 else None,
                                  size=ED_PT * sc_ if abs(sc_ - 1) > 0.001 else None,
                                  color=ACC if abs(sc_ - 1) > 0.001 else None)
                ed.reset_undo()
                ed._last = ed.get()
                cur["loading"] = True
                v_lh.set(int(round(e.get("lh", it.get("lh", 1.0)) * 100)))
                v_scale.set(int(round(e.get("scale", 1.0) * 100)))
                v_bold.set(e.get("bold", it["bold"]))
                v_ital.set(e.get("italic", it["italic"]))
                v_head.set(e.get("heading", it["heading"]))
                v_align.set(e.get("align", it["align"]))
                cur["loading"] = False
                after_change(None)

            def select_area(ar: dict) -> None:
                store()
                cur["sel"] = ("area", ar)
                lb.selection_clear(0, "end")
                ed.set("")
                ed.set_readonly(True)
                after_change(None)

            def show(_e=None) -> None:
                sel_ = lb.curselection()
                if sel_:
                    select(int(sel_[0]), True)

            lb.bind("<<ListboxSelect>>", show)

            # ---- the place: numbers, arrows, buttons
            def unit() -> float:
                return 25.4 / 72 if v_unit.get() == "mm" else 1.0

            def show_pos() -> None:
                k, ar = sel_block(), sel_area()
                b = moved_box(k) if k is not None else (area_box(ar) if ar is not None else None)
                f_ = unit()
                for var, en, v in ((v_x, ents["X"], b and b[0]), (v_y, ents["Y"], b and b[1]),
                                   (v_w, ents["Width"], b and b[2] - b[0]), (v_h, ents["Height"], b and b[3] - b[1])):
                    if win.focus_get() is en:
                        continue                              # the user is typing there
                    var.set("" if b is None else f"{v * f_:.1f}")
                ents["Width"].config(state="normal" if k is not None else "disabled")
                ents["Height"].config(state="disabled")

            def apply_pos() -> None:
                k, ar = sel_block(), sel_area()
                try:
                    f_ = unit()
                    x, y = float(v_x.get().replace(",", ".")) / f_, float(v_y.get().replace(",", ".")) / f_
                    w_ = float(v_w.get().replace(",", ".")) / f_ if v_w.get().strip() else None
                except ValueError:
                    note.config(text="Type numbers for X, Y and Width.")
                    return
                if k is not None:
                    bb = paras[k]["bbox"]
                    e = edits.setdefault(str(k), {})
                    e["dx"], e["dy"] = round(x - bb[0], 2), round(y - bb[1], 2)
                    if w_ is not None and abs(w_ - (moved_box(k)[2] - moved_box(k)[0])) > 0.3:
                        e["dw"] = round(w_ - (bb[2] - bb[0]), 2)
                elif ar is not None:
                    ar["dx"], ar["dy"] = round(x - ar["rect"][0], 2), round(y - ar["rect"][1], 2)
                else:
                    note.config(text="Select a text block or frame an area first.")
                    return
                cv.focus_set()
                after_change(100)

            def step() -> float:
                try:
                    return max(0.1, float(v_step.get().replace(",", ".")))
                except ValueError:
                    return 1.0

            def nudge(dx: float, dy: float, big: bool = False) -> None:
                f_ = step() * (10 if big else 1)
                k, ar = sel_block(), sel_area()
                if k is not None:
                    e = edits.setdefault(str(k), {})
                    e["dx"], e["dy"] = round(e.get("dx", 0.0) + dx * f_, 2), round(e.get("dy", 0.0) + dy * f_, 2)
                elif ar is not None:
                    ar["dx"], ar["dy"] = round(ar.get("dx", 0.0) + dx * f_, 2), round(ar.get("dy", 0.0) + dy * f_, 2)
                else:
                    note.config(text="Select a text block or frame an area first.")
                    return
                after_change(900)

            def widen(dw: float) -> None:
                k = sel_block()
                if k is None:
                    note.config(text="Select a text block first.")
                    return
                e = edits.setdefault(str(k), {})
                e["dw"] = e.get("dw", 0.0) + dw
                after_change(900)

            def unmove() -> None:
                k, ar = sel_block(), sel_area()
                if k is not None and str(k) in edits:
                    for key in ("dx", "dy", "dw"):
                        edits[str(k)].pop(key, None)
                elif ar is not None:
                    ar["dx"] = ar["dy"] = 0.0
                after_change(100)

            def grow(dh: float) -> None:
                """More (or less) height for the selected block; everything below it moves along."""
                k = sel_block()
                if k is None:
                    note.config(text="Select a text block first.")
                    return
                it = paras[k]
                e = edits.setdefault(str(k), {})
                e["dh"] = e.get("dh", 0.0) + dh
                x0, y0, x1, y1 = moved_box(k)
                wide = (x1 - x0) > 0.55 * page_w(it.get("pi", 0))
                last = spaces[-1] if spaces else None
                if last and last.get("block") == k:
                    last["dy"] += dh                          # the same block again: one push
                    if not last["dy"]:
                        spaces.pop()
                else:
                    spaces.append({"page": it.get("pi", 0), "y": round(y1 - e["dh"], 2), "dy": dh,
                                   "x0": -1e4 if wide else x0 - 8, "x1": 1e4 if wide else x1 + 8, "block": k})
                after_change(900)

            def erase_area() -> None:
                ar = sel_area()
                if ar is None:
                    note.config(text="Frame an area first (drag on an empty place, or the Frame tool).")
                    return
                ar["delete"], ar["dx"], ar["dy"] = True, 0.0, 0.0
                cur["sel"] = None
                after_change(50)

            # ---- formats and text of the selected block
            def changed_fmt() -> None:
                if cur.get("loading"):
                    return
                store()
                after_change(500)

            def text_changed() -> None:
                if cur.get("loading") or sel_block() is None:
                    return
                if cur["store_job"] is not None:
                    win.after_cancel(cur["store_job"])
                cur["store_job"] = win.after(1200, lambda: (cur.update(store_job=None), store(), after_change(300)))

            def ed_key(vk: int, ctrl: bool, shift: bool) -> bool:
                if vk == 0x1B:                                 # Esc in the editor: select nothing
                    win.after(1, clear_sel)
                    win.after(5, cv.focus_set)
                    return True
                return False

            def sel_range():
                a, b = ed.selection()
                if b <= a:
                    note.config(text="Select some words in the editor first.")
                    return None
                return a, b

            def sel_size(f: float) -> None:
                r_ = sel_range()
                if not r_:
                    return
                old = ed.char_format(r_[0])[0] / ED_PT
                ed.select(*r_)
                new = old * f
                ed.set_format(*r_, size=ED_PT * new, color=ACC if abs(new - 1) > 0.01 else INK)
                store()
                after_change(500)

            def sel_flag(tg: str) -> None:
                r_ = sel_range()
                if not r_:
                    return
                _sz, bo, itl = ed.char_format(r_[0])
                ed.select(*r_)
                if tg == "b":
                    ed.set_format(*r_, bold=not bo)
                else:
                    ed.set_format(*r_, italic=not itl)
                store()
                after_change(500)

            def sel_clear() -> None:
                r_ = sel_range()
                if r_:
                    ed.set_format(*r_, bold=False, italic=False, size=ED_PT, color=INK)
                    ed.select(*r_)
                    store()
                    after_change(500)

            def formats() -> List[list]:
                """[[start, end, size factor, bold, italic], …] of the formatted words of the editor."""
                per = ed.formats()
                keyed = [(round(sz / ED_PT, 3), 1 if bo else -1, 1 if itl else -1) for sz, bo, itl in per]
                out: List[list] = []
                c = 0
                n = len(keyed)
                while c < n:
                    key_ = keyed[c]
                    j = c
                    while j < n and keyed[j] == key_:
                        j += 1
                    if key_ != (1.0, -1, -1):
                        out.append([c, j, key_[0], key_[1], key_[2]])
                    c = j
                return out

            def store() -> None:
                """Remember the editor content of the selected block (only what was changed)."""
                k = sel_block()
                if k is None:
                    return
                it = paras[k]
                e: dict = {kk: vv for kk, vv in edits.get(str(k), {}).items() if kk in ("dx", "dy", "dw", "dh") and vv}
                text = ed.get()                                  # Enter = a new line in the block
                try:
                    lh_ = max(0.5, min(3.0, int(v_lh.get()) / 100))
                except Exception:
                    lh_ = 1.0
                if abs(lh_ - float(it.get("lh", 1.0))) > 0.005:
                    e["lh"] = lh_
                fmt_ = formats()
                if fmt_:
                    e["fmt"] = fmt_
                if text.strip() != it["text"].strip():
                    e["text"] = text
                try:
                    sc_ = max(0.4, min(2.5, int(v_scale.get()) / 100))
                except Exception:
                    sc_ = 1.0
                if abs(sc_ - 1.0) > 0.005:
                    e["scale"] = sc_
                if v_bold.get() != it["bold"]:
                    e["bold"] = bool(v_bold.get())
                if v_ital.get() != it["italic"]:
                    e["italic"] = bool(v_ital.get())
                if v_head.get() != it["heading"]:
                    e["heading"] = bool(v_head.get())
                if v_align.get() and v_align.get() != it["align"]:
                    e["align"] = v_align.get()
                if e:
                    edits[str(k)] = e
                else:
                    edits.pop(str(k), None)

            # ---- mouse on the page
            def hit(pi: int, x: float, y: float) -> Optional[int]:
                best, area_ = None, 1e18
                for k, it in enumerate(paras):
                    if it.get("pi") != pi or not it.get("bbox"):
                        continue
                    bx = moved_box(k)
                    if bx[0] - 2 <= x <= bx[2] + 2 and bx[1] - 2 <= y <= bx[3] + 2:
                        a = (bx[2] - bx[0]) * (bx[3] - bx[1])
                        if a < area_:
                            best, area_ = k, a
                return best

            def hit_area(pi: int, x: float, y: float) -> Optional[dict]:
                for ar in reversed(areas):
                    if ar["page"] == pi and not ar.get("delete"):
                        b = area_box(ar)
                        if b[0] <= x <= b[2] and b[1] <= y <= b[3]:
                            return ar
                return None

            def press(ev) -> None:
                cv.focus_set()
                cx, cy = cv.canvasx(ev.x), cv.canvasy(ev.y)
                at = to_page(cx, cy)
                cur["drag"] = None
                if at is None:
                    clear_sel()
                    return
                pi, x, y = at
                if mode.get() == "space":
                    try:
                        dy_ = float(v_space.get())
                    except Exception:
                        dy_ = 12.0
                    if not dy_:
                        return
                    pw = page_w(pi)
                    x0_, x1_ = ((-1e4, pw / 2) if x < pw / 2 else (pw / 2, 1e4)) if v_col.get() else (-1e4, 1e4)
                    spaces.append({"page": pi, "y": round(y, 2), "dy": dy_, "x0": x0_, "x1": x1_})
                    after_change(100)
                    return
                ar = hit_area(pi, x, y)
                if ar is not None:                            # drag a framed area
                    select_area(ar)
                    cur["drag"] = ("area", ar, ev.x, ev.y, x, y, ar.get("dx", 0.0), ar.get("dy", 0.0), False)
                    return
                k = hit(pi, x, y) if mode.get() == "block" else None
                if k is not None:
                    if sel_block() != k:
                        select(k)
                    e = edits.get(str(k), {})
                    cur["drag"] = ("block", k, ev.x, ev.y, x, y, e.get("dx", 0.0), e.get("dy", 0.0), False)
                    return
                # an empty place (or the Frame tool): draw a frame that can then be moved
                store()
                cur["sel"] = None
                lb.selection_clear(0, "end")
                ed.set("")
                ed.set_readonly(True)
                for a in [a for a in areas if not (a.get("delete") or a.get("dx") or a.get("dy"))]:
                    areas.remove(a)
                cur["rid"] += 1
                new = {"rid": cur["rid"], "page": pi, "rect": [x, y, x, y], "dx": 0.0, "dy": 0.0}
                areas.append(new)
                cur["drag"] = ("frame", new, ev.x, ev.y, x, y)
                overlay()

            def motion(ev) -> None:
                dr = cur["drag"]
                if not dr:
                    return
                at = to_page(cv.canvasx(ev.x), cv.canvasy(ev.y))
                if at is None:
                    return
                pi, x, y = at
                if dr[0] in ("block", "area"):
                    kind, obj, sx, sy, x0, y0, dx0, dy0, started = dr
                    if not started and abs(ev.x - sx) + abs(ev.y - sy) < 5:
                        return                                # a click is not a move
                    cur["drag"] = (kind, obj, sx, sy, x0, y0, dx0, dy0, True)
                    if kind == "block":
                        if paras[obj].get("pi") != pi:
                            return
                        e = edits.setdefault(str(obj), {})
                        e["dx"], e["dy"] = round(dx0 + x - x0, 1), round(dy0 + y - y0, 1)
                    else:
                        if obj["page"] != pi:
                            return
                        obj["dx"], obj["dy"] = round(dx0 + x - x0, 1), round(dy0 + y - y0, 1)
                    cv.config(cursor="fleur")
                elif dr[0] == "frame" and dr[1]["page"] == pi:
                    _t, ar, _sx, _sy, fx, fy = dr
                    ar["rect"] = [min(fx, x), min(fy, y), max(fx, x), max(fy, y)]
                overlay()

            def release(_ev) -> None:
                dr, cur["drag"] = cur["drag"], None
                cv.config(cursor=cursor_for())
                if not dr:
                    return
                if dr[0] == "frame":
                    r = dr[1]["rect"]
                    if r[2] - r[0] < 4 or r[3] - r[1] < 4:
                        areas.remove(dr[1])                   # a click, not a frame: select nothing
                        clear_sel()
                        return
                    select_area(dr[1])
                    note.config(text="Frame ready – drag it, use the arrow keys or type its place; Delete erases it.")
                    return
                if dr[-1]:                                    # it was really moved
                    after_change(60)

            def hover(ev) -> None:
                if cur["drag"] or mode.get() != "block":
                    return
                at = to_page(cv.canvasx(ev.x), cv.canvasy(ev.y))
                k = hit(*at) if at else None
                ar = hit_area(*at) if at else None
                cv.config(cursor="fleur" if (k is not None or ar is not None) else cursor_for())
                if k != cur["hover"]:
                    cur["hover"] = k
                    overlay()

            def cursor_for() -> str:
                return {"area": "tcross", "space": "sb_v_double_arrow"}.get(mode.get(), "crosshair")

            def set_mode() -> None:
                """Another tool: what was selected with the old one is let go, the page is clean again."""
                clear_sel()
                cur["hover"] = None
                cv.config(cursor=cursor_for())
                overlay()

            cv.bind("<ButtonPress-1>", press)
            cv.bind("<B1-Motion>", motion)
            cv.bind("<ButtonRelease-1>", release)
            cv.bind("<Motion>", hover)
            cv.bind("<Leave>", lambda _e: (cur.update(hover=None), overlay()))
            for keysym, (dx_, dy_) in (("Left", (-1, 0)), ("Right", (1, 0)), ("Up", (0, -1)), ("Down", (0, 1))):
                cv.bind(f"<{keysym}>", lambda _e, a=(dx_, dy_): (nudge(*a), "break")[1])
                cv.bind(f"<Shift-{keysym}>", lambda _e, a=(dx_, dy_): (nudge(*a, big=True), "break")[1])
            cv.bind("<Delete>", lambda _e: erase_area())
            cv.bind("<Escape>", clear_sel)
            win.bind("<Escape>", clear_sel)

            # ---- the end of the review of this part
            def has_changes() -> bool:
                store()
                s_ = state_now()
                return bool(s_["edits"] or s_["areas"] or s_["spaces"])

            def undo_all() -> None:
                if not has_changes():
                    note.config(text="Nothing to undo.")
                    return
                if not messagebox.askyesno("Undo all", "Undo every change of this part?", parent=win):
                    return
                edits.clear()
                areas.clear()
                spaces.clear()
                cur["sel"] = None
                ed.set("")
                after_change(30)

            def nxt() -> None:
                store()
                if cur["live_job"] is not None:
                    win.after_cancel(cur["live_job"])
                self._review_answer(dict(state_now(), action="next"))

            def cancel() -> None:
                if has_changes() and not messagebox.askyesno(
                        "Cancel", "Throw away the changes of this part and keep it as it was translated?",
                        parent=win, default="no"):
                    return
                if cur["live_job"] is not None:
                    win.after_cancel(cur["live_job"])
                self._review_answer({"action": "cancel"})

            b_cancel = ttk.Button(bottom, text="Cancel", command=cancel)
            b_cancel.pack(side="right")
            b_next = ttk.Button(bottom, text="✔  Save and next part  ▶", style="Accent.TButton", command=nxt)
            b_next.pack(side="right", padx=8)
            ttk.Button(bottom, text="↺ Undo all", command=undo_all).pack(side="right")
            win.protocol("WM_DELETE_WINDOW", cancel)
            win.after(150, lambda: zoom(0))
            self._review_api = {"edits": edits, "areas": areas, "cur": cur, "select": select, "nudge": nudge,
                                "spaces": spaces, "grow": grow, "sel_size": sel_size, "sel_flag": sel_flag,
                                "zoom": zoom, "v_lh": v_lh, "v_space": v_space, "store": store, "formats": formats,
                                "press": press, "motion": motion, "release": release, "mode": mode,
                                "save": nxt, "next": nxt, "ed": ed, "cv": cv, "erase": erase_area,
                                "clear": clear_sel, "apply_pos": apply_pos, "v_x": v_x, "v_y": v_y,
                                "set_mode": set_mode, "state": state_now, "undo_all": undo_all, "to_cv": to_cv,
                                "live_lbl": live_lbl}
            after_change(None)
            ed.set_readonly(True)
            note.config(text="Click a text block to edit or move it · drag on an empty place to frame anything.")


        # ------------------------------------------------------------ queue
        def _log(self, msg: str, tag: str = "") -> None:
            if msg.startswith(("ERROR", "Warning")):
                self.err_count += 1
                self.err_lbl.config(text=f"Errors / warnings: {self.err_count}")
            if not tag:
                if msg.startswith(("ERROR", "Warning")):
                    tag = "err"
                elif msg.startswith(("Saved", "Engine check OK", "Font ready")):
                    tag = "ok"
                elif msg.startswith("━━"):
                    tag = "hd"
            stamp = time.strftime("%H:%M:%S")             # every line starts with the time it happened
            msg = "\n".join(f"{stamp}  {ln}" if ln.strip() else ln for ln in msg.split("\n"))
            self.log_box.config(state="normal")
            self.log_box.insert("end", msg + "\n", tag)
            if int(float(self.log_box.index("end-1c").split(".")[0])) > 3000:       # keep the window light
                self.log_box.delete("1.0", "500.0")
            self.log_box.see("end")
            self.log_box.config(state="disabled")

        def _show_preview(self, which: str, token: int, png: Optional[bytes], msg: str, rtl: bool = False) -> None:
            if token != self.pv_token[which]:
                return                                   # the user has already chosen another font
            cvs = self.pv_lbl[which]
            cvs.delete("all")
            cw = int(cvs.winfo_width()) if int(cvs.winfo_width()) > 20 else 420
            if png:
                img = tk.PhotoImage(data=base64.b64encode(png).decode("ascii"))
                self.pv_img[which] = img                 # keep a reference, otherwise Tk drops the picture
                iw, ih = img.width(), img.height()
                x = max(0, cw - iw) if rtl else 0        # Persian sits at the right edge, English at the left
                cvs.create_image(x, 1, anchor="nw", image=img)
                cvs.configure(scrollregion=(0, 0, max(iw, cw), ih))
                cvs.xview_moveto(1.0 if rtl else 0.0)
            else:
                cvs.create_text(6, 15, anchor="w", text=msg, fill=MUTE, font=self.f_s)
                cvs.configure(scrollregion=(0, 0, cw, 30))

        def _act(self, text: str, tag: str) -> None:
            if tag == "s":                                  # status line of the fixed bar (phase, pages ready)
                self.phase_lbl.config(text=text)
                return
            if tag == "eta":                                # remaining seconds; the label counts down by itself
                try:
                    self.eta_left, self.eta_at = float(text), time.time()
                except (TypeError, ValueError):
                    self.eta_left = None
                    if self.review_win is None:
                        self.eta_lbl.config(text="")
                return
            if tag == "review":
                self._review(text)
                return
            if tag == "review_upd":
                f_ = getattr(self, "_review_update", None)
                if f_ and self.review_win is not None:
                    f_(text)
                return
            if tag == "load":
                self._load_msg(text)
                return
            if tag == "part":
                self._play("part")
                return
            self._log(text, "act_" + tag)

        def _tick(self) -> None:
            """Moving dots + elapsed time: shows that the program is alive."""
            import math
            self.spin_i += 1
            c = self.spin
            c.delete("all")
            for k in range(7):
                if self.running:
                    r = 3.0 + 3.2 * (0.5 + 0.5 * math.sin(self.spin_i * 0.35 - k * 0.8))
                    col = "#7DD3FC" if k % 2 else "#86EFAC"
                else:
                    r, col = 2.5, "#475569"
                c.create_oval(8 + k * 13 - r, 11 - r, 8 + k * 13 + r, 11 + r, fill=col, outline="")
            if self.running and self.t0 is not None:
                sec = int(time.time() - self.t0)
                self.elapsed_lbl.config(text=f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}  Elapsed time")
                if self.eta_left is not None and self.review_win is None:
                    left = max(0.0, self.eta_left - (time.time() - self.eta_at))
                    self.eta_lbl.config(text=f"Remaining time: {fmt_dur(left) if left >= 60 else '< 1 min'}")
                    self.eta_note.config(text="The remaining time is calculated from previous translations "
                                              "and is not exact.")
            if self.running and self.spin_i % 4 == 0 and getattr(self, "load_head", -1) >= 0:
                self._draw_load()
            self.after(80, self._tick)

        def _reset_view(self) -> None:
            """A new file was chosen: clean, tidy, ready."""
            if self.running:
                return
            self.log_box.config(state="normal")
            self.log_box.delete("1.0", "end")
            self.log_box.config(state="disabled")
            self.err_count = 0
            self.err_lbl.config(text="Errors / warnings: 0")
            self.elapsed_lbl.config(text="00:00:00  Elapsed time")
            self.phase_lbl.config(text="Ready – a new file is loaded")
            self._load_reset()
            self.pb["value"] = 0
            self.status.config(text="Ready")
            self.pages_var.set("")
            self._log(f"{APP_TITLE} {APP_VERSION} (build {APP_BUILD}) ready. Tip: test with pages 1-10 first.")

        def _handle(self, item: tuple) -> None:
            kind = item[0]
            if kind == "log":
                self._log(item[1])
            elif kind == "act":
                self._act(item[1], item[2])
            elif kind == "preview":
                self._show_preview(item[1], item[2], item[3], item[4], item[5] if len(item) > 5 else False)
            elif kind == "progress":
                self.pb["value"] = item[1] * 1000
                self.status.config(text=item[2])
            elif kind == "terms":
                self._terms_dialog(item[1], item[2], item[3], item[4])
            elif kind == "qt":
                f_ = getattr(self, "_quick_result", None)
                if f_ and getattr(self, "quick_win", None) is not None:
                    f_(item[1], item[2], item[3], item[4])
            elif kind == "qt_speak":
                f_ = getattr(self, "_quick_spoken", None)
                if f_ and getattr(self, "quick_win", None) is not None:
                    f_(item[1], item[2])
            elif kind in ("qt_dict", "qt_dict_part", "qt_dict_st"):
                f_ = getattr(self, "_quick_dict", None)
                if f_ and getattr(self, "quick_win", None) is not None:
                    f_(*item)
            elif kind in ("live_text", "live_part", "live_st", "live_tr"):
                f_ = getattr(self, "_quick_live", None)
                if f_ and getattr(self, "quick_win", None) is not None:
                    f_(*item)
            elif kind == "comp":
                f_ = getattr(self, "_settings_event", None)
                if f_:
                    f_(*item[1:])
            elif kind == "stats":
                self._stats_done(item[1], item[2], item[3])
            elif kind in ("done", "cancelled", "error"):
                self._job_finished(kind, item[1] if len(item) > 1 else None)

        def _poll(self) -> None:
            try:
                while True:
                    self._handle(self.q.get_nowait())
            except queue.Empty:
                pass
            jq = self.job_q
            if jq is not None:
                try:
                    for _ in range(300):                 # a burst per tick keeps the window responsive
                        self._handle(jq.get_nowait())
                    self.dead_ticks = 0
                except queue.Empty:
                    if self.proc is not None and not self.proc.is_alive():
                        self.dead_ticks += 1             # second tick: every message has certainly been read
                        if self.dead_ticks >= 2:
                            self._job_finished("error", "The translation process stopped unexpectedly "
                                                        f"(exit code {self.proc.exitcode}). See the log above.")
                    else:
                        self.dead_ticks = 0
            self.after(100, self._poll)

    app = App()
    if _test is not None:
        _test(app)
    else:
        app.mainloop()


# ════════════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════════════
MODEL_ALIASES = {"madlad": "google/madlad400-3b-mt", "nllb": "facebook/nllb-200-distilled-1.3B",
                 "nllb-1.3b": "facebook/nllb-200-distilled-1.3B", "nllb-600m": "facebook/nllb-200-distilled-600M"}


def run_cli(argv: List[str]) -> None:
    ap = argparse.ArgumentParser(prog="book_translator.py --cli", description=APP_TITLE)
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", default="translated")
    ap.add_argument("-l", "--langs", default="fa", help="comma list, e.g. fa  (all = every language)")
    ap.add_argument("-f", "--font", default=DEFAULT_FA_FONT,
                    help="body text font: a name from the font list or the path to a .ttf/.otf")
    ap.add_argument("--heading-font", default="", help="heading / title / subtitle font (default: same as --font)")
    ap.add_argument("--font-scale", type=float, default=100.0, help="font-size factor in %% (100 = as the original)")
    ap.add_argument("--formats", default="pdf", help="comma list of pdf, docx, txt")
    ap.add_argument("-m", "--model", default="madlad",
                    help="madlad | nllb | nllb-600m | a Hugging Face id | a model folder on disk")
    ap.add_argument("-p", "--pages", default="")
    ap.add_argument("--min-scale", type=float, default=0.5)
    ap.add_argument("--specialty", default="", help='up to 4 fields, comma separated, e.g. "Chemistry, AI"')
    ap.add_argument("--no-auto-specialty", action="store_true", help="do not detect the subject of the book")
    ap.add_argument("--no-names", action="store_true", help="translate proper names / Capitalized terms too")
    ap.add_argument("--no-terms", action="store_true", help="translate technical terms too")
    ap.add_argument("--no-auto-terms", action="store_true", help="do not auto-detect acronyms / units / formulas")
    ap.add_argument("--no-bilingual-headings", action="store_true",
                    help="do not add the English heading in brackets after the Persian sub-heading")
    ap.add_argument("--speed", choices=["accurate", "fast"], default="accurate",
                    help="accurate (default, full layout) | fast (text only, .txt output, no typesetting)")
    ap.add_argument("--no-rtl", action="store_true", help="do not set Right-To-Left direction")
    ap.add_argument("--no-align-right", action="store_true", help="do not mirror Align Left to Align Right")
    ap.add_argument("--offline", action="store_true", help="never download anything")
    ap.add_argument("--part-pages", type=int, default=2, help="pages per part (finished parts are cached; default 2)")
    ap.add_argument("--no-swap-columns", action="store_true",
                    help="Persian: do not mirror the two columns of two-column pages")
    ap.add_argument("--no-justify", action="store_true", help="do not justify the body text")
    ap.add_argument("--best-quality", action="store_true",
                    help="beam search with 2 candidates per sentence (a little better, about 2x slower)")
    a = ap.parse_args(argv)
    langs = list(LANGS) if a.langs == "all" else [x.strip() for x in a.langs.split(",") if x.strip()]

    def pick(value: str) -> Tuple[str, Optional[str]]:
        if Path(value).is_file():
            return CUSTOM_FONT_LABEL, value
        if value not in PERSIAN_FONTS:
            sys.exit(f"Unknown font '{value}'. Choose one of: {', '.join(PERSIAN_FONTS)} or give a font file path.")
        return value, None

    body, body_file = pick(a.font)
    head, head_file = pick(a.heading_font) if a.heading_font else (body, body_file)
    fmts = {x.strip().lower() for x in a.formats.split(",") if x.strip()}
    bad = fmts - {"pdf", "docx", "doc", "txt", "text"}
    if bad or not fmts:
        sys.exit("--formats takes a comma list of: pdf, docx, txt")
    opts = Options(pages=a.pages, min_scale=a.min_scale, model=MODEL_ALIASES.get(a.model, a.model),
                   keep_terms=not a.no_terms, auto_terms=not a.no_auto_terms, allow_download=not a.offline, speed=a.speed,
                   bilingual_headings=not a.no_bilingual_headings,
                   keep_names=not a.no_names, specialties=parse_specialties(a.specialty)[0],
                   auto_specialty=not a.no_auto_specialty,
                   rtl_direction=not a.no_rtl, align_right=not a.no_align_right,
                   part_pages=max(1, a.part_pages), swap_columns=not a.no_swap_columns,
                   justify_body=not a.no_justify, best_quality=a.best_quality,
                   heading_font=head, body_font=body, heading_font_file=head_file, body_font_file=body_file,
                   font_scale=max(0.3, min(3.0, a.font_scale / 100)),
                   out_pdf="pdf" in fmts, out_docx=bool(fmts & {"docx", "doc"}), out_txt=bool(fmts & {"txt", "text"}))
    run_job(a.pdf, a.out, langs, opts, print,
            lambda f, m: print(f"\r[{f * 100:5.1f}%] {m:<70}", end="", flush=True), threading.Event())
    print()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()                      # needed on Windows for the translation worker process
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        run_cli(sys.argv[2:])
    else:
        try:
            run_gui()
        except ImportError as exc:
            sys.exit(f"The GUI needs tkinter ({exc}). Install it, or use --cli.")
