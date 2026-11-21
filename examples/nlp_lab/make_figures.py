# Author : Hadi Sarhangi Fard
# Date   : 2026-11-21
# Project: DeepTome Translator - NLP laboratory (the measurements of README Part III)
# File   : make_figures.py - all figures of README Part III from results.json
"""NLP figures for the README from the real measurements in results.json / *.npy."""
from pathlib import Path
import json, os, unicodedata, re
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

H = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "images", "nlp")
os.makedirs(OUT, exist_ok=True)
R = json.load(open(os.path.join(H, "results.json"), encoding="utf-8"))
plt.rcParams.update({"font.family": ["Segoe UI", "Tahoma"], "font.size": 10})
NAVY, BLUE, GREEN = "#063360", "#3D98FF", "#16A34A"


# ---- minimal Arabic shaping (matplotlib draws letters unjoined and left-to-right)
def _form(c, kind):
    try:
        return unicodedata.lookup(unicodedata.name(c) + " " + kind + " FORM")
    except Exception:
        return None


def shape(t):
    if not re.search("[\u0600-\u06ff]", t):
        return t
    out = []
    chars = list(t)
    def joins_left(c):  # can connect to the following letter
        return _form(c, "INITIAL") is not None or _form(c, "MEDIAL") is not None
    def arabic(c):
        return _form(c, "ISOLATED") is not None or _form(c, "FINAL") is not None
    for i, c in enumerate(chars):
        if not arabic(c):
            out.append(c); continue
        prev = chars[i - 1] if i else ""
        nxt = chars[i + 1] if i + 1 < len(chars) else ""
        p = bool(prev) and arabic(prev) and joins_left(prev)
        n = bool(nxt) and arabic(nxt) and joins_left(c)
        kind = "MEDIAL" if p and n else "FINAL" if p else "INITIAL" if n else "ISOLATED"
        out.append(_form(c, kind) or _form(c, "ISOLATED") or c)
    # visual order: reverse Arabic runs (tokens are short, no nested Latin needed)
    s = "".join(out)
    return "".join(reversed(s)) if not re.search("[A-Za-z0-9]", s) else s


def lab(p):
    return shape(p.replace(chr(0x2581), "_"))


def heat(ax, M, xl, yl, title):
    ax.imshow(M, cmap="Blues", aspect="auto", vmin=0, vmax=max(1e-6, M.max()))
    ax.set_xticks(range(len(xl))); ax.set_xticklabels([lab(x) for x in xl], rotation=70, ha="right", fontsize=8.5)
    ax.set_yticks(range(len(yl))); ax.set_yticklabels([lab(y) for y in yl], fontsize=8.5)
    ax.set_title(title, color=NAVY, fontsize=11, fontweight="bold", loc="left")
    ax.tick_params(length=0)


# ---------------------------------------------------------------- cross-attention alignments
for lang, item in (("fa", R["s1"][0]), ("de", R["s1"][1]), ("fa_ph", R["ph"][0]), ("de_ph", R["ph"][1])):
    if True:                                          # replaced by the full-model figure below
        continue
    M = np.array(item["attention"])                   # target tokens × source tokens (CTranslate2 alignment head)
    tgt = item["out_pieces"][: M.shape[0]]
    src = item["src_pieces"][: M.shape[1]]
    fig, ax = plt.subplots(figsize=(max(7, 0.42 * len(src) + 2), max(4, 0.36 * len(tgt) + 1.6)), dpi=140)
    heat(ax, M[: len(tgt), : len(src)], src, tgt,
         f"Cross-attention  English → {('Persian' if lang.startswith('fa') else 'German')}  (MADLAD-400 3B int8, CTranslate2 alignment attention)")
    ax.set_xlabel("source SentencePiece tokens (encoder)"); ax.set_ylabel("generated tokens (decoder)")
    fig.tight_layout(); fig.savefig(os.path.join(OUT, f"cross_attention_{lang}.png")); plt.close(fig)

