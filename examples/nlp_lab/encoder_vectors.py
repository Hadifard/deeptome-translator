# Author : Hadi Sarhangi Fard
# Date   : 2026-11-21
# Project: DeepTome Translator - NLP laboratory (the measurements of README Part III)
# File   : encoder_vectors.py - float32 encoder: sentence vectors, encoder self-attention, input embeddings
"""Part B again: the encoder in float32 WITH its real input embedding (stored once in the checkpoint as
decoder.embed_tokens.weight, shared by encoder and decoder)."""
from pathlib import Path
import json, time, os
import numpy as np
import torch
from safetensors import safe_open
from transformers import T5Tokenizer, T5EncoderModel
OUT = os.path.dirname(os.path.abspath(__file__))
SRC = str(Path.home() / ".pdf_book_translator" / "models" / "google__madlad400-3b-mt-src")
CT2 = str(Path.home() / ".pdf_book_translator" / "models" / "google__madlad400-3b-mt-ct2-int8")
R = json.load(open(os.path.join(OUT, "results.json"), encoding="utf-8"))
tok = T5Tokenizer.from_pretrained(CT2)
par = R["parallel"]
S1 = "Distance estimation is an essential part of 3D scene recognition and orientation."
torch.set_num_threads(4)
t = time.time()
encm = T5EncoderModel.from_pretrained(SRC, dtype=torch.float32, low_cpu_mem_usage=True, attn_implementation="eager")
E = safe_open(os.path.join(SRC, "model.safetensors"), "pt").get_tensor("decoder.embed_tokens.weight").float()
encm.shared.weight.data.copy_(E)
encm.encoder.embed_tokens.weight.data.copy_(E)
encm.eval()
R["enc_load_s"] = round(time.time() - t, 1)
R["enc_params"] = sum(p.numel() for p in encm.parameters())
vecs, labels = [], []
for l, ss in par.items():
    for i, s in enumerate(ss):
        ids = tok(s, return_tensors="pt").input_ids
        with torch.no_grad():
            h = encm(input_ids=ids).last_hidden_state[0]
        vecs.append(h.mean(0).numpy()); labels.append((l, i))
np.save(os.path.join(OUT, "sentvec.npy"), np.stack(vecs)); R["sent_labels"] = labels
ids = tok(f"<2de> {S1}", return_tensors="pt").input_ids
with torch.no_grad():
    o = encm(input_ids=ids, output_attentions=True, output_hidden_states=True)
np.save(os.path.join(OUT, "enc_de.npy"), torch.stack([a[0] for a in o.attentions]).numpy())
R["enc_tokens"] = tok.convert_ids_to_tokens(ids[0])
R["hidden_norms"] = [float(h[0].norm(dim=-1).mean()) for h in o.hidden_states]
words = {"camera": ["camera", "دوربین", "Kamera", "caméra", "cámara"],
         "distance": ["distance", "فاصله", "Entfernung", "distancia"],
         "network": ["network", "شبکه", "Netzwerk", "réseau"],
         "image": ["image", "تصویر", "Bild", "imagen"]}
emb = {}
for c, ws in words.items():
    for w in ws:
        ii = tok(w, add_special_tokens=False).input_ids
        emb[f"{c}|{w}"] = {"pieces": tok.convert_ids_to_tokens(ii), "ids": ii, "vec": E[ii].mean(0).numpy().tolist()}
json.dump(emb, open(os.path.join(OUT, "wordemb.json"), "w", encoding="utf-8"), ensure_ascii=False)
R["ph_pieces"] = {t_: tok.convert_ids_to_tokens(tok.encode(t_, add_special_tokens=False))
                  for t_ in ("ZX1XZ", "ZX12XZ", "ZX137XZ", "[[1]]", "<x1>", "{1}", "__TERM_1__")}
json.dump(R, open(os.path.join(OUT, "results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("PARTB", R["enc_load_s"], R["enc_params"], R["ph_pieces"])
