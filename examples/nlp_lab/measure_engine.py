# Author : Hadi Sarhangi Fard
# Date   : 2026-11-21
# Project: DeepTome Translator - NLP laboratory (the measurements of README Part III)
# File   : measure_engine.py - translations, timings, log-probabilities and speed with the app's int8 engine
"""Real measurements for the README.
Part A: the app's own engine (CTranslate2 int8 MADLAD-400 3B): translations, timings, cross-attention, per-token
        log-probabilities, greedy vs beam on short lines.
Part B (encoder) is in encoder_vectors.py."""
from pathlib import Path
import sys
import json, time, os, sys
import numpy as np
OUT = os.path.dirname(os.path.abspath(__file__))
SRC = str(Path.home() / ".pdf_book_translator" / "models" / "google__madlad400-3b-mt-src")
CT2 = str(Path.home() / ".pdf_book_translator" / "models" / "google__madlad400-3b-mt-ct2-int8")
R = {}


def dump():
    json.dump(R, open(os.path.join(OUT, "results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


import ctranslate2
from transformers import T5Tokenizer
tok = T5Tokenizer.from_pretrained(CT2)
t0 = time.time()
ct = ctranslate2.Translator(CT2, device="cpu", compute_type="int8", inter_threads=1, intra_threads=4)
R["ct2_load_s"] = round(time.time() - t0, 1)
print("ct2 loaded", R["ct2_load_s"], flush=True)


def enc(text, lang):
    return tok.convert_ids_to_tokens(tok.encode(f"<2{lang}> {text}"))


def tr(text, lang, beams=1, attn=False):
    s = enc(text, lang)
    t = time.time()
    r = ct.translate_batch([s], beam_size=beams, num_hypotheses=beams, return_scores=True, return_attention=attn,
                           max_decoding_length=int(min(420, 2.5 * len(s) + 24)))[0]
    dt = time.time() - t
    hyps = [tok.decode(tok.convert_tokens_to_ids(h), skip_special_tokens=True) for h in r.hypotheses]
    res = {"src": text, "lang": lang, "beams": beams, "out": hyps[0], "all": hyps, "sec": round(dt, 2),
           "src_pieces": s, "src_ids": tok.convert_tokens_to_ids(s), "out_pieces": r.hypotheses[0],
           "out_ids": tok.convert_tokens_to_ids(r.hypotheses[0]), "scores": [float(x) for x in r.scores]}
    if attn and r.attention:
        res["attention"] = np.asarray(r.attention[0]).tolist()
    sc = ct.score_batch([s], [r.hypotheses[0]])[0]
    res["logprobs"] = [float(x) for x in sc.log_probs]
    print(lang, beams, round(dt, 2), hyps[0], flush=True)
    return res


S1 = "Distance estimation is an essential part of 3D scene recognition and orientation."
R["s1"] = [tr(S1, l, attn=True) for l in ("fa", "de", "fr", "es")]
dump()
P1 = ("ZX1XZ is an essential part of ZX2XZ scene recognition and orientation, allowing various autonomous devices to "
      "move in the natural environment.")
R["ph"] = [tr(P1, l, attn=True) for l in ("fa", "de")]
dump()
R["short"] = [tr(x, "fa", b) for x in ("Examples", ". Examples", "Institutional Review Board Statement",
                                       "Institutional review board statement", "Funding", "Conflicts of Interest")
              for b in (1, 4)]
dump()
R["num"] = [tr("The data set was published on 27 January 2022 and contains 7481 images.", "fa"),
            tr("The data set was published on 27 January 2022 and contains 7481 images.", "de")]
R["fa_en"] = [tr("تخمین فاصله بخش مهمی از شناخت صحنهٔ سه‌بعدی است.", "en"),
              tr("تخمین فاصله بخش مهمی از شناخت صحنهٔ سه‌بعدی است.", "de")]
dump()
# speed: tokens per second for a realistic batch (one page of the Dist-YOLO article, sentence by sentence)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import book_translator as bt, fitz
d = fitz.open((sys.argv[1] if len(sys.argv) > 1 else "Dist-YOLO.pdf"))
sents = bt.split_sentences(" ".join(d[2].get_text("text").split()))[:40]
for beams in (1, 2):
    src = [enc(s, "fa") for s in sorted(sents, key=len)]
    t = time.time()
    rs = ct.translate_batch(src, beam_size=beams, max_batch_size=2048, batch_type="tokens", max_input_length=300)
    dt = time.time() - t
    n_out = sum(len(r.hypotheses[0]) for r in rs)
    R[f"speed_beam{beams}"] = {"sentences": len(src), "src_tokens": sum(map(len, src)), "out_tokens": n_out,
                               "sec": round(dt, 1), "tok_per_s": round(n_out / dt, 1)}
    print("speed", beams, R[f"speed_beam{beams}"], flush=True)
dump()
SENTS = ["The camera measures the distance to the object.",
         "Neural networks learn features from large data sets.",
         "The temperature of the gas rises when it is compressed.",
         "The author thanks the reviewers for their comments.",
         "Each image is divided into a grid of cells."]
par = {"en": SENTS}
for l in ("fa", "de", "fr", "es"):
    par[l] = [tr(s, l)["out"] for s in SENTS]
R["parallel"] = par
dump()
dump()
print("DONE - run encoder_vectors.py, cross_attention.py and make_figures.py next", flush=True)
