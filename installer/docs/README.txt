DEEPTOME TRANSLATOR  -  version {VERSION}
==========================================

Translates PDF books and articles between English, Persian, German, French and Spanish and keeps the page layout:
every paragraph goes back to its place, formulas, figures, tables, names and technical terms stay as they are.
The translation runs on your own computer (offline) or, if you choose it, through an online service.

Copyright (c) 2026 Hadi Sarhangi Fard. All rights reserved. See LICENSE.txt.


1. WHAT YOU NEED
----------------
  * Windows 10 or Windows 11, 64-bit.
  * An internet connection during the installation.
  * No Python and no other program is needed. No administrator rights are needed.
  * Memory: 8 GB works, 16 GB is better.  A graphics card is not needed.
  * Free disk space and download size depend on the engines you choose (measured on 2026-11-16):

        Choice in Setup                         Download      Disk space afterwards
        ---------------------------------------------------------------------------
        Small    - app only                      0.33 GB       about 1.6 GB
        Standard - built-in engine              12.11 GB       about 4.4 GB   (17 GB free during setup)
        Advanced - all engines (default)        17.32 GB       about 12.8 GB  (25 GB free during setup)

    What is downloaded:
        Private Python 3.12                      42 MB
        Program packages (54)                   289 MB
        Built-in engine MADLAD-400 3B         11.78 GB   (converted once; then 2.8 GB on the disk)
        Ollama                                 1.86 GB
        Ollama model gemma3:4b                 3.35 GB

    THE FIRST INSTALLATION TAKES LONG.  All engines: about 25 minutes with a 100 Mbit/s line, about 2 hours with
    20 Mbit/s, about 8 hours with 5 Mbit/s - plus 15 to 40 minutes in which the built-in model is converted.
    You can use the computer meanwhile.  If the download is interrupted, start Setup again: it continues.


2. INSTALLATION
---------------
  1. Double-click  DeepTome_Setup.exe .
  2. Windows may show "Windows protected your PC", because the program has no paid digital signature.
     Click "More info", then "Run anyway".
  3. Choose the engines (Advanced = all engines is the default) and click "Install".
  4. When it is finished, click "Finish".  The program starts, and a shortcut "DeepTome Translator" is on the
     desktop and in the Start menu.

  If your computer blocks the .exe file: unpack  DeepTome_Setup_files.zip  into a folder and double-click
  "Setup.cmd" in it.  It is the same installation.

  The program is installed for your Windows user in
        %LOCALAPPDATA%\Programs\DeepTome
  Translation models, fonts, your glossary and your settings are kept in
        %USERPROFILE%\.pdf_book_translator


3. FIRST STEPS
--------------
  1. Start "DeepTome Translator" from the desktop.
  2. "Browse..." - choose a PDF.  The program shows its language, the number of pages and tokens.
  3. Tick the target language.
  4. Press the green RUN button.  Tip: try a few pages first (field "Pages", for example 1-5).
  5. The result is saved as  Translated_to_<language>__<original name>.pdf  in the folder you chose.

  The Help button in the program opens an illustrated guide in English, Persian, German, French and Spanish and
  a full reference.


4. THE THREE TRANSLATION ENGINES
--------------------------------
  Built-in (MADLAD / NLLB)   Offline, nothing to set up.  On a computer without a graphics card it needs
                             several minutes per page.
  Ollama (Gemma, Qwen ...)   A language model on your computer.  Follows your glossary and your instructions.
                             Other models:  ollama pull <name>   then "List models" in the program.
  Online API                 Any service with the OpenAI protocol.  You type the address, the model and your
                             own key.  Fast, but the text of your document is sent to that service and the
                             service may charge for it.


5. GOOD TO KNOW
---------------
  * The PDF must contain real text.  A scanned book (pictures of pages) can not be translated.
  * A file of more than 700 pages is not accepted.  Split it first.
  * English to Persian is the best tested direction.  The other language pairs are newer.
  * A machine translation can contain mistakes.  Check important texts before you use them.
  * "Translate with review" lets you correct every part before it is saved.


6. REMOVING THE PROGRAM
-----------------------
  Windows Settings > Apps > "DeepTome Translator" > Uninstall.
  You are asked whether the downloaded models and your settings are deleted too.  Your translations are never
  touched.  Ollama is a separate program; remove it in the same list if you do not need it.


7. HELP AND CONTACT
-------------------
  GitHub    https://github.com/Hadifard

  If the installation stops, please send the file  %TEMP%\DeepTome_setup.log  .


Files in this package
---------------------
  DeepTome_Setup.exe          the installer (double-click)
  DeepTome_Setup_files.zip    the same installer as a folder, for computers that block .exe files
  README.txt                  this file
  README_fa.txt               the same in Persian
  LICENSE.txt                 the terms of use
  THIRD_PARTY_NOTICES.txt     the open-source components the program uses, and their licences
  CHANGELOG.txt               what is new in each version
