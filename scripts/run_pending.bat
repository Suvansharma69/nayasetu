@echo off
rem Pending work after the 2026-10-01 research step. Run from a NORMAL terminal
rem (Claude Code's memory cleanup kills long jobs it starts). Close Chrome first.
rem Both steps resume where they stopped; re-run this file if interrupted.
cd /d D:\nayasetu
set HF_HUB_OFFLINE=1

echo [1/2] finish the Node 1 union evaluation on the dev set (4 cases left)
venv\Scripts\python.exe -u scripts\eval_broad.py --fixture tests/fixtures/phase2_testset.json --out union_dev > docs\union_dev.log 2>&1

echo [2/2] finish downloading the reranker (2.27 GB; resumes; can take hours on this link)
set HF_HUB_OFFLINE=
cd /d D:\hf-cache\local\bge-reranker-v2-m3
for %%F in (config.json special_tokens_map.json tokenizer_config.json sentencepiece.bpe.model tokenizer.json model.safetensors) do (
  curl -L -C - --retry 20 --retry-delay 10 -o %%F https://huggingface.co/BAAI/bge-reranker-v2-m3/resolve/main/%%F
)
cd /d D:\nayasetu
echo ALL DONE > docs\pending_done.flag
echo All done. Tell Claude.
pause
