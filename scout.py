from __future__ import annotations

import json
import math
import re
import sqlite3
import statistics
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

BASE = "https://www.wg-gesucht.de"
OHNE = "https://www.ohne-makler.net"
FRAUENLAND = "https://www.wg-frauenland.de"
HC24 = "https://www.hc24.de"
SOURCES = (
    {"id": "wg-gesucht", "name": "WG-Gesucht", "icon": "🏠",
     "url": f"{BASE}/wohnungen-in-Wuerzburg.141.2.1.0.html",
     "kind": "regular", "collection": "automatic", "note": "Studios and whole apartments.",
     "searches": (("WG-Gesucht studios", f"{BASE}/1-zimmer-wohnungen-in-Wuerzburg.141.1.1.0.html"),
                  ("WG-Gesucht apartments", f"{BASE}/wohnungen-in-Wuerzburg.141.2.1.0.html"))},
    {"id": "ohne-makler", "name": "ohne-makler", "icon": "🔑",
     "url": f"{OHNE}/immobilien/wohnung-mieten/bayern/kreis-wuerzburg-stadt/",
     "kind": "regular", "collection": "automatic", "note": "Whole apartments in Würzburg city.",
     "searches": (("ohne-makler apartments", f"{OHNE}/immobilien/wohnung-mieten/bayern/kreis-wuerzburg-stadt/"),)},
    {"id": "frauenland", "name": "Frauenland", "icon": "🏘️", "url": f"{FRAUENLAND}/mieten/",
     "kind": "regular", "collection": "automatic", "note": "Cooperative membership required.",
     "searches": (("Frauenland apartments", f"{FRAUENLAND}/mieten/"),)},
    {"id": "immoscout24", "name": "ImmoScout24", "icon": "🏢",
     "url": "https://www.immobilienscout24.de/Suche/de/bayern/wuerzburg/wohnung-mieten",
     "kind": "regular", "collection": "website", "note": "Browse apartment offers on the provider website."},
    {"id": "kleinanzeigen", "name": "Kleinanzeigen", "icon": "📣",
     "url": "https://www.kleinanzeigen.de/s-wohnung-mieten/c203l7667",
     "kind": "regular", "collection": "website", "note": "Check that the offer is a whole apartment."},
    {"id": "immowelt", "name": "Immowelt", "icon": "🌍",
     "url": "https://www.immowelt.de/suche/mieten/wohnung/bayern/wurzburg-97070/ad08de7873",
     "kind": "regular", "collection": "website", "note": "Browse apartment offers on the provider website."},
    {"id": "stadtbau", "name": "Stadtbau Würzburg", "icon": "🏙️",
     "url": "https://stadtbau-wuerzburg.de/wohnungssuche/",
     "kind": "regular", "collection": "website", "note": "Apartment search through Immomio."},
    {"id": "main-post", "name": "Main-Post", "icon": "📰",
     "url": "https://anzeigen.mainpost.de/category/immobilien/vermietungen/",
     "kind": "regular", "collection": "website", "note": "Check location and whole-apartment availability."},
    {"id": "wunderflats", "name": "Wunderflats", "icon": "🛋️", "url": "https://wunderflats.com/en",
     "kind": "furnished", "collection": "website", "note": "Choose Würzburg. Check service fees and minimum stay."},
    {"id": "housinganywhere", "name": "HousingAnywhere", "icon": "🌐",
     "url": "https://housinganywhere.com/it/s/W%C3%BCrzburg--Germania/appartamenti-ammobiliati",
     "kind": "furnished", "collection": "website", "note": "Select whole apartments and check extra charges."},
    {"id": "hc24", "name": "HC24", "icon": "🛏️",
     "url": f"{HC24}/de/moeblierter-wohnraum-in-wuerzburg/",
     "kind": "furnished", "collection": "automatic", "note": "Temporary furnished apartments. Extra charges need confirmation.",
     "searches": (("HC24 apartments", f"{HC24}/de/moeblierter-wohnraum-in-wuerzburg/"),)},
)
SEARCHES = tuple(search for source in SOURCES if source["collection"] == "automatic"
                 for search in source.get("searches", ()))


def source_catalog():
    return [{key: value for key, value in source.items() if key != "searches"} for source in SOURCES]


