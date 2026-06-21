# Skill Registry

**Uso exclusivo del delegador.** Quien lance subagentes debe resolver las reglas aplicables desde este archivo e inyectarlas como `## Project Standards (auto-resolved)`. Los subagentes no leen este registro ni los `SKILL.md`.

Protocolo completo: `C:\Users\celestinoh\.codex\skills\_shared\skill-resolver.md`.

## User Skills

| Trigger | Skill | Path |
|---|---|---|
| Ejecutar un candidato aprobado y generar artefactos de corrida | backtest_execution | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\skills\backtest_execution\SKILL.md` |
| Crear, abrir o preparar pull requests | branch-pr | `C:\Users\celestinoh\.config\opencode\skills\branch-pr\SKILL.md` |
| Generar el próximo candidato de research | candidate_generation | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\skills\candidate_generation\SKILL.md` |
| Caveman mode, respuestas breves, menor consumo de tokens | caveman | `C:\Users\celestinoh\.codex\skills\caveman\SKILL.md` |
| PRs de más de 400 líneas, stacked PRs, review slices | chained-pr | `C:\Users\celestinoh\.config\opencode\skills\chained-pr\SKILL.md` |
| Guías, README, RFC, onboarding, arquitectura o docs de review | cognitive-doc-design | `C:\Users\celestinoh\.config\opencode\skills\cognitive-doc-design\SKILL.md` |
| Comentarios de PR, issues, reviews o mensajes colaborativos | comment-writer | `C:\Users\celestinoh\.config\opencode\skills\comment-writer\SKILL.md` |
| Construir o iterar un juego web HTML/JS | develop-web-game | `C:\Users\celestinoh\.codex\skills\develop-web-game\SKILL.md` |
| Clasificar fallas y recuperar una corrida de research | failure_recovery | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\skills\failure_recovery\SKILL.md` |
| Tests Go, cobertura, Bubbletea, teatest o golden files | go-testing | `C:\Users\celestinoh\.config\opencode\skills\go-testing\SKILL.md` |
| Generar o editar imágenes raster | imagegen | `C:\Users\celestinoh\.codex\skills\.system\imagegen\SKILL.md` |
| Crear issues, bugs o feature requests en GitHub | issue-creation | `C:\Users\celestinoh\.config\opencode\skills\issue-creation\SKILL.md` |
| Judgment Day, revisión dual o adversarial | judgment-day | `C:\Users\celestinoh\.config\opencode\skills\judgment-day\SKILL.md` |
| Detectar candidatos sin efecto material | no_op_detection | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\skills\no_op_detection\SKILL.md` |
| OpenAI APIs, productos, Codex, modelos actuales o migraciones | openai-docs | `C:\Users\celestinoh\.codex\skills\.system\openai-docs\SKILL.md` |
| Debug interactivo de browser o Electron con Playwright | playwright-interactive | `C:\Users\celestinoh\.codex\skills\playwright-interactive\SKILL.md` |
| Crear o actualizar plugins locales de Codex | plugin-creator | `C:\Users\celestinoh\.codex\skills\.system\plugin-creator\SKILL.md` |
| Decidir rechazo, seguimiento, parent o baseline | promotion_governance | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\skills\promotion_governance\SKILL.md` |
| Evaluar robustez de resultados de trading | robustness_review | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\skills\robustness_review\SKILL.md` |
| Revisión explícita de seguridad para Python, JS/TS o Go | security-best-practices | `C:\Users\celestinoh\.codex\skills\security-best-practices\SKILL.md` |
| Crear skills o instrucciones reutilizables para agentes | skill-creator | `C:\Users\celestinoh\.config\opencode\skills\skill-creator\SKILL.md` |
| Listar o instalar skills de Codex | skill-installer | `C:\Users\celestinoh\.codex\skills\.system\skill-installer\SKILL.md` |
| Comparar cualquier estrategia contra SPY | spy_comparison | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\skills\spy_comparison\SKILL.md` |
| Convertir bibliografía en reglas de trading testeables | strategy_from_bibliography | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\skills\strategy_from_bibliography\SKILL.md` |
| Desplegar una aplicación o sitio en Vercel | vercel-deploy | `C:\Users\celestinoh\.codex\skills\vercel-deploy\SKILL.md` |
| Dividir implementación y commits en unidades revisables | work-unit-commits | `C:\Users\celestinoh\.config\opencode\skills\work-unit-commits\SKILL.md` |

## Compact Rules

