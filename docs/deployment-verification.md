> Zapis historyczny z 21.10.2026. Aktualne wydanie: [deployment.md](deployment.md), stały adres `/sentinelhub/`.

# Wdrożenie i sprawdzenia — 2026-10-21

## Aktualizacja 20261021-02: scenariusz dla rekrutera

Na głównym ekranie „Wczytaj przykład” tworzy przestrzeń, zapisuje syntetyczne
GeoJSON przez zwykłe API i przygotowuje punkty trasy. Drugie kliknięcie
„Oblicz i zapisz analizę” wykonuje obliczenia i zapisuje historię. Bez
przygotowywania plików, konta i klucza operatora. Można pobrać oba GeoJSON.
Podmiana istniejących danych wymaga potwierdzenia; historia pozostaje zachowana.

Wydanie `releases/20261021-02` (symlink `current`), obrazy z tagiem 20261021-02.
Backup przed aktualizacją: `/app/data/before-recruiter-20261021-02.sqlite3`.
Nie zmieniono tunelu, konfiguracji Sentinel ani schematu bazy.
Test `browser-recruiter.cjs` przeszedł lokalnie i przez publiczne HTTPS:
bez wybierania plików, rzeczywisty wynik 582 m / 1 z 4 zablokowanych odcinków,
historia, pobieranie poprawnych GeoJSON i widoki 1440/390 px bez overflow.
Po aktualizacji potwierdzono również odczyt wcześniejszego wyniku tym samym
kluczem oraz pełny ingress smoke. Zrzuty: `docs/assets/recruiter-*.png`.
SHA256 nowego archiwum:
`aae60f3a1e78c848cc6e4ed179b58390eeb92949e6465f2a2656aed3e989c161`.
Poniżej zachowano dowody pierwszego wdrożenia.

Publiczny adres: https://proud-publicly-dependent-talk.trycloudflare.com.
Jest tymczasowy: Cloudflare Quick Tunnel zmienia hostname po restarcie.
Nie jest to docelowy, stały link do portfolio.

## Faktyczne wydanie

- Host `luxonis`, Debian 12, kernel `6.12.109+rpt-rpi-2712`, aarch64, Python 3.12.15.
- Katalog `/opt/stacks/sentinelhub/releases/20261021-01`, symlink `current`.
- Snapshot roboczy, bez `.git`, `.env`, lokalnych baz, venv i node_modules.
- SHA256 archiwum: `5c2925af573f9bf9cac9a22a401f94c221e02dbaa9cbe4a0c85d0e66375d6ea3`.
- Obraz API: `sentinelhub-api:20261021-01`, manifest
  `sha256:1549f67754efe3df3e08636c7544d7280814b43aad655c19aba6a2c1f644c4c8`.
- Obraz web: `sentinelhub-web:20261021-01`, manifest
  `sha256:86872300e6c3e098e8f061aa015a9b2d7903f31e0b379733dd6db28de076ed99`.
- Osobny cloudflared 2026.10.0, przypięty digestem w Compose; bez tokena
  i bez zmian istniejącego tunelu ChordLab.
- Własny wolumen SQLite i sieć, hostowy port `127.0.0.1:8090`.
- Nowy klucz operatora w prywatnym `.env` (0600), poza obrazami i wydaniem.

Późniejsze poprawki dotyczą testowego allowlist origin, opisu pomiaru i
dokumentacji. Nie zmieniają wdrożonego kodu aplikacji. Nie wykonano commit/push.

## Wykonane kontrole

| Zakres | Dowód |
| --- | --- |
| Build ARM64 | Oba obrazy zbudowano natywnie na Raspberry Pi, w tym biblioteki natywne |
| Testy ARM64 | 101 passed in 3.07s w osobnym obrazie testowym; bez sieci i bez produkcyjnego wolumenu |
| Ingress na serwerze | `tests/container_smoke.py`: health, ready, pliki UI, API, upload, obliczenie, historia, autoryzacja, usunięcie |
| Publiczne HTTPS | Ten sam ingress test przeszedł z komputera przez publiczny adres |
| UI aplikacji przez HTTPS | Utworzenie przestrzeni, pobranie klucza, własne pliki, wynik, historia, eksport, błędne wejście, rotacja klucza, reconnect, desktop/mobile |
| Trwałość | Restart API oraz force-recreate API i web; przeglądarka odczytała stare dane i zapisany wynik tym samym kluczem |
| Backup/restore | Online Backup API, integrity check, odtworzenie do nowego pliku; porównano przestrzenie, dane, historie i pełne wyniki |
| Przykład przez HTTPS | Objazd/przejazd/brak przejazdu, reset, eksport, awaria/retry; 390/720/1024/1440 px bez overflow, zewnętrznych zasobów ani błędów JS |
| Prawdziwy Overpass na Pi | HTTP 200, zapis 252 obiektów drogowych, flood=null; bez klucza operatora 403 |
| Brak Sentinel | HTTP 503, poprzednie dane zachowane; osobna rzeczywista próba lokalnej konfiguracji wykazała wygaśnięcie konta |

Zrzuty `docs/assets/application-*.png` i `demo-*.png` pochodzą z testów
przeglądarki przez publiczny HTTPS. Przed zrzutem ukryto panel klucza.
Telefon sprawdzono przez viewport w przeglądarce, nie na fizycznym urządzeniu.
Nie restartowano całego hosta ani innych usług.

## Zasoby i pozostałe zależności

Osobny kontener testowy ARM64, 1 CPU, syntetyczne 900 węzłów / 1740 odcinków,
5 kolejnych żądań: mediana 415,17 ms, min 364,28, max 467,18 ms, peak RSS
107,48 MiB. Obejmuje TestClient, przetwarzanie i SQLite, bez Nginx/WMS.
Nie jest to test wielu użytkowników ani porównanie przed/po.

Docker: cgroup v2/systemd, `MemoryLimit=false`, `PidsLimit=true`,
`CpuCfsQuota=true`. Deklarowane limity pamięci nie są egzekwowane; statystyki
Dockera pokazują 0B. Nie zmieniono ustawień rozruchowych wspólnego serwera.
Ograniczenia plików, rozmiaru grafu, liczby przestrzeni, współbieżności,
czasu i retencji pozostają aktywne w aplikacji.

**Nie można uznać pełnej integracji Sentinel za uruchomioną.** Właściciel
potwierdził potrzebę odnowienia wygasłego konta. Potrzebne są nowa aktywna
instancja OGC, warstwa FLOOD i test rzeczywistego wyniku; starej wartości
z historii Git nie wdrożono. Własne GeoJSON nie wymagają tej usługi.
Stały link wymaga domeny i osobnego nazwanego tunelu. Inne usługi oraz
chronione katalogi Luxonis/DepthAI pozostały nienaruszone.
