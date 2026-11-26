"""Análise das notícias com inteligência artificial (planos gratuitos de várias plataformas).

Todas as plataformas aceitam o formato da API da OpenAI (`POST <base>/chat/completions`), por isso há uma só ligação,
só com a biblioteca padrão (funciona também no Android). Em Definições escolhe-se a plataforma principal, uma
alternativa (usada quando a principal falha ou atinge o limite do dia), a chave de cada uma e o modelo.

Só se enviam as notícias (títulos, resumos, fonte e data), que são públicas; os valores da carteira nunca saem da
aplicação. A análise fica guardada e só se volta a pedir quando há notícias novas (ou com «Analisar outra vez»).
"""
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from ..models import NewsItem, Setting

# plataforma: (nome, endereço base, modelo por omissão, variável de ambiente da chave, onde se pede a chave)
PROVIDERS = {
    "gemini": ("Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-flash-latest",
               "GEMINI_API_KEY", "https://aistudio.google.com/apikey"),
    "groq": ("Groq", "https://api.groq.com/openai/v1", "openai/gpt-oss-120b", "GROQ_API_KEY",
             "https://console.groq.com/keys"),
    "openrouter": ("OpenRouter", "https://openrouter.ai/api/v1", "openrouter/free", "OPENROUTER_API_KEY",
                   "https://openrouter.ai/settings/keys"),
    "mistral": ("Mistral", "https://api.mistral.ai/v1", "mistral-small-latest", "MISTRAL_API_KEY",
                "https://console.mistral.ai/api-keys"),
    "ollama": ("Ollama (no computador)", "http://localhost:11434/v1", "llama3.2", None, "https://ollama.com/download"),
}
KEY_RE = re.compile(r"^[A-Za-z0-9_\-.:]{8,200}$")
TIMEOUT = 90
DAYS = 7               # notícias dos últimos dias
PER_TICKER = 12        # no máximo por ativo
MAX_NEWS = 120         # no máximo por análise (os planos gratuitos limitam os tokens)
SUMMARY_CHARS = 280
SCOPES = {"carteira": "Os meus ativos", "mercado": "Mercado", "radar": "Radar"}
TONES = ("positivo", "neutro", "negativo", "misto")


class AiError(Exception):
    """Falha ao pedir a análise, com uma mensagem legível. `limited`: a plataforma limitou os pedidos."""

    def __init__(self, message, limited=False):
        super().__init__(message)
        self.limited = limited


# ------------------------------------------------------------------ configuração
def api_key(provider):
    env = PROVIDERS[provider][3]
    return (env and os.environ.get(env)) or Setting.get(f"ai_key_{provider}") or None


def key_from_env(provider):
    env = PROVIDERS[provider][3]
    return bool(env and os.environ.get(env))


def needs_key(provider):
    return PROVIDERS[provider][3] is not None


def model(provider):
    return Setting.get(f"ai_model_{provider}") or PROVIDERS[provider][2]


def base_url(provider):
    if provider == "ollama":
        return (Setting.get("ai_ollama_url") or PROVIDERS["ollama"][1]).rstrip("/")
    return PROVIDERS[provider][1]


def primary():
    p = Setting.get("ai_provider")
    return p if p in PROVIDERS else None


def fallback():
    p = Setting.get("ai_fallback")
    return p if p in PROVIDERS and p != primary() else None


def ready(provider):
    return provider in PROVIDERS and (not needs_key(provider) or bool(api_key(provider)))


def chain():
    """As plataformas a tentar, por ordem (só as que têm chave)."""
    return [p for p in (primary(), fallback()) if p and ready(p)]


def enabled():
    return bool(chain())


def settings_view():
    """O que a página de Definições mostra de cada plataforma."""
    return {"primary": primary(), "fallback": fallback(), "ollama_url": base_url("ollama"),
            "providers": [{"key": p, "name": v[0], "default_model": v[2], "model": model(p), "signup": v[4],
                           "needs_key": needs_key(p), "env": key_from_env(p), "saved": bool(Setting.get(f"ai_key_{p}")),
                           "env_name": v[3]} for p, v in PROVIDERS.items()]}