### backtest_execution
- Ejecutá únicamente candidatos previamente aprobados.
- Validá columnas mínimas `date`, `ticker` y `close`.
- Abortá ante equity vacía, SPY ausente o precio diario inexistente tras la señal.
- Generá equity, trades, métricas, comparaciones SPY diaria/mensual/anual y resumen.
- No imprimas CSV completos; priorizá `summary.md`, `metrics.json` y JSON compactos.
- La ejecución produce evidencia, nunca promueve estrategias.

### branch-pr
- Todo PR debe vincular un issue aprobado con `Closes`, `Fixes` o `Resolves`.
- Usá exactamente una etiqueta `type:*` y el template del repositorio.
- Nombrá branches como `type/description`, en minúsculas y con Conventional Commit types.
- Usá commits convencionales; nunca agregues atribución de IA.
- Ejecutá los checks requeridos antes de declarar el PR listo.
- No abras PRs vacíos ni sin vínculo a un issue `status:approved`.

### candidate_generation
- Cambiá una variable principal por candidato; dos como máximo.
- Consultá rechazos y cooldowns antes de reutilizar una idea.
- Preferí cambios causales a búsquedas aleatorias de parámetros.
- Cada candidato debe declarar parent, cambios, motivo y efecto esperado.
- No repitas candidatos rechazados.
- No generes candidatos sin una hipótesis causal verificable.

### caveman
- Respondé con máxima concisión sin perder exactitud técnica.
- Eliminá relleno, cortesías, repeticiones y hedging innecesario.
- Conservá términos técnicos, código y errores textuales sin deformarlos.
- Usá frases completas cuando seguridad, irreversibilidad o secuencias complejas lo exijan.
- No apliques estilo caveman a commits, PRs ni código.
- Mantené el nivel elegido hasta que el usuario pida volver al modo normal.

### chained-pr
- Dividí PRs de más de 400 líneas salvo `size:exception` explícita.
- Mantené cada PR revisable en aproximadamente 60 minutos.
- Cada PR representa una unidad entregable con sus tests y docs.
- Declarà inicio, fin, dependencias, fuera de alcance y trabajo posterior.
- Eliminá diffs contaminados mediante retarget o rebase.
- No mezcles estrategias de cadena una vez elegida.

### cognitive-doc-design
- Abrí con la decisión, resultado o acción; el contexto viene después.
- Aplicá divulgación progresiva: camino feliz, detalles, edge cases y referencias.
- Dividí contenido en secciones cortas, tablas y checklists.
- Preferí reconocimiento sobre memoria: ejemplos concretos y plantillas.
- Indicá qué revisar primero y qué queda fuera de alcance.
- Diseñá la documentación para que el reviewer no reconstruya la intención.

### comment-writer
- Empezá por el punto accionable; no recapitules todo el contexto.
- Mantené tono cálido, directo y breve.
- Explicá la razón técnica cuando pidas un cambio.
- Priorizá el problema de mayor valor; evitá acumular preferencias menores.
- Escribí en el idioma del hilo y usá voseo natural en español.
- No uses em dash; preferí puntos, comas o paréntesis.

### develop-web-game
- Implementá cambios pequeños y repetí: actuar, pausar, observar y ajustar.
- Exponé `window.render_game_to_text` con estado visible y accionable.
- Preferí `window.advanceTime(ms)` para pasos deterministas.
- Ejecutá el cliente Playwright después de cada cambio significativo.
- Inspeccioná screenshots, estado textual y errores de consola; no supongas resultados.
- Registrá progreso, decisiones y pendientes en `progress.md`.

### failure_recovery
- Clasificá cada falla como fatal, recuperable, de datos o candidato no material.
- Registrá el tipo antes de decidir retry, rechazo o cooldown.
- Conservá logs y resúmenes compactos.
- Nunca sobrescribas artefactos útiles de una corrida.
- No inventes datos faltantes ni relances a ciegas.
- Un problema de datos bloquea cualquier conclusión.

### go-testing
- Preferí tests table-driven con `t.Run`.
- Testeá comportamiento y transiciones, no detalles internos.
- Usá `t.TempDir()` para filesystem; nunca el home real.
- Hacé skippable lo lento o externo con `testing.Short()`.
- Probá `Model.Update()` directamente; reservá `teatest` para interacción completa.
- Actualizá goldens solo por el flujo `-update` y revalidá sin ese flag.

### imagegen
- Usá `image_gen` integrado por defecto para generación y edición raster.
- No reemplaces SVG, HTML/CSS o assets vectoriales editables con bitmaps generados.
- Para editar un archivo local, cargalo primero con `view_image`.
- Tratá transparencia con chroma key y postproceso; pedí confirmación antes de degradar a CLI/modelo alternativo.
- Inspeccioná composición, texto e invariantes antes de aceptar un resultado.
- Copiá assets consumidos por el proyecto al workspace y reportá sus rutas.

