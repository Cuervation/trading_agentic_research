"""Build compact context packs for each agent role.

This script reads only the small governance/state files needed to brief agents.
It never reads CSV datasets, full run folders, or backtest artifacts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "reports" / "context_packs"

SOURCE_FILES = [
    "AGENTS.md",
    "SPEC.md",
    "agents/analyst.md",
    "agents/auditor.md",
    "agents/coder.md",
    "agents/coordinator.md",
    "agents/executor.md",
    "agents/librarian.md",
    "agents/literature_researcher.md",
    "configs/project_config.json",
    "state/current_parent.json",
    "state/current_baseline.json",
    "state/research_state.json",
]

COMMON_HARD_RULES = [
    "No inventar datos.",
    "No correr backtests sin pedido explícito.",
    "No promover baseline sin audit.json y comparaciones SPY diaria, mensual y anual.",
    "No cambiar state/current_parent.json sin aprobación manual explícita.",
    "No modificar lógica de backtesting desde tareas de análisis/contexto.",
    "Comparar siempre contra SPY; SPY es el costo de oportunidad.",
    "Costos obligatorios: 0.24% compra + 0.24% venta.",
    "Python calcula; agentes leen evidencia compacta y deciden.",
]

GLOBAL_DO_NOT_READ = [
    "data/*.csv y data/**/*.csv salvo resumen puntual generado por Python.",
    "runs/** completo.",
    "runs/*/trades.csv, equity_curve.csv o spy_comparison_daily.csv salvo anomalía puntual justificada.",
    "reports/** grandes o históricos no relacionados con la tarea.",
    "runs.zip u otros dumps comprimidos.",
]

TOKEN_WARNINGS = [
    "Leer primero este context pack, no el repo entero.",
    "Para runs, pedir summary.md + metrics.json + audit.json antes de cualquier CSV.",
    "Si falta evidencia, reportar missing y parar; no compensar leyendo carpetas enormes.",
    "Pedir a Python un resumen nuevo cuando la evidencia compacta sea insuficiente.",
    "Mantener respuestas y decisiones breves: evidencia, decisión, próximo paso.",
]


ROLES: dict[str, dict[str, Any]] = {
    "coordinator": {
        "title": "Coordinator",
        "role": "Orquestar research, decidir próximo paso y mantener estado simple.",
        "can_read": [
            "SPEC.md",
            "AGENTS.md",
            "configs/project_config.json",
            "state/*.json compactos",
            "runs/*/summary.md",
            "runs/*/metrics.json",
            "runs/*/audit.json",
        ],
        "inputs": ["objetivo de research", "estado actual", "evidencia compacta de runs", "restricciones de promoción"],
        "outputs": ["decisión breve", "siguiente acción", "rechazo/follow-up justificado", "cambio de estado solo si fue aprobado"],
        "checklist": [
            "¿Existe audit.json?",
            "¿Existe comparación SPY diaria, mensual y anual?",
            "¿La decisión respeta current_parent bloqueado/manual?",
            "¿La próxima acción necesita Python o agente?",
        ],
    },
    "analyst": {
        "title": "Analyst",
        "role": "Convertir evidencia/bibliografía en hipótesis testeables.",
        "can_read": [
            "SPEC.md",
            "configs/strategy_registry.json si la tarea lo exige",
            "state/parameter_effect_memory.json",
            "state/rejected_candidates.json",
            "resúmenes bibliográficos provistos por usuario",
        ],
        "inputs": ["principio causal", "familia de estrategia", "evidencia compacta previa", "restricciones de riesgo"],
        "outputs": ["hipótesis compacta", "parámetros candidatos", "racional causal", "riesgos esperados"],
        "checklist": [
            "¿La hipótesis tiene bibliography_basis o empirical_basis?",
            "¿El cambio no es una variante random?",
            "¿La expectativa causal es falsable?",
            "¿Se marcó concentration_risk/riskier_candidate/defensive_improvement si aplica?",
        ],
    },
    "coder": {
        "title": "Coder",
        "role": "Implementar utilidades Python pequeñas, testeables y sin dependencias pesadas.",
        "can_read": [
            "SPEC.md",
            "AGENTS.md",
            "scripts/*.py puntuales",
            "backtester/*.py solo si la tarea lo exige",
            "tests/*.py puntuales",
            "configs/*.json puntuales",
        ],
        "inputs": ["contrato de cambio", "archivos puntuales", "criterios de aceptación", "restricciones de no tocar trading logic"],
        "outputs": ["script/utilidad pequeña", "reporte generado", "errores claros si faltan archivos", "sin cambios de baseline/parent"],
        "checklist": [
            "¿El cambio es chico y reversible?",
            "¿Usa Python estándar cuando alcanza?",
            "¿Evita modificar backtesting si no fue pedido?",
            "¿Reporta missing sin fallar innecesariamente?",
        ],
    },
    "executor": {
        "title": "Executor",
        "role": "Ejecutar corridas aprobadas y producir artefactos comparables.",
        "can_read": [
            "configs/*.json aprobados",
            "state/current_baseline.json",
            "state/current_parent.json",
            "scripts Python necesarios",
            "datos de entrada validados por Python",
        ],
        "inputs": ["run_id aprobado", "strategy_config aprobada", "project_config", "datos validados"],
        "outputs": [
            "spy_comparison_daily.csv",
            "spy_comparison_monthly.csv",
            "spy_comparison_yearly.csv",
            "metrics.json",
            "audit.json",
            "summary.md",
        ],
        "checklist": [
            "¿La corrida fue explícitamente aprobada?",
            "¿Costos 0.24% por lado aplicados?",
            "¿Se generaron todos los artefactos SPY?",
            "¿No tomó decisiones de promoción?",
        ],
    },
    "auditor": {
        "title": "Auditor",
        "role": "Revisar sesgos, costos, robustez y confiabilidad antes de decidir.",
        "can_read": [
            "SPEC.md",
            "runs/*/summary.md",
            "runs/*/metrics.json",
            "runs/*/audit.json",
            "runs/*/spy_comparison_monthly.csv si summary/audit no alcanza",
            "runs/*/spy_comparison_yearly.csv si summary/audit no alcanza",
            "tests relevantes puntuales",
        ],
        "inputs": ["run_id", "strategy_id", "summary", "metrics", "audit", "comparación SPY compacta"],
        "outputs": ["rejected", "accepted_for_followup", "promoted_to_baseline solo con evidencia completa", "razones concretas"],
        "checklist": [
            "¿Hay lookahead, leakage, survivorship u overfitting?",
            "¿Ganó contra SPY por varios años o por un outlier?",
            "¿Costos aplicados?",
            "¿Drawdown/retorno justifican follow-up?",
        ],
    },
    "librarian": {
        "title": "Librarian",
        "role": "Mantener bibliografía, taxonomía y memoria conceptual ordenadas.",
        "can_read": [
            "SPEC.md",
            "configs/strategy_registry.json",
            "notas bibliográficas provistas",
            "state/rejected_candidates.json",
            "state/parameter_effect_memory.json",
        ],
        "inputs": ["paper/nota", "familia de estrategia", "hipótesis existentes", "rechazos previos"],
        "outputs": ["referencias normalizadas", "familias de estrategia", "duplicados conceptuales", "cooldown sugerido"],
        "checklist": [
            "¿La referencia tiene source_id?",
            "¿La familia ya existe?",
            "¿Hay duplicado conceptual?",
            "¿La evidencia previa pide cooldown?",
        ],
    },
    "literature_researcher": {
        "title": "Literature Researcher",
        "role": "Convertir bibliografía y evidencia empírica en hipótesis testeables, no ideas vagas.",
        "can_read": [
            "bibliography/sources.yaml",
            "bibliography/extracted_principles.jsonl",
            "bibliography/hypothesis_bank.jsonl",
            "state/learning_memory.json",
            "state/evidence_memory.json",
            "state/rejected_hypotheses.jsonl",
            "state/accepted_hypotheses.jsonl",
        ],
        "inputs": ["source_id o run_id", "principio extraído", "aprendizaje previo", "familia objetivo"],
        "outputs": ["hipótesis con basis", "source_id/run_id/learning_id", "flags de riesgo", "cooldown si corresponde"],
        "checklist": [
            "¿Tiene bibliography_basis o empirical_basis?",
            "¿No es variante random?",
            "¿Incluye flags concentration_risk/riskier_candidate/defensive_improvement si aplica?",
            "¿No promueve baseline?",
        ],
    },
}


def read_text(path: Path) -> tuple[str, str]:
    if not path.exists():
        return "missing", ""
    try:
        return "ok", path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return "ok", path.read_text(encoding="latin-1")
    except Exception as exc:
        return f"error: {exc}", ""


def read_json(path: Path) -> tuple[str, dict[str, Any]]:
    status, text = read_text(path)
    if status != "ok":
        return status, {}
    try:
        return "ok", json.loads(text)
    except Exception as exc:
        return f"error: {exc}", {}


def bullet(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def source_status() -> dict[str, str]:
    return {rel: read_text(REPO_ROOT / rel)[0] for rel in SOURCE_FILES}


def compact_state() -> dict[str, Any]:
    project_status, project = read_json(REPO_ROOT / "configs" / "project_config.json")
    parent_status, parent = read_json(REPO_ROOT / "state" / "current_parent.json")
    baseline_status, baseline = read_json(REPO_ROOT / "state" / "current_baseline.json")
    research_status, research = read_json(REPO_ROOT / "state" / "research_state.json")
    notes = research.get("notes", []) if isinstance(research.get("notes"), list) else []
    return {
        "project_config_status": project_status,
        "project_name": project.get("project_name", "missing"),
        "benchmark_ticker": project.get("benchmark_ticker", "missing"),
        "cost_per_side_pct": project.get("cost_per_side_pct", "missing"),
        "initial_capital": project.get("initial_capital", "missing"),
        "rebalance_frequency": project.get("rebalance_frequency", "missing"),
        "signal_frequency": project.get("signal_frequency", "missing"),
        "execution_frequency": project.get("execution_frequency", "missing"),
        "current_parent_status": parent_status,
        "current_parent_run_id": parent.get("current_parent_run_id", "missing"),
        "current_parent_strategy_id": parent.get("current_parent_strategy_id", "missing"),
        "parent_updates_require_manual_approval": parent.get("parent_updates_require_manual_approval", "missing"),
        "parent_promotion_blocked": parent.get("parent_promotion_blocked", "missing"),
        "current_baseline_status": baseline_status,
        "current_baseline_run_id": baseline.get("current_baseline_run_id", "missing"),
        "current_baseline_strategy_id": baseline.get("current_baseline_strategy_id", "missing"),
        "baseline_reason": baseline.get("reason", "missing"),
        "research_state_status": research_status,
        "loop_status": research.get("loop_status", "missing"),
        "active_strategy_family": research.get("active_strategy_family", "missing"),
        "last_run_id": research.get("last_run_id", "missing"),
        "mode": research.get("mode", "missing"),
        "recent_notes": notes[-8:],
    }


def render_state_section(state: dict[str, Any]) -> str:
    lines = [
        "## Estado actual relevante",
        "",
        f"- Project: `{state['project_name']}` ({state['project_config_status']})",
        f"- Benchmark: `{state['benchmark_ticker']}`",
        f"- Cost per side: `{state['cost_per_side_pct']}%`",
        f"- Frequencies: signal `{state['signal_frequency']}`, rebalance `{state['rebalance_frequency']}`, execution `{state['execution_frequency']}`",
        f"- Current parent: `{state['current_parent_run_id']}` / `{state['current_parent_strategy_id']}` ({state['current_parent_status']})",
        f"- Parent manual approval required: `{state['parent_updates_require_manual_approval']}`",
        f"- Parent promotion blocked: `{state['parent_promotion_blocked']}`",
        f"- Current baseline: `{state['current_baseline_run_id']}` / `{state['current_baseline_strategy_id']}` ({state['current_baseline_status']})",
        f"- Baseline reason: {state['baseline_reason']}",
        f"- Research loop: `{state['loop_status']}`, mode `{state['mode']}`, active family `{state['active_strategy_family']}`, last run `{state['last_run_id']}` ({state['research_state_status']})",
    ]
    if state["recent_notes"]:
        lines.extend(["", "### Recent compact notes"])
        lines.extend(f"- {note}" for note in state["recent_notes"])
    return "\n".join(lines)


def render_source_section(statuses: dict[str, str]) -> str:
    lines = ["## Source file availability", ""]
    for rel, status in statuses.items():
        lines.append(f"- `{rel}`: {status}")
    return "\n".join(lines)


def render_role_pack(name: str, spec: dict[str, Any], state: dict[str, Any], statuses: dict[str, str]) -> str:
    no_read = list(GLOBAL_DO_NOT_READ)
    if name != "coder":
        no_read.append("backtester/*.py salvo pedido explícito y acotado.")
        no_read.append("scripts/*.py completos salvo script puntual relacionado.")
    if name != "executor":
        no_read.append("datos de entrada crudos para backtests.")

    lines = [
        f"# {spec['title']} Context Pack",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Rol del agente",
        "",
        spec["role"],
        "",
        "## Qué archivos puede leer",
        "",
        bullet(spec["can_read"]),
        "",
        "## Qué archivos NO debe leer",
        "",
        bullet(no_read),
        "",
        "## Inputs mínimos esperados",
        "",
        bullet(spec["inputs"]),
        "",
        "## Outputs esperados",
        "",
        bullet(spec["outputs"]),
        "",
        "## Reglas duras",
        "",
        bullet(COMMON_HARD_RULES),
        "",
        render_state_section(state),
        "",
        "## Checklist de decisión",
        "",
        bullet(spec["checklist"]),
        "",
        "## Advertencias para ahorrar tokens",
        "",
        bullet(TOKEN_WARNINGS),
        "",
        render_source_section(statuses),
        "",
    ]
    return "\n".join(lines)


def render_repo_pack(state: dict[str, Any], statuses: dict[str, str]) -> str:
    lines = [
        "# Repository Context Pack",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Decisión central",
        "",
        "Este repo usa Python para calcular y agentes para decidir sobre evidencia compacta. Nada se promueve sin auditoría y comparación completa contra SPY.",
        "",
        "## Reglas duras globales",
        "",
        bullet(COMMON_HARD_RULES),
        "",
        "## Lectura recomendada mínima",
        "",
        bullet(
            [
                "Este repo_context_pack.md.",
                "Context pack específico del rol.",
                "Para una corrida: runs/<run_id>/summary.md, metrics.json y audit.json.",
                "Solo después, monthly/yearly SPY CSV si el resumen no alcanza.",
            ]
        ),
        "",
        "## No leer por defecto",
        "",
        bullet(GLOBAL_DO_NOT_READ),
        "",
        render_state_section(state),
        "",
        "## Roles disponibles",
        "",
        bullet([f"`{key}`: {value['role']}" for key, value in ROLES.items()]),
        "",
        "## Token discipline",
        "",
        bullet(TOKEN_WARNINGS),
        "",
        render_source_section(statuses),
        "",
    ]
    return "\n".join(lines)


def render_readme() -> str:
    role_files = {
        "coordinator": "coordinator_context.md",
        "analyst": "analyst_context.md",
        "coder": "coder_context.md",
        "executor": "executor_context.md",
        "auditor": "auditor_context.md",
        "librarian": "librarian_context.md",
        "literature_researcher": "literature_researcher_context.md",
    }
    lines = [
        "# Context Packs",
        "",
        "Usá estos packs para darle a Codex el contexto justo según el rol. La idea es simple: menos repo entero, más contrato compacto.",
        "",
        "## Qué pasarle a Codex según la tarea",
        "",
        "| Tarea | Archivo recomendado |",
        "|---|---|",
        "| Orientación general del repo | `repo_context_pack.md` |",
        "| Decidir próximo paso de research | `coordinator_context.md` |",
        "| Crear hipótesis desde evidencia | `analyst_context.md` |",
        "| Escribir scripts/utilidades | `coder_context.md` |",
        "| Ejecutar corridas aprobadas | `executor_context.md` |",
        "| Auditar resultados | `auditor_context.md` |",
        "| Ordenar bibliografía/taxonomía | `librarian_context.md` |",
        "| Convertir papers en hipótesis | `literature_researcher_context.md` |",
        "",
        "## Cuándo usar cada context pack",
        "",
    ]
    for key, file_name in role_files.items():
        lines.append(f"- `{file_name}`: {ROLES[key]['role']}")
    lines.extend(
        [
            "",
            "## Cómo evitar lectura innecesaria de CSV/runs",
            "",
            "1. Pasá primero `repo_context_pack.md` + el pack del rol.",
            "2. Para una corrida, pedí solo `summary.md`, `metrics.json` y `audit.json`.",
            "3. Si falta evidencia anual/mensual, recién ahí permitir `spy_comparison_yearly.csv` o `spy_comparison_monthly.csv`.",
            "4. No leer `spy_comparison_daily.csv`, `trades.csv` o `equity_curve.csv` salvo anomalía puntual.",
            "5. Si hace falta detalle pesado, pedí un script Python que genere un resumen chico.",
            "",
            "## Qué agente usar por problema",
            "",
            "- ¿No sabés qué hacer después? `Coordinator`.",
            "- ¿Querés una hipótesis nueva? `Analyst` o `Literature Researcher`.",
            "- ¿Hay que crear un script o utilidad? `Coder`.",
            "- ¿Hay que correr una estrategia aprobada? `Executor`.",
            "- ¿Hay que decidir si un resultado sirve? `Auditor`.",
            "- ¿Hay duplicados conceptuales o bibliografía desordenada? `Librarian`.",
            "",
            "## Regla práctica",
            "",
            "Si Codex pide leer un CSV grande, exigile primero que explique qué pregunta concreta no puede responder con los packs, `summary.md`, `metrics.json` y `audit.json`. Esto no es burocracia: es arquitectura. Si no cuidás el contexto, el agente se vuelve caro, lento y peor.",
            "",
        ]
    )
    return "\n".join(lines)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def main() -> int:
    statuses = source_status()
    state = compact_state()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    outputs: list[Path] = []
    repo_pack = OUTPUT_DIR / "repo_context_pack.md"
    write(repo_pack, render_repo_pack(state, statuses))
    outputs.append(repo_pack)

    for role_name, role_spec in ROLES.items():
        out = OUTPUT_DIR / f"{role_name}_context.md"
        write(out, render_role_pack(role_name, role_spec, state, statuses))
        outputs.append(out)

    readme = OUTPUT_DIR / "README_CONTEXT_PACKS.md"
    write(readme, render_readme())
    outputs.append(readme)

    print("Generated context packs:")
    for path in outputs:
        print(f"- {path.relative_to(REPO_ROOT)} ({line_count(path)} lines)")
    print()
    print("Recommended use:")
    print("- Start with reports/context_packs/repo_context_pack.md.")
    print("- Add exactly one role pack for the task.")
    print("- For run analysis, add only summary.md, metrics.json, and audit.json before any CSV.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
