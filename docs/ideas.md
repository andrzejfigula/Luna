# Luna — ideas (not built, not promised)

Proposals to sift, written 4 Nov 2026 after checking each against the backlog,
`CO_NOWEGO.md`, `data/whatsnew.txt` and the code. Filter and mark them with the
tool, no need to read this file:

    python -X utf8 tools/ideas.py area=games size=S       # filters add up
    python -X utf8 tools/ideas.py value=3 needs=- maja    # plain words search the text
    python -X utf8 tools/ideas.py stats                   # how many in each group
    python -X utf8 tools/ideas.py drop 12 40 area=hw      # numbers and/or a filter
    python -X utf8 tools/ideas.py keep 7 / undo 7 / built 7

Dropped ideas stay here, hidden, so nobody proposes them again.

- **Mark**: `·` undecided, `✓` keep, `✗` drop, `✅` built
- **Area**: learn, games, play, music, home, family, her, face, voice, info, health, privacy, robust, cost, dev, hw
- **For**: maja, grown (Andrzej, Emilka), all, dev (the code, not the family)
- **Size**: S a few hours, M a day or two, L several days. **Value**: 3 high, 2 medium, 1 nice to have. Both are guesses.
- **Kind**: new, or better (improves something that exists; the Idea names the module)
- **Needs**: `-` nothing extra, `model` costs OpenAI money per use, `net` another online service, `hw` something to buy, `sudo` Andrzej installs something
- `#N` in a row is a backlog row (`tools/backlog.py show N`); another row here is "idea N".
- Left out on purpose: anything parked (voice interrupt, web panel) and idle animations. Anything nudging on its own is opt-in, asked for by voice.

