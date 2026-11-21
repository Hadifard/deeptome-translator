"""
File    : installer/build_setup.py
Author  : Hadi Sarhangi Fard
Date    : 2026-11-19   (DeepTome Translator 3.4)
Purpose : Builds everything that is given away.
Copyright (c) 2026 Hadi Sarhangi Fard. All rights reserved.

Builds the folder  deeptome/  next to book_translator.py:

    deeptome/
        Send_to_others/     what you give to other people: DeepTome_Setup.exe (one file, runs on a Windows 10/11 PC
                            that has nothing installed), the same as a zip, README (English + Persian), LICENSE,
                            THIRD_PARTY_NOTICES, CHANGELOG
        For_me/             a copy of the source of this build: the program, the logo files, the installer scripts
                            and a note on how to change and rebuild it

    python installer/build_setup.py

It needs only what Windows already has (IExpress) plus Pillow for the icon.  The Setup program carries the app
(book_translator.py, requirements.txt, assets, documents); Python, the packages and the engines are downloaded
while it runs.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "deeptome"
DOCS = ("README.txt", "README_fa.txt", "LICENSE.txt", "THIRD_PARTY_NOTICES.txt", "CHANGELOG.txt")
BOM = bytes([0xEF, 0xBB, 0xBF])
CRLF = chr(13) + chr(10)
LF = chr(10)


def _content_box(im, bg, pad: int):
    """Box around everything in the picture that is not background, with a margin."""
    from PIL import Image, ImageChops
    diff = ImageChops.difference(im.convert("RGB"), Image.new("RGB", im.size, bg)).convert("L").point(
        lambda v: 255 if v > 24 else 0)
    x0, y0, x1, y1 = diff.getbbox()
    return max(0, x0 - pad), max(0, y0 - pad), min(im.width, x1 + pad), min(im.height, y1 + pad)


def make_icon(dst: Path) -> None:
    """The desktop / window icon is the picture  assets/icon_source_1220.png  (1220 x 1220, chosen by the author),
    scaled down with care to every size Windows asks for - always the whole picture."""
    from PIL import Image, ImageChops
    src = Image.open(ROOT / "assets" / "icon_source_1220.png").convert("RGBA")
    bg = src.convert("RGB").getpixel((3, 3))
    # tree and book: the upper part of the picture, above the word DEEPTOME
    top = src.crop((0, 0, src.width, int(src.height * 0.44)))
    diff = ImageChops.difference(top.convert("RGB"), Image.new("RGB", top.size, bg)).convert("L").point(
        lambda v: 255 if v > 30 else 0)
    x0, y0, x1, y1 = diff.getbbox()
    side = int(max(x1 - x0, y1 - y0) * 1.12)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    mark = Image.new("RGBA", (side, side), bg + (255,))
    mark.paste(top.crop((cx - side // 2, cy - side // 2, cx + side // 2, cy + side // 2)), (0, 0))
    frames = []
    for size in (256, 128, 96, 72, 64, 48, 40, 32, 24, 20, 16):
        art = src                                                  # the whole picture at every size
        frames.append(art.resize((size, size), Image.LANCZOS))
    dst.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(dst, format="ICO", append_images=frames[1:], sizes=[f.size for f in frames], bitmap_format="bmp")
    src.resize((256, 256), Image.LANCZOS).save(dst.with_name("deeptome_icon_256.png"))


def make_logos() -> None:
    """Logo of the Setup window (sharp, twice the size it is shown in) and of the program header, both cut from
    the 2000-pixel logo.  Their background is exactly the header colour #063360."""
    from PIL import Image
    src = Image.open(ROOT / "assets" / "logo_square_2000.png").convert("RGB")
    wide = src.crop((215, 738, 1775, 1241))                       # mark + DEEPTOME + AI Translator, ratio 3.1 : 1
    wide.resize((596, 192), Image.LANCZOS).save(ROOT / "assets" / "logo_setup.png")
    wide.resize((310, 100), Image.LANCZOS).save(ROOT / "assets" / "logo.png")


