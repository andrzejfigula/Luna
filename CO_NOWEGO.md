# Luna — co nowego (paczka-niespodzianka)

Ściąga: co Luna teraz potrafi i jak to wywołać. Wszystko po polsku, zwykłymi
zdaniami. Szczegóły techniczne i ustawienia są w `SETUP.md` i `BACKLOG.md`.

## Rozmowa

| Co | Jak |
|---|---|
| Szybsze odpowiedzi | samo działa — mówi pierwsze zdanie, zanim model dopisze resztę (pierwszy dźwięk ~1–1,5 s) |
| Głos z emocjami | samo działa — wesoła odpowiedź brzmi weselej, smutna łagodniej; ciszej i spokojniej, gdy wyglądasz na zmęczonego |
| Mów bez „Luna” | **przytrzymaj palec na ekranie** ~1 s → „hm?” i słucha |
| Przerwij jej | **stuknij w ekran**, kiedy mówi |
| Koniec rozmowy | „Pa!”, „Do zobaczenia”, „Dzięki, to wszystko” — pomacha i przestanie słuchać |
| Czeka na odpowiedź | gdy zada pytanie, słucha dłużej (+8 s) |
| Powtórz | „Powtórz”, „Co powiedziałaś?” — odtwarza ostatnią odpowiedź od razu, bez pytania chmury |
| Bajki i dłuższe wyjaśnienia | „Opowiedz mi bajkę o smoku”, „Wyjaśnij dokładnie, jak działa…” |
| Co potrafi | „Luna, co potrafisz?” |
| Tłumacz | „Tłumacz na angielski” (niemiecki, hiszpański, francuski, włoski, ukraiński…) — każde zdanie wraca przetłumaczone, w obie strony; „Koniec tłumaczenia” |
| Jak się czuje | „Jak się czujesz?” — zna temperaturę swojego procesora i czas pracy |

## Pamięć i nastrój

| Co | Jak |
|---|---|
| Pamięta Cię między dniami | samo działa — imię, plany, ważne sprawy; po rozmowie o czymś ważnym zapyta później, jak poszło |
| Poranne powitanie | pierwsze „cześć” danego dnia zna pogodę (jeśli włączona), przypomnienia i wczorajsze sprawy |
| Co o mnie wiesz | „Co o mnie pamiętasz?” |
| Wyczyść pamięć | „Luna, zapomnij wszystko” |
| Nastrój z kamery | samo działa — dopasowuje ton; skomentuje najwyżej raz na 30 min |

## Przydatne

| Co | Jak |
|---|---|
| Minutnik | „Minutnik na 10 minut”, „na pół godziny”, „na kwadrans” — od razu, bez chmury (działa też bez internetu); „Nastaw minutnik na makaron, 8 minut” — z etykietą |
| Przypomnienie | „Przypomnij mi o 18:30, żeby zadzwonić do mamy” |
| Ile zostało | „Ile zostało na minutniku?” — odliczanie widać też w prawym górnym rogu, a ostatnie 5 sekund wielkimi cyframi |
| Anuluj | „Wyłącz minutnik”, „Usuń przypomnienie o mamie” |
| Budzik ze świtem | „Obudź mnie jutro o siódmej” — 10 min wcześniej ekran powoli się rozjaśnia |
| Powtarzające się | „Budzik w dni robocze na 6:30”, „Codziennie o 21 przypominaj mi o tabletkach” (też „w weekendy”) |
| Lista | „Pokaż przypomnienia” — wszystko, co ustawione, na ekranie |
| Listy zakupów / zadań | „Dopisz mleko i chleb do listy zakupów”, „Skreśl chleb”, „Co mam na liście?”, „Dodaj do listy rzeczy do zrobienia: …”, „Pokaż listę zakupów” (na ekranie) |
| Tryb skupienia | „Włącz tryb skupienia” (albo „pomodoro na 50 minut”) — 25 min ciszy, potem „czas na przerwę” i 5 min przerwy; „koniec skupienia” wyłącza |
| Oddech | „Ćwiczenie oddechowe” / „Pomóż mi się uspokoić” — okrąg na ekranie i jej głos: wdech 4 s, pauza 2 s, wydech 6 s |
| Głośność | „Głośniej”, „Ciszej”, „Głośność na 40” |
| Tempo mowy | „Mów wolniej”, „Szybciej”, „Mów normalnie” (zapamiętuje) |
| Pogoda | „Jaka będzie jutro pogoda?” — **trzeba włączyć**: w `.env` wpisz `LUNA_LAT=` i `LUNA_LON=` (np. 52.23 / 21.01) |