DEFAULTS = {"current_total": 1000, "budget": 850, "min_size": 30,
            "extra_costs": 60, "include_temporary": False}


def now():
    return datetime.now(timezone.utc).isoformat()


def number(text):
    match = re.search(r"\d[\d.,]*", text.replace("\xa0", ""))
    if not match:
        return None
    return float(match[0].replace(".", "").replace(",", "."))


def nightly_stay(title):
    return bool(re.search(r"overnight|übernachtung|pro nacht|per night|nightly|tagesmiete", title, re.I))


def housing_type(listing, description=""):
    text = " ".join((listing["title"], listing.get("location", ""), description)).casefold()
    if (listing.get("housing_type") == "non_residential"
            or re.search(r"\b(?:ladenfläche|gewerbefläche|bürofläche|praxisfläche|verkaufsfläche)\b", text)
            or re.search(r"\bladen\s+(?:links|rechts|zu\s+vermieten)\b", listing["title"], re.I)):
        return "non_residential"
    occupancy_claims = re.sub(r"\b(?:keine?|ohne)\s+(?:wg(?:-zimmer)?|wohngemeinschaft)\b|"
                  r"\bwg[- ](?:geeignet|tauglich)\b", "", text)
    if re.search(r"\bwg[- ]?zimmer\b|\bzimmer\s+in\s+(?:einer\s+)?wg\b|"
                 r"\bwohngemeinschaft\b|\bwg\b(?![- ](?:gesucht|geeignet|tauglich))|"
                 r"\bshared\s+(?:flat|apartment|kitchen|bathroom|shower|toilet)\b|"
                 r"\b(?:gemeinschafts|mitbenutzungs)(?:küche|bad|dusche|wc)\b|"
                 r"\b(?:küchen|bad|badezimmer|dusch|wc)[- ]?mitbenutzung\b|"
                 r"\b(?:geteilte[nrsm]?|gemeinsame[nrsm]?)\s+(?:küche|bad|badezimmer|wc)\b|"
                 r"\betagenbad\b|\b(?:bad|badezimmer)\s+auf\s+dem\s+flur\b|"
                 r"\b(?:küche|bad|badezimmer)\s+(?:zur\s+)?(?:mitbenutzung|gemeinschaftlichen\s+nutzung)\b",
                 occupancy_claims):
        return "shared"
    if listing.get("housing_type") == "shared":
        return "shared"
    url = listing.get("url", "")
    if re.match(r"https://www\.wg-gesucht\.de/(?:1-zimmer-wohnungen|wohnungen)-in-", url):
        return "entire_apartment"
    if listing.get("source") == "ohne-makler" and listing.get("housing_type") == "entire_apartment":
        return "entire_apartment"
    if (listing.get("source") == "Frauenland" and url == FRAUENLAND + "/mieten/"
            and listing.get("housing_type") == "entire_apartment"):
        return "entire_apartment"
    if (listing.get("source") == "HC24" and listing.get("housing_type") == "entire_apartment"
            and listing.get("private_facilities") is True
            and re.fullmatch(re.escape(HC24) + r"/de/expose/wu\d+/", url)):
        return "entire_apartment"
    return "unknown"


def listing_image(container, selector, page_url):
    for image in container.select(selector):
        for attribute in ("data-src", "data-large", "src"):
            value = image.get(attribute, "").strip()
            if not value or re.search(r"[\s\\]", value):
                continue
            try:
                url = urljoin(page_url, value)
                parts = urlsplit(url)
            except ValueError:
                continue
            path = parts.path.replace("/./", "/")
            if (parts.scheme == "https" and parts.netloc.lower() in
                    {"img.wg-gesucht.de", "www.wg-gesucht.de"}
                    and path.startswith("/media/up/") and "/../" not in path
                    and re.search(r"\.(jpe?g|png|webp|avif)$", path, re.I)
                    and "user_photo" not in path.casefold()):
                return url
    return None


