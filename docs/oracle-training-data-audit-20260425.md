# Oracle Training Data Audit

Generated: 2026-04-25
Training root: `/Users/scawful/src/training`
Eval files indexed: `23`

## Executive Findings

- `qwen3_oracle_14b_v7` is heavily weighted by duplication (178/201 duplicate rows, 88.6%). Keep this only when each weight maps to a measured failure bucket.
- `qwen3_oracle_14b_v7` has tiny validation/test splits (val 1, test 1); treat them as smoke checks, not promotion gates.
- `qwen3_oracle_14b_v7` has no actual tool-call transcript rows. If this trains a tool-using Oracle lane, add deployed-format tool call/result/final-answer examples.
- `qwen3_oracle_14b_v7` overlaps Oracle eval material (prompt rows 68, answer rows 402). Use those evals as regression checks and keep a fresh holdout for promotion.
- `oracle_repo_code_v3` is heavily weighted by duplication (1094/1296 duplicate rows, 84.4%). Keep this only when each weight maps to a measured failure bucket.
- `oracle_repo_code_v3` has no actual tool-call transcript rows. If this trains a tool-using Oracle lane, add deployed-format tool call/result/final-answer examples.
- `oracle_repo_code_v3` overlaps Oracle eval material (prompt rows 428, answer rows 96). Use those evals as regression checks and keep a fresh holdout for promotion.
- `oracle_fast_4b_candidate_v1` is heavily weighted by duplication (1799/2049 duplicate rows, 87.8%). Keep this only when each weight maps to a measured failure bucket.
- `oracle_9b_candidate_v1` overlaps Oracle eval material (prompt rows 4823, answer rows 4352). Use those evals as regression checks and keep a fresh holdout for promotion.
- `oracle_longctx_v1` is heavily weighted by duplication (384/544 duplicate rows, 70.6%). Keep this only when each weight maps to a measured failure bucket.
- `oracle_longctx_v1` has no actual tool-call transcript rows. If this trains a tool-using Oracle lane, add deployed-format tool call/result/final-answer examples.
- `oracle_longctx_dpo_v1` is heavily weighted by duplication (384/544 duplicate rows, 70.6%). Keep this only when each weight maps to a measured failure bucket.
- `oracle_longctx_dpo_v1` has no actual tool-call transcript rows. If this trains a tool-using Oracle lane, add deployed-format tool call/result/final-answer examples.

## Dataset Summary

| Dataset | Rows | Train | Val | Test | Unique Rows | Duplicate Rows | Tool Transcript Rows | Prompt Eval Overlaps | Answer Eval Overlaps |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `qwen3_oracle_14b_v7` | 201 | 199 | 1 | 1 | 23 | 178 | 0 | 68 | 402 |
| `oracle_repo_code_v3` | 1296 | 1270 | 13 | 13 | 202 | 1094 | 0 | 428 | 96 |
| `oracle_fast_4b_candidate_v1` | 2049 | 1990 | 29 | 30 | 250 | 1799 | 1810 | 0 | 0 |
| `oracle_9b_candidate_v1` | 37642 | 25249 | 5527 | 6866 | 32092 | 5550 | 9199 | 4823 | 4352 |
| `oracle_longctx_v1` | 544 | 512 | 16 | 16 | 160 | 384 | 0 | 0 | 0 |
| `oracle_longctx_dpo_v1` | 544 | 512 | 16 | 16 | 160 | 384 | 0 | 0 | 0 |

## Dataset Details

### `qwen3_oracle_14b_v7`

- Path: `/Users/scawful/src/training/datasets/qwen3_oracle_14b_v7`
- Rows: `201`; unique row payloads: `23`; duplicate row pressure: `88.6%`
- Unique prompts: `23`; prompt duplicate pressure: `88.6%`
- Unique answers: `11`
- Split content overlap: `{'train/val': 1, 'train/test': 1, 'val/test': 0}`
- Split prompt overlap: `{'train/val': 1, 'train/test': 1, 'val/test': 0}`

Tool surface:
- `prose-only`: 201

Bucket counts (expanded rows):
- `abi_and_width_contracts`: 132
- `debug_capture_and_triage`: 54
- `hardware_register_grounding`: 5
- `uncertainty_and_scope_control`: 4
- `oracle_docs_and_system_reasoning`: 3
- `hook_safety_and_authoring`: 3

Bucket unique row counts:
- `abi_and_width_contracts`: 13
- `debug_capture_and_triage`: 6
- `oracle_docs_and_system_reasoning`: 1
- `hook_safety_and_authoring`: 1
- `uncertainty_and_scope_control`: 1
- `hardware_register_grounding`: 1

Role counts:
- `failure_target`: 170
- `stability_anchor`: 31

Style counts:
- `rewrite`: 34
- `score_gap`: 34
- `direct`: 34
- `contract`: 34
- `abi_precision`: 24
- `stability_anchor`: 21

