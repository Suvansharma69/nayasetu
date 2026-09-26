r"""Human sign-off for the IPC <-> BNS mapping.

CLAUDE.md calls this the highest-risk task in Phase 1 and says not to fully
automate it. `build_mapping.py` proposes; this is where a person decides. It
shows both sections' REAL INGESTED TEXT side by side, because the whole point
is checking the proposal against the statute rather than against a score.

Output is data/mappings/ipc_bns_map.json -- the verified mapping Node 3 reads
in Phase 5 for the IPC-predecessor check. It is written after every decision,
so quitting halfway loses nothing and re-running resumes where you stopped.

Order of review is deliberate. Highest-confidence rows come first so the
obvious ones go quickly and your attention is still fresh when it reaches the
`low_evidence` rows at the end -- those are where the scorer is known to fail
(both of its 2 misses out of 21 known correspondences were flagged that way).

Keys:  y = correct      n = wrong, no BNS equivalent
       e = wrong, let me type the right BNS section
       s = skip (decide later)      b = back one      q = save and quit

Run:  venv\Scripts\python.exe scripts\review_mapping.py
      venv\Scripts\python.exe scripts\review_mapping.py --all        (all 574)
      venv\Scripts\python.exe scripts\review_mapping.py --summary
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.ingest.statutes import parse_bns, parse_ipc

MAPPINGS = ROOT / "data" / "mappings"
CANDIDATES = MAPPINGS / "ipc_bns_candidates.json"
VERIFIED = MAPPINGS / "ipc_bns_map.json"

WRAP = 78
EXCERPT = 1100


def best_window(bns, ipc, width=EXCERPT):
    """The passage of `bns` that actually corresponds to `ipc`.

    Gazette BNS sections are long -- they inline every Explanation and
    Illustration -- and the matching provision is often nowhere near the top.
    IPC 34 (common intention) maps to BNS 3(5), which sits about 3,000
    characters into a section whose opening is about general exceptions. Simply
    printing the first N characters shows a reviewer text that looks unrelated
    and gives them no way to confirm a correspondence that is in fact correct.

    So the window is chosen by overlap with the IPC section's own vocabulary,
    which puts the evidence on screen instead of the section's preamble.
    """
    if len(bns) <= width:
        return bns, False
    terms = {w for w in ipc.lower().split() if len(w) > 4}
    if not terms:
        return bns[:width], True

    step, best, best_hits = 200, 0, -1
    for start in range(0, max(1, len(bns) - width), step):
        hits = sum(bns[start:start + width].lower().count(t) for t in terms)
        if hits > best_hits:
            best, best_hits = start, hits
    return bns[best:best + width], True


def wrap(text, indent="    ", width=WRAP):
    out, line = [], indent
    for word in (text or "").split():
        if len(line) + len(word) + 1 > width:
            out.append(line)
            line = indent + word
        else:
            line = f"{line} {word}" if line.strip() else indent + word
    if line.strip():
        out.append(line)
    return "\n".join(out)


def load_verified():
    if VERIFIED.exists():
        return json.loads(VERIFIED.read_text(encoding="utf-8"))
    return {
        "_README": [
            "VERIFIED IPC<->BNS mapping. Every entry was confirmed by a person",
            "against the real ingested text of both sections.",
            "",
            "decision: 'confirmed'  the proposed BNS section is the correspondence",
            "          'corrected'  a human supplied a different BNS section",
            "          'none'       the IPC section has no BNS equivalent",
            "",
            "Written by scripts/review_mapping.py. Node 3 (Phase 5) reads this for",
            "the IPC-predecessor check on post-2024 cases; it must never read",
            "ipc_bns_candidates.json, which is unverified machine output.",
        ],
        "verified_on": None,
        "entries": {},
    }


def save(verified):
    verified["verified_on"] = date.today().isoformat()
    conf = sum(1 for e in verified["entries"].values() if e["decision"] != "none")
    verified["counts"] = {"decided": len(verified["entries"]), "with_bns": conf}
    VERIFIED.write_text(
        json.dumps(verified, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def show(row, i, total, ipc_text, bns_text, done):
    print("\n" + "=" * WRAP)
    flag = "  [LOW EVIDENCE - scorer is unreliable here]" if row["low_evidence"] else ""
    print(f"[{i + 1}/{total}]  decided so far: {done}{flag}")
    print("=" * WRAP)

    print(f"\nIPC {row['ipc_section']} - {row['ipc_title']}")
    print(wrap(ipc_text.get(row["ipc_section"], "<no text>")))

    print(f"\n  ==> proposed: BNS {row['bns_section']} - {row['bns_title']}"
          f"   (containment {row['similarity']:.2f}, "
          f"{row['ipc_terms']} content words)")
    excerpt, trimmed = best_window(
        bns_text.get(row["bns_section"], "<no text>"),
        ipc_text.get(row["ipc_section"], ""),
    )
    if trimmed:
        print("    [showing the passage that best matches the IPC section; "
              "section is longer]")
    print(wrap(excerpt))

    ru = row.get("runner_up")
    if ru and ru["similarity"] >= row["similarity"] - 0.15:
        # A close second means the top pick is much weaker than it looks.
        print(f"\n  runner-up was close: BNS {ru['bns_section']} - "
              f"{ru['bns_title']} ({ru['similarity']:.2f})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="review all 574, not just in-scope")
    ap.add_argument("--summary", action="store_true", help="print progress and exit")
    args = ap.parse_args()

    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    verified = load_verified()

    rows = [r for r in candidates["rows"] if args.all or r["in_scope"]]
    # Confident rows first, low-evidence last -- see module docstring.
    rows.sort(key=lambda r: (r["low_evidence"], -r["similarity"]))

    if args.summary:
        done = sum(1 for r in rows if r["ipc_section"] in verified["entries"])
        print(f"{done}/{len(rows)} reviewed")
        for d in ("confirmed", "corrected", "none"):
            n = sum(1 for e in verified["entries"].values() if e["decision"] == d)
            print(f"  {d:10} {n}")
        return 0

    ipc_chunks, _ = parse_ipc()
    bns_chunks = parse_bns()
    ipc_text = {c["section"]: c["text"] for c in ipc_chunks}
    bns_text = {c["section"]: c["text"] for c in bns_chunks}
    bns_valid = set(bns_text)

    todo = [r for r in rows if r["ipc_section"] not in verified["entries"]]
    print(f"{len(rows)} rows in scope, {len(rows) - len(todo)} already decided, "
          f"{len(todo)} to go.")
    print("Keys: y=correct  n=no BNS equivalent  e=enter correct section  "
          "s=skip  b=back  q=quit")

    i = 0
    while i < len(todo):
        row = todo[i]
        show(row, i, len(todo), ipc_text, bns_text, len(verified["entries"]))
        try:
            key = input("\n  [y/n/e/s/b/q] > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\ninterrupted")
            break

        if key == "q":
            break
        if key == "b":
            i = max(0, i - 1)
            continue
        if key == "s":
            i += 1
            continue

        if key == "y":
            entry = {"bns_section": row["bns_section"], "decision": "confirmed"}
        elif key == "n":
            entry = {"bns_section": None, "decision": "none"}
        elif key == "e":
            got = input("  correct BNS section (blank to cancel) > ").strip().upper()
            if not got:
                continue
            if got not in bns_valid:
                # Never let a hand-typed section into the mapping unchecked:
                # the same rule the pipeline enforces at runtime.
                print(f"  !! BNS {got} is not an ingested section - not recorded")
                continue
            entry = {"bns_section": got, "decision": "corrected"}
        else:
            continue

        entry.update({
            "ipc_title": row["ipc_title"],
            "bns_title": bns_text and row["bns_title"],
            "similarity": row["similarity"],
            "low_evidence": row["low_evidence"],
        })
        if entry["decision"] == "corrected":
            entry["bns_title"] = next(
                (c["section_title"] for c in bns_chunks
                 if c["section"] == entry["bns_section"]), None)
            entry["proposed_was"] = row["bns_section"]

        verified["entries"][row["ipc_section"]] = entry
        save(verified)
        i += 1

    save(verified)
    print(f"\nsaved {len(verified['entries'])} decisions -> {VERIFIED}")
    remaining = len([r for r in rows if r["ipc_section"] not in verified["entries"]])
    print(f"{remaining} still undecided in this scope")
    return 0


if __name__ == "__main__":
    sys.exit(main())
