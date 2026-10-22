# Pliki do pierwszej analizy

`roads.geojson` i `flood.geojson` to ręcznie zdefiniowane, **syntetyczne** dane
testowe. Współrzędne nie dowodzą istnienia takich dróg ani zalania w terenie.
Są zwykłymi plikami wejściowymi; aplikacja nie podmienia na nie danych użytkownika.

Wczytaj oba pliki, zaznacz „To są dane przykładowe”, podaj źródło „Syntetyczne
pliki examples” i datę `2026-01-01 10:00`. START: `52,21`, CEL: `52,21.002`.
Powinien powstać objazd jednego zablokowanego odcinka.

Własne dane: GeoJSON RFC 7946 w WGS84, kolejność współrzędnych `lon,lat`.
Drogi: FeatureCollection z LineString / MultiLineString, opcjonalnie `highway`,
`access`, `motorcar`, `oneway` i `osm_node_ids` w properties. Samo przecięcie
linii nie tworzy skrzyżowania — wspólny wierzchołek lub ID OSM musi być w danych.
Zalanie: Polygon / MultiPolygon, dozwolone poprawne, jawnie puste `features: []`.
Zapisujesz zawsze oba zbiory razem, ze źródłem i datą. Stare analizy zachowują
własny snapshot wejściowy po zmianie zbiorów.
