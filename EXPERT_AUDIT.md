# OCR Service — Expert Audit (3 perspectives consolidées)

> Audit cross-fonctionnel mené par 3 experts en parallèle (Senior Python Dev, Software Architect, Code Reviewer) sur `/ocr-service`. Les P0 du précédent audit (auth constant-time, rate-limit branché, bomb cap, locks PaddleOCR, deadline globale, log 500s, README) ont déjà été appliqués — ce document liste **ce qu'il reste pour atteindre la perfection**.

**Date** : 2026-05-18
**Périmètre** : `/Users/Apple/Desktop/ocr-turbodrive/ocr-service/` (~1 800 LoC, 52 tests verts)

---

## Verdict consolidé

| Expert | Note | Verdict en 1 ligne |
|---|---|---|
| 🐍 Senior Python Dev | **6.5 / 10** | Solide sur les P0, mais event loop bloqué, `Any` partout, schemas mal câblés, aucun outillage (ruff/mypy/lockfile). |
| 🏛️ Software Architect | **6.5 / 10** | Monolithe FastAPI bien tenu, pas un microservice "parfait" : God-Function dans le router, parser 850 LoC, pas de tracing, pas de plan de scale-out. |
| 🔍 Code Reviewer | **6.5 / 10** | Plusieurs vrais bugs (1 reproductible en 500), `_AR_LETTER` matche de la ponctuation, lifecycle d'init/fixtures fragiles. |

**Moyenne consolidée : 6.5/10** — code "bon stagiaire/junior+" mais pas encore "production-grade exemplaire".

---

## 🔥 Bugs vérifiés (reproductibles maintenant)

