## Opis

Projekt prezentuje aplikację do wyznaczania tras ewakuacji z uwzględnieniem zagrożeń powodziowych.
System łączy dane drogowe z **OpenStreetMap** z danymi satelitarnymi **Sentinel Hub** i wyznacza trasę omijającą zalane odcinki dróg.

Aplikacja składa się z:

* backendu w **Python (FastAPI)**, który przetwarza dane przestrzenne i oblicza trasę,
* prostego interfejsu webowego umożliwiającego wizualizację mapy, flood zones i trasy ewakuacji.

Całość można uruchomić lokalnie jedną komendą przy użyciu **Dockera**.

---

## Proces uruchomienia i korzystania z aplikacji

### 1. Uruchomienie aplikacji

Aplikacja uruchamiana jest przy użyciu **Docker Compose**.

W katalogu głównym projektu należy wykonać polecenie:

```bash
docker compose up --build
```

Frontend będzie dostępny pod adresem:
**[http://localhost:8080/](http://localhost:8080/)**

---

### 2. Pobranie danych drogowych

Po wejściu na frontend użytkownik pracuje na mapie OpenStreetMap.

Proces pobierania dróg:

* użytkownik ustawia obszar na mapie,
* kliknięcie przycisku **„Pobierz drogi dla widoku”** wysyła do backendu aktualny bounding box,
* backend pobiera dane drogowe,
* dane są konwertowane do formatu **GeoJSON**,
* na ich podstawie budowany jest graf dróg w pamięci aplikacji.

Po tym kroku graf dróg jest gotowy do dalszych obliczeń.

---

### 3. Nałożenie flood zones

Aplikacja obsługuje dwa sposoby pozyskania stref zalania.

#### Tryb Sentinel Hub

* kliknięcie przycisku **„Pobierz strefy zalania dla widoku”** powoduje pobranie obrazu satelitarnego przez Sentinel Hub OGC WMS,
* obraz jest analizowany piksel po pikselu,
* wykrywane są obszary zalania,
* maska zalania jest konwertowana do poligonów,
* poligony zapisywane są jako aktualne flood zones.

#### Tryb testowy

* użytkownik może uruchomić tryb testowy flood zones,
* generowany jest sztuczny prostokątny obszar zalania,
* tryb ten pozwala testować algorytm bez dostępu do Sentinel Hub.

---

### 4. Blokowanie zalanych odcinków dróg

Przed wyznaczeniem trasy backend:

* wczytuje aktualne flood zones,
* sprawdza przecinanie się każdej krawędzi grafu dróg z poligonami zalania,
* oznacza przecinające się odcinki jako zablokowane.

Zablokowane odcinki nie są brane pod uwagę przy wyznaczaniu trasy.

---

### 5. Wybór punktów START i META

Użytkownik:

* kliknięciem na mapie ustawia punkt **START**,
* kliknięciem na mapie ustawia punkt **META**.

Punkty te są automatycznie dopasowywane do najbliższych węzłów grafu drogowego.

---

### 6. Wyznaczenie trasy ewakuacji

Po kliknięciu przycisku **„Wyznacz trasę”**:

* frontend wysyła zapytanie do endpointu:

```
GET /api/evac/route?start=lat,lon&end=lat,lon
```

* backend buduje podgraf zawierający tylko niezablokowane odcinki,
* uruchamiany jest algorytm najkrótszej ścieżki,
* wyznaczana jest trasa omijająca zalane fragmenty,
* wynik zwracany jest w formacie **GeoJSON** wraz z metadanymi.

---

### 7. Wizualizacja wyniku

Frontend:

* rysuje trasę ewakuacji na mapie,
* wyświetla ją na tle dróg i stref zalania,
* pozwala łatwo porównać trasę z i bez zagrożeń.

---

## Podsumowanie procesu

Pełny proces działania aplikacji:

1. Uruchomienie aplikacji
2. Pobranie dróg z OpenStreetMap
3. Pobranie lub wygenerowanie flood zones
4. Zablokowanie zalanych odcinków
5. Ustawienie punktów START i META
6. Wyznaczenie trasy ewakuacji
7. Wizualizacja trasy na mapie

---

## Pliki

### Frontend

**frontend/index.html**
Interfejs użytkownika oparty o HTML i JavaScript (Leaflet).
Odpowiada za wyświetlanie mapy, interakcje użytkownika oraz komunikację z backendem.

### Backend

**main.py**
Punkt startowy aplikacji backendowej. Tworzy instancję FastAPI, konfiguruje middleware oraz rejestruje endpointy API.

**routes.py**
Definicja endpointów HTTP udostępnianych przez backend, w tym wyznaczania trasy oraz operacji administracyjnych.

**evac_service.py**
Główna warstwa logiki aplikacji. Łączy pobieranie dróg, przetwarzanie flood zones oraz wyznaczanie trasy ewakuacji.

**osm_downloader.py**
Pobiera dane drogowe z OpenStreetMap przy użyciu Overpass API na podstawie bounding boxa.

**osm_to_geojson.py**
Konwertuje dane OSM w formacie XML do formatu GeoJSON.

**graph_builder.py**
Buduje graf dróg (NetworkX) na podstawie danych GeoJSON.

**sentinel_flood_ogc_client.py**
Pobiera obrazy satelitarne z Sentinel Hub (OGC WMS) i przetwarza je na maskę oraz poligony zalania.

**flood_loader.py**
Wczytuje flood zones zapisane w plikach GeoJSON do dalszego przetwarzania.

**flood_intersector.py**
Sprawdza przecięcia między flood zones a odcinkami dróg i oznacza zalane krawędzie jako zablokowane.

**router.py**
Odpowiada za wyznaczanie najkrótszej trasy ewakuacji z pominięciem zablokowanych odcinków.

**utils.py**
Zawiera funkcje pomocnicze wykorzystywane w różnych modułach, m.in. obliczanie odległości.

---

## Endpointy

### Wyznaczanie trasy ewakuacji

```
GET /api/evac/route?start=lat,lon&end=lat,lon
```

**Opis:**
Wyznacza trasę ewakuacji pomiędzy punktami START i META z pominięciem zalanych odcinków dróg.

**Parametry:**

* `start` – współrzędne punktu startowego (latitude, longitude)
* `end` – współrzędne punktu docelowego (latitude, longitude)

**Zwraca:**

* GeoJSON typu `LineString` reprezentujący trasę ewakuacji
* metadane trasy (długość, liczba segmentów, liczba zablokowanych odcinków)

---

### Operacje administracyjne (backend)

#### Aktualizacja dróg

```
POST /api/admin/update-roads
```

**Opis:**
Pobiera dane drogowe z OpenStreetMap dla aktualnego obszaru mapy i przebudowuje graf dróg.

**Wejście:**
Bounding box `(south, west, north, east)` w ciele zapytania

**Zwraca:**
Komunikat statusowy potwierdzający pobranie i przetworzenie dróg

---

#### Aktualizacja flood zones

```
POST /api/admin/update-flood
```

**Opis:**
Pobiera i przetwarza strefy zalania z Sentinel Hub dla aktualnego obszaru mapy.

**Wejście:**
Bounding box `(south, west, north, east)` w ciele zapytania

**Zwraca:**
Komunikat statusowy potwierdzający aktualizację flood zones

---

#### Testowe flood zones

```
POST /api/admin/set-test-flood-rect
```

**Opis:**
Generuje testowy, sztuczny obszar zalania w postaci prostokąta.
Endpoint przeznaczony do testów i debugowania.

**Wejście:**
Bounding box `(south, west, north, east)` w ciele zapytania

**Zwraca:**
Komunikat statusowy potwierdzający utworzenie testowych flood zones

---

### Endpointy diagnostyczne

```
GET /api/debug/flood-geojson
```

**Opis:**
Zwraca aktualnie załadowane strefy zalania w postaci GeoJSON.

**Zwraca:**
GeoJSON typu `Polygon` lub `MultiPolygon` reprezentujący flood zones

---

## Pomysły na rozwój

* Uwzględnienie danych czasowych (time series) z Sentinel Hub w celu śledzenia rozwoju zalania w czasie
* Dynamiczna aktualizacja flood zones w trakcie działania aplikacji
* Rozszerzenie algorytmu routingu o dodatkowe kryteria (typ drogi, prędkość ruchu, przepustowość)
* Wprowadzenie wag dla krawędzi grafu w zależności od poziomu zagrożenia
* Integracja z systemami i danymi meteorologicznymi