Examples by bucket:
- `abi_and_width_contracts`: `qwen3_oracle_14b_corrective_v6_rewrite_oracle_main_stz_long_address`, `qwen3_oracle_14b_corrective_v6_rewrite_oracle_main_stz_long_address`, `qwen3_oracle_14b_corrective_v6_abi_precision_oracle_main_v2_rep20_store_then_flag`, `qwen3_oracle_14b_corrective_v6_rewrite_oracle_main_v2_rep20_store_then_flag`
- `debug_capture_and_triage`: `qwen3_oracle_14b_corrective_v6_score_gap_oracle_main_v2_capture_assert_jtl`, `qwen3_oracle_14b_corrective_v6_capture_first_oracle_main_v2_capture_assert_jtl`, `qwen3_oracle_14b_corrective_v6_rewrite_oracle_main_v2_capture_assert_jtl`, `qwen3_oracle_14b_corrective_v6_rewrite_oracle_main_v2_capture_assert_jtl`
- `hardware_register_grounding`: `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_mdmaen_vs_hdmaen`, `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_mdmaen_vs_hdmaen`, `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_mdmaen_vs_hdmaen`, `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_mdmaen_vs_hdmaen`
- `hook_safety_and_authoring`: `qwen3_oracle_14b_corrective_v6_protective_anchor_oracle_main_v2_hook_stub_overwritten_logic`, `qwen3_oracle_14b_corrective_v6_protective_anchor_oracle_main_v2_hook_stub_overwritten_logic`, `qwen3_oracle_14b_corrective_v6_protective_anchor_oracle_main_v2_hook_stub_overwritten_logic`
- `oracle_docs_and_system_reasoning`: `qwen3_oracle_14b_corrective_v6_protective_anchor_oracle_main_zso_time_system`, `qwen3_oracle_14b_corrective_v6_protective_anchor_oracle_main_zso_time_system`, `qwen3_oracle_14b_corrective_v6_protective_anchor_oracle_main_zso_time_system`
- `uncertainty_and_scope_control`: `qwen3_oracle_14b_corrective_v6_protective_anchor_oracle_main_v2_docs_refuse_fake_symbol`, `qwen3_oracle_14b_corrective_v6_protective_anchor_oracle_main_v2_docs_refuse_fake_symbol`, `qwen3_oracle_14b_corrective_v6_protective_anchor_oracle_main_v2_docs_refuse_fake_symbol`, `qwen3_oracle_14b_corrective_v6_protective_anchor_oracle_main_v2_docs_refuse_fake_symbol_test_anchor`

Largest prompt-family clusters:
- count `60`, unique prompts `5`, splits `{'train': 60}`, buckets `{'abi_and_width_contracts': 60}`; samples `qwen3_oracle_14b_corrective_v6_rewrite_oracle_main_stz_long_address`, `qwen3_oracle_14b_corrective_v6_rewrite_oracle_main_stz_long_address`, `qwen3_oracle_14b_corrective_v6_abi_precision_oracle_main_stz_long_address`, `qwen3_oracle_14b_corrective_v6_score_gap_oracle_main_stz_long_address`, `qwen3_oracle_14b_corrective_v6_abi_precision_oracle_main_stz_long_address`; preview: Why does `STZ $7E2000,X` fail to assemble? Show two correct fixes.  A previous answer still failed this Oracle-main capability check: ```text <think>  </think>  `STZ` does not have
- count `60`, unique prompts `5`, splits `{'train': 60}`, buckets `{'abi_and_width_contracts': 60}`; samples `qwen3_oracle_14b_corrective_v6_abi_precision_oracle_main_v2_rep20_store_then_flag`, `qwen3_oracle_14b_corrective_v6_rewrite_oracle_main_v2_rep20_store_then_flag`, `qwen3_oracle_14b_corrective_v6_direct_oracle_main_v2_rep20_store_then_flag`, `qwen3_oracle_14b_corrective_v6_score_gap_oracle_main_v2_rep20_store_then_flag`, `qwen3_oracle_14b_corrective_v6_rewrite_oracle_main_v2_rep20_store_then_flag`; preview: Inside a `REP #$20` region, why is it unsafe to do 8-bit flag logic before the replaced 16-bit store, and what is the safe pattern?  A previous answer was still too fuzzy about the
- count `50`, unique prompts `5`, splits `{'train': 50}`, buckets `{'debug_capture_and_triage': 50}`; samples `qwen3_oracle_14b_corrective_v6_score_gap_oracle_main_v2_capture_assert_jtl`, `qwen3_oracle_14b_corrective_v6_capture_first_oracle_main_v2_capture_assert_jtl`, `qwen3_oracle_14b_corrective_v6_rewrite_oracle_main_v2_capture_assert_jtl`, `qwen3_oracle_14b_corrective_v6_rewrite_oracle_main_v2_capture_assert_jtl`, `qwen3_oracle_14b_corrective_v6_direct_oracle_main_v2_capture_assert_jtl`; preview: When should you use `capture_blackout.py arm --assert-jtl`, and what does it help prove?  A previous answer missed the scorer on these exact points: - include one of: `upstream` /
- count `5`, unique prompts `1`, splits `{'train': 4, 'val': 1}`, buckets `{'hardware_register_grounding': 5}`; samples `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_mdmaen_vs_hdmaen`, `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_mdmaen_vs_hdmaen`, `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_mdmaen_vs_hdmaen`, `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_mdmaen_vs_hdmaen`, `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_mdmaen_vs_hdmaen_val_anchor`; preview: Explain what $420B (MDMAEN) and $420C (HDMAEN) do and when you would use each.  Answer concretely and preserve the exact contract details that make this Oracle-main answer pass. -
- count `4`, unique prompts `1`, splits `{'train': 4}`, buckets `{'debug_capture_and_triage': 4}`; samples `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_v2_darkroom_capture_order`, `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_v2_darkroom_capture_order`, `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_v2_darkroom_capture_order`, `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_v2_darkroom_capture_order`; preview: A dark-room transition blacks out. What should you capture first, and why is that better than blind spotlight patching?  Answer concretely and preserve the exact contract details t
- count `4`, unique prompts `1`, splits `{'train': 4}`, buckets `{'abi_and_width_contracts': 4}`; samples `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_v2_torch_loop_return_path`, `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_v2_torch_loop_return_path`, `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_v2_torch_loop_return_path`, `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_v2_torch_loop_return_path`; preview: A hook does `SEP #$30` and then `JML $0188C9` back into the vanilla torch loop. Why can that black-screen even if the code assembles?  Answer concretely and preserve the exact cont

Top eval overlaps:
- prompt `evals/oracle_main_capability_eval_v1.jsonl`: 34
- prompt `evals/oracle_main_grounded_eval_v2.jsonl`: 22
- prompt `evals/oracle_main_grounded_eval_v1.jsonl`: 12
- answer `evals/oracle_main_capability_eval_v1.jsonl`: 201
- answer `evals/oracle_main_grounded_eval_v2.jsonl`: 125
- answer `evals/oracle_main_grounded_eval_v1.jsonl`: 76

