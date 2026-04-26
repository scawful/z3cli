# Oracle Training Data Audit

Generated: 2026-04-25
Training root: `/Users/scawful/src/training`
Eval files indexed: `23`

## Executive Findings

- `qwen3_oracle_14b_v7_capped3` is heavily weighted by duplication (42/65 duplicate rows, 64.6%). Keep this only when each weight maps to a measured failure bucket.
- `qwen3_oracle_14b_v7_capped3` has tiny validation/test splits (val 1, test 1); treat them as smoke checks, not promotion gates.
- `qwen3_oracle_14b_v7_capped3` has no actual tool-call transcript rows. If this trains a tool-using Oracle lane, add deployed-format tool call/result/final-answer examples.
- `qwen3_oracle_14b_v7_capped3` overlaps Oracle eval material (prompt rows 18, answer rows 130). Use those evals as regression checks and keep a fresh holdout for promotion.
- `oracle_repo_code_v3_capped3` is heavily weighted by duplication (352/554 duplicate rows, 63.5%). Keep this only when each weight maps to a measured failure bucket.
- `oracle_repo_code_v3_capped3` has no actual tool-call transcript rows. If this trains a tool-using Oracle lane, add deployed-format tool call/result/final-answer examples.
- `oracle_repo_code_v3_capped3` overlaps Oracle eval material (prompt rows 139, answer rows 72). Use those evals as regression checks and keep a fresh holdout for promotion.
- `oracle_fast_4b_candidate_v1_capped3` is heavily weighted by duplication (382/632 duplicate rows, 60.4%). Keep this only when each weight maps to a measured failure bucket.
- `oracle_longctx_v1_capped3` is heavily weighted by duplication (256/416 duplicate rows, 61.5%). Keep this only when each weight maps to a measured failure bucket.
- `oracle_longctx_v1_capped3` has no actual tool-call transcript rows. If this trains a tool-using Oracle lane, add deployed-format tool call/result/final-answer examples.
- `oracle_longctx_dpo_v1_capped3` is heavily weighted by duplication (256/416 duplicate rows, 61.5%). Keep this only when each weight maps to a measured failure bucket.
- `oracle_longctx_dpo_v1_capped3` has no actual tool-call transcript rows. If this trains a tool-using Oracle lane, add deployed-format tool call/result/final-answer examples.

## Dataset Summary

| Dataset | Rows | Train | Val | Test | Unique Rows | Duplicate Rows | Tool Transcript Rows | Prompt Eval Overlaps | Answer Eval Overlaps |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `qwen3_oracle_14b_v7_capped3` | 65 | 63 | 1 | 1 | 23 | 42 | 0 | 18 | 130 |
| `oracle_repo_code_v3_capped3` | 554 | 528 | 13 | 13 | 202 | 352 | 0 | 139 | 72 |
| `oracle_fast_4b_candidate_v1_capped3` | 632 | 573 | 29 | 30 | 250 | 382 | 575 | 0 | 0 |
| `oracle_longctx_v1_capped3` | 416 | 384 | 16 | 16 | 160 | 256 | 0 | 0 | 0 |
| `oracle_longctx_dpo_v1_capped3` | 416 | 384 | 16 | 16 | 160 | 256 | 0 | 0 | 0 |

## Dataset Details

### `qwen3_oracle_14b_v7_capped3`

- Path: `/Users/scawful/src/training/datasets/qwen3_oracle_14b_v7_capped3`
- Rows: `65`; unique row payloads: `23`; duplicate row pressure: `64.6%`
- Unique prompts: `23`; prompt duplicate pressure: `64.6%`
- Unique answers: `11`
- Split content overlap: `{'train/val': 0, 'train/test': 0, 'val/test': 0}`
- Split prompt overlap: `{'train/val': 0, 'train/test': 0, 'val/test': 0}`

Tool surface:
- `prose-only`: 65

Bucket counts (expanded rows):
- `abi_and_width_contracts`: 39
- `debug_capture_and_triage`: 18
- `hook_safety_and_authoring`: 3
- `oracle_docs_and_system_reasoning`: 3
- `hardware_register_grounding`: 1
- `uncertainty_and_scope_control`: 1

Bucket unique row counts:
- `abi_and_width_contracts`: 13
- `debug_capture_and_triage`: 6
- `hook_safety_and_authoring`: 1
- `oracle_docs_and_system_reasoning`: 1
- `hardware_register_grounding`: 1
- `uncertainty_and_scope_control`: 1

