# Portfolio — SentinelHub 0.4

## PL

**SentinelHub — analiza tras na własnych danych przestrzennych.** Aplikacja
Python/FastAPI przyjmuje drogi i zalanie w GeoJSON, buduje skierowany graf,
wyklucza odcinki przecinające poligony i porównuje najkrótszy przejazd z trasą
bez zalania. SQLite trwale zapisuje wersjonowane wejście i snapshoty wyników.
Prywatny klucz przestrzeni chroni odczyt i zmianę danych. Operator może korzystać
z prawdziwego Overpass i konfiguracji Sentinel WMS; przykład syntetyczny jest
osobnym, bezstanowym ekranem.

Problem: mapa zalania nie określa sama dostępności między punktami. Rozwiązanie
łączy topologię, geometrię i trwały przepływ danych, z jawnym wynikiem braku
połączenia oraz historią umożliwiającą odtworzenie wcześniejszego obliczenia.

Widoczne decyzje: NetworkX MultiDiGraph zachowuje identyfikatory i kierunki OSM;
Shapely sprawdza przecięcia; START jest zakotwiczony przed usunięciem krawędzi.
Transakcje SQLite i revision zapobiegają utracie równoczesnej aktualizacji.
Każde żądanie prywatne sprawdza właściciela; kosztowne importy wymagają dodatkowo
operatora. Niepoprawne dane i nieznane obszary WMS nie stają się brakiem zalania.

Stan: wdrożono na Luxonis ARM64. Przez publiczne HTTPS sprawdzono własne
pliki → wynik → zapis → odtworzenie kontenerów → odczyt, desktop/mobile,
eksport i rotację klucza. Na ARM64 przeszło 101 testów i backup/restore.
Stały adres publiczny: https://luxonis.tail6ad453.ts.net:8443/sentinelhub/. Import Sentinel wymaga odnowienia wygasłego konta
i nowej konfiguracji; pełnego przepływu WMS nie potwierdzono.
To analiza modelu dostępności, nie system prowadzenia
ewakuacji ani empirycznie zweryfikowany detektor powodzi.

## EN

**SentinelHub — routing analysis with user-supplied geospatial data.** A Python /
FastAPI application accepts road and flood GeoJSON, builds a directed graph,
excludes road segments intersecting flood polygons, and compares the remaining
shortest route with its baseline. SQLite persists versioned inputs and result
snapshots. Workspace ownership keys protect reads and writes. Operator-gated
imports use actual Overpass and a configurable Sentinel WMS integration; the
synthetic example is a separate, stateless screen.

The engineering problem is to connect spatial overlays with road connectivity
and a reproducible data workflow. Decisions include OSM node identities,
directed multigraphs, spatial intersections, anchoring endpoints before flood
exclusions, transactional writes and optimistic revision checks. Each private
request checks workspace ownership; external imports also require an operator
key. Missing data never triggers a simulated integration response.

Status: deployed on Luxonis ARM64 with 101 passing Python tests and verified
backup/restore. Public HTTPS browser tests cover user data, calculation,
persistence across container recreation, key rotation, exports and desktop/mobile.
The stable public URL is https://luxonis.tail6ad453.ts.net:8443/sentinelhub/. Sentinel remains blocked by an expired
account; renewal and a new active OGC instance are required. The WMS result has
not been verified.
The application is not operational evacuation guidance or a validated flood
detection model.

## Autorstwo

Zastano wcześniejszy kod integracji, grafu i routingu oraz niezacommitowane
zmiany z 37 testami. Poprzedni etap tego zadania dostarczył osobny przykład
z 71 testami. Aktualizacja do 0.4 dodaje własne dane, prywatne przestrzenie,
SQLite, wersjonowanie, trwałą historię, migrację i backup/restore. Nie przypisuj
tej późniejszej rozbudowy wcześniejszemu doświadczeniu zawodowemu.

Motywacja osobista, daty pierwotnych prac, samodzielny wkład autora i udział
innych osób wymagają jego potwierdzenia. Brak dowodów historycznych wdrożeń,
realnych użytkowników, zastosowań zawodowych i wyników jakości detekcji.

## Prezentacja 2–3 minuty

1. 0:00–0:30: wyjaśnij problem dostępności, źródło i datę danych. Utwórz przestrzeń
   i zapisz klucz. Zaznacz, że pliki `examples` są syntetyczne, a endpoint akceptuje
   również inne poprawne GeoJSON.
2. 0:30–1:15: wczytaj oba pliki, zapisz, ustaw `52,21` → `52,21.002`.
   Oblicz rzeczywisty wynik backendu: około 137 m → 582 m, jeden zablokowany odcinek.
3. 1:15–2:00: pobierz snapshot, odśwież stronę, otwórz przestrzeń kluczem i odczytaj
   ten sam wynik z historii. Pokaż odmowę dostępu błędnym kluczem.
4. 2:00–2:45: pokaż test transakcyjnego konfliktu, procedurę backup/restore i granicę
   integracji: brak Sentinel daje jawny błąd. Podaj faktyczny stan ARM64 / HTTPS.

Trzy tematy techniczne: topologia OSM i snap; transakcje/revision/snapshoty;
uwierzytelnianie kluczem przestrzeni i oddzielenie kosztownych importów operatora.