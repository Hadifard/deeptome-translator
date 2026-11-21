<!--
  File    : examples/nlp_lab/README.md
  Author  : Hadi Sarhangi Fard
  Date    : 2026-11-21
  Purpose : how to reproduce the measurements and figures of README Part III
-->
# NLP laboratory

These scripts produced every number and figure in Part III of the main README. They need the model in the folder
DeepTome uses (`~/.pdf_book_translator/models`): the converted int8 engine and the downloaded checkpoint.

| Order | Script | What it does | Time on a 4-core CPU |
|---|---|---|---|
| 1 | `measure_engine.py [Dist-YOLO.pdf]` | translations, per-token log-probabilities, greedy vs beam, speed, parallel sentences (int8 engine) | ≈ 12 min |
| 2 | `encoder_vectors.py` | float32 encoder: sentence vectors, encoder self-attention, input embeddings, placeholder tokenization | ≈ 3 min |
| 3 | `cross_attention.py` | full model in bfloat16, one teacher-forced pass: cross-attention of 32 layers × 16 heads | ≈ 20 min, 10 GB RAM |
| 4 | `make_figures.py` | all figures into `docs/images/nlp` | seconds |

Note: the MADLAD-400 checkpoint stores the shared input embedding only as `decoder.embed_tokens.weight`.
`encoder_vectors.py` copies it into the encoder explicitly. Without that step the encoder would start from random vectors.