### issue-creation
- Buscá duplicados antes de crear un issue.
- Usá siempre el template de bug o feature; los issues en blanco están deshabilitados.
- Completá todos los campos y prechecks obligatorios.
- Todo issue nuevo comienza como `status:needs-review`.
- Esperá `status:approved` antes de abrir un PR.
- Derivá preguntas generales a Discussions.

### judgment-day
- Resolvé e inyectá las mismas reglas de proyecto a ambos jueces.
- Lanzá dos jueces ciegos en paralelo y esperá ambos resultados.
- Confirmá solo issues reproducibles en uso normal; degradá hipótesis teóricas a INFO.
- Pedí aprobación antes de corregir hallazgos confirmados de la primera ronda.
- Rejuzgá con ambos jueces después de cualquier fix.
- Cerrá únicamente como `JUDGMENT: APPROVED` o `JUDGMENT: ESCALATED`.

### no_op_detection
- Compará señales, trades, métricas y SPY contra el parent.
- Etiquetá no-ops como `signal_no_effect`, `trade_no_effect`, `metric_no_effect` o duplicado.
- Un cambio cosmético de configuración no cuenta como comportamiento nuevo.
- `metric_no_effect` no puede mover el parent.
- Rechazá o enfriá candidatos sin efecto material.
- Conservá evidencia compacta de la comparación.

### openai-docs
- Para Codex general, consultá primero el manual oficial mediante el helper local.
- Para otras APIs OpenAI, usá Docs MCP y obtené la página relevante antes de responder.
- Para modelos actuales, verificá `latest-model.md`; no confíes en memoria.
- Preservá modelos objetivo explícitos y mantené migraciones acotadas.
- Restringí el fallback web a dominios oficiales de OpenAI y citá fuentes.
- No inventes precios, disponibilidad, parámetros ni breaking changes.

### playwright-interactive
- Requiere `js_repl`; reutilizá handles persistentes y evitá resets rutinarios.
- Definí un inventario de QA que cubra requisitos, comportamiento y claims finales.
- Reutilizá browser/context/page; recargá renderer o relanzá proceso según el cambio.
- Separá QA funcional de QA visual.
- Probá controles con input normal y al menos dos escenarios fuera del happy path.
- Verificá viewport y capturá evidencia antes del cierre.

### plugin-creator
- Creá siempre `.codex-plugin/plugin.json` con nombre normalizado igual al directorio.
- Usá los scripts de scaffold; no dejes placeholders `TODO`.
- No declares `apps` o `mcpServers` sin crear sus archivos asociados.
- Usá marketplace personal por defecto; repo/team solo por pedido explícito.
- Para actualizar plugins existentes, usá cachebuster y flujo de reinstalación.
- Validá el plugin con `scripts/validate_plugin.py` antes de entregarlo.

### promotion_governance
- Decidí explícitamente entre rechazo, seguimiento, candidato promovido y baseline.
- Exigí `audit.json`, comparaciones SPY diaria/mensual/anual, costos y cero warnings críticos.
- Nunca movás baseline sin auditoría.
- Nunca auto-promuevas a baseline.
- `can_promote_baseline` permanece falso hasta que exista gobernanza manual.
- Falta de evidencia implica rechazo o seguimiento, no promoción.

### robustness_review
- Revisá consistencia anual y mensual, drawdown, trades y exceso sobre SPY.
- Detectá dependencia de un año aislado o de pocos trades.
- Marcá sensibilidad grande a parámetros como riesgo.
- Clasificá `pass`, `weak` o `fail` con razones verificables.
- No rescates resultados pobres con narrativa.
- Evidencia primero, interpretación después.

### security-best-practices
- Activá revisión completa solo ante pedido explícito de seguridad.
- Detectá todos los lenguajes/frameworks y cargá únicamente referencias aplicables.
- Priorizá hallazgos por severidad e incluí impacto y líneas de código.
- Escribí el reporte en markdown y resumí su ubicación.
- Pedí confirmación antes de aplicar fixes del reporte.
- Corregí un hallazgo por vez y preservá funcionalidad.

### skill-creator
- Creá skills solo para patrones repetibles o decisiones no triviales.
- Tratá `SKILL.md` como contrato para LLM, no como tutorial.
- Usá frontmatter YAML válido y descripción trigger-first en una sola línea.
- Estructurá: Activation, Hard Rules, Decision Gates, Steps, Output y References.
- Mové ejemplos, schemas y detalle extenso a `assets/` o `references/`.
- Registrá skills de proyecto en `AGENTS.md`.

