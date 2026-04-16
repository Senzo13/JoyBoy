"""
Web Search - recherche internet pour l'IA.

Surface volontairement simple et auditable:
- SearXNG local si disponible
- DuckDuckGo HTML en fallback
- lecture des pages publiques classiques
"""

from __future__ import annotations

import re
import subprocess
import sys
from html import unescape
from typing import Dict


REQUIRED_PACKAGES = {
    "requests": "requests>=2.31.0",
    "bs4": "beautifulsoup4>=4.12.0",
    "lxml": "lxml>=4.9.0",
}

_dependencies_checked = False


def check_and_install_dependencies(silent: bool = False, progress_callback=None) -> bool:
    """
    Verifie et installe les dependances web search publiques.

    Args:
        silent: Si True, pas de print.
        progress_callback: Callback(package, current, total, status).
    """
    global _dependencies_checked

    if _dependencies_checked:
        return True

    missing = []
    for module_name, pip_package in REQUIRED_PACKAGES.items():
        try:
            __import__(module_name)
        except ImportError:
            missing.append((module_name, pip_package))

    if not missing:
        _dependencies_checked = True
        return True

    total = len(missing)
    if not silent:
        print(f"\n[WEB_SEARCH] Installation de {total} dependance(s) manquante(s)...")
        print("=" * 50)

    try:
        for i, (_module_name, pip_package) in enumerate(missing, 1):
            package_name = pip_package.split(">=")[0].split("==")[0]

            if not silent:
                progress = int((i - 1) / total * 100)
                bar_width = 30
                filled = int(bar_width * (i - 1) / total)
                bar = "#" * filled + "." * (bar_width - filled)
                print(f"\r[{bar}] {progress}% - Installation de {package_name}...", end="", flush=True)

            if progress_callback:
                progress_callback(package_name, i, total, "installing")

            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", pip_package, "-q", "--disable-pip-version-check"],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                if not silent:
                    print(f"\n[WEB_SEARCH] {package_name}: {result.stderr[:120]}")
                if progress_callback:
                    progress_callback(package_name, i, total, "error")
                continue

            if progress_callback:
                progress_callback(package_name, i, total, "done")

        if not silent:
            print(f"\r[{'#' * 30}] 100% - Termine!                    ")
            print("=" * 50)

        _dependencies_checked = True
        return True

    except Exception as exc:
        if not silent:
            packages = " ".join(p for _, p in missing)
            print(f"\n[WEB_SEARCH] Erreur installation: {exc}")
            print(f"[WEB_SEARCH] Installe manuellement: pip install {packages}")
        return False


def ensure_dependencies() -> bool:
    return check_and_install_dependencies(silent=True)


_deps_ok = check_and_install_dependencies(silent=True)

try:
    import requests
except ImportError:
    requests = None
    print("[WEB_SEARCH] ERREUR: requests non disponible")


SEARXNG_URL = "http://localhost:8080"
SEARXNG_TIMEOUT = 10

DDG_URL = "https://html.duckduckgo.com/html/"
DDG_TIMEOUT = 10


def _clean_html_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value or "")
    value = unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def is_searxng_available() -> bool:
    """Verifie si SearXNG est disponible localement."""
    if requests is None:
        return False
    try:
        response = requests.get(f"{SEARXNG_URL}/healthz", timeout=2)
        return response.status_code == 200
    except Exception:
        try:
            response = requests.get(SEARXNG_URL, timeout=2)
            return response.status_code == 200
        except Exception:
            return False