Overlap examples:
- `answer` with `evals/oracle_main_capability_eval_v1.jsonl` via row `qwen3_oracle_14b_corrective_v6_rewrite_oracle_main_stz_long_address`
- `answer` with `evals/oracle_main_grounded_eval_v1.jsonl` via row `qwen3_oracle_14b_corrective_v6_rewrite_oracle_main_stz_long_address`
- `answer` with `evals/oracle_main_capability_eval_v1.jsonl` via row `qwen3_oracle_14b_corrective_v6_score_gap_oracle_main_v2_capture_assert_jtl`
- `answer` with `evals/oracle_main_grounded_eval_v2.jsonl` via row `qwen3_oracle_14b_corrective_v6_score_gap_oracle_main_v2_capture_assert_jtl`
- `answer` with `evals/oracle_main_capability_eval_v1.jsonl` via row `qwen3_oracle_14b_corrective_v6_capture_first_oracle_main_v2_capture_assert_jtl`
- `answer` with `evals/oracle_main_grounded_eval_v2.jsonl` via row `qwen3_oracle_14b_corrective_v6_capture_first_oracle_main_v2_capture_assert_jtl`
- `answer` with `evals/oracle_main_capability_eval_v1.jsonl` via row `qwen3_oracle_14b_corrective_v6_protective_anchor_oracle_main_zso_time_system`
- `answer` with `evals/oracle_main_grounded_eval_v1.jsonl` via row `qwen3_oracle_14b_corrective_v6_protective_anchor_oracle_main_zso_time_system`

### `oracle_repo_code_v3`

- Path: `/Users/scawful/src/training/datasets/oracle_repo_code_v3`
- Rows: `1296`; unique row payloads: `202`; duplicate row pressure: `84.4%`
- Unique prompts: `196`; prompt duplicate pressure: `84.9%`
- Unique answers: `120`
- Split content overlap: `{'train/val': 0, 'train/test': 2, 'val/test': 0}`
- Split prompt overlap: `{'train/val': 1, 'train/test': 1, 'val/test': 0}`

Tool surface:
- `prose-only`: 1296

Bucket counts (expanded rows):
- `compile_grounding`: 490
- `code_repair`: 480
- `repo_retrieval`: 326

Bucket unique row counts:
- `code_repair`: 89
- `compile_grounding`: 71
- `repo_retrieval`: 42

Role counts:
- `unspecified`: 1296

Style counts:
- `unspecified`: 1296

Examples by bucket:
- `code_repair`: `oracle_coder_corrective_v2_asar_clean_oracle_code_repair_v2_03`, `code_repair_fe15000230c1ef3d`, `oracle_coder_corrective_v2_rewrite_oracle_code_repair_02`, `code_repair_9b63b8f6503717cb`
- `compile_grounding`: `oracle_coder_corrective_v2_asar_clean_oracle_compile_grounding_v2_01`, `oracle_coder_corrective_v2_asar_clean_oracle_compile_grounding_bea6670e75fbd132`, `oracle_coder_corrective_v2_asar_clean_oracle_compile_grounding_v2_05`, `oracle_coder_corrective_v2_direct_oracle_compile_grounding_v2_01`
- `repo_retrieval`: `oracle_coder_corrective_v2_rewrite_oracle_repo_retrieval_v2_02`, `oracle_coder_corrective_v2_rewrite_oracle_repo_retrieval_03`, `oracle_coder_corrective_v2_direct_oracle_repo_retrieval_v2_04`, `oracle_coder_corrective_v2_exact_path_oracle_repo_retrieval_03`

Largest prompt-family clusters:
- count `108`, unique prompts `5`, splits `{'train': 104, 'test': 4}`, buckets `{'compile_grounding': 108}`; samples `oracle_coder_corrective_v2_asar_clean_oracle_compile_grounding_bea6670e75fbd132`, `oracle_coder_corrective_v2_direct_oracle_compile_grounding_9aaddd0341d33fc8`, `oracle_coder_corrective_v2_rewrite_oracle_compile_grounding_9aaddd0341d33fc8`, `oracle_coder_corrective_direct_oracle_compile_grounding_bea6670e75fbd132`, `oracle_coder_corrective_v2_rewrite_oracle_compile_grounding_9aaddd0341d33fc8`; preview: Write a 65816 routine that (Using Oracle of Secrets symbols).  A previous answer failed under the assembler: ```text ```asm ; ======================================================
- count `52`, unique prompts `4`, splits `{'train': 52}`, buckets `{'repo_retrieval': 52}`; samples `oracle_coder_corrective_v2_rewrite_oracle_repo_retrieval_03`, `oracle_coder_corrective_v2_exact_path_oracle_repo_retrieval_03`, `oracle_coder_corrective_v2_direct_oracle_repo_retrieval_03`, `oracle_coder_corrective_direct_oracle_repo_retrieval_03`, `oracle_coder_corrective_v2_rewrite_oracle_repo_retrieval_03`; preview: Use the file map below.  [File A] Docs/Technical/MemoryMap.md Explains active labels vs stale UNUSED comments.  [File B] Core/sram_progress.asm Implements custom progression fields
- count `52`, unique prompts `4`, splits `{'train': 52}`, buckets `{'repo_retrieval': 52}`; samples `oracle_coder_corrective_rewrite_oracle_repo_retrieval_06`, `oracle_coder_corrective_v2_rewrite_oracle_repo_retrieval_06`, `oracle_coder_corrective_v2_exact_path_oracle_repo_retrieval_06`, `oracle_coder_corrective_rewrite_oracle_repo_retrieval_06`, `oracle_coder_corrective_v2_direct_oracle_repo_retrieval_06`; preview: Repository sketch:  [File A] datasets/sources/oracle_harness_awareness_v1.jsonl Tool-activation and identity repairs.  [File B] scripts/build_qwen35_oracle_fast_v2_dataset.py Build
- count `42`, unique prompts `4`, splits `{'train': 42}`, buckets `{'code_repair': 42}`; samples `oracle_coder_corrective_v2_rewrite_oracle_code_repair_06`, `oracle_coder_corrective_v2_asar_clean_oracle_code_repair_06`, `oracle_coder_corrective_direct_oracle_code_repair_06`, `oracle_coder_corrective_v2_asar_clean_oracle_code_repair_06`, `oracle_coder_corrective_v2_asar_clean_oracle_code_repair_06`; preview: Repair the hook body below.  ```asm MagicBeanAdvance:     lda MagicBeanProg     inc     sta MagicBeanProg     rtl ```  Problem: `MagicBeanProg` is structured quest state and must n
- count `42`, unique prompts `4`, splits `{'train': 42}`, buckets `{'code_repair': 42}`; samples `oracle_coder_corrective_v2_asar_clean_oracle_code_repair_04`, `oracle_coder_corrective_v2_rewrite_oracle_code_repair_04`, `oracle_coder_corrective_v2_asar_clean_oracle_code_repair_04`, `oracle_coder_corrective_direct_oracle_code_repair_04`, `oracle_coder_corrective_v2_asar_clean_oracle_code_repair_04`; preview: Repair the logic below.  ```asm MaybeSkipDecompress:     lda TransGFXModule_PriorSheets     cmp CurrentSheetGroup     beq .skip     jsl DecompressCurrentSheets .skip     rtl ```  P
- count `39`, unique prompts `3`, splits `{'train': 39}`, buckets `{'compile_grounding': 39}`; samples `oracle_coder_corrective_v2_direct_oracle_compile_grounding_01bf680436b51de6`, `oracle_coder_corrective_v2_rewrite_oracle_compile_grounding_01bf680436b51de6`, `oracle_coder_corrective_v2_rewrite_oracle_compile_grounding_01bf680436b51de6`, `oracle_coder_corrective_v2_direct_oracle_compile_grounding_01bf680436b51de6`, `oracle_coder_corrective_v2_rewrite_oracle_compile_grounding_01bf680436b51de6`; preview: Write a 65816 routine named Palette_ArbitraryLoad.