Role counts:
- `failure_target`: 45
- `stability_anchor`: 20

Style counts:
- `stability_anchor`: 13
- `contract`: 9
- `direct`: 9
- `rewrite`: 9
- `score_gap`: 9
- `protective_anchor`: 7

Examples by bucket:
- `abi_and_width_contracts`: `qwen3_oracle_14b_corrective_v6_abi_precision_oracle_main_stz_long_address`, `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_v2_torch_loop_return_path`, `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_jsr_rtl_mismatch`, `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_v2_torch_loop_return_path`
- `debug_capture_and_triage`: `qwen3_oracle_14b_corrective_v6_contract_oracle_main_v2_capture_assert_jtl`, `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_v2_darkroom_capture_order`, `qwen3_oracle_14b_corrective_v6_capture_first_oracle_main_v2_capture_assert_jtl`, `qwen3_oracle_14b_corrective_v6_rewrite_oracle_main_v2_capture_assert_jtl`
- `hardware_register_grounding`: `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_mdmaen_vs_hdmaen_val_anchor`
- `hook_safety_and_authoring`: `qwen3_oracle_14b_corrective_v6_protective_anchor_oracle_main_v2_hook_stub_overwritten_logic`, `qwen3_oracle_14b_corrective_v6_protective_anchor_oracle_main_v2_hook_stub_overwritten_logic`, `qwen3_oracle_14b_corrective_v6_protective_anchor_oracle_main_v2_hook_stub_overwritten_logic`
- `oracle_docs_and_system_reasoning`: `qwen3_oracle_14b_corrective_v6_protective_anchor_oracle_main_zso_time_system`, `qwen3_oracle_14b_corrective_v6_protective_anchor_oracle_main_zso_time_system`, `qwen3_oracle_14b_corrective_v6_protective_anchor_oracle_main_zso_time_system`
- `uncertainty_and_scope_control`: `qwen3_oracle_14b_corrective_v6_protective_anchor_oracle_main_v2_docs_refuse_fake_symbol_test_anchor`

Largest prompt-family clusters:
- count `15`, unique prompts `5`, splits `{'train': 15}`, buckets `{'abi_and_width_contracts': 15}`; samples `qwen3_oracle_14b_corrective_v6_abi_precision_oracle_main_stz_long_address`, `qwen3_oracle_14b_corrective_v6_rewrite_oracle_main_stz_long_address`, `qwen3_oracle_14b_corrective_v6_direct_oracle_main_stz_long_address`, `qwen3_oracle_14b_corrective_v6_score_gap_oracle_main_stz_long_address`, `qwen3_oracle_14b_corrective_v6_direct_oracle_main_stz_long_address`; preview: Why does `STZ $7E2000,X` fail to assemble? Show two correct fixes.  A previous answer was still too fuzzy about the width / stack contract: ```text <think>  </think>  `STZ` does no
- count `15`, unique prompts `5`, splits `{'train': 15}`, buckets `{'debug_capture_and_triage': 15}`; samples `qwen3_oracle_14b_corrective_v6_contract_oracle_main_v2_capture_assert_jtl`, `qwen3_oracle_14b_corrective_v6_capture_first_oracle_main_v2_capture_assert_jtl`, `qwen3_oracle_14b_corrective_v6_rewrite_oracle_main_v2_capture_assert_jtl`, `qwen3_oracle_14b_corrective_v6_contract_oracle_main_v2_capture_assert_jtl`, `qwen3_oracle_14b_corrective_v6_capture_first_oracle_main_v2_capture_assert_jtl`; preview: When should you use `capture_blackout.py arm --assert-jtl`, and what does it help prove?  Answer in 3-6 sentences. - Stay capture-first. Name the first registers/state to inspect a
- count `15`, unique prompts `5`, splits `{'train': 15}`, buckets `{'abi_and_width_contracts': 15}`; samples `qwen3_oracle_14b_corrective_v6_direct_oracle_main_v2_rep20_store_then_flag`, `qwen3_oracle_14b_corrective_v6_abi_precision_oracle_main_v2_rep20_store_then_flag`, `qwen3_oracle_14b_corrective_v6_abi_precision_oracle_main_v2_rep20_store_then_flag`, `qwen3_oracle_14b_corrective_v6_direct_oracle_main_v2_rep20_store_then_flag`, `qwen3_oracle_14b_corrective_v6_abi_precision_oracle_main_v2_rep20_store_then_flag`; preview: Inside a `REP #$20` region, why is it unsafe to do 8-bit flag logic before the replaced 16-bit store, and what is the safe pattern?
- count `3`, unique prompts `1`, splits `{'train': 3}`, buckets `{'abi_and_width_contracts': 3}`; samples `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_v2_torch_loop_return_path`, `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_v2_torch_loop_return_path`, `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_v2_torch_loop_return_path`; preview: A hook does `SEP #$30` and then `JML $0188C9` back into the vanilla torch loop. Why can that black-screen even if the code assembles?  Answer concretely and preserve the exact cont
- count `3`, unique prompts `1`, splits `{'train': 3}`, buckets `{'abi_and_width_contracts': 3}`; samples `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_jsr_rtl_mismatch`, `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_jsr_rtl_mismatch`, `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_jsr_rtl_mismatch`; preview: Explain the bug and fix it:  ```asm JSR $1234 LDA #$01 STA $7E2000 RTL ```  Answer concretely and preserve the exact contract details that make this Oracle-main answer pass. - Name
- count `3`, unique prompts `1`, splits `{'train': 3}`, buckets `{'debug_capture_and_triage': 3}`; samples `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_v2_darkroom_capture_order`, `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_v2_darkroom_capture_order`, `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_v2_darkroom_capture_order`; preview: A dark-room transition blacks out. What should you capture first, and why is that better than blind spotlight patching?  Answer concretely and preserve the exact contract details t