### skill-installer
- Listá `.curated` por defecto y `.experimental` solo cuando se solicite.
- Usá los scripts incluidos para listar o instalar; no recrees el instalador.
- Instalá desde nombre curado o ruta GitHub explícita.
- No sobrescribas un skill existente silenciosamente.
- Explicá errores de red/autenticación y el fallback a sparse checkout.
- Indicá reiniciar Codex después de instalar.

### spy_comparison
- Toda estrategia debe compararse contra SPY diaria, mensual y anualmente.
- Reportá CAGR y drawdown de estrategia y benchmark.
- Leé primero summary SPY, métricas y resumen de corrida.
- Retorno nominal positivo no alcanza.
- Rechazá si gana menos que SPY sin reducir riesgo de forma fuerte.
- Sin comparación SPY, la estrategia se rechaza.

### strategy_from_bibliography
- Extraé una sola hipótesis testeable por tarjeta.
- Mapeá señal, frecuencia, holding, riesgo y benchmark a columnas disponibles.
- No inventes datos ni features ausentes.
- Declarà bibliografía, edge esperado y riesgos conocidos.
- No afirmes resultados de backtest sin una corrida real.
- Si faltan datos, marcá `blocked_by_data`.

### vercel-deploy
- Usá el script de deploy provisto por el skill.
- Desplegá en preview salvo que el usuario pida producción.
- No bloquees esperando estado; devolvé URL y claim link.
- Si falla, explicá el error concreto y el próximo paso.
- No asumas autenticación o configuración inexistente.
- Reportá claramente el alcance desplegado.

### work-unit-commits
- Cada commit representa un comportamiento, fix, migración o unidad documental entregable.
- No dividas por tipo de archivo; mantené código, tests y docs de la unidad juntos.
- Cada commit debe poder revisarse y revertirse sin arrastrar trabajo ajeno.
- Usá mensajes Conventional Commits que describan el resultado.
- Convertí unidades en PRs encadenados si el cambio supera 400 líneas.
- No agregues `Co-Authored-By` ni atribución de IA.

## Project Conventions

| File | Path | Notes |
|---|---|---|
| AGENTS.md | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\AGENTS.md` | Índice principal de reglas, roles y evidencia |
| SPEC.md | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\SPEC.md` | Contrato funcional y criterios de research |
| AGENTS.md | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\AGENTS.md` | Referenciado por el índice |
| configs/*.json | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\configs\*.json` | Configuración de estrategias y proyecto |
| state/*.json | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\state\*.json` | Estado compacto para agentes |
| runs/*/summary.md | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\runs\*\summary.md` | Primera evidencia a leer |
| runs/*/metrics.json | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\runs\*\metrics.json` | Métricas calculadas |
| runs/*/audit.json | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\runs\*\audit.json` | Evidencia obligatoria de auditoría |
| state/research_state.json | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\state\research_state.json` | Estado del research |
| state/current_parent.json | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\state\current_parent.json` | Parent vigente |
| configs/strategy_registry.json | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\configs\strategy_registry.json` | Catálogo de estrategias |
| state/parameter_effect_memory.json | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\state\parameter_effect_memory.json` | Memoria causal de parámetros |
| state/rejected_candidates.json | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\state\rejected_candidates.json` | Historial de rechazos |
| backtester/*.py | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\backtester\*.py` | Motor de backtest |
| scripts/*.py | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\scripts\*.py` | Entrypoints y orquestación |
| tests/*.py | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\tests\*.py` | Suite pytest |
| state/current_baseline.json | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\state\current_baseline.json` | Baseline vigente |
| configs/project_config.json | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\configs\project_config.json` | Configuración global |
| bibliography/sources.yaml | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\bibliography\sources.yaml` | Fuentes bibliográficas |
| bibliography/extracted_principles.jsonl | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\bibliography\extracted_principles.jsonl` | Principios extraídos |
| bibliography/hypothesis_bank.jsonl | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\bibliography\hypothesis_bank.jsonl` | Banco de hipótesis |
| state/learning_memory.json | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\state\learning_memory.json` | Aprendizaje persistido |
| state/evidence_memory.json | `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\state\evidence_memory.json` | Evidencia persistida |

Leé estas convenciones antes de delegar trabajo. Las reglas centrales son: Python calcula, agentes leen evidencia compacta; no correr backtests sin pedido explícito; no promover sin auditoría y comparación SPY; código y JSON en inglés; documentación puede estar en español; costo obligatorio de 0,24% por lado.