Top eval overlaps:
- prompt `evals/oracle_compile_grounding_eval_v1.jsonl`: 100
- prompt `evals/oracle_repo_retrieval_eval_v1.jsonl`: 68
- prompt `evals/oracle_code_repair_eval_v1.jsonl`: 52
- prompt `evals/oracle_compile_grounding_eval_v2.jsonl`: 48
- prompt `evals/oracle_code_repair_eval_v2.jsonl`: 40
- answer `evals/oracle_main_capability_eval_v1.jsonl`: 48
- answer `evals/oracle_main_grounded_eval_v1.jsonl`: 48

Overlap examples:
- `prompt` with `evals/oracle_repo_retrieval_eval_v2.jsonl` via row `oracle_coder_corrective_v2_direct_oracle_repo_retrieval_v2_04`
- `prompt` with `evals/oracle_compile_grounding_eval_v2.jsonl` via row `oracle_coder_corrective_v2_direct_oracle_compile_grounding_v2_01`
- `prompt` with `evals/oracle_compile_grounding_eval_v1.jsonl` via row `oracle_coder_corrective_v2_direct_oracle_compile_grounding_01bf680436b51de6`
- `prompt` with `evals/oracle_repo_retrieval_eval_v1.jsonl` via row `oracle_coder_corrective_v2_direct_oracle_repo_retrieval_03`
- `prompt` with `evals/oracle_compile_grounding_eval_v1.jsonl` via row `oracle_coder_corrective_v2_direct_oracle_compile_grounding_007c5c554e7799f5`
- `prompt` with `evals/oracle_compile_grounding_eval_v1.jsonl` via row `oracle_coder_corrective_v2_direct_oracle_compile_grounding_007c5c554e7799f5`
- `prompt` with `evals/oracle_code_repair_eval_v1.jsonl` via row `oracle_coder_corrective_direct_oracle_code_repair_06`
- `prompt` with `evals/oracle_repo_retrieval_eval_v1.jsonl` via row `oracle_coder_corrective_direct_oracle_repo_retrieval_02`

### `oracle_fast_4b_candidate_v1`

- Path: `/Users/scawful/src/training/datasets/oracle_fast_4b_candidate_v1`
- Rows: `2049`; unique row payloads: `250`; duplicate row pressure: `87.8%`
- Unique prompts: `128`; prompt duplicate pressure: `93.8%`
- Unique answers: `236`
- Split content overlap: `{'train/val': 0, 'train/test': 0, 'val/test': 0}`
- Split prompt overlap: `{'train/val': 14, 'train/test': 16, 'val/test': 4}`

Tool surface:
- `tool-role-transcript`: 1810
- `prose-only`: 142
- `prose-tool-context`: 97

Bucket counts (expanded rows):
- `unbucketed`: 1068
- `chain`: 405
- `oracle-fast-corrective3`: 315
- `domain`: 261

Bucket unique row counts:
- `unbucketed`: 100
- `chain`: 92
- `domain`: 44
- `oracle-fast-corrective3`: 14

Role counts:
- `unspecified`: 2049

Style counts:
- `unspecified`: 2049

Examples by bucket:
- `chain`: `156cfd7f-16ec-4128-ae31-8936c2028ce1`, `930d5555-d939-4e84-9a5f-828e8e2805c8`, `1f985df7-ae93-4da8-9213-f865ffbdaf54`, `386bc257-1a03-4ee0-af4a-d33aae2404dc`
- `domain`: `a6e43db0-4280-47d7-9268-953c8fb14fae`, `7764764b-9f1d-4c64-ac62-ef5007c7a71f`, `3493b612-97fc-48ac-a158-f19d80e6c0e5`, `1389a10b-e9c6-4296-a774-fe840968644d`
- `oracle-fast-corrective3`: `train.jsonl:9`, `train.jsonl:12`, `train.jsonl:14`, `train.jsonl:20`
- `unbucketed`: `train.jsonl:1`, `train.jsonl:3`, `train.jsonl:5`, `train.jsonl:7`