Top eval overlaps:
- prompt `evals/oracle_main_capability_eval_v1.jsonl`: 9
- prompt `evals/oracle_main_grounded_eval_v2.jsonl`: 6
- prompt `evals/oracle_main_grounded_eval_v1.jsonl`: 3
- answer `evals/oracle_main_capability_eval_v1.jsonl`: 65
- answer `evals/oracle_main_grounded_eval_v2.jsonl`: 40
- answer `evals/oracle_main_grounded_eval_v1.jsonl`: 25

Overlap examples:
- `answer` with `evals/oracle_main_capability_eval_v1.jsonl` via row `qwen3_oracle_14b_corrective_v6_abi_precision_oracle_main_stz_long_address`
- `answer` with `evals/oracle_main_grounded_eval_v1.jsonl` via row `qwen3_oracle_14b_corrective_v6_abi_precision_oracle_main_stz_long_address`
- `answer` with `evals/oracle_main_capability_eval_v1.jsonl` via row `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_v2_torch_loop_return_path`
- `answer` with `evals/oracle_main_grounded_eval_v2.jsonl` via row `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_v2_torch_loop_return_path`
- `answer` with `evals/oracle_main_capability_eval_v1.jsonl` via row `qwen3_oracle_14b_corrective_v6_contract_oracle_main_v2_capture_assert_jtl`
- `answer` with `evals/oracle_main_grounded_eval_v2.jsonl` via row `qwen3_oracle_14b_corrective_v6_contract_oracle_main_v2_capture_assert_jtl`
- `answer` with `evals/oracle_main_capability_eval_v1.jsonl` via row `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_jsr_rtl_mismatch`
- `answer` with `evals/oracle_main_grounded_eval_v1.jsonl` via row `qwen3_oracle_14b_corrective_v6_stability_anchor_oracle_main_jsr_rtl_mismatch`

### `oracle_repo_code_v3_capped3`

- Path: `/Users/scawful/src/training/datasets/oracle_repo_code_v3_capped3`
- Rows: `554`; unique row payloads: `202`; duplicate row pressure: `63.5%`
- Unique prompts: `196`; prompt duplicate pressure: `64.6%`
- Unique answers: `120`
- Split content overlap: `{'train/val': 0, 'train/test': 0, 'val/test': 0}`
- Split prompt overlap: `{'train/val': 1, 'train/test': 0, 'val/test': 0}`

Tool surface:
- `prose-only`: 554

Bucket counts (expanded rows):
- `code_repair`: 243
- `compile_grounding`: 193
- `repo_retrieval`: 118

Bucket unique row counts:
- `code_repair`: 89
- `compile_grounding`: 71
- `repo_retrieval`: 42

Role counts:
- `unspecified`: 554

Style counts:
- `unspecified`: 554