def app_version() -> str:
    m = re.search(r'^APP_VERSION = "(.+?)"', (ROOT / "book_translator.py").read_text("utf-8"), re.M)
    return m.group(1) if m else "?"


def win_text(text: str) -> bytes:
    """Text for Windows: UTF-8 with a byte-order mark (Notepad then shows Persian correctly) and CRLF line ends."""
    return BOM + text.replace(CRLF, LF).replace(LF, CRLF).encode("utf-8")


def write_doc(name: str, dst: Path, version: str) -> None:
    dst.write_bytes(win_text((HERE / "docs" / name).read_text("utf-8").replace("{VERSION}", version)))


def make_github(version: str) -> None:
    """deeptome/GitHub: the repository as it is published (source, installer scripts, README with pictures)."""
    gh = OUT / "GitHub"
    gh.mkdir(parents=True, exist_ok=True)
    for item in gh.iterdir():                  # empty the folder but keep the git repository (.git) of the user
        if item.name == ".git":
            continue
        shutil.rmtree(item) if item.is_dir() else item.unlink()
    src = ROOT / "github"
    shutil.copytree(src, gh, ignore=shutil.ignore_patterns("__pycache__"), dirs_exist_ok=True)
    shutil.copy(ROOT / "book_translator.py", gh)
    shutil.copy(ROOT / "requirements.txt", gh)
    (gh / "assets").mkdir()
    for f in ("logo.png", "logo_setup.png", "deeptome.ico", "deeptome_icon_256.png", "logo_square_2000.png",
              "logo_wide_6776.png", "icon_source_1220.png", "logo_stacked_dark.png", "logo_stacked_light.png"):
        if (ROOT / "assets" / f).is_file():
            shutil.copy(ROOT / "assets" / f, gh / "assets")
    (gh / "installer" / "docs").mkdir(parents=True)
    for f in ("install.ps1", "uninstall.ps1", "build_setup.py"):
        shutil.copy(HERE / f, gh / "installer")
    for f in DOCS:
        shutil.copy(HERE / "docs" / f, gh / "installer" / "docs")
    shutil.copy(HERE / "docs" / "LICENSE.txt", gh / "LICENSE")
    log = (HERE / "docs" / "CHANGELOG.txt").read_text("utf-8").splitlines()
    md = ["# Changelog", ""]
    for line in log[3:]:
        if line.startswith("Version "):
            md += ["", "## " + line.strip()]
        elif line.strip().startswith("*"):
            md.append("- " + line.strip()[1:].strip())
        elif line.strip() and md and md[-1].startswith("- "):
            md[-1] += " " + line.strip()
    (gh / "CHANGELOG.md").write_text(LF.join(md).strip() + LF, "utf-8")