def parse_search(html, source_url=BASE):
    if urlsplit(source_url).hostname == "www.hc24.de":
        return parse_hc24_search(html)
    if urlsplit(source_url).hostname == "www.wg-frauenland.de":
        return parse_frauenland_search(html)
    if urlsplit(source_url).hostname == "www.ohne-makler.net":
        return parse_ohne_search(html)
    soup = BeautifulSoup(html, "html.parser")
    listings = []
    readable = 0
    for card in soup.select(".offer_list_item[data-id]"):
        link = card if card.name == "a" else card.select_one("h2 a")
        title_element = card.select_one(".ad-title") if card.name == "a" else link
        facts = card.select_one(".middle, .middle-row")
        location = card.select_one(".ad-subtitle, .card_body .col-xs-11 span")
        if not link or not title_element or not facts or not location:
            continue
        text = facts.get_text(" ", strip=True)
        price_row = card.select_one(".price-row")
        price_text = price_row.get_text(" ", strip=True) if price_row else text
        period = price_row.select_one(".card-subtitle") if price_row else None
        if period and period.get_text(" ", strip=True).casefold() != "pro monat":
            continue
        price = re.search(r"([\d.,]+)\s*€", price_text)
        size = re.search(r"([\d.,]+)\s*m[²2]", text)
        if not price or not size:
            continue
        readable += 1
        url = urljoin(BASE, link.get("href", ""))
        if not url.startswith(BASE + "/"):
            continue
        title = title_element.get_text(" ", strip=True)
        if nightly_stay(title):
            continue
        listing = {"id": card["data-id"], "title": title, "url": url,
                         "source": "WG-Gesucht",
                         "image_url": listing_image(card, "img.top-image-card, .card_image img", url),
                         "rent": number(price[1]), "size": number(size[1]),
                         "location": " ".join(location.get_text(" ", strip=True).split()),
                         "available": " to ".join(re.findall(r"\d{2}\.\d{2}\.\d{4}", text)),
                         "temporary": bool(re.search(r"zwischenmiete|befristet|sublet|temporary", title, re.I)),
                         "rent_basis": "advertised", "base_rent": None,
                         "service_costs": None, "other_costs": None, "deposit": None,
                         "details_checked": False}
        listing["housing_type"] = housing_type(listing)
        listings.append(listing)
    # A changed layout or challenge must not masquerade as an empty market.
    if not readable:
        raise ValueError("No readable listing cards. The source may be empty, blocked, or have changed layout.")
    return listings


def parse_detail(html, listing):
    if listing.get("source") == "HC24":
        return parse_hc24_detail(html, listing)
    if listing.get("source") == "Frauenland":
        return dict(listing)
    if listing.get("source") == "ohne-makler":
        return parse_ohne_detail(html, listing)
    soup = BeautifulSoup(html, "html.parser")
    result = dict(listing)
    description = soup.select_one("#ad_description_text")
    title = soup.select_one(".detailed-view-title")
    if title:
        result["title"] = title.get_text(" ", strip=True)
    result["housing_type"] = housing_type(result, description.get_text(" ", strip=True) if description else "")
    result["housing_checked"] = description is not None
    result["image_url"] = listing_image(soup, "img.sp-image", listing["url"]) or listing.get("image_url")
    for label in soup.select(".key_fact_detail"):
        if label.get_text(strip=True) == "Gesamtmiete":
            value = label.parent.select_one(".key_fact_value")
            if value and "€" in value.get_text():
                result["rent"] = number(value.get_text())
                result["rent_basis"] = "listed total"
    labels = {"Miete:": "base_rent", "Nebenkosten:": "service_costs",
              "Sonstige Kosten:": "other_costs", "Kaution:": "deposit"}
    for label in soup.select(".section_panel_detail"):
        key = label.get_text(" ", strip=True)
        row = label.find_parent("div", class_="row")
        value = row.select_one(".section_panel_value") if row else None
        if key in labels and value:
            text = value.get_text(" ", strip=True)
            result[labels[key]] = number(text) if "€" in text else None
        if key == "frei bis:" and value and re.search(r"\d{2}\.\d{2}\.\d{4}", value.get_text()):
            result["temporary"] = True
            result["available"] += " → " + value.get_text(strip=True)
    result["details_checked"] = result["rent_basis"] == "listed total"
    return result


