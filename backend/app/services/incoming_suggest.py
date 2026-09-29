"""Подсказка отдела и плательщика для входящей корреспонденции.

Адаптация маршрутизации agent-pochta (RuleRouter + keyword-RAG) на локальных данных
из data/pochta: deterministic_sales_rules.json → routing_rules.json (content_rules)
→ rag_department_keywords.json → резерв «Управление делами». Без Qdrant/BGE/LLM:
в agent-pochta эти слои — fallback, детерминированный каскад покрывает основную массу.

Подсказка только ПРЕДЗАПОЛНЯЕТ форму: предлагаются исключительно отделы,
сопоставленные с 1С (есть GUID в odata_department_keys.json), без руководства.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from app.services.erp_incoming import (
    ORG_FULL_NAMES,
    _load_json_map,
    _pochta_data_dir,
    _resolve_payer_direction,
)

RESERVE_DEPARTMENT_CODE = "00-000066"

# Руководство — в agent-pochta допускается только для info@turbo-don.ru;
# ручная регистрация в оркестраторе идёт из личных ящиков, поэтому не подсказываем.
LEADERSHIP_DEPARTMENT_CODES = frozenset({"00-000001", "00-000152", "00-000182"})

# Как agent-pochta routing/organizations.py: направление XML по коду отдела.
_COMMERCIAL_DEPARTMENT_CODES = frozenset(
    {"00-000015", "00-000042", "00-000054", "00-000058", "00-000076", "00-000155"}
)
_PRODUCTION_DIRECTION_DEPARTMENT_CODES = frozenset({"00-000065"})
_KS_DIRECTION_DEPARTMENT_CODES = frozenset(
    {"00-000001", "00-000152", "00-000182", "00-000044"}
)
_ORG_AS_DIRECTION = frozenset({"АЛ", "МГ", "АМ", "МИ", "БМ"})
_DIRECTION_DEFAULT = "ПР"
_DIRECTION_UNCLEAR = "КС"

_ORG_FROM_RECIPIENT = (("almaz", "АЛ"), ("mgs_", "МГ"), ("mgs@", "МГ"))

# Домены/TLD, не считающиеся зарубежными (как deterministic_sales.py).
_DOMESTIC_DOMAIN_SUFFIXES = (
    ".com.ru",
    ".net.ru",
    ".org.ru",
    ".pp.ru",
    ".ru",
    ".рф",
    ".su",
    ".by",
    ".kz",
    ".uz",
)
_EMAIL_DOMAIN_RE = re.compile(r"[\w.+-]+@([\w.-]+\.[\w.-]+)", re.IGNORECASE)


@dataclass
class _Candidate:
    code: str
    name: str
    direction: str
    source: str
    reasoning: str
    score: float
    organization: str | None = None
    matched_keywords: list[str] = field(default_factory=list)


def _load_json(name: str) -> Any:
    path = _pochta_data_dir() / name
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


@lru_cache(maxsize=1)
def _routing_rules() -> dict[str, Any]:
    data = _load_json("routing_rules.json")
    return data if isinstance(data, dict) else {}


@lru_cache(maxsize=1)
def _sales_rules() -> dict[str, Any]:
    data = _load_json("deterministic_sales_rules.json")
    return data if isinstance(data, dict) else {}


@lru_cache(maxsize=1)
def _rag_keywords() -> dict[str, list[str]]:
    data = _load_json("rag_department_keywords.json")
    if not isinstance(data, dict):
        return {}
    return {
        str(code): [str(kw) for kw in keywords if str(kw).strip()]
        for code, keywords in data.items()
        if isinstance(keywords, list)
    }


@lru_cache(maxsize=1)
def _payer_display() -> dict[str, str]:
    data = _load_json("odata_payer_direction_display.json")
    if not isinstance(data, dict):
        return {}
    return {str(code): str(name) for code, name in data.items()}


def reset_suggest_caches() -> None:
    _routing_rules.cache_clear()
    _sales_rules.cache_clear()
    _rag_keywords.cache_clear()
    _payer_display.cache_clear()


def _normalize_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def _keyword_in_text(keyword: str, text: str) -> bool:
    """Как agent-pochta normalize.py: короткие токены — только по границам слова."""
    kw = (keyword or "").lower().strip()
    if not kw:
        return False
    if len(kw) <= 3:
        return bool(re.search(rf"(?<![а-яёa-z0-9]){re.escape(kw)}(?![а-яёa-z0-9])", text))
    return kw in text


def _hits(markers: list[Any], text: str) -> list[str]:
    found: list[str] = []
    for marker in markers:
        value = str(marker or "").strip().lower()
        if value and _keyword_in_text(value, text):
            found.append(value)
    return found


def detect_organization(text: str, *, recipient: str = "") -> str:
    """Как RouteEngine.detect_organization: маркеры получателя, затем ключевые слова."""
    recipient_low = (recipient or "").lower()
    for marker, org in _ORG_FROM_RECIPIENT:
        if marker in recipient_low:
            return org
    normalized = _normalize_text(text)
    org_keywords = _routing_rules().get("organization_keywords") or {}
    scored: list[tuple[int, str]] = []
    if isinstance(org_keywords, dict):
        for org, keywords in org_keywords.items():
            active = [str(kw).strip() for kw in (keywords or []) if str(kw).strip()]
            found = [kw for kw in active if _keyword_in_text(kw, normalized)]
            if found:
                scored.append((max(len(kw) for kw in found), str(org)))
    if scored:
        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored[0][1]
    return "НП"


def _normalize_domain(raw: str) -> str:
    host = (raw or "").strip().lower().rstrip(".,;:)>\"'")
    if host.startswith("www."):
        host = host[4:]
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    return host


def _is_domestic_domain(domain: str, exclude: set[str]) -> bool:
    if not domain or domain in exclude:
        return True
    for suffix in _DOMESTIC_DOMAIN_SUFFIXES:
        if domain == suffix.lstrip(".") or domain.endswith(suffix):
            return True
    return False


def _foreign_domains(text: str, sender_email: str) -> list[str]:
    """Зарубежные домены в from/тексте — hard-foreign признак для ВЭД."""
    rules = _sales_rules()
    exclude = {str(d).lower() for d in (rules.get("foreign_exclude_domains") or [])}
    domains: set[str] = set()
    if "@" in (sender_email or ""):
        domains.add(_normalize_domain(sender_email))
    for match in _EMAIL_DOMAIN_RE.finditer(text or ""):
        domains.add(_normalize_domain(match.group(1)))
    return sorted(
        domain
        for domain in domains
        if domain and "." in domain and not _is_domestic_domain(domain, exclude)
    )


def _match_deterministic_sales(text: str, sender_email: str) -> _Candidate | None:
    """Порт match_deterministic_sales (без leadership-веток info@)."""
    cfg = _sales_rules()
    if not cfg:
        return None

    # 1) Продуктовые правила по приоритету (БМИ, бытовые, СПУ, сервис).
    commercial_markers = (
        "ткп",
        "коммерческ",
        "кп ",
        "запрос цен",
        "счет",
        "счёт",
        "ценовое",
        "стоимость",
    )
    product_rules = sorted(
        cfg.get("product_rules") or [],
        key=lambda rule: int(rule.get("priority") or 100),
    )
    for rule in product_rules:
        found = _hits(list(rule.get("keywords") or []), text)
        if not found:
            continue
        if rule.get("id") == "bmi_equipment" and any(
            _keyword_in_text(marker, text) for marker in commercial_markers
        ):
            return _Candidate(
                code="00-000128",
                name="Отдел продаж БМИ",
                direction="БМ",
                source="det_product_bmi_equipment_commercial",
                reasoning="Коммерческий запрос на оборудование БМИ",
                score=0.9,
                organization="БМ",
                matched_keywords=found,
            )
        return _Candidate(
            code=str(rule["department_id"]),
            name=str(rule.get("department_name") or rule["department_id"]),
            direction=str(rule.get("direction") or _DIRECTION_DEFAULT),
            source=f"det_product_{rule.get('id') or 'x'}",
            reasoning=str(rule.get("reasoning") or "product"),
            score=0.9,
            organization=rule.get("organization"),
            matched_keywords=found,
        )

    # 2) Продажи: нужен sales-context или явный dealer/gazprom/orkk маркер.
    sales_hits = _hits(list(cfg.get("sales_context_markers") or []), text)
    dealer_hits = _hits(list(cfg.get("dealer_markers") or []), text)
    industrial_hits = _hits(list(cfg.get("industrial_markers") or []), text)
    gazprom_hits = _hits(list(cfg.get("gazprom_markers") or []), text)
    orkk_hits = _hits(list(cfg.get("orkk_holdings") or []), text)
    orkk_request_hits = _hits(list(cfg.get("orkk_request_markers") or []), text)
    spu_hits = _hits(
        ["спу", "стационарная поверочная", "поверочная установка", "spu-5", "spu 5"],
        text,
    )
    if not (
        sales_hits or dealer_hits or gazprom_hits or orkk_hits or orkk_request_hits or spu_hits
    ):
        return None

    # Зарубежный контур → ВЭД (только при hard foreign домене, как антиложный ВЭД).
    foreign = _foreign_domains(text, sender_email)
    if foreign and bool(cfg.get("ved_deterministic_routing_enabled", False)):
        return _Candidate(
            code=str(cfg.get("foreign_department_id") or "00-000015"),
            name=str(cfg.get("foreign_department_name") or "ВЭД"),
            direction=_DIRECTION_DEFAULT,
            source="det_sales_foreign",
            reasoning="Зарубежный домен + коммерческий контекст → ВЭД",
            score=0.85,
            matched_keywords=foreign,
        )

    if spu_hits:
        return _Candidate(
            code="00-000074",
            name="Отдел продаж эталонного оборудования и услуг",
            direction=_DIRECTION_DEFAULT,
            source="det_sales_spu",
            reasoning="СПУ → отдел продаж эталонного оборудования",
            score=0.85,
            matched_keywords=spu_hits,
        )
    if dealer_hits:
        return _Candidate(
            code=str(cfg.get("dealer_department_id") or "00-000155"),
            name=str(cfg.get("dealer_department_name") or "Отдел дилерских продаж"),
            direction=_DIRECTION_DEFAULT,
            source="det_sales_dealer",
            reasoning="Гранд / UFG-H → отдел дилерских продаж",
            score=0.85,
            matched_keywords=dealer_hits,
        )
    if orkk_request_hits:
        return _Candidate(
            code=str(cfg.get("orkk_department_id") or "00-000042"),
            name=str(cfg.get("orkk_department_name") or "ОРКК"),
            direction=_DIRECTION_DEFAULT,
            source="det_sales_orkk_request",
            reasoning="ТКП / запрос поставки → ОРКК",
            score=0.85,
            matched_keywords=orkk_request_hits,
        )
    if gazprom_hits:
        return _Candidate(
            code=str(cfg.get("gazprom_department_id") or "00-000076"),
            name=str(cfg.get("gazprom_department_name") or "Отдел по работе с ПАО Газпром"),
            direction=_DIRECTION_DEFAULT,
            source="det_sales_gazprom",
            reasoning="Газпром / дочерние общества → ОПГ",
            score=0.85,
            matched_keywords=gazprom_hits,
        )
    if orkk_hits:
        return _Candidate(
            code=str(cfg.get("orkk_department_id") or "00-000042"),
            name=str(cfg.get("orkk_department_name") or "ОРКК"),
            direction=_DIRECTION_DEFAULT,
            source="det_sales_orkk",
            reasoning="Ключевой холдинг → ОРКК",
            score=0.8,
            matched_keywords=orkk_hits,
        )
    if industrial_hits and sales_hits:
        return _Candidate(
            code=str(cfg.get("orkk_department_id") or "00-000042"),
            name=str(cfg.get("orkk_department_name") or "ОРКК"),
            direction=_DIRECTION_DEFAULT,
            source="det_sales_industrial",
            reasoning="Промышленная тематика без холдинга → ОРКК",
            score=0.7,
            matched_keywords=industrial_hits,
        )
    return None


def _content_rule_candidates(text: str) -> list[_Candidate]:
    """content_rules из routing_rules.json — счёт по количеству/длине совпадений."""
    rules = _routing_rules().get("content_rules") or []
    names = _department_names()
    found: list[_Candidate] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        hits = _hits(list(rule.get("keywords") or []), text)
        if not hits:
            continue
        code = str(rule.get("code") or "").strip()
        if not code:
            continue
        score = min(0.5 + 0.1 * len(hits), 0.8)
        found.append(
            _Candidate(
                code=code,
                name=str(rule.get("name") or names.get(code) or code),
                direction=str(rule.get("direction") or _DIRECTION_DEFAULT),
                source="content",
                reasoning=f"Совпадение по содержимому: {', '.join(hits[:5])}",
                score=score,
                organization=rule.get("organization"),
                matched_keywords=hits,
            )
        )
    found.sort(key=lambda c: (-len(c.matched_keywords), -max(len(k) for k in c.matched_keywords)))
    return found


def _rag_keyword_candidates(text: str) -> list[_Candidate]:
    """Keyword-RAG fallback: скоринг по rag_department_keywords.json."""
    names = _department_names()
    found: list[_Candidate] = []
    for code, keywords in _rag_keywords().items():
        hits = _hits(keywords, text)
        if not hits:
            continue
        found.append(
            _Candidate(
                code=code,
                name=names.get(code, code),
                direction=_DIRECTION_DEFAULT,
                source="keyword_rag",
                reasoning=f"Ключевые слова отдела: {', '.join(hits[:5])}",
                score=min(0.35 + 0.05 * len(hits), 0.6),
                matched_keywords=hits,
            )
        )
    found.sort(
        key=lambda c: (
            -sum(max(len(k) - 3, 1) for k in c.matched_keywords),
            -len(c.matched_keywords),
        )
    )
    return found


def _department_names() -> dict[str, str]:
    from app.services.erp_incoming import _load_department_names

    return _load_department_names()


def _resolve_direction(candidate: _Candidate, organization: str) -> str:
    """Порт resolve_direction_for_department: коммерция → ПР, руководство/юристы → КС."""
    if organization in _ORG_AS_DIRECTION:
        return organization
    code = candidate.code
    if code in _KS_DIRECTION_DEPARTMENT_CODES:
        return _DIRECTION_UNCLEAR
    if code in _COMMERCIAL_DEPARTMENT_CODES:
        return _DIRECTION_DEFAULT
    if code in _PRODUCTION_DIRECTION_DEPARTMENT_CODES:
        return _DIRECTION_DEFAULT
    direction = (candidate.direction or "").strip().upper()
    if candidate.source == "reserve":
        return _DIRECTION_UNCLEAR
    return direction or _DIRECTION_DEFAULT


def _reserve_candidate() -> _Candidate:
    names = _department_names()
    return _Candidate(
        code=RESERVE_DEPARTMENT_CODE,
        name=names.get(RESERVE_DEPARTMENT_CODE, "Управление делами"),
        direction=_DIRECTION_UNCLEAR,
        source="reserve",
        reasoning="Резервный маршрут: явных правил не найдено",
        score=0.2,
    )


def _mapped_to_onec(code: str, department_keys: dict[str, str]) -> bool:
    return bool(department_keys.get(code, "").strip())


def suggest_incoming_route(
    *,
    subject: str = "",
    body: str = "",
    sender_email: str = "",
    sender_name: str = "",
    recipient: str = "",
) -> dict[str, Any]:
    """Каскад подсказки: det sales → content rules → keyword RAG → резерв.

    Возвращает только отделы с GUID в odata_department_keys.json и без руководства.
    """
    text = _normalize_text(f"{subject} {body} {sender_name}")
    department_keys = _load_json_map("odata_department_keys.json")

    ordered: list[_Candidate] = []
    det = _match_deterministic_sales(text, sender_email)
    if det is not None:
        ordered.append(det)
    ordered.extend(_content_rule_candidates(text))
    ordered.extend(_rag_keyword_candidates(text))
    ordered.append(_reserve_candidate())

    # Только сопоставленные с 1С и не руководство; без дублей.
    seen: set[str] = set()
    allowed: list[_Candidate] = []
    for candidate in ordered:
        code = candidate.code
        if code in seen:
            continue
        seen.add(code)
        if code in LEADERSHIP_DEPARTMENT_CODES:
            continue
        if not _mapped_to_onec(code, department_keys):
            continue
        allowed.append(candidate)
    if not allowed:
        allowed = [_reserve_candidate()]

    primary = allowed[0]
    organization = primary.organization or detect_organization(text, recipient=recipient)
    if organization not in ORG_FULL_NAMES:
        organization = "НП"
    direction = _resolve_direction(primary, organization)
    payer_code = _resolve_payer_direction(organization, direction)
    payer_names = _payer_display()

    return {
        "summary": (
            f"Подсказка: {primary.name} / {payer_names.get(payer_code, payer_code)}"
        ),
        "department": {"code": primary.code, "name": primary.name},
        "organization": {
            "code": organization,
            "name": ORG_FULL_NAMES.get(organization, organization),
        },
        "direction": direction,
        "payer": {"code": payer_code, "name": payer_names.get(payer_code, payer_code)},
        "confidence": round(primary.score, 2),
        "source": primary.source,
        "reasoning": primary.reasoning,
        "matched_keywords": primary.matched_keywords[:10],
        "candidates": [
            {"code": c.code, "name": c.name, "source": c.source, "score": round(c.score, 2)}
            for c in allowed[:5]
        ],
        "payer_options": [
            {"code": code, "name": name} for code, name in payer_names.items()
        ],
    }


def handle_incoming_suggest(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    """Инструмент onec.incoming_suggest: подсказка отдела/плательщика по письму."""
    return suggest_incoming_route(
        subject=str(args.get("subject") or args.get("theme") or ""),
        body=str(args.get("body") or args.get("text") or args.get("content") or ""),
        sender_email=str(args.get("sender_email") or args.get("email_sender") or ""),
        sender_name=str(args.get("sender") or args.get("sender_name") or ""),
        recipient=str(args.get("recipient") or args.get("email_recipient") or ""),
    )