| # | Mark | Area | For | Size | Value | Kind | Needs | Idea | Why |
|---|---|---|---|---|---|---|---|---|---|
| 1 | · | learn | maja | S | 3 | better | - | **Packing from the timetable** — "Co spakować na jutro?" names tomorrow's subjects from the plan lekcji, kids.py's routine step uses it | "Spakuj plecak" says nothing about what goes in, and the timetable is already there |
| 2 | · | learn | maja | M | 3 | better | model | **Questions after reading** — reading.py asks two short questions about what was just read, and keeps the score | It checks the words only; school cares whether the child understood |
| 3 | · | learn | maja | M | 3 | new | model | **Maja teaches Luna** — "Pobawmy się w szkołę": Luna is the pupil, makes planted mistakes, the child corrects them | Explaining to someone else teaches best, and being the teacher is fun at 8 |
| 4 | · | learn | maja | M | 3 | new | - | **A poem by heart** — poem from the camera or by voice, then line by line, then with words left out, then whole | A regular Polish homework that nothing here helps with yet |
| 5 | · | learn | maja | M | 3 | new | - | **Playing shop** — a price list and coins on the touchscreen, the child pays, Luna asks for the change | Money isn't covered by any quiz, and it's a real game rather than a test |
| 6 | · | learn | maja | M | 3 | better | - | **Words come back on a schedule** — quiz.py's mistakes move through boxes: tomorrow, in 3 days, in a week | #142 brings back recent mistakes (14 days) in dictation and tables only, with no schedule for what was learned |
| 7 | · | learn | maja | S | 2 | new | - | **Parts of speech game** — "Zagrajmy w części mowy": rzeczownik, czasownik, przymiotnik, from a hand-written word list | Third-grade grammar, a new quiz on the existing engine |
| 8 | · | learn | maja | S | 2 | better | - | **Reading speed over the weeks** — reading.py stores words a minute, "Jak mi idzie czytanie?" says the trend | Progress you can hear motivates; the numbers are already passing through |
| 9 | · | learn | maja | M | 2 | new | - | **A touch map of Poland** — "Gdzie leży Kraków?" tap the outline; voivodeships and rivers as rounds | Geography by touch; the flags and capitals have no map behind them |
| 10 | · | learn | maja | S | 2 | better | - | **Times-table heat map** — a 10×10 grid coloured by that child's mistakes, a page for child and parent | Shows at a glance which products are weak; #141 reports each round's missed sums, not the whole picture |
| 11 | · | learn | maja | M | 2 | new | - | **Experiment of the week** — safe home experiments from a checked list, step by step on the cooking.py engine | Science is hands on, and the step-by-step engine exists |
| 12 | · | learn | maja | S | 2 | new | - | **Why-notebook** — the child's own questions kept: "O co dziś pytałam?", parents can hear them | Children's questions are worth keeping, and they show what interests the child |
| 13 | · | learn | maja | S | 2 | new | - | **Fractions in pictures** — pizza slices on screen, "ile to jest trzy czwarte?", tap the slices | Fractions need pictures, and the voice quiz can't show them |
| 14 | · | learn | maja | M | 2 | new | - | **Written sums on screen** — column addition and subtraction, digit by digit with the carry | The way school teaches it; the maths quiz is mental only |
| 15 | · | learn | maja | M | 2 | better | - | **Revision before a test** — "W piątek sprawdzian z przyrody" brings a few questions each day until then, if asked for | #524 starts a quiz only when asked, with nothing spread over the days before |
| 16 | · | learn | maja | M | 2 | new | model | **English role-play** — at the shop, at the airport: Luna plays the other person and corrects gently | English practice now is words and dictation, never a conversation |
| 17 | · | learn | maja | M | 2 | better | - | **Tracing letters** — dotted letters in Malowanie (paint.py), followed with a finger, joined handwriting too | Handwriting practice on a surface that's already there |
| 18 | · | learn | maja | M | 2 | better | model | **Drawing lesson** — "Naucz mnie rysować kota": drawing.py's picture broken into steps to copy on paper or in Malowanie | Drawing ends in a finished picture, not in a new skill |
| 19 | · | learn | maja | S | 2 | better | - | **What's set for homework** — "Zadane z matmy na środę" kept by subject and due date, on the morning plan | lists.py has due dates; school needs subject + date + "zrobione" |
| 20 | · | learn | maja | S | 1 | new | - | **Roman numerals and months** — small quiz rounds: order of months, seasons, Roman numerals | Curriculum bits, hand-written, cheap |
| 21 | · | learn | maja | S | 1 | new | - | **Landmarks and famous Poles** — a photo quiz on webphoto.py, like the animals | A third photo round for little work |
| 22 | · | learn | all | S | 1 | new | - | **Word and proverb of the day** — on request: a new word or przysłowie, what it means, and an example | Vocabulary, nice with breakfast |
| 23 | · | learn | maja | S | 1 | new | model | **Presentation practice** — "Posłuchaj mojej prezentacji": timed, then one thing good and one to fix | Reading mode almost does this already |
| 24 | · | learn | maja | M | 1 | better | net | **Real classics from Wikisource** — public-domain poems word for word instead of the model's memory | Poems by a named poet shouldn't be invented |
| 25 | · | learn | maja | M | 1 | new | - | **Pronunciation check in English** — compare what's said with the target word, say which sound | Transcription tends to autocorrect, so it needs a try first |
| 26 | · | games | maja | S | 3 | new | - | **Hangman** — "Zagrajmy w wisielca", letters on the touchscreen or by voice, from a checked word list | A classic missing from the shelf; helps spelling too |
| 27 | · | games | all | S | 3 | new | - | **Word chain** — each word starts with the last letter of the one before; Luna plays from a dictionary | A voice-only game with nothing to look at, works across the room |
| 28 | · | games | maja | S | 3 | new | - | **Colour sequence** — colours and tones to repeat on the touchscreen, one longer each round; records per person | Fast, no words needed, and the touchscreen suits it |
| 29 | · | games | all | M | 3 | new | - | **Team quiz** — two teams, buzz in on either side of the screen, scores on screen | Family game night; every quiz today is one player |
| 30 | · | games | all | S | 3 | new | model | **She guesses your drawing** — "Zgadnij, co rysuję": Malowanie's picture goes to the vision model, she guesses aloud | Uses paint.py and the camera path; a very Luna kind of game |
| 31 | · | games | maja | S | 3 | new | model | **Bring me something red** — a thing to find at home, shown to the camera, she judges | Gets the child moving, and the camera is the point of having her |
| 32 | · | games | maja | M | 3 | new | - | **Treasure hunt** — a parent hides clues by voice, she hands them out one by one, photo or word as proof | Half an hour of play from one rainy afternoon's setup |
| 33 | · | games | maja | S | 3 | new | - | **Freeze when she looks** — "Raz, dwa, trzy, Baba Jaga patrzy": music, then stop, camera motion finds who moved | Traditional game, and gesture_module's motion measure already exists |
| 34 | · | games | maja | S | 2 | new | - | **The quiet game** — who stays quietest for a minute, from the mic level, a meter on screen | Simple, and parents like it too |
| 35 | · | games | all | S | 2 | new | - | **Connect four** — on the touchscreen, against her or two players, on tictac.py's pattern | A step up from noughts and crosses |
| 36 | · | games | all | M | 2 | new | - | **Battleships by voice** — "B5!", the board on screen, she keeps her ships honest | Good at a distance; letter and number recognition is a test of its own |
| 37 | · | games | maja | S | 2 | new | - | **Sliding puzzle from your photos** — gallery.py's picture cut into squares | The family's own photos make it personal |
| 38 | · | games | maja | S | 2 | new | - | **Finger maze** — a new maze each time, drawn with a finger, harder each round | Quick, quiet, no model and no talking |
| 39 | · | games | all | S | 2 | new | - | **Charades** — she shows one person a word while the rest look away; a timer; a score | Family game with no equipment |
| 40 | · | games | all | M | 2 | new | model | **You guess her drawing** — she draws stroke by stroke, you shout what it is | Pictures reveal gradually; a nice twin of idea 30 |
| 41 | · | games | all | S | 2 | new | - | **Quiz about the family** — questions from what she knows (birthdays, favourites), secrets and surprises never | Funny because it's about you |
| 42 | · | games | all | S | 2 | better | - | **League table** — a page with this month's champion per game from the records (#107) | Sibling-style rivalry, from data already saved |
| 43 | · | games | all | S | 2 | new | - | **Tongue twisters** — she says one, you try, she judges by the transcript | Polish is great for it, and it makes everybody laugh |
| 44 | · | games | maja | S | 2 | new | - | **Children's jokes** — "Opowiedz kawał": a hand-written, checked set that doesn't repeat | The model's jokes repeat and sometimes fall flat |
| 45 | · | games | maja | M | 2 | better | model | **Answer with fingers** — in a maths quiz show the number, the vision model counts, as it judges the hand in #314 | Answers without speech, good with the radio on |
| 46 | · | games | maja | M | 2 | new | - | **A virtual pet** — fed and walked by voice and touch, only when opened, never calling for attention | Teaches care, and it fits the no-idle rule if it just waits |
| 47 | · | games | all | M | 1 | new | - | **Draughts** — on the touchscreen for two players, or against a simple opponent | A family board game with a real rule set |
| 48 | · | games | maja | S | 1 | new | - | **Mini sudoku** — 4×4 and 6×6 with pictures or numbers | Quiet logic for an 8-year-old |
| 49 | · | games | all | S | 1 | new | - | **Bingo night** — she draws the numbers, cards printed on the home printer | Uses printer.py; needs a crowd |
| 50 | · | games | all | S | 1 | new | - | **Would you rather** — silly choices from a checked list, she says which she'd pick and why | A filler for dinner or the bath |
| 51 | · | games | maja | S | 1 | new | - | **Magic ball** — "Czy jutro będzie fajnie?": a shaken ball on screen answers | Ten seconds of fun, all local |
| 52 | · | play | maja | S | 3 | new | model | **A story from my drawing** — "Opowiedz bajkę o moim rysunku": Malowanie's picture starts story.py | Links her two best things, and the child is the author |
| 53 | · | play | all | M | 3 | better | model | **Stories with many voices** — story.py: narrator, dragon and princess each get a voice instruction, a take cached per line | Her stories are told in one voice, and a child hears the difference at once |
| 54 | · | play | maja | M | 3 | new | - | **Stop-motion film** — "Zróbmy film": a frame per tap with onion-skin on screen, plays back as a little film | A real project for an afternoon with toys; camera and screen are there |
| 55 | · | play | maja | S | 3 | new | - | **Blow out the candles** — a cake on screen, the mic hears the blow, candles go out; birthdays.py offers it on the day | One minute that gets remembered; the birthday list is there |
| 56 | · | play | maja | M | 3 | new | - | **Advent calendar** — 24 windows on screen, one opens a day per child: a riddle, a drawing or a small task | It's 4 November: right on time, and visible every day of December |
| 57 | · | play | maja | S | 3 | new | - | **Letter to Santa** — dictated, polished and printed; parents can ask what's in it, and Santa stays magic for the child (#329, #410) | Seasonal; parents learn the wishes without asking |
| 58 | · | play | maja | S | 2 | better | - | **Sounds inside stories** — ambience.py's rain, forest or fire under a scene, and sounds.py when something happens | Bedtime stories get a soundscape with no new assets |
| 59 | · | play | maja | M | 2 | new | model | **Comic strip** — four panels from drawing.py with speech bubbles, kept and printable | Stories get a form the child can carry away |
| 60 | · | play | maja | S | 2 | better | - | **A printed story booklet** — printer.py lays out a kept story.py story with its pictures as a folded A4 booklet | The child has a real book at the end; the parts exist |
| 61 | · | play | maja | M | 2 | new | - | **Hats in the mirror** — live overlays on the camera mirror: a crown, glasses, ears, tracked to the face | The mirror (#23) does nothing playful yet; faces are tracked anyway |
| 62 | · | play | maja | S | 2 | new | - | **Touch piano** — keys on screen, record a melody, she plays it back, or a song to follow | Music you make, not only listen to |
| 63 | · | play | maja | M | 2 | better | - | **She wears your drawing** — a hat or sticker painted in Malowanie, worn on her face | The child designs part of Luna |
| 64 | · | play | maja | S | 2 | better | - | **Toys she remembers** — "To jest Pan Miś": a toy's name and look kept for stories and hellos | Toys become part of her world, memory.py can keep it |
| 65 | · | play | maja | S | 2 | new | model | **Pretend play** — she plays the doctor, the shopkeeper, the pet; a mode with a clear stop | Long imaginative play, a good use of the model |
| 66 | · | play | all | S | 2 | better | - | **Costumes through the year** — Santa hat in December, pumpkin in October, from a date table, on request or for the greeting | Environment already follows the seasons, her face doesn't |
| 67 | · | play | maja | S | 1 | new | - | **Your painting as her sky** — a Malowanie picture as the page behind the clock or lamp | A small pride for the artist |
| 68 | · | music | all | S | 3 | better | - | **Song history** — radio.py keeps titles: "Co grało przed chwilą?", "Zapisz tę piosenkę", read back as a list | The song you liked is always over by the time you ask |
| 69 | · | music | all | S | 3 | new | - | **Audiobooks from a folder** — "Włącz audiobook" plays local files per child and resumes where it stopped | Long listening with no model cost and no internet, good for bedtime |
| 70 | · | music | all | S | 2 | better | net | **Titles from more stations** — now-playing feeds beyond RMF, 357 and Nowy Świat (Polskie Radio first) | "Co to za piosenka" still fails on the stations that don't send it |
| 71 | · | music | all | M | 2 | new | net | **Podcasts** — a few RSS feeds, "Włącz podcast o…", resumes the episode | The player and the station page exist; only the feed is missing |
| 72 | · | music | all | M | 2 | new | sudo | **She plays your phone** — the Pi as a Bluetooth input, the phone's music on her speaker, her face dancing to it | Uses visualizer.py for any music |
| 73 | · | music | all | S | 1 | better | - | **A station on a schedule** — "Codziennie o 7 włącz Trójkę" without being an alarm | Wake-up radio exists, a routine doesn't |
| 74 | · | music | all | M | 1 | new | net | **Song recognition** — a fingerprint service for stations without titles | Costs money per call; idea 70 covers most of the need |
| 75 | · | music | maja | S | 1 | new | - | **Guess the instrument** — recorded sounds with a licence that allows it, a photo after each | Music education, but needs sound files |
| 76 | · | music | grown | S | 1 | new | - | **Metronome** — "Metronom 90", ticks and a beating screen, voice for faster and slower | Trivial, and useful for anyone practising |
| 77 | · | home | all | S | 3 | better | - | **Recipe into the shopping list** — cooking.py: "Dopisz składniki" adds what you need, without what's already on the list | Cooking and lists don't talk to each other at all |
| 78 | · | home | grown | M | 3 | new | model | **Week's menu → shopping list** — "Zaplanuj obiady": menu on the plan page, one voice yes puts it on the list | Deciding what to eat is the daily family question |
| 79 | · | home | grown | M | 3 | better | model | **Rubbish calendar** — a photo of the harmonogram (like "plan z kartki"), "Jutro wystawić plastik" in the evening hello | Every Polish house misses a collection; the OCR path exists |
| 80 | · | home | grown | S | 3 | new | - | **The list on your phone by QR** — the list on screen as a plain-text QR, no server involved | The list is at home when you're in the shop; no web panel needed |
| 81 | · | home | grown | M | 3 | new | net | **Family calendar** — a read-only iCal link per person, shown in the plan and the morning hello | Everything on phones is unknown to her, and it's the family's real diary |
| 82 | · | home | all | S | 3 | better | - | **Alarms that know holidays** — a workday alarm stays quiet on 11 November and through school breaks, and says so the night before | timers.py doesn't know days off, while kids.school_day does; 11 November is next week |
| 83 | · | home | grown | S | 2 | better | - | **Recipes for six** — cooking.py scales for "na 6 osób" and says the new amounts | Recipes are fixed at 2–4 people |
| 84 | · | home | grown | S | 2 | new | model | **What can I make from this** — fridge held to the camera, or items said out loud, gives three ideas | Evening rescue; uses the camera path |
| 85 | · | home | grown | M | 2 | better | model | **A family cookbook** — "Zapisz ten przepis" or a photo of grandma's card; a named recipe comes back any time | Cooking now invents a recipe each time |
| 86 | · | home | grown | S | 2 | better | - | **Shopping list in shop order** — lists.py groups by department on screen and when read out | Saves walking back; a hand-written table of stems |
| 87 | · | home | grown | S | 2 | new | model | **"Dopisz to"** — show an empty package to the camera, she reads it and adds it to the list | The fastest way to add when your hands hold the thing |
| 88 | · | home | grown | S | 2 | new | - | **Deadlines book** — car inspection, insurance, passports: warned 30 and 7 days before, a list on request | Annual dates are what a reminder gets wrong; they need lead time |
| 89 | · | home | all | S | 2 | better | - | **Packing list templates** — "Pakujemy się na narty": a list from a template, each person's part, ticked by touch | lists.py is fine; only the start is missing |
| 90 | · | home | grown | S | 2 | better | - | **Medicine reminder that insists** — timers.py repeats until "wzięłam"; the day's doses listed on request | A reminder that rings once is easily missed |
| 91 | · | home | grown | L | 2 | new | hw,sudo | **Lights and plugs through Home Assistant** — "Zgaś światło" in a room, the lamp scene matching a real bulb | The obvious step for a home robot, and big enough to need its own plan |
| 92 | · | home | grown | M | 2 | better | sudo | **Who's home from phones on Wi-Fi** — opt-in per person, helps "Czy Emilka już wróciła?" when she hasn't seen them | She answers only from what the camera saw |
| 93 | · | home | grown | S | 1 | new | - | **Wi-Fi for guests** — a QR on screen for the guest network; never said aloud or kept in the model's context | One small nice moment with visitors |
| 94 | · | home | grown | M | 1 | new | model | **Receipt check** — a receipt shown to the camera, what was bought is crossed off the list | Fun, though a tap on the list is often quicker |
| 95 | · | home | grown | M | 1 | new | hw,sudo | **Remote for the TV** — an IR diode: "Wyłącz telewizor", Radio ↔ TV | Cheap hardware, fiddly setup |
| 96 | · | family | all | M | 3 | new | net | **Messages from your phone** — a private Telegram bot: text or voice to Luna, she tells them at home; the child can answer | The biggest gap in messages.py: everyone has to be at home today |
| 97 | · | family | all | S | 3 | better | - | **A drawing as a message** — "Zostaw ten rysunek dla mamy": shown when she sees mum | A child's message is often a picture; messages.py + paint.py |
| 98 | · | family | maja | S | 3 | better | - | **Bedtime story in a parent's voice** — recorded in advance, one chapter a night, played when a parent is away | Nothing a TTS voice can do replaces this one |
| 99 | · | family | all | S | 2 | new | - | **The quote book** — "Zapisz, co powiedziała Maja": what children say, dated, read back on request | These get forgotten within a week |
| 100 | · | family | maja | S | 2 | new | - | **Milestones and height** — "Maja ma 132 cm", first lost tooth: a dated list and a growth chart | The family's album, kept by the family robot |
| 101 | · | family | all | S | 2 | better | - | **On this day** — "Co robiliśmy miesiąc temu?": a photo and a memory from that date | Memory and gallery both have dates; she started in September, so months first, then years |
| 102 | · | family | all | S | 2 | new | - | **Time capsule** — a voice message to be opened on a date: "Otwórz za rok" | Very cheap on the messages.py engine, and a lovely surprise a year later |
| 103 | · | family | all | M | 2 | new | - | **Interview a grandparent** — she asks about childhood, the recordings are kept as a family archive | Genuinely valuable, for only a list of questions |
| 104 | · | family | all | M | 2 | better | - | **Group photo that waits** — "Zróbmy zdjęcie rodzinne": waits until all faces are in frame and smiling, retakes for closed eyes | "Zrób nam zdjęcie" just counts down, and someone always blinks |
| 105 | · | family | all | M | 2 | new | - | **Family vote** — "Zapytaj wszystkich, co na obiad": she asks each person when she sees them and reports | A use for errands.py that no phone gives you |
| 106 | · | family | grown | S | 2 | new | net | **Photos and drawings to your phone** — "Wyślij to tacie" through the bot in idea 96 | Pictures are trapped on the Pi; follows from idea 96 |
| 107 | · | family | all | M | 1 | new | - | **A printed year book** — at year's end: photos, quotes and stars laid out on A4 | A real object from a year of data, once there's a year of data |
| 108 | · | her | all | M | 3 | better | - | **Correct her hearing** — "Nie basen, tylko Basia": the pair goes into the transcriber's hint for that person | Misheard words keep repeating, and only a person can tell her which |
| 109 | · | her | all | S | 2 | new | - | **What to call me** — "Mów do mnie Majka": a nickname per person, in hellos and replies | Asked for naturally, and only "Mów do mnie po angielsku" exists |
| 110 | · | her | all | M | 2 | new | - | **Voice shortcuts** — "Kiedy powiem film, zgaś lampkę i wycisz radio": a phrase runs a few commands | The family can add features without waiting for Claude; #432 does two at once already |
| 111 | · | her | all | S | 2 | new | - | **A topic for dinner** — "Daj temat do rozmowy": a question for everyone, from a checked list | Screens away, and she's the reason why |
| 112 | · | her | maja | S | 2 | new | - | **Feelings wheel** — in the evening routine, on request: tap a colour or a face for how the day was | A child who can't say it can point at it; stays with the child |
| 113 | · | her | maja | M | 2 | new | - | **A private diary** — "Mój pamiętnik": dictated, read back only to that face, and she says it's private | Trust and writing practice; must never leak into chat or memory |
| 114 | · | her | all | S | 1 | better | - | **"Dlaczego to zrobiłaś?"** — she says what she heard and which rule or action fired | Helps the family and the logs; makes her less magical, more honest |
| 115 | · | her | all | S | 1 | better | - | **How long we've known each other** — first-met dates per person, "Znamy się już rok" on that day | Warm, nearly free; relationship.py + memory.py |
| 116 | · | her | all | S | 1 | better | - | **Shared jokes** — a running joke from a good moment is remembered and comes back months later | Friends have those; easy to overdo, so rare |
| 117 | · | face | maja | S | 3 | better | - | **A timer you can see from far** — a big shrinking disc, full-screen on request | At 8, "5 minutes" means nothing, and today's number is in a small corner |
| 118 | · | face | maja | S | 2 | better | - | **Routine in pictures** — kids.py's steps as icons with ticks, ticked by touch | Reading less, doing more; the steps exist in voice only |
| 119 | · | face | all | S | 2 | better | - | **Her character follows the person** — opt-in: Maja's Mochi when Maja is alone with her, Luna otherwise | themes.py is global today, so the family keeps switching |
| 120 | · | face | grown | S | 2 | better | - | **A sign on her screen during a meeting** — "Tata ma spotkanie", when "bądź cicho do 15" is on | The rest of the house sees why it's quiet, for one line of UI |
| 121 | · | face | all | S | 1 | better | - | **Pin a countdown** — "Do wakacji 42 dni" in the status bar until the date comes | statusbar.py has room, and the counting is there |
| 122 | · | face | all | S | 1 | better | - | **Larger text for guests** — a setting doubling the size in cards and lists | Grandparents; settings_page.py has the place |
| 123 | · | face | all | S | 1 | better | - | **Clock faces to choose from** — large digits, an analogue dial, the one from clockgame.py | "Pokaż zegar" has a single design |
| 124 | · | voice | all | L | 3 | new | sudo | **Who's speaking, by voice** — a small local speaker model on sherpa-onnx, for when no face is in view | Names and child rules rest on the camera alone (#768), and she often can't see |
| 125 | · | voice | all | S | 2 | better | - | **Her volume follows the room** — louder over a noisy kitchen, lower in a quiet room, from the mic level | One fixed volume can't suit both a noisy kitchen and a quiet evening |
| 126 | · | voice | all | S | 2 | better | - | **Teach her to pronounce** — "Mówi się Szymborska z akcentem…": a respelling per word in polish.py | When she says a name wrong, nobody in the family can fix it without a code change |
| 127 | · | voice | all | S | 2 | better | - | **Speaker battery** — the Bluetooth speaker's level in the status bar, a word when it's low | She goes silent with no warning when it dies |
| 128 | · | voice | all | M | 2 | better | sudo | **A local voice for bad days** — Piper as a fallback when OpenAI's voice fails; the same words, a plainer sound | #190 covers fixed lines only; a real answer would still get through |
| 129 | · | voice | dev | L | 2 | better | model | **Try the Realtime API** — one measured evening: latency, Polish quality, cost per conversation | The biggest possible latency win; it needs numbers, not opinions |
| 130 | · | voice | all | S | 1 | better | - | **Volume by distance** — face size from the camera nudges the volume: close = quieter | Cheap once idea 125 exists |
| 131 | · | voice | all | S | 1 | better | - | **More languages for her** — "Mów do mnie po niemiecku", same as the English switch, for guests or practice | #504 is English only, though translation covers many |
| 132 | · | voice | all | M | 1 | new | - | **Clap to call her** — two claps count like her name, with the radio on as well | Fun, and it works when no word can get through the music |
| 133 | · | voice | grown | L | 1 | new | sudo | **Sounds of the house** — a smoke alarm or doorbell recognised, and she says so | A small sound classifier on the Pi; its false alarms are the risk |
| 134 | · | info | all | S | 3 | better | net | **Smog and air quality** — open-meteo or GIOŚ: "Czy można dziś biegać?", a line in the morning hello when it's bad | A real winter question in Poland, and weather.py has the shape |
| 135 | · | info | all | S | 2 | better | net | **Weather warnings** — IMGW storms and frost, on the hello and in the status bar | Forecasts don't say "dangerous" |
| 136 | · | info | all | M | 2 | better | net | **Rain radar** — "Pokaż radar": the map on screen, moving | "Will it hit us in 20 minutes?" is what a picture answers best |
| 137 | · | info | grown | S | 2 | new | net | **Exchange rates from NBP** — a free official API, local answer, also "ile to w euro?" in calc.py | #293 stopped invented rates, but it still goes through web search |
| 138 | · | info | all | S | 2 | new | model | **Ideas for the weekend** — "Co porobić w sobotę?": forecast + ages + a search for what's on nearby | Combines what she already knows, and it's a question families really ask |
| 139 | · | info | all | M | 1 | better | net | **What's in the sky tonight** — planets to see and space-station passes, next to moon.py | "Luna" and the Moon: fits her name, and it's a good moment with a child |
| 140 | · | info | grown | S | 1 | better | net | **Pollen** — from open-meteo's air-quality data, in season, for those who ask | Small, and useful to a few |
| 141 | · | info | grown | M | 1 | new | net | **Next tram or bus** — from the city's timetable data: "Kiedy mam autobus?" | Handy only if the stop is really used |
| 142 | · | info | grown | S | 1 | new | net | **My team's score** — "Jak zagrała…": results for a team you name | News covers sport headlines, not your team |
| 143 | · | health | maja | S | 2 | new | - | **A movement break** — "Zróbmy gimnastykę": three minutes of moves with pictures and counting | A good pair for homework and for rainy days |
| 144 | · | health | grown | S | 2 | better | - | **Interval timer** — "Trening 30 na 10, osiem razy": counted aloud, a big timer | Focus mode's little sibling, timers can't chain now |
| 145 | · | health | grown | S | 2 | better | - | **Desk break, opt-in** — "Przypominaj mi o przerwach": from the seated-at-desk state (#609), never unasked | Better than an hourly reminder because it knows you're really sitting |
| 146 | · | health | grown | S | 2 | new | - | **Fever and medicine log** — "Maja dostała syrop o 14": says only when and how long ago, never a dose or advice | The 3 a.m. question; it records and never advises |
| 147 | · | privacy | all | S | 2 | better | - | **A sign when the picture leaves** — a small icon each time a camera frame goes to the cloud | "Wyłącz kamerę" exists, but nobody can see when a frame is sent |
| 148 | · | privacy | grown | S | 2 | new | - | **Today's cloud page** — how many frames and voice clips left today, and what for | Parents can answer "what does she send?" with numbers |
| 149 | · | privacy | grown | S | 2 | new | - | **Game time for a child** — opt-in: after N minutes a day she suggests something else, a parent sets it | Screen rules that don't need a parent to step in |
| 150 | · | privacy | grown | S | 1 | better | - | **Grown-ups' settings** — the reset and privacy settings only after a grown-up face (#189 covers erasing by voice only) | The settings page can be tapped by anyone |
| 151 | · | privacy | grown | S | 1 | new | - | **Guest photos fade** — opt-in: guests' photos and face samples go to the bin after N days, never deleted for good | Guests didn't sign up for an archive |
| 152 | · | robust | dev | S | 3 | better | - | **Backup off the Pi** — backup.py's copy goes to the PC or a USB stick too, photos and recordings included | It lives on the same SD card that can die, and it skips recordings |
| 153 | · | robust | grown | S | 3 | new | net | **A message when she's down** — a heartbeat to ntfy or healthchecks, a phone alert after 10 silent minutes | You find out she was dead only when someone speaks to her |
| 154 | · | robust | dev | M | 2 | better | - | **Automatic rollback** — three failed starts after a deploy bring the previous version back, and the screen says so | A bad deploy at night leaves the family with no Luna |
| 155 | · | robust | dev | S | 2 | better | - | **A quiet check before morning** — before the first alarm: mic, camera, speaker link and cloud checked, with no sound, the result in status | The alarm is what must not fail, and nobody tests it before it rings |
| 156 | · | robust | dev | L | 1 | new | sudo | **Read-only system on the SD card** — an overlay filesystem, only data/ writable | Power cuts hold no fear, but updates get harder |
| 157 | · | robust | grown | M | 1 | new | net | **A second brain for outages** — another provider for chat when OpenAI is down, a smaller reply | Rare outages, but she goes mute when they hit |
| 158 | · | cost | grown | S | 2 | better | - | **Money in złoty** — weekly.py converts calls into an estimated cost per feature | #173 counts calls, and a family decides in złoty |
| 159 | · | cost | grown | M | 2 | better | - | **A daily limit that bends** — above a set amount, shorter answers and no drawings, and she says why | #854 handles an empty account, not a slow leak |
| 160 | · | cost | dev | M | 2 | better | - | **Prompt on a diet** — brain.py's prompt measured per section against the logs, unused parts dropped | Every call pays for it, and the prompt only grows |
| 161 | · | cost | dev | S | 2 | better | - | **Her lines recorded in advance** — fixed lines rendered overnight, not at first use (#181) | First use is the slow one, and nobody's waiting at night |
| 162 | · | cost | all | S | 1 | better | - | **Same question, same answer** — factual answers cached for a day or more | Children ask again; it saves little money but a lot of waiting |
| 163 | · | dev | dev | S | 3 | new | - | **What actually gets used** — a report per feature over 30 days from luna.log | With 860+ features, it says what to polish and what to retire |
| 164 | · | dev | grown | S | 3 | new | - | **Claude on her screen** — a Claude Code hook on the PC drops a file on the Pi: a silent icon for "finished" or "needs you" | The robot on your desk is the perfect signal, and it's cheap and silent |
| 165 | · | dev | dev | S | 2 | better | - | **Phrase miner** — from the logs: sentences that went to the model but ended in a local action, as routing-test candidates | Automates what the log rounds do by hand, at a lower cost |
| 166 | · | dev | dev | M | 2 | better | - | **Replay a real day** — a day's heard sentences through a new build's routing, with no model, and the differences shown | Catches a change in behaviour before the family does |
| 167 | · | dev | dev | M | 2 | new | - | **Luna on the PC** — type, and see the routing and answer in a window, with no Pi, mic or speaker | Faster iteration on commands and pages; no audio at night |
| 168 | · | dev | dev | M | 2 | new | - | **Screenshots that compare** — each page rendered and compared to a saved picture, the changes shown | #228 was a one-off pass, and pages drift without anyone noticing |
| 169 | · | dev | dev | L | 1 | better | - | **Split the giants** — robot_face.py 4070 lines, brain.py 3240: pieces with one job each | Each read costs tokens; a risk with little visible gain |
| 170 | · | hw | maja | M | 3 | new | hw | **Cards you tap** — an NFC reader, a card or figure starts a story, a station or a game | A child with no words needs nothing else, and the cards are a toy too |
| 171 | · | hw | dev | M | 2 | new | hw,sudo | **SSD instead of SD** — a USB SSD boot disk for speed and for a long life | Cheap insurance against the most likely failure |
| 172 | · | hw | all | L | 2 | new | hw,sudo | **A neck** — two servos so she really turns to whoever speaks; eyes already follow | Biggest possible jump in presence, and body.py and #274 are ready for it |
| 173 | · | hw | maja | M | 2 | new | hw,sudo | **Sticker printer** — a small thermal printer: a star, a riddle, a drawing as a sticker | Stars you can stick on the fridge |
| 174 | · | hw | all | M | 2 | new | hw,sudo | **Room sensor** — temperature, humidity, CO₂: "Otwórz okno", "Ile jest w pokoju stopni?" | She knows the weather outside but nothing about her own room |
| 175 | · | hw | all | M | 2 | new | hw,sudo | **A battery** — a UPS board: moves around the house, a clean shutdown in a power cut | She could spend a morning in the kitchen and survive power cuts |
| 176 | · | hw | maja | S | 1 | new | hw | **A big button** — one physical button for "Luna, słucham" | For hands that are full, or for someone small |
| 177 | · | hw | all | L | 1 | new | hw | **A second ear in the kitchen** — an ESP32 mic and speaker talking to the same Luna | camera_thread already talks ESP32; the audio path is the real work |
