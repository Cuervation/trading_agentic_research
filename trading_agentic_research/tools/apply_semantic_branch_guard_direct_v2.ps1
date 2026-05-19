param(
  [string]$RepoRoot = "."
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
Push-Location $RepoRoot

# 1) pre_run_duplicate_guard.py
$pre = ".\scripts\research\pre_run_duplicate_guard.py"
$text = Get-Content $pre -Raw

if ($text -notmatch "semantic_branch_preflight") {
  $anchor = "from scripts.research.strategy_effect_signature import read_json, strategy_effect_signature_from_path`n"
  $insert = $anchor + "from scripts.research.semantic_branch_guard import semantic_branch_preflight`n"
  if (-not $text.Contains($anchor)) { throw "pre_run_duplicate_guard.py import anchor not found" }
  $text = $text.Replace($anchor, $insert)
}

if ($text -notmatch "SEMANTIC_BRANCH_GUARD_DIRECT_V2") {
  $anchor = '    sig=info.get("strategy_effect_signature"); cfg_hash=info.get("config_hash")
'
  $block = @'
    # SEMANTIC_BRANCH_GUARD_DIRECT_V2
    semantic = semantic_branch_preflight(
        state_dir=state_dir,
        runs_dir=runs_dir,
        hypothesis_id=hypothesis_id or info.get("hypothesis_id"),
        family=family or info.get("strategy_family"),
    )
    if semantic.get("blocked"):
        return {
            "blocked": True,
            "reason": semantic.get("reason") or "semantic_branch_exhausted",
            "duplicate_of_run_id": semantic.get("duplicate_of_run_id"),
            "semantic_branch": semantic,
            "candidate": info,
            "hypothesis_id": hypothesis_id,
            "family": family,
        }

    sig=info.get("strategy_effect_signature"); cfg_hash=info.get("config_hash")
'@
  if (-not $text.Contains($anchor)) { throw "pre_run_duplicate_guard.py signature anchor not found" }
  $text = $text.Replace($anchor, $block)
}

Set-Content $pre $text -Encoding UTF8

# 2) evaluate_candidate.py
$eval = ".\scripts\evaluate_candidate.py"
$text = Get-Content $eval -Raw

if ($text -notmatch "refresh_semantic_branch_state") {
  $anchor = "from scripts.research.candidate_review_learning import update_candidate_review_learning_from_run`n"
  $insert = $anchor + "from scripts.research.semantic_branch_guard import refresh_semantic_branch_state`n"
  if (-not $text.Contains($anchor)) { throw "evaluate_candidate.py import anchor not found" }
  $text = $text.Replace($anchor, $insert)
}

if ($text -notmatch "SEMANTIC_BRANCH_REFRESH_DIRECT_V2") {
  $anchor = @'
    candidate_review_learning = update_candidate_review_learning_from_run(
        run_dir=run_dir,
        state_dir=args.state_dir,
        audit=audit,
    )

'@
  $block = $anchor + @'
    # SEMANTIC_BRANCH_REFRESH_DIRECT_V2
    semantic_branch_state = refresh_semantic_branch_state(
        state_dir=args.state_dir,
        runs_dir=args.runs_dir,
    )

'@
  if (-not $text.Contains($anchor)) { throw "evaluate_candidate.py candidate_review anchor not found" }
  $text = $text.Replace($anchor, $block)

  $printAnchor = '    print(f"Candidate-review learning: {candidate_review_learning.get('
  if ($text.Contains($printAnchor)) {
    $text = $text.Replace(
      '    print(f"Candidate-review learning: {candidate_review_learning.get(''reason'') or candidate_review_learning.get(''exhausted_axes'') or candidate_review_learning.get(''updated'')}")',
      '    print(f"Candidate-review learning: {candidate_review_learning.get(''reason'') or candidate_review_learning.get(''exhausted_axes'') or candidate_review_learning.get(''updated'')}")' + "`n" +
      '    print(f"Semantic branch exhausted: {sum(1 for b in (semantic_branch_state.get(''branches'') or {}).values() if b.get(''status'') == ''exhausted'')}")'
    )
  }
}

Set-Content $eval $text -Encoding UTF8

# 3) feature_space_expansion_factory.py
$factory = ".\scripts\research\feature_space_expansion_factory.py"
$text = Get-Content $factory -Raw

if ($text -notmatch "is_semantic_branch_exhausted") {
  $anchor = "from scripts.research.cooldown_governance import hard_active_cooldown_families`n"
  $insert = $anchor + "from scripts.research.semantic_branch_guard import is_semantic_branch_exhausted`n"
  if (-not $text.Contains($anchor)) { throw "feature_space_expansion_factory.py import anchor not found" }
  $text = $text.Replace($anchor, $insert)
}

if ($text -notmatch "SEMANTIC_BRANCH_SKIP_DIRECT_V2") {
  $anchor = @'
        hypothesis_id = f"HYP_FSPACE_{safe_parent}_{suffix}_V1"
        if hypothesis_id in ids:
'@
  $block = @'
        hypothesis_id = f"HYP_FSPACE_{safe_parent}_{suffix}_V1"
        # SEMANTIC_BRANCH_SKIP_DIRECT_V2
        semantic = is_semantic_branch_exhausted(
            state_dir=state_dir,
            runs_dir="runs",
            hypothesis_id=hypothesis_id,
            family=effective_family,
        )
        if semantic.get("exhausted"):
            skipped.append({
                "field": spec.field,
                "reason": "semantic_branch_exhausted",
                "hypothesis_id": hypothesis_id,
                "layer": layer,
                "branch_key": semantic.get("branch_key"),
                "semantic_reason": semantic.get("reason"),
            })
            return
        if hypothesis_id in ids:
'@
  if (-not $text.Contains($anchor)) { throw "feature_space_expansion_factory.py hypothesis_id anchor not found" }
  $text = $text.Replace($anchor, $block)
}

Set-Content $factory $text -Encoding UTF8

python -m py_compile `
  .\scripts\research\semantic_branch_guard.py `
  .\scripts\research\pre_run_duplicate_guard.py `
  .\scripts\evaluate_candidate.py `
  .\scripts\research\feature_space_expansion_factory.py

python .\scripts\research\semantic_branch_guard.py --state-dir .\state --runs-dir .\runs

Write-Host "Semantic Branch Guard direct v2 applied."
Pop-Location