Largest prompt-family clusters:
- count `52`, unique prompts `1`, splits `{'train': 52}`, buckets `{'oracle-fast-corrective3': 36, 'unbucketed': 16}`; samples `train.jsonl:14`, `train.jsonl:45`, `train.jsonl:48`, `train.jsonl:53`, `train.jsonl:74`; preview: Debug a crash: first read the current CPU state, then set a breakpoint at the crash point, then step through 3 instructions.
- count `52`, unique prompts `1`, splits `{'train': 52}`, buckets `{'oracle-fast-corrective3': 36, 'unbucketed': 16}`; samples `train.jsonl:32`, `train.jsonl:102`, `train.jsonl:134`, `train.jsonl:160`, `train.jsonl:262`; preview: The game crashes in room 0xB8. Inspect the room, then check the sprite list, then read Link's position.
- count `52`, unique prompts `1`, splits `{'train': 52}`, buckets `{'oracle-fast-corrective3': 36, 'unbucketed': 16}`; samples `train.jsonl:66`, `train.jsonl:69`, `train.jsonl:104`, `train.jsonl:106`, `train.jsonl:111`; preview: Audit room 0x45: inspect the room layout, validate hooks used in it, then run ROM doctor.
- count `46`, unique prompts `1`, splits `{'train': 46}`, buckets `{'oracle-fast-corrective3': 30, 'unbucketed': 16}`; samples `train.jsonl:7`, `train.jsonl:33`, `train.jsonl:133`, `train.jsonl:248`, `train.jsonl:288`; preview: Explain how the A register width affects LDA in different processor modes. When should I use SEP vs REP?
- count `46`, unique prompts `1`, splits `{'train': 46}`, buckets `{'oracle-fast-corrective3': 30, 'unbucketed': 16}`; samples `train.jsonl:9`, `train.jsonl:20`, `train.jsonl:31`, `train.jsonl:59`, `train.jsonl:109`; preview: How does the original game determine which palette to use for each overworld area?
- count `46`, unique prompts `1`, splits `{'train': 46}`, buckets `{'oracle-fast-corrective3': 30, 'unbucketed': 16}`; samples `train.jsonl:12`, `train.jsonl:15`, `train.jsonl:117`, `train.jsonl:140`, `train.jsonl:147`; preview: I want to add a crystal switch toggle to a dungeon room. What subsystems are involved?

Top eval overlaps:
- none

### `oracle_9b_candidate_v1`

- Path: `/Users/scawful/src/training/datasets/oracle_9b_candidate_v1`
- Rows: `37642`; unique row payloads: `32092`; duplicate row pressure: `14.7%`
- Unique prompts: `10391`; prompt duplicate pressure: `72.4%`
- Unique answers: `11841`
- Split content overlap: `{'train/val': 4, 'train/test': 5, 'val/test': 1}`
- Split prompt overlap: `{'train/val': 2888, 'train/test': 3405, 'val/test': 1645}`

Tool surface:
- `prose-only`: 28250
- `native-tool-calls`: 5695
- `tool-role-transcript`: 3504
- `prose-tool-context`: 193

Bucket counts (expanded rows):
- `unbucketed`: 34202
- `chain`: 790
- `oracle_docs_and_system_reasoning`: 592
- `domain`: 510
- `abi_and_width_contracts`: 399
- `uncertainty_and_scope_control`: 377
- `oracle-main-corrective`: 324
- `debug_capture_and_triage`: 208

Bucket unique row counts:
- `unbucketed`: 31879
- `chain`: 91
- `domain`: 43
- `oracle-main-corrective`: 27
- `abi_and_width_contracts`: 18
- `oracle_docs_and_system_reasoning`: 13
- `uncertainty_and_scope_control`: 11
- `debug_capture_and_triage`: 9

Role counts:
- `unspecified`: 37642

Style counts:
- `unspecified`: 35826
- `rewrite`: 436
- `contract`: 436
- `direct`: 436
- `docs_chain`: 218
- `anchor_direct`: 132

