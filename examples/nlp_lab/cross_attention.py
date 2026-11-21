# Author : Hadi Sarhangi Fard
# Date   : 2026-11-21
# Project: DeepTome Translator - NLP laboratory (the measurements of README Part III)
# File   : cross_attention.py - cross-attention of all 32 decoder layers x 16 heads (teacher-forced pass)
"""Cross-attention of the full MADLAD-400 3B (all 32 decoder layers x 16 heads) for translations produced by the
app's engine: ONE teacher-forced forward pass (no generation), bfloat16."""
from pathlib import Path
import json, os, time
import numpy as np
import torch
from transformers import T5ForConditionalGeneration, T5Tokenizer
OUT = os.path.dirname(os.path.abspath(__file__))
SRC = str(Path.home() / ".pdf_book_translator" / "models" / "google__madlad400-3b-mt-src")
R = json.load(open(os.path.join(OUT, "results.json"), encoding="utf-8"))
tok = T5Tokenizer.from_pretrained(SRC)
torch.set_num_threads(4)
t = time.time()
m = T5ForConditionalGeneration.from_pretrained(SRC, dtype=torch.bfloat16, low_cpu_mem_usage=True,
                                               attn_implementation="eager")
m.eval()
print("loaded", round(time.time() - t), flush=True)
for key, item in (("s1_fa", R["s1"][0]), ("s1_de", R["s1"][1]), ("ph_fa", R["ph"][0]), ("ph_de", R["ph"][1])):
    src = torch.tensor([item["src_ids"]])
    dec = torch.tensor([[0] + item["out_ids"]])          # decoder start token (pad = 0) + the generated tokens
    t = time.time()
    with torch.no_grad():
        o = m(input_ids=src, decoder_input_ids=dec, output_attentions=True)
    ca = torch.stack([a[0].float() for a in o.cross_attentions]).numpy()      # layers, heads, tgt, src
    np.save(os.path.join(OUT, f"xattn_{key}.npy"), ca.astype(np.float16))
    print(key, ca.shape, round(time.time() - t, 1), flush=True)
print("DONE")
