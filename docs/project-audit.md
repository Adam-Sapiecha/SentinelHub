# Audyt SentinelHub — 2026-10-21, aktualizacja wymagań pełnej aplikacji

## Zakres i punkt odniesienia

Oceniono zastany katalog, a nie sam HEAD: przed pracami zawierał niezacommitowane
poprawki i 37 przechodzących testów. Pierwszy etap dodał bezstanowy przykład
syntetyczny (71 testów). Nowe nadrzędne wymaganie właściciela wymaga własnych
danych i trwałości: sam przykład był do tego niewystarczający. Niniejszy dokument
zastępuje wcześniejszy werdykt i opisuje końcowy zakres 0.4.

Problem jest sensowny jako aplikacja analizy dostępności drogowej. Istniejący
rdzeń NetworkX / Shapely oraz OSM / WMS zachowano. Nie znaleziono dowodów
wcześniejszych wdrożeń, użytkowników ani jakości detekcji terenowej. Wcześniejsze
mocne strony: MultiDiGraph, tożsamości węzłów OSM, atomowe pliki, RLock, walidacja
API i testy bez płatnych usług. Zastany interfejs oceniono z kodu; przed zmianami
uruchomiono testy, nie pełny wcześniejszy przepływ UI.

## Ustalenia, skutki i status po naprawach

| Waga | Dowód i skutek przed | Stan / weryfikacja po |
| --- | --- | --- |
| P1 | `EvacRouter.find_route` snapował na grafie po wykluczeniach; odcięty START mógł przeskoczyć na inną drogę | Naprawiony. Snap przed blokadami; test odciętego węzła i brak fałszywej trasy |
| P1 | `load_flood_geometries` pomijał LineString i brak features; uszkodzone dane mogły oznaczać brak wody | Naprawiony. Walidacja kolekcji, geometrii, CRS i skończonych współrzędnych; regresje fail-closed |
| P1 | Syntetyczny ekran nie przyjmował własnych danych i nie zapisywał wyników | Naprawiony. `/` obsługuje własne GeoJSON, realny algorytm, zapis SQLite i historię; `/sample.html` pozostaje oddzielny |
| P1 | Wspólne pliki i brak modelu właściciela nie wystarczały do danych prywatnych wielu odwiedzających | Naprawiony w trybie application. Losowy klucz 256-bit, hash w bazie, autoryzacja każdego zasobu i testy cudzych kluczy |
| P1 | Brak kontroli jednoczesnych zapisów i utrwalonej wersji wejścia | Naprawiony. Transakcje i revision; edycja podczas obliczenia daje 409 zamiast błędnego zapisu; historia trzyma snapshoty |
| P1 | Pełne drogi Overpass wykraczają poza BBOX maski WMS | Naprawiony. Zachowane tylko kompletne segmenty wewnątrz pokrycia; graniczne odrzucone, test zachowania OSM IDs |
| P1 | Raster przezroczysty/częściowo nieznany mógł dawać brak zalania | Naprawiony. Każdy nieznany alpha odrzuca WMS; nie ma fallbacku danych |
| P2 | BBOX -180..180 omijał pole liczone krótszym łukiem | Naprawiony; regresja walidacji |
| P2 | Rondo ignorowało jawne oneway=no / -1 | Naprawiony; regresje obu kierunków |
| P2 | Brak trwałej historii, migracji i odtworzenia | Naprawiony. SQLite v1, backup API, integrity/foreign-key checks, restore bez nadpisania; sprawdzony odczyt po odtworzeniu |
| P2 | Publiczne porty API i web bez izolacji/limitów | Poprawione i sprawdzone na ARM64: loopback 8090, własny stos/sieć/wolumen; host nie egzekwuje limitów RAM |
| P2 | Nieograniczona odpowiedź zewnętrzna i anonimowe generowanie kosztów | Limit strumienia 4 MiB, jeden import naraz, wymagane role właściciel + operator; brak auto retry |
| P2 | Brak opisu pełnego uruchomienia i stanu serwera | Dokumentacja z read-only preflight luxonis, ARM64, backup/restore/rollback i placeholderami publicznego URL |
| P1/sekrety | HEAD zawierał `.env` z niepustą wartością | Zastane staged deletion zachowano, wykluczenie z obrazu sprawdzone. Historia nie została przepisana. Rotacja u dostawcy nadal wymagana |

## Decyzje tego etapu