Examples by bucket:
- `abi_and_width_contracts`: `qwen3_oracle_14b_corrective_v2_contract_oracle_main_jsr_rtl_mismatch`, `qwen3_oracle_14b_corrective_v2_contract_oracle_main_jsr_rtl_mismatch`, `qwen3_oracle_14b_corrective_v2_contract_oracle_main_v2_jumptablelocal_sep10`, `qwen3_oracle_14b_corrective_v2_contract_oracle_main_v2_jumptablelocal_sep10`
- `chain`: `19fe80bb-cb06-4140-be1d-bc5c272e1dc7`, `6e37f1b6-af6f-4979-a660-7b6422a025af`, `7f64ba16-fe55-43a3-9d6f-aee7ed3210d5`, `8f79607d-6a09-4151-9a87-71fae54b2f22`
- `debug_capture_and_triage`: `qwen3_oracle_14b_corrective_v2_rewrite_oracle_main_v2_capture_assert_jtl`, `qwen3_oracle_14b_corrective_v2_contract_oracle_main_v2_capture_assert_jtl`, `qwen3_oracle_14b_corrective_v2_contract_oracle_main_v2_capture_assert_jtl`, `qwen3_oracle_14b_corrective_v2_capture_first_oracle_main_v2_capture_assert_jtl`
- `domain`: `ad3e2bb4-a938-450f-9562-edcacb3b4f28`, `7da58f0e-5e7b-48a1-a257-0860e53d65da`, `a6e43db0-4280-47d7-9268-953c8fb14fae`, `a6ef33db-0d53-4c69-bd6e-c6b6ed57cd9f`
- `hardware_register_grounding`: `qwen3_oracle_14b_corrective_v2_contract_oracle_main_mdmaen_vs_hdmaen`, `qwen3_oracle_14b_corrective_v2_direct_oracle_main_mdmaen_vs_hdmaen`, `qwen3_oracle_14b_corrective_v2_direct_oracle_main_mdmaen_vs_hdmaen`, `qwen3_oracle_14b_corrective_v2_rewrite_oracle_main_mdmaen_vs_hdmaen`
- `hook_safety_and_authoring`: `qwen3_oracle_14b_corrective_v2_contract_oracle_main_v2_hook_stub_overwritten_logic`, `qwen3_oracle_14b_corrective_v2_rewrite_oracle_main_v2_hook_stub_overwritten_logic`, `qwen3_oracle_14b_corrective_v2_hook_precision_oracle_main_v2_hook_stub_overwritten_logic`, `qwen3_oracle_14b_corrective_v2_hook_precision_oracle_main_v2_hook_stub_overwritten_logic`
- `oracle-main-corrective`: `qwen3_oracle_14b_corrective_v1_direct_oracle_main_rep20_hook_contract`, `qwen3_oracle_14b_corrective_v1_rewrite_oracle_main_do_not_invent_symbols`, `qwen3_oracle_14b_corrective_v1_rewrite_oracle_main_do_not_invent_symbols`, `qwen3_oracle_14b_corrective_v1_direct_oracle_main_songbank_blackout`
- `oracle_docs_and_system_reasoning`: `qwen3_oracle_14b_corrective_v2_rewrite_oracle_main_v2_songbank_wait_loop`, `qwen3_oracle_14b_corrective_v2_rewrite_oracle_main_v2_songbank_wait_loop`, `qwen3_oracle_14b_corrective_v2_contract_oracle_main_zso_time_system`, `qwen3_oracle_14b_corrective_v2_direct_oracle_main_v2_songbank_wait_loop`
- `unbucketed`: `train.jsonl:1`, `train.jsonl:2`, `train.jsonl:4`, `train.jsonl:5`
- `uncertainty_and_scope_control`: `qwen3_oracle_14b_corrective_v2_docs_chain_oracle_main_v2_no_bank_guess`, `qwen3_oracle_14b_corrective_v2_rewrite_oracle_main_v2_no_bank_guess`, `qwen3_oracle_14b_corrective_v2_rewrite_oracle_main_v2_no_bank_guess`, `qwen3_oracle_14b_corrective_v2_docs_chain_oracle_main_v2_no_bank_guess`

Largest prompt-family clusters:
- count `3383`, unique prompts `1`, splits `{'train': 1835, 'val': 676, 'test': 872}`, buckets `{'unbucketed': 3383}`; samples `train.jsonl:32`, `train.jsonl:42`, `train.jsonl:48`, `train.jsonl:49`, `train.jsonl:54`; preview: Write a 65816 routine that (Using Oracle of Secrets symbols).
- count `1752`, unique prompts `721`, splits `{'train': 904, 'val': 395, 'test': 453}`, buckets `{'unbucketed': 1752}`; samples `train.jsonl:7`, `train.jsonl:26`, `train.jsonl:27`, `train.jsonl:156`, `train.jsonl:247`; preview: Write a 65816 routine that ; *$29DD6-$29E65 JUMP LOCATION.
- count `1337`, unique prompts `551`, splits `{'train': 693, 'val': 278, 'test': 366}`, buckets `{'unbucketed': 1337}`; samples `train.jsonl:61`, `train.jsonl:85`, `train.jsonl:86`, `train.jsonl:121`, `train.jsonl:148`; preview: Write a 65816 routine that *$103C7-$10569 LOCAL.
- count `951`, unique prompts `391`, splits `{'train': 502, 'val': 196, 'test': 253}`, buckets `{'unbucketed': 951}`; samples `train.jsonl:103`, `train.jsonl:197`, `train.jsonl:223`, `train.jsonl:258`, `train.jsonl:261`; preview: Write a 65816 routine that ; *$D748-$D7BF LONG.
- count `488`, unique prompts `167`, splits `{'train': 259, 'val': 101, 'test': 128}`, buckets `{'unbucketed': 488}`; samples `train.jsonl:6`, `train.jsonl:14`, `train.jsonl:74`, `train.jsonl:251`, `train.jsonl:269`; preview: Write a 65816 routine that =================================================================================================== TODO ================================================
- count `360`, unique prompts `5`, splits `{'train': 360}`, buckets `{'uncertainty_and_scope_control': 360}`; samples `qwen3_oracle_14b_corrective_v2_docs_chain_oracle_main_v2_no_bank_guess`, `qwen3_oracle_14b_corrective_v2_rewrite_oracle_main_v2_no_bank_guess`, `qwen3_oracle_14b_corrective_v2_rewrite_oracle_main_v2_no_bank_guess`, `qwen3_oracle_14b_corrective_v2_docs_chain_oracle_main_v2_no_bank_guess`, `qwen3_oracle_14b_corrective_v2_refusal_boundary_oracle_main_v2_no_bank_guess`; preview: The blackout notes mention a `LoadSongBank` handshake wait loop. Which bank is the exact internal routine label in?  A previous answer drifted away from the documented Oracle evide

Top eval overlaps:
- prompt `evals/oracle_compile_grounding_eval_v1.jsonl`: 3396
- prompt `evals/oracle_main_capability_eval_v1.jsonl`: 700
- prompt `evals/oracle_main_grounded_eval_v1.jsonl`: 372
- prompt `evals/oracle_main_grounded_eval_v2.jsonl`: 328
- prompt `evals/oracle_tool_use_eval_v1.jsonl`: 27
- answer `evals/oracle_main_capability_eval_v1.jsonl`: 2176
- answer `evals/oracle_main_grounded_eval_v2.jsonl`: 1240
- answer `evals/oracle_main_grounded_eval_v1.jsonl`: 936