def parse_ohne_search(html):
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select('a[data-om-id][data-om-type="RENT"]')
    listings, readable = [], 0
    for card in cards:
        title = card.select_one("h4")
        price = card.select_one("span")
        size = card.select_one('[title="Wohnfläche"] span')
        location = title.parent.select_one("div span") if title else None
        if not all((title, price, size, location)):
            continue
        rent, area = number(price.get_text()), number(size.get_text())
        if rent is None or not area or "€" not in price.get_text():
            continue
        readable += 1
        place = " ".join(location.get_text(" ", strip=True).split())
        if not re.search(r"\b970(?:70|72|74|76|78|80|82|84)\s+Würzburg\b", place):
            continue
        url = urljoin(OHNE, card.get("href", ""))
        if not re.fullmatch(re.escape(OHNE) + r"/immobilie/\d+/", url):
            continue
        row = {"id": "ohne-makler:" + card["data-om-id"], "source": "ohne-makler",
               "title": title.get_text(" ", strip=True), "url": url, "location": place,
               "rent": rent, "search_rent": rent, "size": area, "available": "Not listed",
               "temporary": bool(re.search(r"zwischenmiete|befristet|sublet|temporary", title.get_text(), re.I)),
               "rent_basis": "advertised; charges unknown",
               "base_rent": None, "service_costs": None, "other_costs": None, "deposit": None,
               "details_checked": False, "housing_type": "entire_apartment", "image_url": None,
               "monthly_charges_known": False}
        row["housing_type"] = housing_type(row)
        if not nightly_stay(row["title"]):
            listings.append(row)
    if not readable:
        raise ValueError("No readable listing cards. The source may be empty, blocked, or have changed layout.")
    return listings


def parse_ohne_detail(html, listing):
    soup = BeautifulSoup(html, "html.parser")
    fields = {}
    for tr in soup.select("tr"):
        cells = tr.select("td")
        if len(cells) == 2:
            fields[cells[0].get_text(" ", strip=True)] = cells[1].get_text(" ", strip=True)
    if fields.get("Objektart") != "Wohnung":
        raise ValueError("Apartment detail layout unavailable.")
    row = dict(listing)
    description = " ".join(node.get_text(" ", strip=True) for node in soup.select(".prose"))
    row["housing_type"] = housing_type(row, description)
    row["housing_checked"] = True
    row["base_rent"] = number(fields.get("Kaltmiete", ""))
    combined = fields.get("Summe Nebenkosten/Heizkosten", "")
    row["service_costs"] = number(combined or fields.get("Nebenkosten ohne Heizkosten", ""))
    row["monthly_charges_known"] = bool(combined) and row["service_costs"] is not None
    row["deposit"] = number(fields.get("Mietsicherheit", ""))
    row["parking_costs"] = number(fields.get("Miete Garage/Stellplatz", ""))
    row["available"] = fields.get("Übernahme ab", "Not listed")
    row["temporary"] = listing["temporary"] or bool(re.search(r"zwischenmiete|befristet|sublet|temporary", description, re.I))
    if row["base_rent"] is not None:
        row["rent"] = row["base_rent"] + (row["service_costs"] or 0)
        row["rent_basis"] = ("cold rent + listed charges" if row["monthly_charges_known"]
                             else "cold rent; heating or charges unknown")
        row["details_checked"] = True
    image = soup.select_one('meta[property="og:image"]')
    value = image.get("content", "") if image else ""
    if re.fullmatch(re.escape(OHNE) + r"/immobilie/\d+/picture/\d+/(?:medium|large)\.jpg", value):
        row["image_url"] = value
    return row