def search_searxng(query: str, num_results: int = 10) -> Dict:
    """Recherche via une instance SearXNG locale."""
    if requests is None:
        return {"success": False, "error": "Module requests non disponible"}

    try:
        response = requests.get(
            f"{SEARXNG_URL}/search",
            params={
                "q": query,
                "format": "json",
                "language": "fr-FR",
                "safesearch": 1,
                "engines": "google,bing,duckduckgo,brave",
            },
            timeout=SEARXNG_TIMEOUT,
            headers={"Accept": "application/json"},
        )

        if response.status_code != 200:
            return {"success": False, "error": f"SearXNG error: {response.status_code}"}

        data = response.json()
        results = []
        for item in data.get("results", [])[:num_results]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", ""),
                "engine": "searxng",
            })

        return {"success": True, "results": results, "source": "searxng", "query": query}

    except requests.exceptions.Timeout:
        return {"success": False, "error": "SearXNG timeout"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def search_duckduckgo(query: str, num_results: int = 10) -> Dict:
    """Recherche publique via DuckDuckGo HTML."""
    if requests is None:
        return {"success": False, "error": "Module requests non disponible"}

    try:
        response = requests.post(
            DDG_URL,
            data={"q": query, "kl": "fr-fr"},
            timeout=DDG_TIMEOUT,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

        if response.status_code != 200:
            return {"success": False, "error": f"DuckDuckGo error: {response.status_code}"}

        html = response.text
        link_pattern = re.compile(
            r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            re.DOTALL,
        )
        snippet_pattern = re.compile(
            r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            re.DOTALL,
        )

        links = link_pattern.findall(html)
        snippets = snippet_pattern.findall(html)
        results = []

        for i, (url, title) in enumerate(links[:num_results]):
            snippet = _clean_html_text(snippets[i])[:300] if i < len(snippets) else ""
            title = _clean_html_text(title)

            if "uddg=" in url:
                from urllib.parse import unquote
                url_match = re.search(r"uddg=([^&]+)", url)
                if url_match:
                    url = unquote(url_match.group(1))

            results.append({
                "title": title,
                "url": unescape(url),
                "snippet": snippet,
                "engine": "duckduckgo",
            })

        return {"success": True, "results": results, "source": "duckduckgo", "query": query}

    except requests.exceptions.Timeout:
        return {"success": False, "error": "DuckDuckGo timeout"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def web_search(query: str, num_results: int = 10, prefer_searxng: bool = True) -> Dict:
    """Recherche web unifiee: SearXNG local puis DuckDuckGo public."""
    if not ensure_dependencies():
        return {
            "success": False,
            "error": "Dependances manquantes. Installe: pip install requests beautifulsoup4 lxml",
        }

    if requests is None:
        return {"success": False, "error": "Module requests non disponible"}

    query = (query or "").strip()
    if len(query) < 2:
        return {"success": False, "error": "Query trop courte"}

    if prefer_searxng and is_searxng_available():
        result = search_searxng(query, num_results)
        if result.get("success"):
            return result
        print(f"[WEB_SEARCH] SearXNG failed, fallback DuckDuckGo: {result.get('error')}")

    return search_duckduckgo(query, num_results)


def fetch_page_content(url: str, timeout: int = 10) -> Dict:
    """Recupere et extrait le contenu textuel d'une page publique."""
    if not ensure_dependencies():
        return {"success": False, "error": "Dependances manquantes"}

    if requests is None:
        return {"success": False, "error": "Module requests non disponible"}

    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            },
            timeout=timeout,
            allow_redirects=True,
        )

        if response.status_code != 200:
            return {"success": False, "error": f"HTTP {response.status_code}"}

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(response.text, "lxml")
        title = soup.title.string if soup.title and soup.title.string else ""

        for tag in soup([
            "script", "style", "nav", "header", "footer", "aside",
            "form", "button", "iframe", "noscript", "svg", "img",
        ]):
            tag.decompose()

        selectors = [
            "article", "main", '[role="main"]',
            ".content", ".post-content", ".article-content", ".entry-content",
            "#content", "#main", "#article",
        ]
        main_content = None
        for selector in selectors:
            main_content = soup.select_one(selector)
            if main_content:
                break
        main_content = main_content or soup.body

        if not main_content:
            return {"success": False, "error": "Pas de contenu trouve"}

        lines = []
        for line in main_content.get_text(separator="\n", strip=True).split("\n"):
            line = line.strip()
            if line and len(line) > 20:
                lines.append(line)

        content = "\n".join(lines)
        if len(content) > 10000:
            content = content[:10000] + "\n... (contenu tronque)"

        return {
            "success": True,
            "content": content,
            "title": title.strip(),
            "url": url,
            "length": len(content),
        }

    except requests.exceptions.Timeout:
        return {"success": False, "error": "Timeout"}
    except requests.exceptions.RequestException as exc:
        return {"success": False, "error": f"Erreur reseau: {str(exc)[:80]}"}
    except Exception as exc:
        return {"success": False, "error": str(exc)[:120]}


def deep_search(query: str, num_results: int = 5, num_pages_to_read: int = 3) -> Dict:
    """Recherche approfondie: recherche + lecture de quelques pages publiques."""
    print(f"[DEEP-SEARCH] Recherche: '{query}'")
    search_results = web_search(query, num_results=num_results)

    if not search_results.get("success"):
        return search_results

    results = search_results.get("results", [])
    print(f"[DEEP-SEARCH] {len(results)} resultats trouves")

    pages_content = []
    pages_read = 0

    for result in results:
        if pages_read >= num_pages_to_read:
            break

        url = result.get("url", "")
        if not url:
            continue

        skip_patterns = [".pdf", ".doc", ".xls", "youtube.com", "twitter.com", "facebook.com", "instagram.com"]
        if any(pattern in url.lower() for pattern in skip_patterns):
            continue

        print(f"[DEEP-SEARCH] Lecture: {url[:60]}...")
        page = fetch_page_content(url)

        if page.get("success"):
            pages_content.append({
                "url": url,
                "title": page.get("title", result.get("title", "")),
                "content": page.get("content", ""),
                "length": page.get("length", 0),
            })
            pages_read += 1
            print(f"[DEEP-SEARCH] OK {page.get('length', 0)} caracteres lus")
        else:
            print(f"[DEEP-SEARCH] Erreur: {page.get('error', 'unknown')}")

    return {
        "success": True,
        "query": query,
        "results": results,
        "pages_content": pages_content,
        "source": search_results.get("source", "web"),
    }


def format_deep_search_for_ai(deep_results: Dict) -> str:
    """Formate les resultats de recherche approfondie pour l'IA."""
    if not deep_results.get("success"):
        return f"Recherche echouee: {deep_results.get('error', 'erreur inconnue')}"

    output = f"Recherche: {deep_results.get('query', '')}\n\n"

    pages = deep_results.get("pages_content", [])
    if pages:
        output += "CONTENU DES PAGES:\n\n"
        for i, page in enumerate(pages, 1):
            output += f"{i}. {page.get('title', 'Sans titre')}\n"
            output += f"URL: {page.get('url', '')}\n"
            output += f"{page.get('content', '')[:2500]}\n\n"

    results = deep_results.get("results", [])
    if results:
        output += "RESULTATS:\n"
        for i, item in enumerate(results[:10], 1):
            output += f"{i}. {item.get('title', 'Sans titre')}\n"
            output += f"   {item.get('url', '')}\n"
            snippet = item.get("snippet", "")
            if snippet:
                output += f"   {snippet}\n"

    return output


def format_results_for_ai(results: Dict) -> str:
    """Formate les resultats simples pour l'IA."""
    if not results.get("success"):
        return f"Recherche echouee: {results.get('error', 'erreur inconnue')}"

    items = results.get("results", [])
    if not items:
        return "Aucun resultat trouve."

    lines = [f"Recherche: {results.get('query', '')}", ""]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. {item.get('title', 'Sans titre')}")
        lines.append(f"   URL: {item.get('url', '')}")
        snippet = item.get("snippet", "")
        if snippet:
            lines.append(f"   {snippet}")
        lines.append("")
    return "\n".join(lines)


def get_searxng_install_instructions() -> str:
    """Retourne les instructions d'installation de SearXNG local."""
    return """
=== INSTALLATION SEARXNG LOCAL ===

Option Docker:
docker run -d --name searxng -p 8080:8080 searxng/searxng

Option Docker Compose:
services:
  searxng:
    image: searxng/searxng
    ports:
      - "8080:8080"
    restart: unless-stopped

Verification: http://localhost:8080
"""


def detect_search_mode(query: str) -> tuple[str, str]:
    """Compatibilite ancienne API: JoyBoy ne garde qu'une recherche web publique."""
    return "normal", query


if __name__ == "__main__":
    print("Test de recherche web...")
    print(f"SearXNG disponible: {is_searxng_available()}")
    print(format_results_for_ai(web_search("python programming", num_results=5)))