# ------------------------------------------------------------------ pedido
def _post(provider, messages, opener=None):
    body = json.dumps({"model": model(provider), "messages": messages, "temperature": 0.2}).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "PortfolioInvestimentos"}
    key = api_key(provider)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if provider == "openrouter":
        headers["X-Title"] = "Portfolio Investimentos"
    req = urllib.request.Request(f"{base_url(provider)}/chat/completions", data=body, headers=headers)
    name = PROVIDERS[provider][0]
    try:
        with (opener or urllib.request.build_opener()).open(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            err = json.loads(exc.read().decode() or "{}")
            err = err[0] if isinstance(err, list) and err else err
            detail = ((err.get("error") or {}).get("message") if isinstance(err.get("error"), dict)
                      else err.get("error") or err.get("message") or "")
        except (ValueError, AttributeError):
            pass
        hint = {401: "chave inválida", 403: "chave sem acesso a este modelo", 404: "modelo inexistente",
                429: "limite de pedidos atingido; tenta mais tarde"}.get(exc.code, "")
        msg = f"{name}: HTTP {exc.code}" + (f" ({hint})" if hint else "") + (f": {str(detail)[:200]}" if detail else "")
        raise AiError(msg, limited=exc.code == 429) from exc
    except (OSError, ValueError) as exc:
        raise AiError(f"{name}: sem ligação ({getattr(exc, 'reason', exc)})") from exc
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise AiError(f"{name}: resposta inesperada") from exc


def complete(messages, opener=None):
    """Pede uma resposta à plataforma principal e, se falhar, à alternativa. Devolve (texto, plataforma)."""
    providers = chain()
    if not providers:
        raise AiError("Escolhe uma plataforma de IA e indica a chave em Definições → Inteligência artificial.")
    errors = []
    for p in providers:
        try:
            return _post(p, messages, opener), p
        except AiError as exc:
            errors.append(str(exc))
    raise AiError(" · ".join(errors), limited=False)


# ------------------------------------------------------------------ análise das notícias
SYSTEM = (
    "És um analista financeiro que escreve em português europeu (de Portugal, nunca do Brasil). Recebes notícias "
    "recentes sobre ações e ETF e tiras conclusões curtas, factuais e prudentes para um investidor particular de "
    "longo prazo. Baseia-te só nas notícias dadas; não inventes números nem factos; quando as notícias não chegam "
    "para concluir, diz isso. Não dês ordens de compra ou venda. Responde só com um objeto JSON válido, sem texto "
    "à volta."
)
FORMAT = (
    'Formato da resposta: {"resumo": "3 a 5 frases com o essencial do conjunto", "ativos": [{"ticker": "...", '
    '"tom": "positivo|neutro|negativo|misto", "conclusao": "2 a 3 frases", "riscos": ["..."], '
    '"a_verificar": ["o que vale a pena confirmar ou acompanhar"], "noticias": [números das notícias usadas]}]}. '
    "Um elemento em «ativos» por ativo com notícias relevantes (no mercado, um por tema), do mais importante para "
    "o menos importante; ignora notícias repetidas ou sem interesse."
)


def news_for(tickers=None, market=False, now=None):
    """As notícias a analisar: dos últimos `DAYS` dias, das fontes ligadas, no máximo `PER_TICKER` por ativo."""
    from . import news
    since = (now or datetime.now()) - timedelta(days=DAYS)
    q = NewsItem.query.filter(NewsItem.published >= since, NewsItem.provider.in_(news.selected()))
    q = q.filter(NewsItem.ticker == "") if market else q.filter(NewsItem.ticker.in_(tickers or [""]))
    out, per, seen = [], {}, set()
    for n in q.order_by(NewsItem.published.desc()).all():
        title = re.sub(r"\s+", " ", n.headline or "").strip().lower()
        if title in seen or per.get(n.ticker, 0) >= PER_TICKER:
            continue  # a mesma notícia em duas fontes conta uma vez
        seen.add(title)
        per[n.ticker] = per.get(n.ticker, 0) + 1
        out.append(n)
        if len(out) >= MAX_NEWS:
            break
    return out


def _prompt(rows, names, scope):
    lines = []
    for i, n in enumerate(rows, 1):
        summary = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", n.summary or "")).strip()[:SUMMARY_CHARS]
        who = n.ticker or "Mercado"
        if n.ticker and names.get(n.ticker):
            who += f" ({names[n.ticker]})"
        lines.append(f"[{i}] {who} · {n.published:%d/%m} · {n.source or '—'} · {n.headline}"
                     + (f" — {summary}" if summary else ""))
    what = {"carteira": "dos ativos da minha carteira", "mercado": "do mercado em geral",
            "radar": "das ações que estou a acompanhar (ainda não as tenho)"}[scope]
    return f"Notícias {what}, dos últimos {DAYS} dias:\n\n" + "\n".join(lines) + "\n\n" + FORMAT


def _parse(text):
    """O objeto JSON da resposta (tolera blocos ```json e texto à volta)."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise AiError("A IA não devolveu uma análise no formato esperado. Tenta outra vez.")
    try:
        data = json.loads(m.group(0))
    except ValueError as exc:
        raise AiError("A IA devolveu uma análise incompleta. Tenta outra vez.") from exc
    if not isinstance(data, dict):
        raise AiError("A IA não devolveu uma análise no formato esperado. Tenta outra vez.")
    return data


def _clean(data, rows):
    """Só os campos esperados, com os tipos certos, e as notícias citadas trocadas pelo título e a ligação."""
    def strs(v, n=5):
        return [str(x)[:300] for x in (v if isinstance(v, list) else []) if str(x).strip()][:n]
    out = {"resumo": str(data.get("resumo") or "")[:1500], "ativos": []}
    for a in (data.get("ativos") if isinstance(data.get("ativos"), list) else [])[:30]:
        if not isinstance(a, dict):
            continue
        refs = []
        for x in (a.get("noticias") if isinstance(a.get("noticias"), list) else []):
            try:
                i = int(x)
            except (TypeError, ValueError):
                continue
            if 1 <= i <= len(rows) and i not in refs:
                refs.append(i)
        tone = str(a.get("tom") or "").lower()
        out["ativos"].append({
            "ticker": str(a.get("ticker") or "")[:40], "tom": tone if tone in TONES else "neutro",
            "conclusao": str(a.get("conclusao") or "")[:1200], "riscos": strs(a.get("riscos")),
            "a_verificar": strs(a.get("a_verificar")),
            "noticias": [{"titulo": rows[i - 1].headline[:200], "url": rows[i - 1].url} for i in refs[:6]]})
    return out


def _key(rows):
    return hashlib.sha1("|".join(f"{n.id}" for n in rows).encode()).hexdigest()


def cached(scope):
    try:
        return json.loads(Setting.get(f"ai_analysis:{scope}") or "null")
    except ValueError:
        return None


def analyse(scope, tickers=None, names=None, force=False, opener=None, now=None):
    """Analisa as notícias de `scope` (carteira, mercado ou radar). Devolve a análise, guardada com a data, a
    plataforma e o modelo; sem notícias novas desde a última, devolve a guardada (a não ser com `force`)."""
    if scope not in SCOPES:
        raise AiError("Âmbito desconhecido.")
    rows = news_for(tickers, market=scope == "mercado", now=now)
    if not rows:
        raise AiError("Não há notícias dos últimos dias para analisar. Atualiza as notícias primeiro.")
    key = _key(rows)
    old = cached(scope)
    if old and old.get("key") == key and not force:
        return {**old, "reused": True}
    text, provider = complete([{"role": "system", "content": SYSTEM},
                               {"role": "user", "content": _prompt(rows, names or {}, scope)}], opener)
    result = _clean(_parse(text), rows)
    saved = {"key": key, "at": (now or datetime.now()).isoformat(timespec="minutes"), "scope": scope,
             "provider": provider, "provider_name": PROVIDERS[provider][0], "model": model(provider),
             "count": len(rows), "result": result}
    Setting.set(f"ai_analysis:{scope}", json.dumps(saved))
    return {**saved, "reused": False}


def test(opener=None):
    """Um pedido curto, para confirmar a chave e o modelo em Definições."""
    text, provider = complete([{"role": "user", "content": "Responde só com a palavra: OK"}], opener)
    return provider, text.strip()[:40]