def parse_frauenland_search(html):
    soup = BeautifulSoup(html, "html.parser")
    offers = soup.select_one('[data-label="angebote"]')
    heading = next((node for node in offers.select("h2")
                    if node.get_text(" ", strip=True) == "Wohnungen"), None) if offers else None
    if heading is None:
        raise ValueError("Frauenland apartment section unavailable.")
    section = []
    for node in heading.find_next_siblings():
        if node.name == "h2":
            break
        section.append(node)
    tables = [node for node in section if node.name == "table"]
    empty_message = re.compile(r"\bkeine[nr]?\s+(?:(?:freien?|verfügbaren?)\s+)?(?:Wohnungen|Angebote)\b", re.I)
    if not tables:
        text = " ".join(node.get_text(" ", strip=True) for node in section)
        if empty_message.search(text) and not re.search(r"\bWohnung\s+\d+", text):
            return []
        raise ValueError("Frauenland apartment table layout changed.")
    listings = []
    ids = set()
    for table in tables:
        if not table.select("td") and table.get_text(" ", strip=True):
            raise ValueError("Frauenland apartment table layout changed.")
        for cell in table.select("td"):
            headings = [node for node in cell.select("h4")
                        if re.match(r"^Wohnung\b", node.get_text(" ", strip=True))]
            if not headings:
                text = cell.get_text(" ", strip=True)
                if text and not empty_message.search(text):
                    raise ValueError("Frauenland apartment units unavailable.")
                continue
            address = cell.select_one("h3")
            location = " ".join(address.get_text(" ", strip=True).split()) if address else ""
            if not re.search(r"\b\d{5}\s+\S+", location):
                raise ValueError("Frauenland apartment address unavailable.")
            prefix = []
            for node in cell.children:
                if node == headings[0]:
                    break
                if getattr(node, "name", None):
                    prefix.append(node.get_text(" ", strip=True))
            building = " ".join(prefix)
            availability = re.search(r"(?:Bezug|bezugsfrei|Einzug|\bab\b).*?(\d{2}\.\d{2}\.\d{4})",
                                     building, re.I)
            available = availability[1] if availability else "Not listed"
            if availability and re.search(r"geplant", building, re.I):
                available += " (planned)"
            for heading in headings:
                unit = re.fullmatch(r"Wohnung\s+(\d+)", heading.get_text(" ", strip=True))
                if unit is None:
                    raise ValueError("Frauenland apartment unit identifier unavailable.")
                fields, description = {}, []
                for node in heading.find_next_siblings():
                    if node.name in ("h3", "h4", "hr"):
                        break
                    text = node.get_text(" ", strip=True)
                    description.append(text)
                    label = node.select_one("strong")
                    if label:
                        key = label.get_text(" ", strip=True).rstrip(": ")
                        fields[key] = text[len(label.get_text(" ", strip=True)):].strip()
                required = ("Zimmer", "Wohnfläche", "Nettokaltmiete", "Betriebskosten", "Heizkosten", "Gesamtmiete")
                if any(key not in fields for key in required):
                    raise ValueError("Frauenland apartment costs or area unavailable.")
                costs = {}
                for key in required[2:]:
                    value = fields[key]
                    if re.fullmatch(r"[\d.,\s]+\s*€", value):
                        costs[key] = number(value)
                    elif re.fullmatch(r"(?:auf Anfrage|unbekannt|k\.?\s*A\.?|[-–])", value, re.I):
                        costs[key] = None
                    else:
                        raise ValueError("Frauenland apartment cost format changed.")
                if not re.fullmatch(r"[\d.,\s]+\s*m[²2]", fields["Wohnfläche"]):
                    raise ValueError("Frauenland apartment area format changed.")
                size = number(fields["Wohnfläche"])
                if not size or costs["Gesamtmiete"] is None or costs["Gesamtmiete"] <= 0:
                    raise ValueError("Frauenland apartment total rent or area unavailable.")
                complete = all(costs[key] is not None for key in required[2:])
                if complete and abs(sum(costs[key] for key in required[2:5]) - costs["Gesamtmiete"]) > .02:
                    raise ValueError("Frauenland apartment costs do not match its total rent.")
                if not re.search(r"\b970(?:70|72|74|76|78|80|82|84)\s+Würzburg\b", location):
                    continue
                identifier = "frauenland:" + re.sub(r"[^\w]+", "-", location.casefold()).strip("-") + ":" + str(int(unit[1]))
                if identifier in ids:
                    raise ValueError("Frauenland apartment identifier repeated.")
                ids.add(identifier)
                row = {"id": identifier, "source": "Frauenland", "url": FRAUENLAND + "/mieten/",
                       "title": f"Wohnung {int(unit[1])}, {location}", "location": location,
                       "rent": costs["Gesamtmiete"], "size": size, "available": available,
                       "temporary": bool(re.search(r"zwischenmiete|befristet|sublet|temporary", building + " ".join(description), re.I)),
                       "rent_basis": "listed total", "base_rent": costs["Nettokaltmiete"],
                       "service_costs": (costs["Betriebskosten"] + costs["Heizkosten"]
                                         if costs["Betriebskosten"] is not None and costs["Heizkosten"] is not None else None),
                       "other_costs": None, "deposit": None, "image_url": None,
                       "details_checked": True, "housing_checked": True, "monthly_charges_known": complete,
                       "housing_type": "entire_apartment", "membership_required": True,
                       "membership_costs": None,
                       "source_note": "Cooperative membership required. Share costs need confirmation."}
                row["housing_type"] = housing_type(row, building + " " + " ".join(description))
                listings.append(row)
    return listings


