# Prawdziwe importy i zależności

## Role i klucze

Właściciel przestrzeni przesyła klucz Bearer. Operator dodatkowo podaje
`X-Admin-Key` zgodny z `ADMIN_API_KEY` serwera (≥32 losowe znaki). Te dwa warunki
są sprawdzane niezależnie. Klucz operatora nie daje dostępu do przestrzeni bez
jej klucza. Nie udostępniaj go rekruterom ani nie zapisuj we frontendzie.
Anonimowy przykład nie wywołuje zewnętrznych usług.

Overpass nie wymaga płatnego konta. Operator wybiera niewielki BBOX i wykonuje
jedno rzeczywiste żądanie XML. Błędy sieci i przekroczenie limitu odpowiedzi nie
nadpisują danych. Sprawdzono rzeczywisty import i zapis; zalania nie dopisano.

## Sentinel Hub OGC WMS

Wymagane: aktywny dostęp do Sentinel Hub z limitem dla Sentinel-2 L2A / OGC,
instancja utworzona w Configuration Utility i warstwa o nazwie **FLOOD**.
`SENTINELHUB_INSTANCE_ID` to ID tej instancji, nie OAuth client_id. Ta integracja
nie wykorzystuje OAuth client_secret; nie przyznawaj aplikacji dostępu do
zarządzania kontem lub innymi instancjami. Dedykowana instancja, jej ID i limity
powinny należeć wyłącznie do tego projektu. Traktuj ID jako prywatną konfigurację
umożliwiającą zużywanie przydziału. Wartość ujawnioną w historii należy zrotować.

W `.env`:

```dotenv
ADMIN_API_KEY=REPLACE_WITH_RANDOM_OPERATOR_SECRET_AT_LEAST_32_CHARACTERS
SENTINELHUB_INSTANCE_ID=REPLACE_WITH_ROTATED_ACTIVE_OGC_INSTANCE
SENTINELHUB_TIME_RANGE=YYYY-MM-DD/YYYY-MM-DD
```

Zakres czasu uzupełnij prawdziwymi datami. Aktualizacja kontenera jest potrzebna
po zmianie env. Aplikacja nie weryfikuje uprawnień konta przez podstawianie danych.
Brak konfiguracji daje 503, odmowa usługi/błędne dane 502, z czytelnym komunikatem.

## Warstwa i kontrakt rastra

W Sentinel-2 L2A skonfiguruj warstwę FLOOD z
[`integrations/sentinel-water.js`](../integrations/sentinel-water.js).
To wykonywalny evalscript v3: NDWI z B03/B08, próg 0,3, przyjęte klasy SCL
4/5/6/7 i dataMask. Woda: niebieski z alpha=1; poprawny, niewodny piksel: czarny
z alpha=1; chmury i nieznane dane: alpha=0. Nie stosuj legendy ani przezroczystego
koloru dla poprawnych danych lądowych. Pełna aktywacja wymaga wykonania tego
kroku w koncie dostawcy; repozytorium nie skonfigurowało go za użytkownika.

Backend pobiera WMS 1.3.0, EPSG:4326, BBOX w porządku south,west,north,east,
PNG 512×512 i wskazany zakres czasu. Każdy przezroczysty piksel powoduje
odrzucenie rastra — brak obserwacji nie jest bezpiecznym lądem. Błędy konta,
rozmiaru, odpowiedzi i geometrii nie uruchamiają trybu zastępczego.

Maska wody jest przetwarzana w blokach 4×4 z progiem udziału 0,1, scalana
w poligony, z filtrem małych komponentów (7 komórek). To dotychczasowy,
przybliżony algorytm; mniejsze obszary mogą zostać pominięte. Skala zależy
od BBOX i nie oznacza natywnej rozdzielczości sensora. Bez walidacji terenowej
nie deklarujemy trafności klasyfikacji ani oceny przejezdności.

Wykrywana jest powierzchniowa woda, **nie zweryfikowana powódź względem
stanu referencyjnego**. Nie ma estymacji głębokości, walidacji mostów ani
gwarancji bezpieczeństwa drogi. Odróżniaj semantykę źródła od działania routera,
który prawidłowo omija przekazane poligony.

## Spójność obszaru i daty

Import obu dostawców musi mieć identyczny BBOX. Zmiana BBOX rozpoczyna nową
parę; brakujący drugi zbiór blokuje analizę 409. Drogi Overpass poza BBOX oraz
segmenty przecinające jego granicę są konserwatywnie odrzucane. Nie wyznaczamy
objazdu przez teren nieobjęty maską WMS. Punkty trasy muszą należeć do BBOX.

Zapis zawiera `providers.*.retrieved_at`, `coverage`, `wms_time_range`,
`saved_at`. `observed_at=null` wskazuje brak potwierdzonej daty obserwacji
konkretnego piksela; czasu pobrania nie przedstawiamy jako pomiaru na żywo.
Maksymalnie jeden import naraz, do 100 km² i 4 MiB odpowiedzi. Nie ma
automatycznych retry ani dowolnych URL użytkownika.

## Stan weryfikacji

2026-10-21: rzeczywista próba lokalnej konfiguracji zwróciła błąd wygaśnięcia
konta. Właściciel potwierdził potrzebę odnowienia. Wartość występuje również
w historii Git — wymagana jest nowa aktywna instancja. Nie skopiowano jej na
serwer. Wdrożone API zwraca 503 bez konfiguracji i zachowuje wcześniejsze dane.

Rzeczywisty Overpass: sprawdzony HTTP 200 i zapis do SQLite. Testy jednostkowe
evalscriptu sprawdzają wodę, ląd, chmurę i brak sygnału. Testy WMS sprawdzają
interpretację PNG, alpha, wymiary i awarie. **Nie wykonano rzeczywistego WMS
z aktywną, zrotowaną instancją i tą warstwą.** Jej brak jest przeszkodą do
uznania całej integracji zewnętrznej za uruchomioną. Własne pliki GeoJSON działają
niezależnie. Mocki testowe nie występują w ścieżce aplikacji.