### 🐛 BUG-1 — Crash 500 sur date février invalide ✅ REPRODUIT
**Fichier** : [utils/parser.py:209](utils/parser.py#L209) + [utils/parser.py:469](utils/parser.py#L469)

`_to_iso_date()` valide `1 ≤ day ≤ 31` indépendamment du mois → accepte `29-02-2023`, retourne `"2023-02-29"`. Ensuite `_iso_to_date()` appelle `datetime.date(2023, 2, 29)` qui lève `ValueError: day is out of range for month` → 500 non géré au client.

**Reproduction** (testée live) :
```python
parse_fields("PERMIS 11111111 5. 29-02-2023 4a. 10-06-2020 4b. 09-06-2028 B", "permis")
# → ValueError: day is out of range for month
```
**Fix** : valider via `datetime.date(year, month, day)` dans `_to_iso_date`, retourner `None` sur `ValueError`.

### 🐛 BUG-2 — `_AR_LETTER` matche de la ponctuation
**Fichier** : [utils/parser.py:22-28](utils/parser.py#L22-L28)

La classe couvre `[؀-ٟ]` qui inclut `،` (U+060C), `؟` (U+061F), `؛`, U+0600 (Arabic Number Sign), et `ـ` (tatweel U+0640 = allongement calligraphique, pas une lettre). Donc `_AR_WORD = {_AR_LETTER}{2,}` matche `"،،،"` ou `"ـــ"` comme des "mots" arabes → pollue le fallback word-order.

**Fix** : restreindre aux **lettres seulement** :
```python
_AR_LETTER = "[ء-غف-يٱ-ۓݐ-ݿﭐ-﷿ﹰ-ﻼ]"
```

### 🐛 BUG-3 — `_parse_assurance` lookbehind 1-char trop permissif
**Fichier** : [utils/parser.py:805](utils/parser.py#L805)

`(?<=[Dd])({_DATE_LOOSE})` matche **toute** lettre D/d collée : `"DAR25/10/2025"`, `"ID25/10/2025"`, `"BAD25/10/2025"` extraient une `date_debut` bidon.

**Fix** : ancrer sur `\bDu?\b` explicitement, supprimer le lookbehind 1-char.

### 🐛 BUG-4 — `unhandled_exception_handler` renvoie 500 mais code mappé à 502
**Fichier** : [errors.py:90-97](errors.py#L90-L97) + [errors.py:22-32](errors.py#L22-L32)

Le handler force `status_code=500` mais utilise le code `OCR_ENGINE_FAILURE` qui dans `_HTTP_STATUS_MAP` est mappé à **502**. Incohérence côté client. **Fix** : nouveau code `OCR_INTERNAL → 500`.

### 🐛 BUG-5 — Fallback Latin CIN capture la chaîne entière
**Fichier** : [utils/parser.py:709-714](utils/parser.py#L709-L714)

`_find_uppercase_names("12345678 OMRI SALAH 03-03-1985 SFAX VILLE")` retourne `["OMRI SALAH SFAX VILLE"]` (un seul match groupant tous les mots majuscules). `legacy[0]` devient `nom="OMRI SALAH SFAX VILLE"`, `prenom=None`. Le test `test_cin_governorate_match_within_text` ne couvre pas ce cas car il n'asserte que `gouvernorat`.

**Fix** : split sur whitespace, filtrer les gouvernorats avant assignation.

### 🐛 BUG-6 — Event loop bloqué (perf critique)
**Fichier** : [routers/ocr.py:23-138](routers/ocr.py#L23-L138)

La route est `async def` mais (a) `preprocess_image(...)` est CPU sync (~50-200 ms PIL+numpy), (b) `run_ocr(...)` fait `fut.result(timeout=...)` qui **bloque l'event loop uvicorn pendant jusqu'à 45 s**. Une requête bloquée fige toutes les autres (y compris `/health/ready`). En charge, throughput effondré.

**Fix** :
```python
img_array = await asyncio.to_thread(preprocess_image, image_bytes)
# run_ocr → async + loop.run_in_executor + asyncio.wait(timeout=...)
```

### 🐛 BUG-7 — Date non-ISO retournée dans le fallback CIN Latin
**Fichier** : [utils/parser.py:730](utils/parser.py#L730)

```python
date_naissance = _to_iso_date(day, month, year) or m.group(1)
```
Si `_to_iso_date` retourne `None` (date invalide), on conserve la string brute du match (`"31/04/2025"`). Contrat "toutes les dates en ISO" cassé silencieusement.

**Fix** : `date_naissance = _to_iso_date(day, month, year)` (laisser `None` si invalide).

---

## 🎯 Top 20 issues prioritaires (toutes catégories confondues)

| # | Sév | Catégorie | Fichier:ligne | Issue | Fix court |
|---|---|---|---|---|---|
| 1 | 🔴 P0 | Bug | parser.py:209 | Crash 500 sur date Feb-29 non bissextile | `datetime.date()` validation |
| 2 | 🔴 P0 | Perf | routers/ocr.py:23 | Event loop bloqué par sync code | `asyncio.to_thread` + executor |
| 3 | 🔴 P0 | Bug | parser.py:22 | `_AR_LETTER` matche ponctuation | restreindre aux lettres |
| 4 | 🔴 P0 | Bug | parser.py:805 | Lookbehind `(?<=[Dd])` faux positif | ancrer sur `\bDu?\b` |
| 5 | 🔴 P0 | Bug | errors.py:90 | 500 vs 502 incohérent | code `OCR_INTERNAL` distinct |
| 6 | 🔴 P0 | Bug | parser.py:709 | Fallback Latin capture phrase entière | split whitespace + filtrer |
| 7 | 🟠 P1 | Contrat | routers/ocr.py:27 | `-> dict`, pas de `response_model` | `OCRExtractResponse` strict |
| 8 | 🟠 P1 | Sécurité | image_processor.py:23 | Capture `DecompressionBombError` seule | + `UnidentifiedImageError`, `OSError` |
| 9 | 🟠 P1 | Archi | routers/ocr.py | God-Function 130 LoC | extraire `OCRExtractUseCase` |
| 10 | 🟠 P1 | Code mort | schemas.py:50 | `from typing import Union` au milieu | virer + `X \| Y` partout |
| 11 | 🟠 P1 | Type | ocr_engine.py:28 | `_ocr_fr: Any` partout | `Protocol` PaddleEngine |
| 12 | 🟠 P1 | Lifecycle | ocr_engine.py:43 | `_executor` créé à l'import | recréer dans `lifespan` |
| 13 | 🟠 P1 | Outillage | absence | Pas de ruff/mypy/pyproject/lockfile | `pyproject.toml` + `uv` + CI |
| 14 | 🟠 P1 | Perf | parser.py | Regex non compilées en hot-path | `re.compile()` module-level |
| 15 | 🟡 P2 | Archi | parser.py | 857 LoC monolithique | split `parsers/{doc_type}.py` |
| 16 | 🟡 P2 | Observ | absence | Pas d'OpenTelemetry/tracing | `opentelemetry-instrumentation-fastapi` |
| 17 | 🟡 P2 | Sec/PII | router log:107 | `raw_text`/noms loggués en clair | redactor middleware |
| 18 | 🟡 P2 | Robustesse | parser.py:67 | `[float(s) for s in scores]` sans garde | check len + `try/except` |
| 19 | 🟡 P2 | Test | absence | Pas de test 429 rate-limit | test après middleware |
| 20 | 🟡 P2 | Style | parser.py:9 | `_UPPERCASE_WORD` dead code | supprimer |

---

## 🐍 Perspective Senior Python Dev (consensus)

### Ce qui hurle
- **Event loop bloqué** (BUG-6 ci-dessus) — issue n°1 perf.
- **`Any` partout** dans `ocr_engine.py` pour les moteurs PaddleOCR : remplacer par `Protocol`.
- **`schemas.py:50`** : `from typing import Union # noqa: E402` au milieu du fichier alors que `X | Y` est utilisé partout ailleurs. *Indéfendable.*
- **`response_model` absent** sur `/ocr/extract` → `/docs` montre `data: dict` opaque, Pydantic ne valide rien.
- **Pas de `pyproject.toml`**, pas de lockfile, pas de séparation prod/dev.
- **Aucun outillage** : ruff, black, mypy, pre-commit, pip-audit, bandit.
- **Regex non compilées** dans la hot-path — `re.search/findall` avec pattern littéral à chaque appel sur ~40 patterns × 30 req/min = pression sur le cache LRU de `re`. Compiler au module-level.
- **`pydantic-settings` non idiomatique** : `validate_runtime()` à la main au lieu de `@model_validator(mode="after")`. Pas de `SecretStr`. Pas de `Field(min_length=32)` sur `INTERNAL_SECRET`. Pas de bornes sur `MAX_UPLOAD_BYTES`.
- **`prefetch_models.py:15`** force `use_textline_orientation=True` indépendamment du `OCR_USE_ORIENTATION_DETECTION` settings → drift prefetch/runtime.
- **Pas de tests `hypothesis`** sur les parsers de dates (combinatoire) ni `@pytest.mark.integration` avec un vrai PaddleOCR derrière un flag.

### Détails à fixer
- `pytest.ini:6` — `ignore::DeprecationWarning` trop large, masque les deprecations critiques (pydantic v3 prep).
- `tests/_helpers.py:21` — `make_oversize` non utilisé (dead code).
- `tests/conftest.py:63` — `Iterator[callable]` doit être `Iterator[Callable[[str], None]]`.
- `middleware/logging.py:19` — `asctime` pas time-zoned → passer en ISO-8601 UTC.
- `from __future__ import annotations` présent dans certains fichiers, absent dans `main.py`/`routers/ocr.py`/`metrics.py` → incohérent.
- Aucun module ne déclare `__all__`.

---

## 🏛️ Perspective Software Architect (consensus)

### Vue d'ensemble actuelle (problèmes structurels)

```
HTTP ─► RequestIDMW ─► SlowAPIMW ─► routers/ocr.py (FAIT TOUT)
                                       │
                ┌──────────────────────┼─────────────────────┐
                ▼                      ▼                     ▼
        validation+IO           preprocess_image       ocr_engine.run_ocr
        (doc_type, ct, size,    (PIL, numpy)           (ThreadPool x2,
         body cap)                                      fr+ar locks, deadline)
                                                              │
                                                              ▼
                                                       utils/parser.parse_fields
                                                       (_PARSERS dict, 850 LOC regex)
                                                              │
                                                              ▼
                                                       metrics + JSON log + dict
```

**Constat** : `routers/ocr.py` orchestre 6 préoccupations (God-Function). `ocr_engine.py` mélange singleton + threading + business rule (`confidence_to_status`). `parser.py` est un fourre-tout 32 KB.

### 10 violations architecturales

1. **SRP / Hexagonal** : Router fait validation + IO + OCR + parsing + metrics + logging. Pas de couche service/domaine.
2. **OCP / Strategy** : `_PARSERS = dict` + `_AR_ONLY_DOC_TYPES` éparpillés. Ajouter un doc_type = toucher 6 fichiers.
3. **Domain Model** : `dict` partout malgré `schemas.py` (`PermisData`, etc.) défini mais inutilisé.
4. **Scalabilité** : engines PaddleOCR stateful in-process + `ThreadPool(2)` global → service mono-replica de fait.
5. **Observability** : pas de tracing W3C `traceparent`/OTel, pas de SLO, métriques business absentes.
6. **RGPD / PII** : `raw_text`, noms, dates loggués en JSON clair, pas de redactor.
7. **Sécurité système** : secrets `.env` en clair, pas de KMS/Vault, pas de mTLS Node↔Python, pas d'audit log.
8. **Résilience** : `lifespan` crash-loop sans backoff si PaddleOCR fail, pas de bulkhead fr/ar (`ThreadPool` partagé).
9. **API contract** : `response_model` absent → OpenAPI faux. Pas de stratégie de versionning documentée.
10. **Déploiement** : image mono-stage avec 500 MB de modèles bakés, pas de séparation prefetch/runtime.

### Architecture cible "perfect"

```
                ┌─────────────────────────────────────────┐
                │  presentation/ (FastAPI routers, DTOs)   │
                │  - response_model strict + OpenAPI       │
                └────────────────┬────────────────────────┘
                                 │ cmd: ExtractDocumentCommand
                                 ▼
                ┌─────────────────────────────────────────┐
                │  application/use_cases/                  │
                │  ExtractDocumentUseCase                  │
                │  (orchestre pipeline, retourne Result)   │
                └──┬─────────┬──────────┬──────────────┬───┘
                   │         │          │              │
                   ▼         ▼          ▼              ▼
            ┌──────────┐ ┌────────┐ ┌─────────┐ ┌──────────────┐
            │ domain/  │ │ ports/ │ │ ports/  │ │ ports/       │
            │ DocType  │ │OCREngn │ │ Parser  │ │MetricsRecord │
            │Confidence│ │Port    │ │Registry │ │              │
            │OCRResult │ └───▲────┘ └────▲────┘ └─────▲────────┘
            └──────────┘     │           │            │
                             │           │            │
          ┌──────────────────┼───────────┼────────────┼───────────────┐
          │ infrastructure/ adapters                                  │
          │  ├─ paddle_engine.py (pool, bulkhead, lifecycle)          │
          │  ├─ parsers/{permis,cin,carte_grise,assurance}/parser.py  │
          │  ├─ prometheus_metrics.py                                 │
          │  ├─ otel_tracing.py                                       │
          │  └─ redis_idempotency.py                                  │
          └──────────────────────────────────────────────────────────┘

  Cross-cutting: OTel traces, PII-redacted logs, audit log
                 mTLS via mesh, Vault secrets, queue async optionnelle
```

### Patterns à appliquer
- **Strategy + Registry** : `@register("permis")` décorateur sur chaque `BaseParser`.
- **Pipeline / Chain of Responsibility** : `Preprocess → OCR → Parse → Validate → Score`.
- **Result/Either** : remplacer le `try/except` cascade du router.
- **Factory** : `EngineFactory.create("fr"|"ar"|"gpu")` pour swap PaddleOCR ↔ Tesseract ↔ Textract sans toucher au use-case.
- **Bulkhead** : 2 `ThreadPoolExecutor` séparés fr/ar (un fr bloqué ne starve plus ar).
- **Idempotency-Key** : header + cache Redis 60 s.

---

## 🔍 Perspective Code Reviewer (consensus)

### Edge cases non couverts (tests à ajouter)
- ✅ **Image PNG corrompue** / bytes aléatoires avec `Content-Type: image/jpeg` → doit retourner 400, pas 500.
- ✅ **`Content-Length: -1`**, header dupliqué.
- ✅ **Multipart avec 2 parts `file`** — comportement non spécifié.
- ✅ **`doc_type=PERMIS`** (majuscules) — policy case-sensitive à confirmer.
- ✅ **`predict()` renvoie** `[]`, `[None]`, `[{"rec_texts": None}]`, scores avec `None`.
- ✅ **NFC vs NFD** sur `بن علي` (`unicodedata.normalize`).
- ✅ **Marqueurs LRM (`‎`) / RLM (`‏`) / ZWJ (`‍`)** au milieu des noms arabes.
- ✅ **Date `9999-99-99`** ou `00/00/0000` par OCR fantaisiste.
- ✅ **Année `2026-02-29`** non bissextile (BUG-1 ci-dessus).
- ✅ **CIN avec uniquement chiffres arabes** pour numéro **ET** date.
- ✅ **Image WebP animée** (multi-frame) — `image.load()` ne charge que la 1re.
- ✅ **Engine timeout** → assert que `cancel()` est bien appelé sur les futures restantes.
- ✅ **`test_metric_incremented_on_extract`** (vérifier `ocr_field_present_total`).
- ✅ **`test_request_id_propagated_in_error_envelope`** (header présent quand 4xx/5xx).
- ✅ **Test 429** après le rate-limit P0 (manquant alors qu'on l'a livré).

### Bugs latents complémentaires
- **`ocr_engine.py:67`** — `[float(s) for s in scores]` sans garde : `None`/str non-numérique → crash. `zip(texts, scores)` tronque silencieusement si longueurs différentes → confidence biaisée sans warning.
- **`ocr_engine.py:124`** — `_AR_ONLY_DOC_TYPES` testé avant validation `doc_type`. Si on factorise et appelle `run_ocr` directement avec invalide, on tombe dans le else (2 engines) silencieusement.
- **`middleware/auth.py:22`** — `if ENV=="dev" and not INTERNAL_SECRET`: si quelqu'un démarre en `ENV=dev` sans secret par accident en prod, l'API est ouverte. `validate_runtime` ne couvre que `ENV != "dev"`.
- **`utils/parser.py:288` + `:602`** — même regex 8-digits pour CIN et permis. Si l'OCR du permis contient l'adresse du titulaire avec un code postal 8 chiffres (rare en TN mais possible sur scans), faux positif silencieux.
- **`utils/image_processor.py:16`** — `Image.MAX_IMAGE_PIXELS = _MAX_PIXELS` est un **paramètre global PIL** muté à l'import — affecte tout autre code Python du process utilisant PIL.
- **`utils/image_processor.py:38-39`** — `image.convert("L").convert("RGB")` est destructrice : perte d'info couleur (sceaux/tampons rouges des cartes grises = moins lisibles).

### Sécurité applicative
- **Aucun header de sécurité** sur les réponses (`X-Content-Type-Options: nosniff`, `Cache-Control: no-store`). Même pour une API JSON interne, c'est de la défense en profondeur — 10 lignes de middleware.
- **`file.filename` non sanitisé** : si on l'ajoute aux logs, log-injection possible via newlines. Préemptivement : `safe_filename = re.sub(r"[\r\n\x00]", "", file.filename[:120] or "")`.
- **ReDoS** : `_AR_WORD` et `_DATE_LOOSE` non audités contre catastrophic backtracking.

---

## 🛣️ Roadmap "perfect" — 3 horizons

### 🚑 Court terme — 1 sprint (les vrais P0 restants)
1. **BUG-1** : Fix `_to_iso_date` (validation `datetime.date()`).
2. **BUG-2** : Restreindre `_AR_LETTER` aux vraies lettres.
3. **BUG-3** : Ancrer le lookbehind `Du?` dans `_parse_assurance`.
4. **BUG-4** : Aligner code/status pour le 500.
5. **BUG-5** : Fixer le fallback Latin CIN.
6. **BUG-6** : Débloquer l'event loop (`asyncio.to_thread` + `run_in_executor`).
7. **BUG-7** : Supprimer le fallback non-ISO dans `_parse_cin`.
8. Brancher `response_model=OCRExtractResponse` + aligner `CINData` avec le champ `pere`.
9. Capture étendue dans `preprocess_image` (`UnidentifiedImageError`, `OSError`).
10. Tests pour le rate-limit 429, pour chacun des bugs ci-dessus, et `test_metric_incremented_on_extract`.

### 🛠️ Moyen terme — 1 trimestre
11. **`pyproject.toml`** + `uv lock` + séparation `[dev]` extras.
12. **Outillage CI** : `ruff check`, `mypy --strict` (ou pyright basic), `pre-commit`, `pip-audit`. GitHub Actions complet.
13. **Compiler les regex** au module-level dans `utils/parser.py` (~40 patterns).
14. **`Protocol` PaddleEngine** + encapsuler dans `EnginePool` dataclass injectable (fini les globals).
15. **`pydantic-settings` idiomatique** : `@model_validator(mode="after")`, `SecretStr`, `Field(min_length=32)` sur secrets, bornes sur `MAX_UPLOAD_BYTES`.
16. **OpenTelemetry FastAPI** + propagation `traceparent`.
17. **Métriques business** : `ocr_in_flight` gauge, `ocr_upload_bytes` histogram, `ocr_requests_total{doc_type, status}` counter.
18. **PII redactor middleware** sur les logs (`raw_text`, noms, dates → hash/masque selon `LOG_LEVEL`).
19. **Splitter `utils/parser.py`** en `parsers/{cin,permis,carte_grise,assurance}/parser.py` + `parsers/common.py`.
20. **Refacto router** : extraire `OCRExtractUseCase`, router = HTTP only.
21. **Multi-stage Dockerfile** : builder (deps + prefetch) + runtime slim.
22. **Tests `hypothesis`** sur `_to_iso_date`, `_compute_confidence` (bounds), `confidence_to_status` (frontières 78/55).
23. **`@pytest.mark.integration`** avec vrai PaddleOCR derrière flag.

### 🏛️ Long terme — 1 an+
24. **Mode asynchrone optionnel** : `POST /ocr/jobs` + queue ARQ/Dramatiq + worker pool indépendant (scale HTTP et CPU séparément).
25. **Plugin architecture parsers** : entry-points Python, ajout doc_type = 1 dossier, 0 fichier core touché.
26. **mTLS via service mesh** (Linkerd/Istio) + secrets via Vault avec rotation auto.
27. **Multi-tenant** : header `X-Tenant-ID` → quotas/métriques par tenant.
28. **A/B testing engines** (PaddleOCR vs Tesseract vs Textract) via `EnginePort` swappable.
29. **SLO Grafana dashboard** : p95 < 8 s, error_rate < 1 %, success_rate par doc_type > 90 %.
30. **Volume PVC modèles partagé** entre N pods K8s (pull une fois, scale fin).

---

## 📊 Trade-offs assumés (ce qu'on ne fera PAS)

| Pattern | Verdict | Raison |
|---|---|---|
| Event sourcing | ❌ Non | 4 doc_types, traffic interne — overkill. |
| CQRS | ❌ Non | Pas de séparation read/write significative. |
| gRPC | ❌ Non | REST + OpenAPI strict suffit pour le besoin Node↔Python. |
| Onion architecture 7 couches | ❌ Non | 3 niveaux (presentation/application/infrastructure) suffisent. |
| Queue async obligatoire | ⏳ Plus tard | Garder synchrone tant que p95 < 10 s. |

---

## 📁 Fichiers les plus critiques (référence rapide)

| Fichier | Verdict | Action prioritaire |
|---|---|---|
| [utils/parser.py](utils/parser.py) (857 LoC) | 🔴 3 bugs + dead code + 0 docstring module + fonctions 60-108 LoC | Fixer 4 bugs (1, 2, 3, 5, 7) → splitter en `parsers/{doc_type}.py` |
| [routers/ocr.py](routers/ocr.py) (148 LoC) | 🔴 God-Function + event loop bloqué + `-> dict` | Refacto en `OCRExtractUseCase` + `asyncio.to_thread` + `response_model` |
| [ocr_engine.py](ocr_engine.py) (140 LoC) | 🟠 `Any` partout + globals + executor module-level | `Protocol` + `EnginePool` injectable + bulkhead 2 executors fr/ar |
| [errors.py](errors.py) (95 LoC) | 🟠 500 vs 502 incohérent + except trop large | Code `OCR_INTERNAL` distinct |
| [schemas.py](schemas.py) (83 LoC) | 🟠 `Union` en plein milieu + DTOs non utilisés | Cleanup + brancher `response_model` |
| [utils/image_processor.py](utils/image_processor.py) (45 LoC) | 🟠 1 exception capturée sur 3 + mutation globale PIL | Capture étendue + isoler `MAX_IMAGE_PIXELS` |
| [config.py](config.py) (43 LoC) | 🟡 `validate_runtime` à la main, pas de `SecretStr`, pas de bornes | `@model_validator` + `SecretStr` + `Field()` bornes |
| [main.py](main.py) (95 LoC) | 🟡 `lifespan` sans retry, imports inline | `tenacity` retry, imports en tête |

---

## ✅ Checklist "perfect" (à valider une fois la roadmap terminée)

- [ ] 0 bug reproductible (les 7 listés ici fixés + tests)
- [ ] `mypy --strict` propre, `ruff check` propre
- [ ] `pip-audit` clean (0 CVE high/critical)
- [ ] `response_model` sur toutes les routes ; `/docs` OpenAPI complet
- [ ] Event loop jamais bloqué (toutes les ops > 10 ms sont `await`)
- [ ] OpenTelemetry trace bout en bout depuis le backend Node
- [ ] PII jamais logguée en clair (audit logs ≠ logs applicatifs)
- [ ] Lockfile reproductible (`uv.lock` / `requirements.lock`)
- [ ] CI GitHub Actions : `pytest` + `mypy` + `ruff` + `pip-audit` + `docker build`
- [ ] Coverage > 90 % (lignes + branches), property-based testing sur parsers de dates
- [ ] SLO documentés (p95, error_rate, success_rate par doc_type) + dashboard Grafana
- [ ] Secrets via Vault/KMS, rotation automatique, jamais dans `.env`
- [ ] Architecture hexagonale "light" : `presentation/`, `application/`, `infrastructure/`, `domain/`
- [ ] Ajout d'un 5e doc_type = 1 PR, 1 dossier `parsers/passeport/`, 0 fichier core modifié
- [ ] Graceful shutdown drainé, lifespan retry/backoff, bulkhead fr/ar

---

*Audit réalisé le 2026-05-18 par consolidation de 3 perspectives expertes (Senior Python Dev, Software Architect, Code Reviewer) lancées en parallèle. Bug-1 vérifié reproductible en direct.*