Overlap examples:
- `answer` with `evals/oracle_main_capability_eval_v1.jsonl` via row `qwen3_oracle_14b_corrective_v2_rewrite_oracle_main_v2_songbank_wait_loop`
- `answer` with `evals/oracle_main_grounded_eval_v2.jsonl` via row `qwen3_oracle_14b_corrective_v2_rewrite_oracle_main_v2_songbank_wait_loop`
- `answer` with `evals/oracle_main_capability_eval_v1.jsonl` via row `qwen3_oracle_14b_corrective_v2_contract_oracle_main_jsr_rtl_mismatch`
- `answer` with `evals/oracle_main_grounded_eval_v1.jsonl` via row `qwen3_oracle_14b_corrective_v2_contract_oracle_main_jsr_rtl_mismatch`
- `answer` with `evals/oracle_main_capability_eval_v1.jsonl` via row `qwen3_oracle_14b_corrective_v2_docs_chain_oracle_main_v2_no_bank_guess`
- `answer` with `evals/oracle_main_grounded_eval_v2.jsonl` via row `qwen3_oracle_14b_corrective_v2_docs_chain_oracle_main_v2_no_bank_guess`
- `prompt` with `evals/oracle_main_capability_eval_v1.jsonl` via row `qwen3_oracle_14b_corrective_v1_direct_oracle_main_rep20_hook_contract`
- `prompt` with `evals/oracle_main_grounded_eval_v1.jsonl` via row `qwen3_oracle_14b_corrective_v1_direct_oracle_main_rep20_hook_contract`

### `oracle_longctx_v1`

- Path: `/Users/scawful/src/training/datasets/oracle_longctx_v1`
- Rows: `544`; unique row payloads: `160`; duplicate row pressure: `70.6%`
- Unique prompts: `160`; prompt duplicate pressure: `70.6%`
- Unique answers: `30`
- Split content overlap: `{'train/val': 0, 'train/test': 0, 'val/test': 0}`
- Split prompt overlap: `{'train/val': 0, 'train/test': 0, 'val/test': 0}`

Tool surface:
- `prose-only`: 496
- `prose-tool-context`: 48

Bucket counts (expanded rows):
- `lost_in_middle`: 168
- `multi_file_synthesis`: 136
- `tool_transcript_grounding`: 136
- `evidence_extraction`: 104

Bucket unique row counts:
- `lost_in_middle`: 40
- `multi_file_synthesis`: 40
- `evidence_extraction`: 40
- `tool_transcript_grounding`: 40

Role counts:
- `unspecified`: 544

Style counts:
- `unspecified`: 544

Examples by bucket:
- `evidence_extraction`: `oracle_longctx_docs_identity_2`, `oracle_longctx_docs_scrolls_bitfield_3`, `oracle_longctx_docs_transgfx_cache_3`, `oracle_longctx_docs_active_label_2`
- `lost_in_middle`: `oracle_longctx_lostmiddle_code_red_3`, `oracle_longctx_lostmiddle_palette_pipeline_1`, `oracle_longctx_lostmiddle_active_label_2`, `oracle_longctx_lostmiddle_palette_pipeline_4`
- `multi_file_synthesis`: `oracle_longctx_synth_synth_debug_evidence_3`, `oracle_longctx_synth_synth_namespace_hooks_2`, `oracle_longctx_synth_synth_gate_reason_3`, `oracle_longctx_synth_synth_debug_evidence_4`
- `tool_transcript_grounding`: `oracle_longctx_transcript_tx_scrolls_4`, `oracle_longctx_transcript_tx_gate_14b_3`, `oracle_longctx_transcript_tx_gate_14b_3`, `oracle_longctx_transcript_tx_code_red_1`

Largest prompt-family clusters:
- count `5`, unique prompts `1`, splits `{'train': 5}`, buckets `{'lost_in_middle': 5}`; samples `oracle_longctx_lostmiddle_code_red_3`, `oracle_longctx_lostmiddle_code_red_3`, `oracle_longctx_lostmiddle_code_red_3`, `oracle_longctx_lostmiddle_code_red_3`, `oracle_longctx_lostmiddle_code_red_3`; preview: Use only the context below.  [Noise] Front-loaded notes discuss old smoke tests and stale launch commands.  [Middle evidence] CODE RED means repro-state integrity failed, so save-s
- count `5`, unique prompts `1`, splits `{'train': 5}`, buckets `{'lost_in_middle': 5}`; samples `oracle_longctx_lostmiddle_palette_pipeline_1`, `oracle_longctx_lostmiddle_palette_pipeline_1`, `oracle_longctx_lostmiddle_palette_pipeline_1`, `oracle_longctx_lostmiddle_palette_pipeline_1`, `oracle_longctx_lostmiddle_palette_pipeline_1`; preview: Use only the context below.  [Noise] Older export notes, benchmark scraps, and unrelated rollout reminders appear first.  [Middle evidence] ZSCustomOverworld chooses the area's bas
- count `5`, unique prompts `1`, splits `{'train': 5}`, buckets `{'lost_in_middle': 5}`; samples `oracle_longctx_lostmiddle_active_label_2`, `oracle_longctx_lostmiddle_active_label_2`, `oracle_longctx_lostmiddle_active_label_2`, `oracle_longctx_lostmiddle_active_label_2`, `oracle_longctx_lostmiddle_active_label_2`; preview: Use only the context below.  [Noise] Legacy router notes and archived quantization chatter appear first but do not answer the question.  [Middle evidence] If an Oracle doc shows bo
- count `5`, unique prompts `1`, splits `{'train': 5}`, buckets `{'lost_in_middle': 5}`; samples `oracle_longctx_lostmiddle_palette_pipeline_4`, `oracle_longctx_lostmiddle_palette_pipeline_4`, `oracle_longctx_lostmiddle_palette_pipeline_4`, `oracle_longctx_lostmiddle_palette_pipeline_4`, `oracle_longctx_lostmiddle_palette_pipeline_4`; preview: Use only the context below.  [Noise] The first section is intentionally distracting and not relevant to the answer.  [Middle evidence] ZSCustomOverworld chooses the area's base pal
- count `5`, unique prompts `1`, splits `{'train': 5}`, buckets `{'lost_in_middle': 5}`; samples `oracle_longctx_lostmiddle_code_red_2`, `oracle_longctx_lostmiddle_code_red_2`, `oracle_longctx_lostmiddle_code_red_2`, `oracle_longctx_lostmiddle_code_red_2`, `oracle_longctx_lostmiddle_code_red_2`; preview: Use only the context below.  [Noise] Legacy router notes and archived quantization chatter appear first but do not answer the question.  [Middle evidence] CODE RED means repro-stat
- count `5`, unique prompts `1`, splits `{'train': 5}`, buckets `{'lost_in_middle': 5}`; samples `oracle_longctx_lostmiddle_transgfx_cache_4`, `oracle_longctx_lostmiddle_transgfx_cache_4`, `oracle_longctx_lostmiddle_transgfx_cache_4`, `oracle_longctx_lostmiddle_transgfx_cache_4`, `oracle_longctx_lostmiddle_transgfx_cache_4`; preview: Use only the context below.  [Noise] The first section is intentionally distracting and not relevant to the answer.  [Middle evidence] The advanced ZScream docs describe a transiti