def hc24_content(html):
    node = BeautifulSoup(html, "html.parser").select_one("script#__NEXT_DATA__")
    try:
        content = json.loads(node.string if node else "")["props"]["pageProps"]["pageData"]["pageContent"]
        if not isinstance(content, dict):
            raise ValueError
        return content
    except (ValueError, TypeError, KeyError):
        raise ValueError("HC24 public listing data unavailable or changed.") from None


def hc24_offer(data, detail=False):
    try:
        geo, prices, texts = data["geo"], data["prices"], data["texts"]
        identifier = str(data["externalId"])
        if not re.fullmatch(r"\d+", identifier) or data["agency"]["agencyShort"] != "WU":
            return None
        if data["propertyType"]["objectType"] != "WOHNUNG":
            return None
        if geo["city"] not in ("Würzburg", "Heidingsfeld"):
            return None
        if detail and not re.fullmatch(r"970(?:70|72|74|76|78|80|82|84)", str(geo.get("zip", ""))):
            return None
        if data.get("active") is False or (detail and data.get("active") is not True):
            return None
        inactive = data.get("inactiveSince")
        if inactive and datetime.fromisoformat(inactive).date() <= datetime.now(timezone.utc).date():
            return None
        if prices.get("rentUnit", "MONTH") != "MONTH" or prices.get("currency", "EUR") != "EUR":
            return None
        title, rent, size = texts["headline"], prices["completeRent"], data["areas"]["squareMeters"]
        if (not isinstance(title, str) or not title.strip() or any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0 for value in (rent, size))):
            raise ValueError
        description = " ".join(str(texts.get(key) or "") for key in
                               ("interiorText", "interiorTextEN", "generalText", "generalTextEN"))
        if nightly_stay(title + " " + description):
            return None
        kitchen = re.search(r"küche|kitchen|kitchenette", description, re.I)
        bathroom = re.search(r"\b(?:bad|badezimmer|dusche|badewanne|bathroom|shower)\b", description, re.I)
        private = bool(kitchen and bathroom)
        image_url = None
        for image in data.get("images", []):
            value = image.get("imageLink", "")
            if isinstance(value, str) and re.fullmatch(r"hcwu/" + identifier + r"_\d+\.jpg", value, re.I):
                image_url = "https://hc24-media-new.s3.eu-central-1.amazonaws.com/" + value
                break
        administration = data["administrationInformation"]
        row = {"id": "hc24:wu" + identifier, "source": "HC24", "title": title.strip(),
               "url": HC24 + "/de/expose/wu" + identifier + "/", "location": geo["city"],
               "rent": rent, "search_rent": rent, "size": size,
               "available": administration.get("availableFrom") or "Not listed",
               "temporary": True, "rent_basis": "advertised; charges need confirmation",
               "base_rent": None, "service_costs": None, "other_costs": None, "deposit": None,
               "details_checked": detail, "housing_checked": detail,
               "monthly_charges_known": False, "private_facilities": private,
               "housing_type": "entire_apartment" if private else "unknown", "image_url": image_url,
               "source_note": "Temporary furnished rental. Confirm extra charges and minimum stay."}
        row["housing_type"] = housing_type(row, description)
        minimum = administration.get("minDays")
        row["minimum_stay_days"] = minimum if isinstance(minimum, int) and not isinstance(minimum, bool) and minimum > 0 else None
        for key, field in (("included_costs", "includedServicesTextDeu"),
                           ("additional_costs", "additionalCostsTextDeu")):
            value = prices.get(field)
            if value is not None and not isinstance(value, str):
                raise ValueError
            row[key] = value or None
        row["one_time_fees"] = None
        if detail:
            deposit = prices.get("deposit")
            if isinstance(deposit, (int, float)) and not isinstance(deposit, bool) and math.isfinite(deposit) and deposit >= 0:
                row["deposit"] = deposit
            if administration.get("availableTo"):
                row["available"] += " → " + administration["availableTo"]
        return row
    except (KeyError, TypeError, AttributeError, ValueError):
        raise ValueError("HC24 apartment fields unavailable or changed.") from None