# ---------------------------------------------------------------- encoder self-attention, one layer per panel
f = os.path.join(H, "enc_de.npy")
if os.path.exists(f):
    ea = np.load(f); src = R["s1"][1]["src_pieces"]
    fig, axs = plt.subplots(1, 3, figsize=(17, 5.6), dpi=130)
    for ax, L in zip(axs, (0, 5, 31)):
        heat(ax, ea[L].mean(0), src, src, f"encoder layer {L + 1} (mean of 16 heads)")
    fig.suptitle("Encoder self-attention on the same sentence: layer 1 attends to neighbours (diagonal); deeper layers park most attention on the first token (an \"attention sink\")",
                 color=NAVY, fontsize=12, fontweight="bold")
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "encoder_attention.png")); plt.close(fig)

# ---------------------------------------------------------------- token confidence of greedy decoding
item = R["s1"][0]
if item.get("logprobs"):
    lp = np.array(item["logprobs"]); toks = (item["out_pieces"] + ["</s>"])[: len(lp)]
    fig, ax = plt.subplots(figsize=(max(8, 0.5 * len(lp)), 3.6), dpi=140)
    ax.bar(range(len(lp)), np.exp(lp), color=[GREEN if v > np.log(0.5) else "#F59E0B" for v in lp])
    ax.set_xticks(range(len(lp))); ax.set_xticklabels([lab(t) for t in toks], rotation=70, ha="right", fontsize=9)
    ax.set_ylim(0, 1.02); ax.set_ylabel("p(token)")
    ax.set_title("Greedy decoding: probability of every chosen token (English → Persian)", color=NAVY, fontweight="bold",
                 loc="left")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "token_confidence.png")); plt.close(fig)

# ---------------------------------------------------------------- sentence vectors: cross-lingual similarity + PCA
f = os.path.join(H, "sentvec.npy")
if os.path.exists(f):
    V = np.load(f); labels = [tuple(x) for x in R["sent_labels"]]
    Vn = V / np.linalg.norm(V, axis=1, keepdims=True)
    S = Vn @ Vn.T
    names = {"en": "EN", "fa": "FA", "de": "DE", "fr": "FR", "es": "ES"}
    order = sorted(range(len(labels)), key=lambda k: (labels[k][1], list(names).index(labels[k][0])))
    fig, axs = plt.subplots(1, 2, figsize=(16, 7), dpi=130, gridspec_kw={"width_ratios": [1.15, 1]})
    ax = axs[0]
    ax.imshow(S[np.ix_(order, order)], cmap="viridis", vmin=S.min(), vmax=1)
    tl = [f"S{labels[k][1] + 1}-{names[labels[k][0]]}" for k in order]
    ax.set_xticks(range(len(tl))); ax.set_xticklabels(tl, rotation=90, fontsize=7.5)
    ax.set_yticks(range(len(tl))); ax.set_yticklabels(tl, fontsize=7.5)
    ax.set_title("Cosine similarity of mean-pooled encoder vectors (1024-d)\n5 sentences × 5 languages",
                 color=NAVY, fontweight="bold", loc="left")
    Xc = V - V.mean(0); U, s_, Wt = np.linalg.svd(Xc, full_matrices=False); P2 = Xc @ Wt[:2].T
    ax = axs[1]
    cols = ["#2563EB", "#16A34A", "#DC2626", "#9333EA", "#EA580C"]
    marks = {"en": "o", "fa": "s", "de": "^", "fr": "D", "es": "P"}
    for k, (l, i) in enumerate(labels):
        ax.scatter(P2[k, 0], P2[k, 1], c=cols[i], marker=marks[l], s=90, edgecolor="white", linewidth=0.8)
    for i in range(5):
        ax.scatter([], [], c=cols[i], marker="o", label=f"S{i + 1}: " + R["parallel"]["en"][i][:38] + "…")
    for l, m in marks.items():
        ax.scatter([], [], c="#64748B", marker=m, label=names[l])
    ax.legend(fontsize=7.5, loc="best", frameon=False)
    ax.set_title("PCA of the same vectors: sentences group by MEANING, not by language", color=NAVY,
                 fontweight="bold", loc="left")
    ax.set_xticks([]); ax.set_yticks([])
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "sentence_vectors.png")); plt.close(fig)
    same = [S[a, b] for a in range(25) for b in range(25) if a < b and labels[a][1] == labels[b][1]]
    diff = [S[a, b] for a in range(25) for b in range(25) if a < b and labels[a][1] != labels[b][1]]
    R["sim_same_meaning"] = float(np.mean(same)); R["sim_diff_meaning"] = float(np.mean(diff))