Examples by bucket:
- `code_repair`: `code_repair_e5844857bde7164c`, `oracle_coder_corrective_v2_asar_clean_oracle_code_repair_v2_02`, `code_repair_1fe7597776c28d2b`, `code_repair_308b770c84333641`
- `compile_grounding`: `compile_grounding_15e378873b6e45f6`, `oracle_coder_corrective_rewrite_oracle_compile_grounding_9aaddd0341d33fc8`, `compile_grounding_1072d3346a7570ee`, `compile_grounding_15f9cbc9f72818cd`
- `repo_retrieval`: `retrieval_code_red_policy_01`, `retrieval_hook_abi_03`, `oracle_coder_corrective_v2_direct_oracle_repo_retrieval_03`, `oracle_coder_corrective_v2_rewrite_oracle_repo_retrieval_v2_02`

Largest prompt-family clusters:
- count `22`, unique prompts `5`, splits `{'train': 18, 'test': 4}`, buckets `{'compile_grounding': 22}`; samples `oracle_coder_corrective_rewrite_oracle_compile_grounding_9aaddd0341d33fc8`, `oracle_coder_corrective_v2_rewrite_oracle_compile_grounding_bea6670e75fbd132`, `oracle_coder_corrective_v2_asar_clean_oracle_compile_grounding_bea6670e75fbd132`, `oracle_coder_corrective_v2_rewrite_oracle_compile_grounding_9aaddd0341d33fc8`, `oracle_coder_corrective_v2_rewrite_oracle_compile_grounding_bea6670e75fbd132`; preview: Write a 65816 routine that (Using Oracle of Secrets symbols).  A previous answer failed this task: ```text ; =======================================================================
- count `12`, unique prompts `4`, splits `{'train': 12}`, buckets `{'code_repair': 12}`; samples `oracle_coder_corrective_v2_rewrite_oracle_code_repair_06`, `oracle_coder_corrective_v2_rewrite_oracle_code_repair_06`, `oracle_coder_corrective_rewrite_oracle_code_repair_06`, `oracle_coder_corrective_direct_oracle_code_repair_06`, `oracle_coder_corrective_v2_asar_clean_oracle_code_repair_06`; preview: Repair the hook body below.  ```asm MagicBeanAdvance:     lda MagicBeanProg     inc     sta MagicBeanProg     rtl ```  Problem: `MagicBeanProg` is structured quest state and must n
- count `12`, unique prompts `4`, splits `{'train': 12}`, buckets `{'repo_retrieval': 12}`; samples `oracle_coder_corrective_v2_direct_oracle_repo_retrieval_03`, `oracle_coder_corrective_v2_exact_path_oracle_repo_retrieval_03`, `oracle_coder_corrective_v2_exact_path_oracle_repo_retrieval_03`, `oracle_coder_corrective_v2_rewrite_oracle_repo_retrieval_03`, `oracle_coder_corrective_v2_direct_oracle_repo_retrieval_03`; preview: Use the file map below.  [File A] Docs/Technical/MemoryMap.md Explains active labels vs stale UNUSED comments.  [File B] Core/sram_progress.asm Implements custom progression fields
- count `12`, unique prompts `4`, splits `{'train': 12}`, buckets `{'repo_retrieval': 12}`; samples `oracle_coder_corrective_v2_direct_oracle_repo_retrieval_06`, `oracle_coder_corrective_v2_rewrite_oracle_repo_retrieval_06`, `oracle_coder_corrective_v2_exact_path_oracle_repo_retrieval_06`, `oracle_coder_corrective_v2_direct_oracle_repo_retrieval_06`, `oracle_coder_corrective_v2_direct_oracle_repo_retrieval_06`; preview: Repository sketch:  [File A] datasets/sources/oracle_harness_awareness_v1.jsonl Tool-activation and identity repairs.  [File B] scripts/build_qwen35_oracle_fast_v2_dataset.py Build
- count `12`, unique prompts `4`, splits `{'train': 12}`, buckets `{'code_repair': 12}`; samples `oracle_coder_corrective_v2_rewrite_oracle_code_repair_04`, `oracle_coder_corrective_rewrite_oracle_code_repair_04`, `oracle_coder_corrective_v2_rewrite_oracle_code_repair_04`, `oracle_coder_corrective_v2_asar_clean_oracle_code_repair_04`, `oracle_coder_corrective_direct_oracle_code_repair_04`; preview: Repair the logic below.  ```asm MaybeSkipDecompress:     lda TransGFXModule_PriorSheets     cmp CurrentSheetGroup     beq .skip     jsl DecompressCurrentSheets .skip     rtl ```  P
- count `9`, unique prompts `3`, splits `{'train': 9}`, buckets `{'code_repair': 9}`; samples `oracle_coder_corrective_v2_asar_clean_oracle_code_repair_v2_02`, `oracle_coder_corrective_v2_rewrite_oracle_code_repair_v2_02`, `oracle_coder_corrective_v2_direct_oracle_code_repair_v2_02`, `oracle_coder_corrective_v2_direct_oracle_code_repair_v2_02`, `oracle_coder_corrective_v2_rewrite_oracle_code_repair_v2_02`; preview: Repair the code below.  ```asm AdvanceBeanStage:     lda MagicBeanProg     inc a     sta MagicBeanProg     rtl ```  Problem: `MagicBeanProg` is structured quest state and must not

Top eval overlaps:
- prompt `evals/oracle_main_capability_eval_v1.jsonl`: 30
- prompt `evals/oracle_main_grounded_eval_v1.jsonl`: 30
- prompt `evals/oracle_compile_grounding_eval_v1.jsonl`: 16
- prompt `evals/oracle_repo_retrieval_eval_v1.jsonl`: 15
- prompt `evals/oracle_compile_grounding_eval_v2.jsonl`: 12
- answer `evals/oracle_main_capability_eval_v1.jsonl`: 36
- answer `evals/oracle_main_grounded_eval_v1.jsonl`: 36

Overlap examples:
- `prompt` with `evals/oracle_repo_retrieval_eval_v1.jsonl` via row `oracle_coder_corrective_v2_direct_oracle_repo_retrieval_03`
- `prompt` with `evals/oracle_compile_grounding_eval_v1.jsonl` via row `oracle_coder_corrective_v2_direct_oracle_compile_grounding_01bf680436b51de6`
- `prompt` with `evals/oracle_compile_grounding_eval_v2.jsonl` via row `oracle_coder_corrective_v2_direct_oracle_compile_grounding_v2_05`
- `prompt` with `evals/oracle_repo_retrieval_eval_v1.jsonl` via row `oracle_coder_corrective_direct_oracle_repo_retrieval_02`
- `prompt` with `evals/oracle_compile_grounding_eval_v2.jsonl` via row `oracle_coder_corrective_v2_direct_oracle_compile_grounding_v2_01`
- `prompt` with `evals/oracle_compile_grounding_eval_v1.jsonl` via row `oracle_coder_corrective_v2_direct_oracle_compile_grounding_01bf680436b51de6`
- `prompt` with `evals/oracle_compile_grounding_eval_v2.jsonl` via row `oracle_coder_corrective_v2_direct_oracle_compile_grounding_v2_04`
- `prompt` with `evals/oracle_repo_retrieval_eval_v2.jsonl` via row `oracle_coder_corrective_v2_direct_oracle_repo_retrieval_v2_02`

### `oracle_fast_4b_candidate_v1_capped3`

- Path: `/Users/scawful/src/training/datasets/oracle_fast_4b_candidate_v1_capped3`
- Rows: `632`; unique row payloads: `250`; duplicate row pressure: `60.4%`
- Unique prompts: `128`; prompt duplicate pressure: `79.7%`
- Unique answers: `236`
- Split content overlap: `{'train/val': 0, 'train/test': 0, 'val/test': 0}`
- Split prompt overlap: `{'train/val': 14, 'train/test': 16, 'val/test': 4}`

Tool surface:
- `tool-role-transcript`: 575
- `prose-only`: 32
- `prose-tool-context`: 25

Bucket counts (expanded rows):
- `unbucketed`: 248
- `chain`: 238
- `domain`: 110
- `oracle-fast-corrective3`: 36

Bucket unique row counts:
- `unbucketed`: 100
- `chain`: 92
- `domain`: 44
- `oracle-fast-corrective3`: 14

Role counts:
- `unspecified`: 632

Style counts:
- `unspecified`: 632

Examples by bucket:
- `chain`: `4cb835fa-a398-4b16-98ef-463c797c8164`, `1f985df7-ae93-4da8-9213-f865ffbdaf54`, `4dc76114-c355-46cd-bc4d-24a08db94b29`, `89a06d99-9460-4219-b96c-85a79b0af08b`
- `domain`: `b158de81-3aa8-49e9-9c35-4f038c1fbd51`, `81bde71d-caf2-492d-9e65-51d2a9b83fb6`, `7c5aec48-052a-411f-a5e8-f5d581f3be24`, `9345d2a1-6820-44c8-b5ad-f6dba8da7b99`
- `oracle-fast-corrective3`: `train.jsonl:3`, `train.jsonl:10`, `train.jsonl:16`, `train.jsonl:21`
- `unbucketed`: `train.jsonl:1`, `train.jsonl:2`, `train.jsonl:4`, `train.jsonl:5`

Largest prompt-family clusters:
- count `15`, unique prompts `1`, splits `{'train': 15}`, buckets `{'domain': 15}`; samples `81bde71d-caf2-492d-9e65-51d2a9b83fb6`, `559a0894-67dd-4d7b-b850-3f52d0498654`, `07c7058f-660a-439c-acf0-4c1dd9aff2a6`, `81bde71d-caf2-492d-9e65-51d2a9b83fb6`, `07c7058f-660a-439c-acf0-4c1dd9aff2a6`; preview: What does the Sprite_CheckIfActive routine do?
- count `15`, unique prompts `1`, splits `{'train': 15}`, buckets `{'chain': 15}`; samples `2da27430-b0eb-462a-b029-425bba16ee53`, `c3a18ff1-d659-4083-80ca-f3546875ab23`, `4fa768c7-f15a-4817-99cb-46597ea88838`, `d5b66364-7f33-49b8-aedf-d6be4cd1b77e`, `c3a18ff1-d659-4083-80ca-f3546875ab23`; preview: Black screen after entering room 0xB8. Check everything.
- count `15`, unique prompts `1`, splits `{'train': 15}`, buckets `{'domain': 15}`; samples `9345d2a1-6820-44c8-b5ad-f6dba8da7b99`, `0019ce7d-06c4-498d-adfb-2b552104a1d0`, `a6e43db0-4280-47d7-9268-953c8fb14fae`, `a6e43db0-4280-47d7-9268-953c8fb14fae`, `6f36cdcb-2f85-4d19-a0dc-49137fd8fca6`; preview: Show me the SNES memory map
- count `15`, unique prompts `1`, splits `{'train': 15}`, buckets `{'chain': 15}`; samples `4272c9a5-45d5-4d4e-852a-4ef348b9b485`, `5097cb77-fc7e-4a51-ad2d-59edaea5e56b`, `055e4d49-1945-4623-aca7-b52286ece630`, `7f64ba16-fe55-43a3-9d6f-aee7ed3210d5`, `4272c9a5-45d5-4d4e-852a-4ef348b9b485`; preview: Check if sprite_minecart.asm has lint errors, then inspect room 0x78
- count `15`, unique prompts `1`, splits `{'train': 15}`, buckets `{'chain': 15}`; samples `385ef35c-ef41-47ca-9721-73b6892927e3`, `385ef35c-ef41-47ca-9721-73b6892927e3`, `24634135-cfda-4ac9-b789-75f2f090a621`, `44fd3b66-9a3d-4024-bb6c-6a45397df038`, `156cfd7f-16ec-4128-ae31-8936c2028ce1`; preview: Check the timer interrupt handler — it feels like it's running too often.
- count `15`, unique prompts `1`, splits `{'train': 15}`, buckets `{'chain': 15}`; samples `0647e735-7536-4a2e-b447-25c0cf307d7d`, `28ec9451-b979-4666-bacd-d82a1bb2e28a`, `0aa391a3-283b-4c0a-9cde-c4f168e08892`, `0647e735-7536-4a2e-b447-25c0cf307d7d`, `0aa391a3-283b-4c0a-9cde-c4f168e08892`; preview: How does room 0x72 compare to the vanilla room — what objects changed?

Top eval overlaps:
- none

### `oracle_longctx_v1_capped3`

- Path: `/Users/scawful/src/training/datasets/oracle_longctx_v1_capped3`
- Rows: `416`; unique row payloads: `160`; duplicate row pressure: `61.5%`
- Unique prompts: `160`; prompt duplicate pressure: `61.5%`
- Unique answers: `30`
- Split content overlap: `{'train/val': 0, 'train/test': 0, 'val/test': 0}`
- Split prompt overlap: `{'train/val': 0, 'train/test': 0, 'val/test': 0}`

Tool surface:
- `prose-only`: 376
- `prose-tool-context`: 40

Bucket counts (expanded rows):
- `tool_transcript_grounding`: 104
- `evidence_extraction`: 104
- `lost_in_middle`: 104
- `multi_file_synthesis`: 104

Bucket unique row counts:
- `tool_transcript_grounding`: 40
- `evidence_extraction`: 40
- `lost_in_middle`: 40
- `multi_file_synthesis`: 40

Role counts:
- `unspecified`: 416

Style counts:
- `unspecified`: 416

Examples by bucket:
- `evidence_extraction`: `oracle_longctx_docs_code_red_3`, `oracle_longctx_docs_identity_3`, `oracle_longctx_docs_identity_2`, `oracle_longctx_docs_active_label_3`
- `lost_in_middle`: `oracle_longctx_lostmiddle_yarn_order_4`, `oracle_longctx_lostmiddle_scrolls_bitfield_2`, `oracle_longctx_lostmiddle_active_label_2`, `oracle_longctx_lostmiddle_palette_pipeline_4`
- `multi_file_synthesis`: `oracle_longctx_synth_synth_progression_state_4`, `oracle_longctx_synth_synth_palette_arch_1`, `oracle_longctx_synth_synth_lsp_scale_1`, `oracle_longctx_synth_synth_namespace_hooks_3`
- `tool_transcript_grounding`: `oracle_longctx_transcript_tx_code_red_3`, `oracle_longctx_transcript_tx_transgfx_4`, `oracle_longctx_transcript_tx_palette_4`, `oracle_longctx_transcript_tx_namespace_4`

Largest prompt-family clusters:
- count `3`, unique prompts `1`, splits `{'train': 3}`, buckets `{'tool_transcript_grounding': 3}`; samples `oracle_longctx_transcript_tx_code_red_3`, `oracle_longctx_transcript_tx_code_red_3`, `oracle_longctx_transcript_tx_code_red_3`; preview: Ground the answer in the transcript below.  assistant -> list_directory(path="Docs") tool -> [FILE] README.md [FILE] RUNBOOK.md [DIR] Debugging assistant -> read_file(path="Docs/RU
- count `3`, unique prompts `1`, splits `{'train': 3}`, buckets `{'evidence_extraction': 3}`; samples `oracle_longctx_docs_code_red_3`, `oracle_longctx_docs_code_red_3`, `oracle_longctx_docs_code_red_3`; preview: Use only the project notes below.  [Excerpt 1] CODE RED means repro-state integrity failed, so save-state reuse is no longer trusted until rebuilt.  [Excerpt 2] After CODE RED, eve
- count `3`, unique prompts `1`, splits `{'train': 3}`, buckets `{'lost_in_middle': 3}`; samples `oracle_longctx_lostmiddle_yarn_order_4`, `oracle_longctx_lostmiddle_yarn_order_4`, `oracle_longctx_lostmiddle_yarn_order_4`; preview: Use only the context below.  [Noise] The first section is intentionally distracting and not relevant to the answer.  [Middle evidence] Qwen3.5 already has a large native context wi
- count `3`, unique prompts `1`, splits `{'train': 3}`, buckets `{'lost_in_middle': 3}`; samples `oracle_longctx_lostmiddle_scrolls_bitfield_2`, `oracle_longctx_lostmiddle_scrolls_bitfield_2`, `oracle_longctx_lostmiddle_scrolls_bitfield_2`; preview: Use only the context below.  [Noise] Legacy router notes and archived quantization chatter appear first but do not answer the question.  [Middle evidence] The repurposed SRAM block
- count `3`, unique prompts `1`, splits `{'train': 3}`, buckets `{'evidence_extraction': 3}`; samples `oracle_longctx_docs_identity_3`, `oracle_longctx_docs_identity_3`, `oracle_longctx_docs_identity_3`; preview: Use only the project notes below.  [Excerpt 1] The local Oracle model should not drift into claiming it is Claude, OpenAI, or Qwen itself. It should answer as the local Oracle mode
- count `3`, unique prompts `1`, splits `{'train': 3}`, buckets `{'tool_transcript_grounding': 3}`; samples `oracle_longctx_transcript_tx_transgfx_4`, `oracle_longctx_transcript_tx_transgfx_4`, `oracle_longctx_transcript_tx_transgfx_4`; preview: Use the transcript below and do not infer beyond it.  assistant -> read_file(path="Docs/World/Overworld/ZSCustomOverworldAdvanced.md") tool -> The transition graphics pipeline stag

Top eval overlaps:
- none

### `oracle_longctx_dpo_v1_capped3`

- Path: `/Users/scawful/src/training/datasets/oracle_longctx_dpo_v1_capped3`
- Rows: `416`; unique row payloads: `160`; duplicate row pressure: `61.5%`
- Unique prompts: `160`; prompt duplicate pressure: `61.5%`
- Unique answers: `40`
- Split content overlap: `{'train/val': 0, 'train/test': 0, 'val/test': 0}`
- Split prompt overlap: `{'train/val': 0, 'train/test': 0, 'val/test': 0}`

Tool surface:
- `prose-only`: 376
- `prose-tool-context`: 40

Bucket counts (expanded rows):
- `multifile_synthesis`: 104
- `lost_middle`: 104
- `tool_transcripts`: 104
- `grounding`: 104

Bucket unique row counts:
- `multifile_synthesis`: 40
- `lost_middle`: 40
- `tool_transcripts`: 40
- `grounding`: 40

Role counts:
- `unspecified`: 416

Style counts:
- `unspecified`: 416

Examples by bucket:
- `grounding`: `train.jsonl:5`, `train.jsonl:11`, `train.jsonl:13`, `train.jsonl:16`
- `lost_middle`: `train.jsonl:3`, `train.jsonl:7`, `train.jsonl:8`, `train.jsonl:14`
- `multifile_synthesis`: `train.jsonl:1`, `train.jsonl:2`, `train.jsonl:6`, `train.jsonl:9`
- `tool_transcripts`: `train.jsonl:4`, `train.jsonl:10`, `train.jsonl:23`, `train.jsonl:25`

Largest prompt-family clusters:
- count `3`, unique prompts `1`, splits `{'train': 3}`, buckets `{'multifile_synthesis': 3}`; samples `train.jsonl:1`, `train.jsonl:175`, `train.jsonl:236`; preview: Combine the notes below without adding outside facts.  [Source 1] The prepared 14B follow-up exists, but it should remain gated until the smaller corrective proves the backbone is
- count `3`, unique prompts `1`, splits `{'train': 3}`, buckets `{'multifile_synthesis': 3}`; samples `train.jsonl:2`, `train.jsonl:40`, `train.jsonl:134`; preview: Combine the notes below without adding outside facts.  [Source 1] After CODE RED, repro reports must explain how the state was rebuilt and what trusted baseline was used.  [Source
- count `3`, unique prompts `1`, splits `{'train': 3}`, buckets `{'lost_middle': 3}`; samples `train.jsonl:3`, `train.jsonl:39`, `train.jsonl:77`; preview: Use only the context below.  [Noise] Front-loaded notes discuss old smoke tests and stale launch commands.  [Middle evidence] The local Oracle model should not drift into claiming
- count `3`, unique prompts `1`, splits `{'train': 3}`, buckets `{'tool_transcripts': 3}`; samples `train.jsonl:4`, `train.jsonl:89`, `train.jsonl:226`; preview: Use the transcript below and do not infer beyond it.  assistant -> list_directory(path="Docs") tool -> [FILE] README.md [FILE] RUNBOOK.md [DIR] Debugging assistant -> read_file(pat
- count `3`, unique prompts `1`, splits `{'train': 3}`, buckets `{'grounding': 3}`; samples `train.jsonl:5`, `train.jsonl:168`, `train.jsonl:259`; preview: Use only the notes below.  [Note A] If an Oracle doc shows both an active label and an `UNUSED_` comment on the same address, the active label wins.  [Note B] The `UNUSED_` note is
- count `3`, unique prompts `1`, splits `{'train': 3}`, buckets `{'multifile_synthesis': 3}`; samples `train.jsonl:6`, `train.jsonl:20`, `train.jsonl:322`; preview: Combine the notes below without adding outside facts.  [Source 1] The local Oracle model should identify as the local `oracle` model inside z3cli rather than as Claude, OpenAI, or

Top eval overlaps:
- none

## Training And Prompt Implications

- Treat eval-overlapping packs as regression suites. Promotion needs fresh prompts or adversarial variants that are not represented in train rows.
- Where duplicate pressure is high, keep metadata-driven weights explicit and cap any bucket that starts regressing previously repaired surfaces.
- Add real deployed-format tool transcripts for Oracle-family models that must learn chain continuation; prose-only rows teach facts but not agent behavior.
- Keep `oracle-coder` rows code/retrieval/compile-focused. Do not blend broad Oracle explanation rows into that worker unless an eval proves it helps.
- For system prompts, prefer short branch rules that mirror the data: ground first, preserve failed-grounding uncertainty, delegate authoring to `oracle-coder`, then verify.
