#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File    : examples/tokenize_demo.py
Author  : Hadi Sarhangi Fard
Date    : 2026-11-19   (DeepTome Translator 3.4)
Purpose : Shows step by step how DeepTome prepares text for the neural translation model:
            1. sentence segmentation                  (book_translator.split_sentences)
            2. protection of terms / names / maths     (book_translator.Protector -> placeholders ZX1XZ)
            3. subword tokenization                    (SentencePiece tokenizer of MADLAD-400 or NLLB-200)
            4. the target-language tag                 (<2fa> for MADLAD, target token for NLLB)
          Optional: --translate runs the real model on the example (needs the converted model, 1-3 min to load).
Copyright (c) 2026 Hadi Sarhangi Fard. All rights reserved.

Usage
    python examples/tokenize_demo.py                       # MADLAD-400 tokenizer, built-in example text
    python examples/tokenize_demo.py --model nllb          # NLLB-200 tokenizer
    python examples/tokenize_demo.py --text "Your text"    # your own text
    python examples/tokenize_demo.py --lang de --translate # also translate (target German)
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import book_translator as bt                                     # noqa: E402

EXAMPLE = ("Distance estimation is an essential part of 3D scene recognition. The YOLOv3 detector predicts a "
           "bounding box and the distance d_i = f·H/h of every object, see Fig. 2. It runs at 45 FPS on an RTX2060.")
HF_ID = {"madlad": "google/madlad400-3b-mt", "nllb": "facebook/nllb-200-distilled-1.3B"}


def find_tokenizer_dir(family: str) -> str:
    """A folder on this computer that holds the tokenizer files (the app keeps them next to its models);
    otherwise the Hugging Face id (the tokenizer, about 20 MB, is then downloaded once)."""
    key = "madlad" if family == "madlad" else "nllb"
    for d in sorted(bt.MODEL_DIR.glob(f"*{key}*")) if bt.MODEL_DIR.is_dir() else []:
        if (d / "spiece.model").is_file() or (d / "sentencepiece.bpe.model").is_file() or \
                (d / "tokenizer.json").is_file():
            return str(d)
    return HF_ID[family]


def show_tokens(tok, text: str, prefix: str = "") -> list:
    ids = tok.encode(prefix + text)
    pieces = tok.convert_ids_to_tokens(ids)
    words = len(text.split())
    print(f"    {len(pieces)} tokens for {words} words  ->  {len(pieces) / max(1, words):.2f} tokens per word")
    print("    " + " | ".join(pieces[:60]) + (" | …" if len(pieces) > 60 else ""))
    print("    ids: " + " ".join(str(i) for i in ids[:24]) + (" …" if len(ids) > 24 else ""))
    return pieces


def main() -> None:
    ap = argparse.ArgumentParser(description="DeepTome tokenization demo")
    ap.add_argument("--model", choices=["madlad", "nllb"], default="madlad")
    ap.add_argument("--text", default=EXAMPLE)
    ap.add_argument("--lang", default="fa", help="target language: fa, de, fr, es, en")
    ap.add_argument("--translate", action="store_true", help="also run the translation model")
    a = ap.parse_args()
    try:
        from transformers import AutoTokenizer
    except ImportError:
        sys.exit("Install the packages first:  pip install -r requirements.txt")

    print("=" * 100)
    print("1. SENTENCE SEGMENTATION  (the models translate best sentence by sentence)")
    sents = bt.split_sentences(a.text)
    for i, s in enumerate(sents, 1):
        print(f"   [{i}] {s}")

    print("\n2. PROTECTION  (terms, names, acronyms and maths are replaced by placeholders before translation)")
    opts = bt.Options()
    proto = bt.Protector(opts, "", set(), [])
    proto.set_lang(a.lang)
    masked, kept = [], {}
    for s in sents:
        out, pos, n = "", 0, len(kept)
        for st, en in proto.spans(s):
            n += 1
            kept[n] = s[st:en]
            out += s[pos:st] + bt.ph_token(n)
            pos = en
        masked.append(out + s[pos:])
    for m in masked:
        print("   " + m)
    for k, v in kept.items():
        print(f"      {bt.ph_token(k)} = {v!r}")

    where = find_tokenizer_dir(a.model)
    print(f"\n3. SUBWORD TOKENIZATION  (SentencePiece, {a.model.upper()} tokenizer from {where})")
    kw = {"src_lang": "eng_Latn"} if a.model == "nllb" else {}
    tok = AutoTokenizer.from_pretrained(where, use_fast=False, **kw)
    print(f"   vocabulary size: {tok.vocab_size:,} subword units")
    print("   '▁' marks the start of a word; rare words are cut into pieces, frequent words stay whole.\n")
    print("   a) the original sentence:")
    show_tokens(tok, sents[0])
    print("   b) the protected sentence (a placeholder costs a few tokens and is copied by the model):")
    show_tokens(tok, masked[0])
    if len(sents) > 1:
        print("   c) a sentence with a formula and identifiers - why they are protected:")
        show_tokens(tok, sents[1])
    samples = {"fa": "تخمین فاصله بخش مهمی از شناخت صحنهٔ سه‌بعدی است.",
               "de": "Die Entfernungsschätzung ist ein wesentlicher Bestandteil der 3D-Szenenerkennung.",
               "fr": "L’estimation de la distance est une partie essentielle de la reconnaissance de scènes 3D.",
               "es": "La estimación de la distancia es una parte esencial del reconocimiento de escenas 3D."}
    print("   d) the same idea in other languages (the tokenizer is shared by 400 languages):")
    for lg, txt in samples.items():
        print(f"      {bt.LANGS[lg]['name']}:")
        show_tokens(tok, txt)

    print("\n4. TARGET-LANGUAGE TAG")
    if a.model == "madlad":
        print(f"   MADLAD-400 is told the target language by a tag in front of the source: <2{a.lang}> …")
        show_tokens(tok, masked[0], f"<2{a.lang}> ")
    else:
        tgt = bt.LANGS[a.lang]["nllb"]
        print(f"   NLLB-200 gets the source language as the first token (eng_Latn) and the target language as")
        print(f"   the first token of the output ({tgt}).")
        show_tokens(tok, masked[0])

    print("\n   Context limits used by the app: 300 input tokens per sentence, at most 2.5 x input + 24 output")
    print("   tokens; scientific English needs about 2 MADLAD tokens per word (measured on three papers: 1.99 - 2.15).")

    if a.translate:
        print("\n5. TRANSLATION  (loading the model, 1 to 3 minutes the first time)")
        mt = bt.LocalMT(bt.DEFAULT_MODEL if a.model == "madlad" else HF_ID["nllb"], a.lang, print, True)
        res = mt.translate_sentences(masked)
        for m, r in zip(masked, res):
            back = r
            for k, v in kept.items():
                back = back.replace(bt.ph_token(k), v)
            print(f"   EN  {m}\n   {a.lang.upper()}  {back}\n")


if __name__ == "__main__":
    main()