**SQLite zamiast dodatkowej bazy/Redis.** Jeden serwer i ograniczona skala nie
wymagają kolejnych usług. WAL, synchronous FULL i BEGIN IMMEDIATE zapewniają
atomowość; optimistic revision zapobiega utracie aktualizacji bez trzymania
transakcji przez czas zapytania do dostawcy. Sprawdzamy revision także przy
zapisie wyniku, po obliczeniu. Zapis danych nie aktualizuje dawnych snapshotów.

**Klucz posiadacza zamiast kont i haseł.** Każda przestrzeń ma losowy klucz,
którego hash jest przechowywany. To rzeczywiste uwierzytelnianie i autoryzacja
zasobu, bez odzyskiwania hasła i tożsamości użytkownika. Utrata klucza oznacza
utratę samodzielnego dostępu; UI umożliwia zapis do pliku i rotację. Nie ma
jawnych kluczy w bazie, URL, logach ani browser storage. Dostęp administratora
systemu do plików i backupów pozostaje zaufaną granicą.

**Stały, mały zakres przetwarzania.** Własne dane mają limity bajtów, geometrii
oraz odcinków; 2 miejsca przetwarzania i 1 import naraz, jeden worker. Wyniki
są liczone synchronicznie; nie dodano atrapy zadań w tle ani kolejki, której
projekt nie potrzebuje. Deadline odpowiedzi nie zabija wątku — limity wejścia,
upstream i współbieżności pozostają konieczne. Po timeout należy najpierw
odczytać stan. Płatnych wywołań nie ponawiamy automatycznie.

**Osobny przykład i własne dane.** Przykład nie zapisuje w bazie. Użytkownik
może wczytać dowolne poprawne GeoJSON w udokumentowanym zakresie; gotowe pliki
są jawnie syntetyczne. Reset przykładu nie usuwa rzeczywistych danych.

Wcześniejsze decyzje autora widoczne w kodzie: NetworkX, Shapely/STRtree,
interpretacja WMS przez maskę kolorów i topologia OSM. Nie przypisujemy autorstwa
lub osobistej motywacji bez potwierdzenia.

## Weryfikacja — osobne poziomy dowodów

**Lokalnie:** świeża instalacja Python 3.12.14 z przypiętymi zależnościami;
101 testów Python, Ruff lint/format, pip check. Rzeczywiste UI Edge/Chromium
przy 390/720/1024/1440 px: utworzenie przestrzeni, klucz do pliku, upload,
obliczenie i zapis, JSON wyniku, historia, błędne wejście, odczyt po odświeżeniu.
Zatrzymano proces Uvicorn i uruchomiono go ponownie — tym samym kluczem odczytano
wejście i zapisany wynik. Zrzuty aplikacji i przykładu powstały z działającego UI.

Testy zachowania: obca przestrzeń/analiza niedostępna, rotacja unieważnia klucz,
konflikt równoległych zmian, edycja podczas obliczeń, quota i retencja, błąd
upstream zachowuje poprzednie dane, uszkodzony backup odrzucony, przyszła wersja
schematu nie jest kasowana, restore odtwarza uprawnienia/dane/wynik. Test jednostkowy
evalscriptu jest oddzielny od testu rzeczywistej usługi.

**Rzeczywista integracja:** Overpass HTTP 200: pierwsza kontrola pobrała 71 surowych obiektów; po wdrożeniu
ograniczenia pokrycia drugi rzeczywisty import zapisał 252 obiekty drogowe
do izolowanej SQLite. Sprawdzono, że wszystkie zachowane wierzchołki należą
do BBOX. Flood pozostał null, bez fałszywego ukończenia pary. Regresja sprawdza
również zachowanie identyfikatorów OSM.
Rzeczywista próba obecnej konfiguracji Sentinel wykazała wygaśnięcie konta.
Właściciel potwierdził potrzebę odnowienia. Wartość występuje w historii Git;
nie wdrożono jej. Wymagana nowa aktywna instancja i warstwa według `sentinel.md`.

**ARM64:** oba obrazy zbudowano natywnie na Luxonis, 101 testów przeszło
w osobnym kontenerze ARM64. Biblioteki natywne działają. Zdalnego CI nie uruchamiano.

**Serwer:** po preflight uruchomiono osobny stos w `/opt/stacks/sentinelhub`,
własną sieć, wolumen i loopback 8090. Nie zmieniano istniejących usług,
Tailscale Serve ani chronionych katalogów Luxonis/DepthAI.

