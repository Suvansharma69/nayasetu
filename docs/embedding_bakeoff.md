# Embedding bake-off

- data: `phase2_testset.json` (933 docs, 15 cases)
- device: cuda
- mode: PHASE 2 GATE

| model | dim | ctx | R@1 | R@3 | R@5 | MRR | peak VRAM | docs/s |
|---|---|---|---|---|---|---|---|---|
| `bhavyagiri/InLegal-Sbert` | 768 | 512 | 0.133 | 0.2 | 0.333 | 0.223 | 0.56 GB | 143.3 |
| `BAAI/bge-m3` | 1024 | 8192 | 0.067 | 0.533 | 0.6 | 0.295 | 3.26 GB | 14.2 |

**Winner on recall@3:** `BAAI/bge-m3`

```json
[
  {
    "model": "bhavyagiri/InLegal-Sbert",
    "dim": 768,
    "max_seq_length": 512,
    "device": "cuda",
    "load_s": 0.9,
    "encode_s": 6.51,
    "docs_per_s": 143.3,
    "peak_vram_gb": 0.56,
    "recall@1": 0.133,
    "recall@3": 0.2,
    "recall@5": 0.333,
    "mrr": 0.223,
    "n_cases": 15,
    "per_case": [
      {
        "query": "The complainant parked his motorcycle outside his house at n...",
        "era": "ipc",
        "offence_type": "theft",
        "pool": 575,
        "top3": [
          "ipc_s443",
          "ipc_s278",
          "ipc_s86"
        ],
        "relevant": [
          "ipc_s378",
          "ipc_s379"
        ],
        "first_hit_rank": 311
      },
      {
        "query": "While the family was away at a wedding the accused entered t...",
        "era": "ipc",
        "offence_type": "theft",
        "pool": 575,
        "top3": [
          "ipc_s278",
          "ipc_s443",
          "ipc_s442"
        ],
        "relevant": [
          "ipc_s378",
          "ipc_s380"
        ],
        "first_hit_rank": 23
      },
      {
        "query": "The accused worked as a salesman at the complainant's cloth ...",
        "era": "ipc",
        "offence_type": "theft",
        "pool": 575,
        "top3": [
          "ipc_s86",
          "ipc_s252",
          "ipc_s354D"
        ],
        "relevant": [
          "ipc_s378",
          "ipc_s381"
        ],
        "first_hit_rank": 108
      },
      {
        "query": "The accused was the accountant of a firm and was given charg...",
        "era": "ipc",
        "offence_type": "criminal breach of trust",
        "pool": 575,
        "top3": [
          "ipc_s185",
          "ipc_s259",
          "ipc_s156"
        ],
        "relevant": [
          "ipc_s405",
          "ipc_s406",
          "ipc_s408"
        ],
        "first_hit_rank": 138
      },
      {
        "query": "During a dispute over a boundary wall the accused struck the...",
        "era": "ipc",
        "offence_type": "assault",
        "pool": 575,
        "top3": [
          "ipc_s320",
          "ipc_s443",
          "ipc_s278"
        ],
        "relevant": [
          "ipc_s320",
          "ipc_s322",
          "ipc_s325",
          "ipc_s326"
        ],
        "first_hit_rank": 1
      },
      {
        "query": "The accused raised a stick above his head and advanced towar...",
        "era": "ipc",
        "offence_type": "assault",
        "pool": 575,
        "top3": [
          "ipc_s278",
          "ipc_s298",
          "ipc_s297"
        ],
        "relevant": [
          "ipc_s351",
          "ipc_s352"
        ],
        "first_hit_rank": 20
      },
      {
        "query": "The accused advertised a flat for sale, showed the complaina...",
        "era": "ipc",
        "offence_type": "cheating",
        "pool": 575,
        "top3": [
          "ipc_s354A",
          "ipc_s489E",
          "ipc_s185"
        ],
        "relevant": [
          "ipc_s415",
          "ipc_s420"
        ],
        "first_hit_rank": 59
      },
      {
        "query": "Four men arrived together at the shop, having agreed beforeh...",
        "era": "ipc",
        "offence_type": "common intention",
        "pool": 575,
        "top3": [
          "ipc_s443",
          "ipc_s297",
          "ipc_s354D"
        ],
        "relevant": [
          "ipc_s322",
          "ipc_s34"
        ],
        "first_hit_rank": 318
      },
      {
        "query": "The complainant parked his motorcycle outside his house at n...",
        "era": "bns",
        "offence_type": "theft",
        "pool": 358,
        "top3": [
          "bns_s18",
          "bns_s303",
          "bns_s19"
        ],
        "relevant": [
          "bns_s303"
        ],
        "first_hit_rank": 2
      },
      {
        "query": "The complainant was walking along the roadside using her pho...",
        "era": "bns",
        "offence_type": "theft",
        "pool": 358,
        "top3": [
          "bns_s52",
          "bns_s18",
          "bns_s51"
        ],
        "relevant": [
          "bns_s303",
          "bns_s304"
        ],
        "first_hit_rank": 16
      },
      {
        "query": "The accused broke the seal on a goods container on a station...",
        "era": "bns",
        "offence_type": "theft",
        "pool": 358,
        "top3": [
          "bns_s57",
          "bns_s18",
          "bns_s280"
        ],
        "relevant": [
          "bns_s303",
          "bns_s305"
        ],
        "first_hit_rank": 6
      },
      {
        "query": "Following an argument outside a tea stall the accused drew a...",
        "era": "bns",
        "offence_type": "assault",
        "pool": 358,
        "top3": [
          "bns_s280",
          "bns_s52",
          "bns_s57"
        ],
        "relevant": [
          "bns_s116",
          "bns_s117",
          "bns_s118"
        ],
        "first_hit_rank": 5
      },
      {
        "query": "The accused ran a scheme promising forty per cent returns in...",
        "era": "bns",
        "offence_type": "cheating",
        "pool": 358,
        "top3": [
          "bns_s57",
          "bns_s52",
          "bns_s51"
        ],
        "relevant": [
          "bns_s318"
        ],
        "first_hit_rank": 4
      },
      {
        "query": "The accused telephoned the complainant claiming to be a bank...",
        "era": "bns",
        "offence_type": "cheating",
        "pool": 358,
        "top3": [
          "bns_s319",
          "bns_s228",
          "bns_s63"
        ],
        "relevant": [
          "bns_s318",
          "bns_s319"
        ],
        "first_hit_rank": 1
      },
      {
        "query": "The three accused went to the victim's house together under ...",
        "era": "bns",
        "offence_type": "common intention",
        "pool": 358,
        "top3": [
          "bns_s51",
          "bns_s53",
          "bns_s52"
        ],
        "relevant": [
          "bns_s3"
        ],
        "first_hit_rank": 28
      }
    ]
  },
  {
    "model": "BAAI/bge-m3",
    "dim": 1024,
    "max_seq_length": 8192,
    "device": "cuda",
    "load_s": 2.8,
    "encode_s": 65.9,
    "docs_per_s": 14.2,
    "peak_vram_gb": 3.26,
    "recall@1": 0.067,
    "recall@3": 0.533,
    "recall@5": 0.6,
    "mrr": 0.295,
    "n_cases": 15,
    "per_case": [
      {
        "query": "The complainant parked his motorcycle outside his house at n...",
        "era": "ipc",
        "offence_type": "theft",
        "pool": 575,
        "top3": [
          "ipc_s446",
          "ipc_s444",
          "ipc_s456"
        ],
        "relevant": [
          "ipc_s378",
          "ipc_s379"
        ],
        "first_hit_rank": 8
      },
      {
        "query": "While the family was away at a wedding the accused entered t...",
        "era": "ipc",
        "offence_type": "theft",
        "pool": 575,
        "top3": [
          "ipc_s496",
          "ipc_s206",
          "ipc_s498"
        ],
        "relevant": [
          "ipc_s378",
          "ipc_s380"
        ],
        "first_hit_rank": 6
      },
      {
        "query": "The accused worked as a salesman at the complainant's cloth ...",
        "era": "ipc",
        "offence_type": "theft",
        "pool": 575,
        "top3": [
          "ipc_s381",
          "ipc_s408",
          "ipc_s413"
        ],
        "relevant": [
          "ipc_s378",
          "ipc_s381"
        ],
        "first_hit_rank": 1
      },
      {
        "query": "The accused was the accountant of a firm and was given charg...",
        "era": "ipc",
        "offence_type": "criminal breach of trust",
        "pool": 575,
        "top3": [
          "ipc_s27",
          "ipc_s405",
          "ipc_s423"
        ],
        "relevant": [
          "ipc_s405",
          "ipc_s406",
          "ipc_s408"
        ],
        "first_hit_rank": 2
      },
      {
        "query": "During a dispute over a boundary wall the accused struck the...",
        "era": "ipc",
        "offence_type": "assault",
        "pool": 575,
        "top3": [
          "ipc_s44",
          "ipc_s357",
          "ipc_s323"
        ],
        "relevant": [
          "ipc_s320",
          "ipc_s322",
          "ipc_s325",
          "ipc_s326"
        ],
        "first_hit_rank": 7
      },
      {
        "query": "The accused raised a stick above his head and advanced towar...",
        "era": "ipc",
        "offence_type": "assault",
        "pool": 575,
        "top3": [
          "ipc_s190",
          "ipc_s355",
          "ipc_s351"
        ],
        "relevant": [
          "ipc_s351",
          "ipc_s352"
        ],
        "first_hit_rank": 3
      },
      {
        "query": "The accused advertised a flat for sale, showed the complaina...",
        "era": "ipc",
        "offence_type": "cheating",
        "pool": 575,
        "top3": [
          "ipc_s207",
          "ipc_s206",
          "ipc_s275"
        ],
        "relevant": [
          "ipc_s415",
          "ipc_s420"
        ],
        "first_hit_rank": 19
      },
      {
        "query": "Four men arrived together at the shop, having agreed beforeh...",
        "era": "ipc",
        "offence_type": "common intention",
        "pool": 575,
        "top3": [
          "ipc_s351",
          "ipc_s356",
          "ipc_s382"
        ],
        "relevant": [
          "ipc_s322",
          "ipc_s34"
        ],
        "first_hit_rank": 77
      },
      {
        "query": "The complainant parked his motorcycle outside his house at n...",
        "era": "bns",
        "offence_type": "theft",
        "pool": 358,
        "top3": [
          "bns_s129",
          "bns_s43",
          "bns_s303"
        ],
        "relevant": [
          "bns_s303"
        ],
        "first_hit_rank": 3
      },
      {
        "query": "The complainant was walking along the roadside using her pho...",
        "era": "bns",
        "offence_type": "theft",
        "pool": 358,
        "top3": [
          "bns_s78",
          "bns_s303",
          "bns_s129"
        ],
        "relevant": [
          "bns_s303",
          "bns_s304"
        ],
        "first_hit_rank": 2
      },
      {
        "query": "The accused broke the seal on a goods container on a station...",
        "era": "bns",
        "offence_type": "theft",
        "pool": 358,
        "top3": [
          "bns_s334",
          "bns_s335",
          "bns_s303"
        ],
        "relevant": [
          "bns_s303",
          "bns_s305"
        ],
        "first_hit_rank": 3
      },
      {
        "query": "Following an argument outside a tea stall the accused drew a...",
        "era": "bns",
        "offence_type": "assault",
        "pool": 358,
        "top3": [
          "bns_s114",
          "bns_s52",
          "bns_s118"
        ],
        "relevant": [
          "bns_s116",
          "bns_s117",
          "bns_s118"
        ],
        "first_hit_rank": 3
      },
      {
        "query": "The accused ran a scheme promising forty per cent returns in...",
        "era": "bns",
        "offence_type": "cheating",
        "pool": 358,
        "top3": [
          "bns_s335",
          "bns_s244",
          "bns_s69"
        ],
        "relevant": [
          "bns_s318"
        ],
        "first_hit_rank": 4
      },
      {
        "query": "The accused telephoned the complainant claiming to be a bank...",
        "era": "bns",
        "offence_type": "cheating",
        "pool": 358,
        "top3": [
          "bns_s182",
          "bns_s335",
          "bns_s319"
        ],
        "relevant": [
          "bns_s318",
          "bns_s319"
        ],
        "first_hit_rank": 3
      },
      {
        "query": "The three accused went to the victim's house together under ...",
        "era": "bns",
        "offence_type": "common intention",
        "pool": 358,
        "top3": [
          "bns_s333",
          "bns_s117",
          "bns_s115"
        ],
        "relevant": [
          "bns_s3"
        ],
        "first_hit_rank": 155
      }
    ]
  }
]
```