def parse_hc24_search(html):
    try:
        features = hc24_content(html)["mapData"]["response"]["properties"]["features"]
        if not isinstance(features, list):
            raise ValueError
        rows = [row for feature in features if (row := hc24_offer(feature["properties"])) is not None]
        if len({row["id"] for row in rows}) != len(rows):
            raise ValueError
        return rows
    except (KeyError, TypeError, ValueError):
        raise ValueError("HC24 apartment search unavailable or changed.") from None


def parse_hc24_detail(html, listing):
    try:
        properties = hc24_content(html)["propertyDetailPageData"]["properties"]
        if not isinstance(properties, list) or len(properties) != 1:
            raise ValueError
        data = properties[0]
        expected = "hc24:wu" + str(data["externalId"])
        if listing["id"] != expected or listing["url"] != HC24 + "/de/expose/wu" + str(data["externalId"]) + "/":
            raise ValueError
        row = hc24_offer(data, detail=True)
        if row is None:
            return dict(listing, housing_type="unknown", private_facilities=False,
                        housing_checked=True, details_checked=True)
        row["search_rent"] = listing.get("search_rent", listing["rent"])
        row["image_url"] = row["image_url"] or listing.get("image_url")
        return dict(listing, **row)
    except (KeyError, TypeError, ValueError):
        raise ValueError("HC24 apartment detail unavailable or changed.") from None


def evaluate(rows, settings):
    rows = [row for row in rows if housing_type(row) == "entire_apartment"]
    for row in rows:
        row["housing_type"] = "entire_apartment"
        row.setdefault("source", "WG-Gesucht")
    market = [r for r in rows if not r["temporary"] and r.get("currently_seen", True)
              and r.get("monthly_charges_known", True)]
    for row in rows:
        row["estimated_total"] = round(row["rent"] + settings["extra_costs"], 2)
        row["estimated_saving"] = round(settings["current_total"] - row["estimated_total"], 2)
        row["price_per_m2"] = round(row["rent"] / row["size"], 2)
        peers = [r["rent"] / r["size"] for r in market
                 if r["id"] != row["id"] and .75 * row["size"] <= r["size"] <= 1.25 * row["size"]]
        row["peer_count"] = len(peers)
        row["value_discount"] = (round((1 - row["price_per_m2"] / statistics.median(peers)) * 100, 1)
                                 if len(peers) >= 3 and not row["temporary"]
                                 and row.get("monthly_charges_known", True) else None)
        row["matches"] = (row["estimated_total"] <= settings["budget"] and row["size"] >= settings["min_size"]
                          and row.get("monthly_charges_known", True)
                          and (settings["include_temporary"] or not row["temporary"]))
        row["good_value"] = row["value_discount"] is not None and row["value_discount"] >= 10
    return rows


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS listings (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new',
                    notified INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        return db

    def get(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value)))

    def settings(self):
        return DEFAULTS | self.get("settings", {})

    def upsert(self, listing, stamp):
        with self.connect() as db:
            db.execute("""INSERT INTO listings (id,payload,first_seen,last_seen) VALUES (?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,last_seen=excluded.last_seen""",
                       (listing["id"], json.dumps(listing), stamp, stamp))

    def rows(self):
        ids = set(self.get("seen_ids", []))
        with self.connect() as db:
            data = db.execute("SELECT * FROM listings ORDER BY first_seen DESC").fetchall()
        return [json.loads(r["payload"]) | {"first_seen": r["first_seen"], "last_seen": r["last_seen"],
                 "status": r["status"], "notified": bool(r["notified"]), "currently_seen": r["id"] in ids}
                for r in data if not nightly_stay(json.loads(r["payload"])["title"])]

    def status(self, id, status):
        if status not in ("new", "saved", "hidden"):
            raise ValueError("Status must be new, saved, or hidden.")
        with self.connect() as db:
            return db.execute("UPDATE listings SET status=? WHERE id=?", (status, id)).rowcount

    def notified(self, id):
        with self.connect() as db:
            db.execute("UPDATE listings SET notified=1 WHERE id=?", (id,))