## Zabawa

| Co | Jak |
|---|---|
| Kamień, papier, nożyce | „Zagrajmy w kamień, papier, nożyce!” — do dwóch wygranych, pokaż rękę do kamery na „!”; „tak” = rewanż |
| Zdjęcie | „Zrób mi zdjęcie” — odliczanie, błysk, zdjęcie jak polaroid; zapisuje się w `~/luna/photos/` (tylko na Pi) |
| Kostka i moneta | „Rzuć kostką”, „Rzuć dwiema kostkami”, „Orzeł czy reszka?” |
| Piątka | „Przybij piątkę” — pokazuje rękę, stuknij w ekran w ciągu 4 s |
| Galeria | „Pokaż zdjęcia” — zrobione zdjęcia, najnowsze pierwsze, co 6 s; stuknięcie = następne |
| Lusterko | „Pokaż lustro” — kamera jako lustro przez 15 s |
| Zegar | „Pokaż zegar” — duża godzina z datą przez 10 s |
| Rekwizyty przy odpowiedzi | samo działa — przy rozmowie o pogodzie słońce/chmury/deszcz/śnieg, przy pomyśle żarówka, przy muzyce nutki |

Każdy pełny ekran (lustro, zdjęcie, zegar) zamyka się stuknięciem.

## Noc

| Co | Jak |
|---|---|
| Lampka nocna | „Włącz lampkę” — cały ekran ciepło świeci (45 %); „wyłącz lampkę” albo stuknięcie gasi |
| Dobranoc | „Dobranoc” — zamyka oczy, ekran prawie gaśnie, nie zagaduje do rana; obudzi się, gdy się do niej odezwiesz |
| Tryb nocny | samo działa — w godzinach ciszy (22–8) ekran przygasa, a głos jest o połowę cichszy (budziki i minutniki dzwonią normalnie) |
| Jasność od światła w pokoju | samo działa — kamera mierzy światło; w ciemnym pokoju ekran schodzi do 25 %. Próg ciemności jest na razie zgadnięty — wartość `light` jest co godzinę w `luna.log` (`[health]`) |
| Cisza | „Luna, cicho” — godzina bez zagadywania (było już wcześniej) |

## Pod maską

- Bez internetu: w lewym górnym rogu przekreślona chmurka, a Luna mówi nagrany wcześniej komunikat zamiast milczeć.
- W pustym pokoju zużywa ~51 % CPU zamiast ~158 % i jest chłodniejsza (~63 °C zamiast ~70 °C).
- Co godzinę w `luna.log` linia `[health]`: temperatura, obciążenie, liczba odpowiedzi i ich średni czas, ewentualne przerwy w dźwięku.
- Testy logiki (na dowolnym komputerze): `python -X utf8 -m unittest discover -s tests`.

## Na co zwrócić uwagę przy pierwszym użyciu

1. **Dźwięk** — odtwarzacz jest teraz stale otwarty. Gdyby coś trzeszczało, w `config.py` ustaw `AUDIO_PERSISTENT = False` (stary sposób) i daj znać.
2. **Pogoda** jest wyłączona, dopóki nie ustawisz współrzędnych.
3. **Kamień, papier, nożyce** i **zdjęcie** nie były testowane z prawdziwą osobą przed kamerą (pokój był pusty) — przebieg gry przetestowałam z symulowanym przeciwnikiem.