Top eval overlaps:
- none

### `oracle_longctx_dpo_v1`

- Path: `/Users/scawful/src/training/datasets/oracle_longctx_dpo_v1`
- Rows: `544`; unique row payloads: `160`; duplicate row pressure: `70.6%`
- Unique prompts: `160`; prompt duplicate pressure: `70.6%`
- Unique answers: `40`
- Split content overlap: `{'train/val': 0, 'train/test': 0, 'val/test': 0}`
- Split prompt overlap: `{'train/val': 0, 'train/test': 0, 'val/test': 0}`

Tool surface:
- `prose-only`: 496
- `prose-tool-context`: 48

Bucket counts (expanded rows):
- `lost_middle`: 168
- `tool_transcripts`: 136
- `multifile_synthesis`: 136
- `grounding`: 104

Bucket unique row counts:
- `lost_middle`: 40
- `tool_transcripts`: 40
- `multifile_synthesis`: 40
- `grounding`: 40

Role counts:
- `unspecified`: 544

Style counts:
- `unspecified`: 544

Examples by bucket:
- `grounding`: `train.jsonl:9`, `train.jsonl:12`, `train.jsonl:17`, `train.jsonl:24`
- `lost_middle`: `train.jsonl:1`, `train.jsonl:2`, `train.jsonl:11`, `train.jsonl:16`
- `multifile_synthesis`: `train.jsonl:4`, `train.jsonl:5`, `train.jsonl:6`, `train.jsonl:10`
- `tool_transcripts`: `train.jsonl:3`, `train.jsonl:7`, `train.jsonl:8`, `train.jsonl:14`

Largest prompt-family clusters:
- count `5`, unique prompts `1`, splits `{'train': 5}`, buckets `{'lost_middle': 5}`; samples `train.jsonl:1`, `train.jsonl:246`, `train.jsonl:328`, `train.jsonl:383`, `train.jsonl:442`; preview: Use only the context below.  [Noise] Front-loaded notes discuss old smoke tests and stale launch commands.  [Middle evidence] CODE RED means repro-state integrity failed, so save-s
- count `5`, unique prompts `1`, splits `{'train': 5}`, buckets `{'lost_middle': 5}`; samples `train.jsonl:2`, `train.jsonl:245`, `train.jsonl:284`, `train.jsonl:297`, `train.jsonl:332`; preview: Use only the context below.  [Noise] Older export notes, benchmark scraps, and unrelated rollout reminders appear first.  [Middle evidence] ZSCustomOverworld chooses the area's bas
- count `5`, unique prompts `1`, splits `{'train': 5}`, buckets `{'lost_middle': 5}`; samples `train.jsonl:11`, `train.jsonl:124`, `train.jsonl:158`, `train.jsonl:209`, `train.jsonl:277`; preview: Use only the context below.  [Noise] The first section is intentionally distracting and not relevant to the answer.  [Middle evidence] The advanced ZScream docs describe a transiti
- count `5`, unique prompts `1`, splits `{'train': 5}`, buckets `{'lost_middle': 5}`; samples `train.jsonl:16`, `train.jsonl:19`, `train.jsonl:255`, `train.jsonl:376`, `train.jsonl:448`; preview: Use only the context below.  [Noise] Front-loaded notes discuss old smoke tests and stale launch commands.  [Middle evidence] The smaller corrective should stay on the critical pat
- count `5`, unique prompts `1`, splits `{'train': 5}`, buckets `{'lost_middle': 5}`; samples `train.jsonl:22`, `train.jsonl:127`, `train.jsonl:128`, `train.jsonl:154`, `train.jsonl:359`; preview: Use only the context below.  [Noise] Older export notes, benchmark scraps, and unrelated rollout reminders appear first.  [Middle evidence] If an Oracle doc shows both an active la
- count `5`, unique prompts `1`, splits `{'train': 5}`, buckets `{'lost_middle': 5}`; samples `train.jsonl:26`, `train.jsonl:48`, `train.jsonl:87`, `train.jsonl:93`, `train.jsonl:365`; preview: Use only the context below.  [Noise] Front-loaded notes discuss old smoke tests and stale launch commands.  [Middle evidence] If an Oracle doc shows both an active label and an `UN

Top eval overlaps:
- none

## Training And Prompt Implications

- Treat eval-overlapping packs as regression suites. Promotion needs fresh prompts or adversarial variants that are not represented in train rows.
- Where duplicate pressure is high, keep metadata-driven weights explicit and cap any bucket that starts regressing previously repaired surfaces.
- Add real deployed-format tool transcripts for Oracle-family models that must learn chain continuation; prose-only rows teach facts but not agent behavior.
- Keep `oracle-coder` rows code/retrieval/compile-focused. Do not blend broad Oracle explanation rows into that worker unless an eval proves it helps.
- For system prompts, prefer short branch rules that mirror the data: ground first, preserve failed-grounding uncertainty, delegate authoring to `oracle-coder`, then verify.
