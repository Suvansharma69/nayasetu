# Prompt: restructure the Pramana deck into a standard major-project presentation

Paste everything below the line into Claude (Claude Code opened on `D:\nayasetu`).

---

I'm presenting my B.Tech CSE major project **Pramana** for final evaluation at IKGPTU. The deck is at `presentation/index.html` (HTML slides; styles in `presentation/assets/deck.css`, `slides.css`, `flow.css`; behaviour in `assets/deck.js`; read `presentation/README.md` first).

The design is good, but the structure doesn't match how major projects are presented and evaluated. Restructure it to the **standard engineering major-project flow**:

**Title → Outline → Introduction & Motivation → Problem Statement → Literature Review & Research Gap → Objectives → Proposed System → Methodology & Architecture → Dataset → Implementation & Tech Stack → Results & Comparison → Challenges & Limitations → Conclusion & Future Scope → References → Thank You / Q&A**, with backup slides after Thank You for questions.

Examiners mark content, presentation and **Q&A**, so every technical choice must be justified on screen ("why this, not that"), and the comparison with existing work must be explicit. Keep it tight: **about 20 main slides, 12–15 minutes**, plus 3–4 backup slides that I won't present.

To make it engaging and not dry, add a **story thread**: a fictional advocate, "Advocate Meera" (a composite user; say in the notes she's illustrative), receives the motorcycle-theft case (15 Aug 2024) that's already in the deck. Introduce her in the Introduction, follow her case through the methodology, and return to her in the Conclusion.

## Ground rules

1. **Keep the existing visual design**: fonts, colours, ink/paper themes, `eyebrow` + `h2`, `rise` / `data-step` builds, `.card`, `.chip`, `.stat`. Reuse existing classes and put new CSS in `flow.css`. Don't restyle the slides I'm keeping.
2. **Eyebrows use the standard section names** (e.g. `03 · Problem statement`, `05 · Literature review`, `08 · Methodology`), so examiners can see the expected structure at a glance. The bottom chrome chapter labels must match.
3. **Only real numbers from this project**, from the sources listed in the README under "Where the numbers come from" and the code. Never invent. Every outside statistic, paper detail or competitor claim gets a visible `[[VERIFY: …]]` placeholder that you list for me at the end.
4. The real stack is qwen3.5:4b on Ollama, BGE-M3, ChromaDB, NetworkX, SQLite, LangGraph, FastAPI + web app. Don't mention Gemini, Gemma or InLegal-SBERT except as an alternative considered or a baseline.
5. Every slide gets `<aside class="notes">` in plain spoken English, with `[click]` markers matching its `data-step`s and a last line that bridges to the next slide.
6. Keep slides minimal: one idea per slide, no paragraphs, at most about 30 words of body text. Use diagrams over tables, and labelled figures.
7. Add inline citation markers like `[3]` wherever a slide uses outside work, matching the References slide.

## Slide-by-slide

| # | Section | What to do |
|---|---|---|
| 1 | **Title** | Keep it. Add the standard details: project title, my name + roll number `[[VERIFY: roll no]]`, team name, guide name + designation `[[VERIFY]]`, Department of CSE, IKGPTU, month and year (Oct 2026). |
| 2 | **Outline** | Keep the agenda slide, but change the items to the standard sections: Introduction · Problem · Literature review · Objectives · Proposed system · Methodology · Implementation · Results · Conclusion. |
| 3 | **Introduction & motivation** | NEW. "Meet Meera." A client walks in with the motorcycle theft. Show her current research as a visual chain: bare act → commentary → search judgments → hours of reading → still unsure. Add 3 motivation chips: *two criminal codes since 2024*, *AI tools invent citations*, *client facts are confidential*. Keep it to 30–40 seconds. |
| 4 | **Problem statement (1)** | Keep the current renumbering slide (302 / 303 / 420). |
| 5 | **Problem statement (2)** | Keep the current hallucination slide, framed as "Meera tries a chatbot." Add one tiny line saying how `20 of 68` was measured (`docs/evaluation_results.md`). Add a cited fact: Magesh et al. found commercial legal AI tools hallucinating in about 17–33% of queries [ref]. End with a boxed **one-sentence formal problem statement**, e.g. *"Build a research assistant for Indian criminal law that identifies applicable sections and precedents across the IPC→BNS transition, never presents a non-existent citation, and runs fully offline."* |
| 6 | **Literature review & research gap** | NEW. Two halves. **Left: research.** 4–5 key papers, one line each on what it did and its limit: RAG (Lewis et al., 2020); LeSICiN statute identification (Paul et al., AAAI 2022); IL-TUR benchmark (ACL 2024); Magesh et al., legal AI hallucination (2024); BGE-M3 (Chen et al., 2024); plus any others the repo docs actually cite. **Right: existing tools.** A compact table of Indian Kanoon, Manupatra / SCC Online, jhana.ai, NyayAssist and Pramana with columns *IPC vs BNS by date*, *verifies citations*, *runs offline*, *free*. Be honest: jhana.ai and NyayAssist also verify citations. Finish with a boxed **Research gap** that names what nobody combines: offline + date-based code routing + an IPC→BNS precedent bridge + graph-verified citations + outcome statistics. Mark all paper details and competitor cells `[[VERIFY]]`. |
| 7 | **Objectives** | NEW. 5 numbered, measurable objectives, each with a small tag pointing to the result that proves it: (1) route the correct code from the offence date → *30/30*; (2) identify applicable sections from facts → *IL-TUR*; (3) never show a non-existent section → *0 in 889 citations*; (4) find precedents for new BNS sections → *IPC bridge*; (5) run offline on a 4 GB laptop GPU at ₹0 → *RTX 3050 Ti*. |
| 8 | **Proposed system** | Keep the current "What Pramana does" slide (facts + date in → checked memo out, three promises). |
| 9 | **Methodology: system architecture** | Keep the current architecture slide. In the notes, say the next slides walk through it stage by stage with Meera's case. |
| 10 | **Dataset** | NEW. A pipeline diagram: sources → processing → stores. Sources are the IPC (575 sections), the BNS parsed from the official gazette (358), ~2,745 SC + HC judgments and the IPC→BNS mapping (575 rows, reviewed). Show the processing steps (parsing, cleaning, chunking into 87,036 passages) and what goes into the 4 ChromaDB collections, the citation graph (933 nodes, 16,493 edges, 539 bridges) and SQLite. Take exact counts and steps from the ingestion code and `build_report.json`. |
| 11 | **Methodology: retrieval (RAG)** | NEW. Left: *why RAG, not fine-tuning*, as a 3-row mini comparison (knowledge stays current, every answer traces to a source, fits a 4 GB GPU). Right: 4 numbered steps with Meera's real values from `app/samples/motorcycle_theft.json`: date → BNS; BGE-M3 embeds facts; statute search + precedent votes fused by reciprocal rank fusion; top candidates with scores (BNS 303 first). Mention the guardrail in one line. |
| 12 | **Methodology: citation verification** | Keep the current verification slide (graph + retry loop). |
| 13 | **Methodology: precedents across the transition** | Keep the current bridge slide. Add one line at the bottom about Node 2b (does a real section actually fit the facts; doubts shown in amber) and Node 5 (outcome statistics computed by SQL with no LLM; small samples suppressed, using the real threshold from the code). |
| 14 | **Implementation: tech stack** | Keep the current tech slide, and add a short **"why / alternative considered"** to each layer: qwen3.5:4b on Ollama (vs cloud GPT/Gemini: privacy, ₹0, fits 4 GB); BGE-M3 (vs a legal-domain model: bake-off 0.533 vs 0.20 recall@3); ChromaDB (vs FAISS/Pinecone: local, persistent, metadata filters); NetworkX (exact existence check); SQLite (exact counts); LangGraph (vs a single prompt: retry edge, parallel nodes, shared state that can be checked step by step); FastAPI. Keep the 4 GB GPU hand-over panel and 422 tests. |
| 15 | **Implementation: live demo** | Keep the current demo slide. Notes: "Here is Meera's case, live." |
| 16 | **Results** | Keep the current big-zero results slide. |
| 17 | **Results: comparison with existing work** | Keep the current IL-TUR benchmark slide. Make sure baselines cite [refs]. |
| 18 | **Challenges & limitations** | NEW. A two-column table, **Challenge → How we handled it**: no digital BNS (parsed the gazette); both models don't fit 4 GB (GPU hand-over); the model invents sections (graph verification + retry); no BNS case law yet (IPC bridge). Then **Limitations**: zero-shot trails trained systems (11.8 vs 28.1); minor companion offences often missed (37% reach the candidate list); mapping not yet reviewed by practising lawyers; substantive criminal law only. |
| 19 | **Conclusion & future scope** | Edit the current impact/roadmap slide. Left: **Conclusion**, with 3 bullets tied back to the objectives plus Meera's morning now ("facts in, checked memo in about a minute, on her own laptop"). Right: **Future scope**, the existing roadmap items, each matched to a limitation. Fold "who it helps" into one line of small chips. |
| 20 | **References** | NEW. 8–12 references in **IEEE style**, numbered to match the `[n]` markers in the slides. Include the papers above plus the BNS 2023 gazette notification, the IPC 1860, and the tools (LangGraph, Ollama, ChromaDB) if cited. Mark each `[[VERIFY]]` until I confirm it. Use a small font, two columns. |
| 21 | **Thank you / Q&A** | Keep the current closing slide. |
| B1–B4 | **Backup (after Thank You, not presented)** | Move the **product screenshots** slide here. Add: **B2 Worked example traced**, with every stage of Meera's case and real values from `motorcycle_theft.json`; **B3 LangGraph state object**, showing the state growing node by node, with LLM / code / graph marked; **B4 Evaluation method**, covering how each result number was produced (test sets, sizes, run once at the end). These answer likely questions. Give them a visible "Backup" eyebrow. |

## Housekeeping

- Update the slide counter, the chapter labels and `#N` navigation. Backup slides should be reachable by number but come after Thank You.
- Update `presentation/README.md`: slide count, timing, demo slide number, and a "backup slides for Q&A" table that says which question each backup answers.
- Regenerate `Pramana_presentation.pdf` with the README command, and check every page in both themes for overflow or clipped text (especially References, Literature review and the tech "why" column).
- Step through all builds and confirm every `[click]` in the notes matches a `data-step`.

## When you're done, give me

1. The final slide list (number, section, title, one line on what it shows).
2. Every `[[VERIFY: …]]` placeholder and what I need to check.
3. Time per section, totalling 12–15 minutes.
4. The 8 questions examiners are most likely to ask, with the slide or backup slide that answers each.