**Kontenery:** ingress Nginx, upload, analiza, historia i auth sprawdzone.
Po restarcie i odtworzeniu API/web przeglądarka odczytała dane i wynik.
Backup/restore na serwerze potwierdził zgodność danych, historii i wyników.
Docker hosta nie egzekwuje limitów RAM; CPU/PID są obsługiwane.

**Publiczne HTTPS:** niezależny Quick Tunnel przeszedł ingress oraz testy UI
aplikacji i przykładu desktop/mobile. Adres jest tymczasowy. Prawdziwy Overpass
na Pi zapisał 252 obiekty; brak Sentinel daje 503 i zachowuje poprzednie dane.
[Raport z dowodami i adresem](deployment-verification.md).

## Pomiar zasobów

`python -m tests.profile_scenario`, Windows 11 AMD64 / Python 3.12.14:
syntetyczna siatka 30×30, 900 węzłów, 1740 odcinków i prostokąt zalania,
5 kolejnych żądań ze snapshotami SQLite. Mediana 237,31 ms, min 204,74,
max 294,55 ms; peak working set procesu 102,36 MiB, mierzony Win32 PSAPI.
Obejmuje zależności i TestClient, bez Nginx i kosztu prawdziwego WMS. Nie jest
pomiarem Pi, scenariuszem współbieżnym ani pomiarem przed/po. Osobny pomiar
ARM64 i brak egzekwowania limitów RAM opisano w raporcie wdrożenia.
Brak deklaracji pojemności dla 10 aplikacji.

## Ograniczenia świadome

To analiza grafu dla dostarczonych danych. Brak ograniczeń skrętów, pomiarów
ruchu i głębokości, analizy dojścia do węzła, bezpieczeństwa mostów oraz
empirycznej walidacji klasyfikacji satelitarnej. WMS NDWI jest heurystyką
powierzchniowej wody, nie detekcją zdarzenia powodzi. Downsample/filtrowanie
może pomijać małe obszary; dokładne parametry opisuje sentinel.md. Przecięcia
w WGS84 są przybliżeniem lokalnym. Data i źródło uploadu są deklaracją użytkownika;
WMS nie udaje znanej daty obserwacji. Bez potwierdzenia jakości nie jest to
narzędzie decyzji ewakuacyjnych. Stan aplikacji własnych plików jest odrębny
od gotowości zewnętrznej usługi i publikacji.

## Ocena 1–10 przed / po

Przed: pierwotny zastany stan z 37 testami; po: pełny zakres 0.4.

| Kategoria | Przed | Po | Uzasadnienie |
| --- | ---: | ---: | --- |
| Sens i zakres | 6 | 8 | Jest pełny przepływ własnych danych i historii, nie tylko przykład |
| Poprawność | 5 | 8 | Naprawy snap/flood/topologii, konflikty i snapshoty; detekcja WMS pozostaje heurystyczna |
| Kod i architektura | 6 | 8 | Zachowany rdzeń, oddzielone walidacja/SQLite/API, bez zbędnego serwera bazy |
| Testowanie | 6 | 8 | 101 testów ARM64, HTTPS UI, recreate, restore i realny Overpass; brak wyniku aktywnego WMS |
| Użyteczność | 2 | 8 | Własne pliki, źródło, geometria, klucz, wynik, historia, eksport i osobny przykład |
| Odtwarzalność | 4 | 8 | Build ARM64, ingress, recreate i restore sprawdzone; adres tunelu tymczasowy |
| Dowód umiejętności backendowych | 5 | 8 | Topologia/przestrzeń, autoryzacja, trwałość, transakcje, konflikty i utrzymanie widoczne w kodzie |

## Werdykt

**Wymaga wskazanych poprawek przed publikacją jako w pełni zintegrowana aplikacja.**
Zakres własnych plików jest wdrożony i gotowy do demonstracji przez publiczne
HTTPS: wejście, wynik, zapis i odczyt po odtworzeniu kontenerów potwierdzono.
Pełny WMS pozostaje zablokowany wygasłym kontem. Potrzebne są odnowienie,
nowa instancja/warstwa i test wyniku. Stały adres wymaga domeny/nazwanego tunelu.

Na Luxonis nie działa kontroler pamięci Dockera. Pomiar ARM64 (1 CPU,
1740 odcinków, 5 żądań) dał medianę 415,17 ms i peak RSS 107,48 MiB.
Zakres pomiaru opisuje raport. Nie deklarujemy obsługi 10 aplikacji naraz.
Nie zmieniono konfiguracji hosta ani niezwiązanych usług.