# ---------------------------------------------------------------- static input embeddings
f = os.path.join(H, "wordemb.json")
if os.path.exists(f):
    E = json.load(open(f, encoding="utf-8"))
    keys = list(E); X = np.array([E[k]["vec"] for k in keys]); Xn = X / np.linalg.norm(X, axis=1, keepdims=True)
    S = Xn @ Xn.T
    fig, ax = plt.subplots(figsize=(9, 8), dpi=140)
    ax.imshow(S, cmap="magma", vmin=0, vmax=1)
    tl = [k.split("|")[0] + ":  " + "  ·  ".join(lab(p) for p in E[k]["pieces"]) for k in keys]
    ax.set_xticks(range(len(keys))); ax.set_xticklabels(tl, rotation=80, fontsize=7.5)
    ax.set_yticks(range(len(keys))); ax.set_yticklabels(tl, fontsize=7.5)
    ax.set_title("Input embedding table of the encoder (256 000 × 1024): cosine similarity of word pieces",
                 color=NAVY, fontweight="bold", loc="left", fontsize=10)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "input_embeddings.png")); plt.close(fig)
json.dump(R, open(os.path.join(H, "results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("figs ok", R.get("sim_same_meaning"), R.get("sim_diff_meaning"))

# ---------------------------------------------------------------- full-model cross-attention (all layers x heads)
names_ = {"fa": "Persian", "de": "German"}
for key, item in (("s1_fa", R["s1"][0]), ("s1_de", R["s1"][1]), ("ph_fa", R["ph"][0]), ("ph_de", R["ph"][1])):
    f = os.path.join(H, f"xattn_{key}.npy")
    if not os.path.exists(f):
        continue
    ca = np.load(f).astype(np.float32)                 # layers, heads, tgt(+1), src
    src = item["src_pieces"]; tgt = item["out_pieces"] + ["</s>"]
    keep = [j for j, p in enumerate(src) if p not in ("\u2581", "</s>") and not re.fullmatch(r"<2\w+>", p)]
    A = ca[:, :, : len(tgt), :][..., keep]
    A = A / A.sum(-1, keepdims=True).clip(1e-9)        # attention sink columns removed, rows renormalised
    ent = -(A * np.log(A.clip(1e-9))).sum(-1).mean(axis=(1, 2))   # sharpness of every layer
    best = np.argsort(ent)[:8]
    M = A[best].mean(axis=(0, 1))
    srcl = [src[j] for j in keep]
    fig, ax = plt.subplots(figsize=(max(7, 0.42 * len(srcl) + 2.5), max(4, 0.34 * len(tgt) + 1.8)), dpi=140)
    heat(ax, M, srcl, tgt, f"Cross-attention English → {names_[key[-2:]]}: the 8 sharpest of 32 decoder layers × 16 heads")
    ax.set_xlabel("source SentencePiece tokens (encoder input)"); ax.set_ylabel("generated tokens (decoder)")
    fig.tight_layout(); fig.savefig(os.path.join(OUT, f"cross_attention_{key}.png")); plt.close(fig)
    R.setdefault("xattn_layers", {})[key] = [int(b) + 1 for b in sorted(best)]
json.dump(R, open(os.path.join(H, "results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("xattn", R.get("xattn_layers"))