def main() -> None:
    version = app_version()
    work = Path(tempfile.mkdtemp(prefix="dt_build_"))
    stage = work / "stage"
    app = stage / "app"
    (app / "assets").mkdir(parents=True)
    make_icon(ROOT / "assets" / "deeptome.ico")                    # the app window uses it too
    make_logos()
    shutil.copy(ROOT / "book_translator.py", app)
    shutil.copy(ROOT / "requirements.txt", app)
    for f in ("logo.png", "logo_setup.png", "deeptome.ico"):
        shutil.copy(ROOT / "assets" / f, app / "assets")
    if (ROOT / "fonts").is_dir():
        shutil.copytree(ROOT / "fonts", app / "fonts")
    shutil.copy(HERE / "install.ps1", stage)
    shutil.copy(HERE / "uninstall.ps1", stage)
    for name in DOCS:
        write_doc(name, stage / name, version)
    (stage / "Setup.cmd").write_bytes(CRLF.join([
        "@echo off",
        "rem DeepTome Translator - double-click this file to install",
        'start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0install.ps1"',
        ""]).encode("ascii"))
    others, mine = OUT / "Send_to_others", OUT / "For_me"
    for d in (others, mine):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)

    # ---- the zip (also the payload of the .exe)
    payload = work / "payload.zip"
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(stage.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(stage).as_posix())
    shutil.copy(payload, others / "DeepTome_Setup_files.zip")
    for name in DOCS:
        write_doc(name, others / name, version)

    # ---- the .exe: IExpress unpacks boot.ps1 + payload.zip into a temporary folder and starts boot.ps1
    pack = work / "pack"
    pack.mkdir()
    shutil.copy(payload, pack / "payload.zip")
    (pack / "boot.ps1").write_bytes(CRLF.join([
        "$here = Split-Path -Parent $MyInvocation.MyCommand.Path",
        "$dst = Join-Path $env:TEMP ('DeepTomeSetup_' + [guid]::NewGuid().ToString('N').Substring(0, 8))",
        "Expand-Archive -LiteralPath (Join-Path $here 'payload.zip') -DestinationPath $dst -Force",
        "& (Join-Path $dst 'install.ps1')",
        "Remove-Item -LiteralPath $dst -Recurse -Force -ErrorAction SilentlyContinue",
        ""]).encode("ascii"))
    target = work / "DeepTome_Setup.exe"
    sed = work / "setup.sed"
    sed.write_text(LF.join([
        "[Version]", "Class=IEXPRESS", "SEDVersion=3",
        "[Options]", "PackagePurpose=InstallApp", "ShowInstallProgramWindow=1", "HideExtractAnimation=1",
        "UseLongFileName=1", "InsideCompressed=0", "CAB_FixedSize=0", "CAB_ResvCodeSigning=0", "RebootMode=N",
        "InstallPrompt=%InstallPrompt%", "DisplayLicense=%DisplayLicense%", "FinishMessage=%FinishMessage%",
        "TargetName=%TargetName%", "FriendlyName=%FriendlyName%", "AppLaunched=%AppLaunched%",
        "PostInstallCmd=%PostInstallCmd%", "AdminQuietInstCmd=%AdminQuietInstCmd%",
        "UserQuietInstCmd=%UserQuietInstCmd%", "SourceFiles=SourceFiles",
        "[Strings]", "InstallPrompt=", "DisplayLicense=", "FinishMessage=",
        f"TargetName={target}", "FriendlyName=DeepTome Translator Setup",
        "AppLaunched=powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File boot.ps1",
        "PostInstallCmd=<None>", "AdminQuietInstCmd=", "UserQuietInstCmd=",
        'FILE0="boot.ps1"', 'FILE1="payload.zip"',
        "[SourceFiles]", f"SourceFiles0={pack}{os.sep}",
        "[SourceFiles0]", "%FILE0%=", "%FILE1%=", ""]), "ascii")
    iexpress = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "iexpress.exe"
    subprocess.run([str(iexpress), "/N", "/Q", str(sed)], check=True)
    if not target.is_file():
        sys.exit("IExpress did not write the Setup program.")
    shutil.copy(target, others / "DeepTome_Setup.exe")

    # ---- For_me: the source of exactly this build
    shutil.copy(ROOT / "book_translator.py", mine)
    shutil.copy(ROOT / "requirements.txt", mine)
    shutil.copytree(ROOT / "assets", mine / "assets")
    (mine / "installer" / "docs").mkdir(parents=True)
    for f in ("install.ps1", "uninstall.ps1", "build_setup.py"):
        shutil.copy(HERE / f, mine / "installer")
    for f in (HERE / "docs").iterdir():
        shutil.copy(f, mine / "installer" / "docs")
    note = (HERE / "docs" / "README_FOR_ME.txt").read_text("utf-8").replace("{VERSION}", version)
    (mine / "README_FOR_ME.txt").write_bytes(win_text(note))
    shutil.rmtree(HERE / "dist", ignore_errors=True)               # the old output folder is not used any more
    make_github(version)

    print(f"DeepTome Translator {version}")
    for d in (others, mine):
        print(f"  {d.relative_to(ROOT)}")
        for f in sorted(d.rglob("*")):
            if f.is_file():
                print(f"      {str(f.relative_to(d)):44s} {f.stat().st_size / 1024:8.0f} KB")
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
