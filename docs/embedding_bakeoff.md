# Embedding bake-off

- data: `bakeoff_smoke.json` (12 docs, 7 cases)
- device: cuda
- mode: SMOKE (harness check, not decisive)

| model | dim | ctx | R@1 | R@3 | R@5 | MRR | peak VRAM | docs/s |
|---|---|---|---|---|---|---|---|---|
| `bhavyagiri/InLegal-Sbert` | 768 | 512 | 0.429 | 0.857 | 1.0 | 0.679 | 0.43 GB | 43.4 |

**Winner on recall@3:** `bhavyagiri/InLegal-Sbert`

```json
[
  {
    "model": "bhavyagiri/InLegal-Sbert",
    "dim": 768,
    "max_seq_length": 512,
    "device": "cuda",
    "load_s": 10.6,
    "encode_s": 0.28,
    "docs_per_s": 43.4,
    "peak_vram_gb": 0.43,
    "recall@1": 0.429,
    "recall@3": 0.857,
    "recall@5": 1.0,
    "mrr": 0.679,
    "n_cases": 7,
    "per_case": [
      {
        "query": "The accused took the complainant's motorcycle parked outside...",
        "top3": [
          "SMOKE-C",
          "SMOKE-A",
          "SMOKE-L"
        ],
        "relevant": [
          "SMOKE-A",
          "SMOKE-B"
        ],
        "first_hit_rank": 2
      },
      {
        "query": "Three men surrounded the victim, one held him while another ...",
        "top3": [
          "SMOKE-C",
          "SMOKE-L",
          "SMOKE-A"
        ],
        "relevant": [
          "SMOKE-C",
          "SMOKE-H"
        ],
        "first_hit_rank": 1
      },
      {
        "query": "The accused persuaded the complainant to transfer money for ...",
        "top3": [
          "SMOKE-D",
          "SMOKE-C",
          "SMOKE-E"
        ],
        "relevant": [
          "SMOKE-D",
          "SMOKE-E"
        ],
        "first_hit_rank": 1
      },
      {
        "query": "During a quarrel the accused struck the victim with an iron ...",
        "top3": [
          "SMOKE-C",
          "SMOKE-F",
          "SMOKE-A"
        ],
        "relevant": [
          "SMOKE-F",
          "SMOKE-G"
        ],
        "first_hit_rank": 2
      },
      {
        "query": "A group of four attacked the shopkeeper together, each playi...",
        "top3": [
          "SMOKE-H",
          "SMOKE-C",
          "SMOKE-A"
        ],
        "relevant": [
          "SMOKE-H"
        ],
        "first_hit_rank": 1
      },
      {
        "query": "The accused set fire to the neighbour's parked car, destroyi...",
        "top3": [
          "SMOKE-A",
          "SMOKE-L",
          "SMOKE-C"
        ],
        "relevant": [
          "SMOKE-I"
        ],
        "first_hit_rank": 4
      },
      {
        "query": "The company accountant was given custody of client funds and...",
        "top3": [
          "SMOKE-A",
          "SMOKE-L",
          "SMOKE-H"
        ],
        "relevant": [
          "SMOKE-K",
          "SMOKE-L"
        ],
        "first_hit_rank": 2
      }
    ]
  }
]
```