class Collector:
    def __init__(self, store, notifier=None):
        self.store, self.notifier = store, notifier
        self.lock = threading.Lock()

    def fetch(self, url):
        # Only fixed source URLs or source-owned listing URLs are used.
        try:
            response = requests.get(url, timeout=(8, 20), headers={"User-Agent": "WohnungScout/1.0 personal research"})
            response.raise_for_status()
            return response.text
        except requests.RequestException:
            raise RuntimeError("Source request failed. Check connectivity or try again later.") from None

    def scan(self, detail_limit=12):
        if not self.lock.acquire(blocking=False):
            return False
        try:
            stamp, found, errors = now(), {}, []
            for label, url in SEARCHES:
                try:
                    for listing in parse_search(self.fetch(url), url):
                        found[listing["id"]] = listing
                except (RuntimeError, ValueError) as exc:
                    errors.append(f"{label}: {exc}")
            previous = {r["id"]: r for r in self.store.rows()}
            # Enrich new affordable homes first; keep full public search results for charts.
            prioritized = sorted(found.values(), key=lambda r: (r["rent"] > self.store.settings()["budget"], r["rent"]))
            checked = 0
            for listing in prioritized:
                old = previous.get(listing["id"])
                if old and not listing.get("image_url"):
                    listing["image_url"] = old.get("image_url")
                if (not listing["details_checked"] and old and old["details_checked"] and old.get("housing_checked")
                        and (old.get("monthly_charges_known", True) or listing.get("source") == "HC24")
                        and old.get("search_rent", old["rent"]) == listing["rent"]):
                    for key in ("rent", "rent_basis", "base_rent", "service_costs", "other_costs", "deposit", "details_checked", "housing_checked"):
                        listing[key] = old[key]
                    for key in ("parking_costs", "monthly_charges_known", "minimum_stay_days", "included_costs",
                                "additional_costs", "one_time_fees", "source_note", "private_facilities"):
                        if key in old and (not listing.get(key) or key in ("monthly_charges_known", "private_facilities")):
                            listing[key] = old[key]
                    if (listing.get("source") == "HC24" and listing["housing_type"] == "unknown"
                            and housing_type(old) == "entire_apartment"):
                        listing["housing_type"] = "entire_apartment"
                    listing["temporary"] = listing["temporary"] or old["temporary"]
                    if " → " in old["available"]:
                        listing["available"] += " → " + old["available"].split(" → ", 1)[1]
                elif not listing["details_checked"] and checked < detail_limit:
                    checked += 1
                    try:
                        listing = parse_detail(self.fetch(listing["url"]), listing)
                    except (RuntimeError, ValueError) as exc:
                        errors.append(f"Details {listing['id']}: {exc}")
                    threading.Event().wait(1)
                if old and housing_type(old) in ("shared", "non_residential"):
                    listing["housing_type"] = housing_type(old)
                self.store.upsert(listing, stamp)
            if found or not errors:
                # On partial failures, retain visibility for rows from the failed category.
                ids = set(found)
                if errors:
                    ids.update(self.store.get("seen_ids", []))
                self.store.put("seen_ids", sorted(ids))
                self.store.put("last_success", stamp)
            self.store.put("last_check", stamp)
            self.store.put("errors", errors)
            self.alert()
            return True
        finally:
            self.lock.release()

    def alert(self):
        if not self.notifier:
            return
        rows = evaluate(self.store.rows(), self.store.settings())
        candidates = sorted((r for r in rows if r["matches"] and r["currently_seen"]
                             and not r["notified"] and r["status"] != "hidden"), key=lambda r: r["estimated_total"])
        for row in candidates[:5]:
            try:
                sent = self.notifier(row)
            except RuntimeError:
                self.store.put("telegram_error", "Alert failed. It will retry on the next check.")
                return
            if sent:
                self.store.notified(row["id"])
                self.store.put("telegram_error", None)


def validate_settings(data):
    result = {}
    bounds = {"current_total": (1, 10000), "budget": (1, 10000), "min_size": (1, 500), "extra_costs": (0, 1000)}
    for key, (low, high) in bounds.items():
        value = float(data[key])
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{key} must be between {low} and {high}.")
        result[key] = value
    if not isinstance(data.get("include_temporary"), bool):
        raise ValueError("include_temporary must be true or false.")
    result["include_temporary"] = data["include_temporary"]
    return result
