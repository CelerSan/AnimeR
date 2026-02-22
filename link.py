from bs4 import BeautifulSoup
from tor import tor_get

FALLBACK_URL = "https://anime-sama.tv"
STATUS_OK_MARKER = "(200)"


def get_url() -> str:
    """
    Récupère l'URL actuelle du site anime-sama à partir
    du tableau des domaines sur la page de status.
    """
    response = tor_get("https://anime-sama.pw/", max_attempts=3, timeout=15)
    if not response:
        return FALLBACK_URL

    soup = BeautifulSoup(response.text, "html.parser")

    # On cherche le premier tableau pertinent
    table = soup.find("table")
    if not table:
        return FALLBACK_URL

    # Parcours des lignes (on ignore éventuellement l'en-tête)
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        first_cell = cells[0]
        last_cell = cells[-1]

        status_text = last_cell.get_text(strip=True)
        if STATUS_OK_MARKER in status_text:
            # On récupère le lien dans la première colonne
            link_tag = first_cell.find("a")
            if link_tag and link_tag.get("href"):
                return link_tag["href"]

    return FALLBACK_URL
