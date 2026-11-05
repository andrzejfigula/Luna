"""The calendar (agenda.py): dates, repeats, reminders, voice, the page's taps."""

import os
import sys
import tempfile
import time
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("LUNA_DATA_DIR", tempfile.mkdtemp(prefix="luna-tests-"))  # never real data

import agenda
import schedule
from shared_state import state

TMP = tempfile.mkdtemp(prefix="luna-tests-")
THU = date(2026, 11, 5)


def at(y, mo, d, h=12, mi=0):
    return time.mktime((y, mo, d, h, mi, 0, 0, 0, -1))


NOW = at(2026, 11, 5, 12)                       # a Thursday, noon


class Base(unittest.TestCase):
    def setUp(self):
        import faces
        self.paths = agenda.PATH, schedule.PATH     # back in tearDown: other tests share this process
        agenda.PATH = os.path.join(TMP, "calendar.json")
        schedule.PATH = os.path.join(TMP, "schedule-agenda.json")
        for f in (agenda.PATH, schedule.PATH):
            if os.path.exists(f):
                os.remove(f)
        agenda._mem.update(mtime=None, data=None)
        schedule._mem.update(mtime=None, data=None)
        agenda._expect.update(until=0.0, draft=None, day=None, tries=0)
        agenda._last.update(ids=[], t=0.0)
        agenda._pending.update(what=None, ids=[], until=0.0, to=None)
        agenda._forget_marks()
        self.now = NOW
        self.said = []
        fam = ["Andrzej", "Emilka", "Maja"]
        self.p = [mock.patch.object(agenda, "_now", lambda: self.now),
                  mock.patch.object(faces, "names", lambda: fam),
                  mock.patch.object(faces, "family", lambda: fam),
                  mock.patch.object(faces, "guest_here", lambda: False),
                  mock.patch.object(faces, "is_family", lambda n, people=None: n in fam),
                  mock.patch.object(faces, "notes", lambda: {"Andrzej": "tata Mai"}),
                  mock.patch.object(faces, "vocatives", lambda: {"Maja": "Maju", "Andrzej": "Andrzeju"})]
        for p in self.p:
            p.start()
        self.face_was = state.face_detected         # (another test may have left a face in view)
        with state.lock:
            state.overlay = None
            state.person = None
            state.face_detected = False

    def tearDown(self):
        for p in self.p:
            p.stop()
        agenda.PATH, schedule.PATH = self.paths
        agenda._mem.update(mtime=None, data=None)
        schedule._mem.update(mtime=None, data=None)
        agenda._forget_marks()
        with state.lock:
            state.overlay = None
            state.person = None
            state.face_detected = self.face_was

    def say(self, sentence):
        return agenda.handle(sentence, self.said.append)

    def only(self):
        evs = agenda.events()
        self.assertEqual(len(evs), 1, evs)
        return evs[0]


class DatesTest(unittest.TestCase):
    def day(self, s):
        got = agenda.parse_date(s, THU)
        return got[0] if got else None

    def test_words(self):
        for s, want in (("dziś", THU), ("jutro", date(2026, 11, 6)), ("pojutrze", date(2026, 11, 7)),
                        ("za 3 dni", date(2026, 11, 8)), ("za tydzień", date(2026, 11, 12)),
                        ("za dwa tygodnie", date(2026, 11, 19)), ("za miesiąc", date(2026, 12, 5)),
                        ("za rok", date(2027, 11, 5))):
            self.assertEqual(self.day(s), want, s)

    def test_weekdays(self):
        for s, want in (("w sobotę", date(2026, 11, 7)), ("we wtorek", date(2026, 11, 10)),
                        ("w czwartek", date(2026, 11, 12)),      # today's name: next week's
                        ("w przyszły piątek", date(2026, 11, 13)),
                        ("w przyszłą środę", date(2026, 11, 11)),
                        ("w środę w przyszłym tygodniu", date(2026, 11, 11)),
                        ("w sobotę za tydzień", date(2026, 11, 14))):
            self.assertEqual(self.day(s), want, s)

    def test_calendar_dates(self):
        for s, want in (("12 listopada", date(2026, 11, 12)), ("3 stycznia", date(2027, 1, 3)),
                        ("dwunastego listopada", date(2026, 11, 12)),
                        ("dwudziestego trzeciego grudnia", date(2026, 12, 23)),
                        ("12.11", date(2026, 11, 12)), ("12.11.2027", date(2027, 11, 12)),
                        ("na dwunastego", date(2026, 11, 12)), ("trzeciego", date(2026, 12, 3)),
                        ("1 maja 2027", date(2027, 5, 1))):
            self.assertEqual(self.day(s), want, s)

    def test_a_time_is_no_date(self):
        self.assertIsNone(self.day("o 10.30"))
        self.assertIsNone(self.day("dentysta o 15"))

    def test_feasts(self):
        self.assertEqual(self.day("w wigilię"), date(2026, 12, 24))
        self.assertEqual(self.day("na wielkanoc"), date(2027, 3, 28))

    def test_ranges(self):
        for s, a, b in (("od 20 grudnia do 3 stycznia", date(2026, 12, 20), date(2027, 1, 3)),
                        ("od 12 do 15 listopada", date(2026, 11, 12), date(2026, 11, 15)),
                        ("od poniedziałku do środy", date(2026, 11, 9), date(2026, 11, 11)),
                        ("w weekend", date(2026, 11, 7), date(2026, 11, 8))):
            got = agenda.parse_date(s, THU)
            self.assertEqual(got[:2], (a, b), s)

    def test_question_ranges(self):
        self.assertEqual(agenda.parse_range("co w tym tygodniu", THU)[:2], (THU, date(2026, 11, 8)))
        self.assertEqual(agenda.parse_range("w przyszłym tygodniu", THU)[:2],
                         (date(2026, 11, 9), date(2026, 11, 15)))
        self.assertEqual(agenda.parse_range("w grudniu", THU)[:2], (date(2026, 12, 1), date(2026, 12, 31)))
        self.assertEqual(agenda.parse_range("na luty", THU)[:2], (date(2027, 2, 1), date(2027, 2, 28)))


class ParseTest(Base):
    def test_parts(self):
        p = agenda.parse("dentysta 12 listopada o 15", None, now=NOW)
        self.assertEqual((p["title"], p["date"], p["at"]), ("dentysta", date(2026, 11, 12), "15:00"))
        p = agenda.parse("Maja ma wycieczkę szkolną w przyszły piątek", None, now=NOW)
        self.assertEqual((p["who"], p["title"]), ("Maja", "wycieczka szkolna"))
        self.assertIsNone(p["at"])
        p = agenda.parse("spotkanie u dr Nowak jutro od 10 do 11", None, now=NOW)
        self.assertEqual((p["at"], p["end"]), ("10:00", "11:00"))
        self.assertIn("Nowak", p["title"])

    def test_speaker_and_house(self):
        p = agenda.parse("mam fryzjera w sobotę o 10", "Emilka", now=NOW)
        self.assertEqual(p["who"], "Emilka")
        p = agenda.parse("mamy gości w sobotę", "Emilka", now=NOW)
        self.assertEqual(p["who"], "")

    def test_the_model_gets_the_day_asked_about(self):
        agenda.add("narty", date(2027, 2, 10), who="Maja", now=NOW)
        line = agenda.prompt_line(now=NOW, text="Co Maja ma 10 lutego?")
        self.assertIn("days just asked about: Maja: narty", line)
        self.assertIn("nothing", agenda.prompt_line(now=NOW, text="Co mamy 11 lutego?"))
        self.assertNotIn("asked about", agenda.prompt_line(now=NOW, text="Opowiedz o meduzach"))

    def test_meeting_someone_is_not_theirs(self):
        p = agenda.parse("spotkanie z Andrzejem jutro", "Emilka", now=NOW)
        self.assertEqual(p["who"], "Emilka")
        self.assertIn("Andrzej", p["title"])

    def test_past_hour_today_is_afternoon(self):
        p = agenda.parse("kolacja dziś o ósmej", None, now=at(2026, 11, 5, 15))
        self.assertEqual(p["at"], "20:00")

    def test_reminders(self):
        self.assertEqual(agenda.remind_of("dentysta przypomnij dzień wcześniej")[0], [agenda.DAY])
        self.assertEqual(agenda.remind_of("przypomnij tydzień i godzinę wcześniej")[0],
                         [agenda.WEEK, agenda.HOUR])
        self.assertEqual(agenda.remind_of("przypomnij 15 minut przed")[0], [15])
        self.assertEqual(agenda.remind_of("przypomnij pół godziny przed")[0], [30])
        self.assertEqual(agenda.remind_of("przypomnij dwa dni wcześniej")[0], [2 * agenda.DAY])
        self.assertEqual(agenda.remind_of("bez przypomnienia")[0], [])
        self.assertIsNone(agenda.remind_of("dentysta w środę")[0])

    def test_repeats(self):
        self.assertEqual(agenda.repeat_of("wywóz co dwa tygodnie")[0], "2weeks")
        self.assertEqual(agenda.repeat_of("rocznica co roku")[0], "year")
        kind, rest = agenda.repeat_of("trening co piątek")
        self.assertEqual(kind, "week")
        self.assertIn("w piątek", rest)


class OccurrencesTest(Base):
    def ev(self, day, **kw):
        return agenda.add("x", day, now=NOW, **kw)

    def test_once_and_span(self):
        e = self.ev(date(2026, 11, 12), end_date=date(2026, 11, 14))
        self.assertEqual(agenda.occurrences(e, date(2026, 11, 13), date(2026, 11, 13)), [date(2026, 11, 12)])
        self.assertEqual(agenda.occurrences(e, date(2026, 11, 15), date(2026, 11, 20)), [])

    def test_weekly_with_a_skip(self):
        e = self.ev(date(2026, 11, 2), repeat="week")
        e["skip"] = ["2026-11-09"]
        self.assertEqual(agenda.occurrences(e, date(2026, 11, 3), date(2026, 11, 17)), [date(2026, 11, 16)])

    def test_two_weeks(self):
        e = self.ev(date(2026, 11, 2), repeat="2weeks")
        self.assertEqual(agenda.occurrences(e, date(2026, 11, 3), date(2026, 11, 30)),
                         [date(2026, 11, 16), date(2026, 11, 30)])

    def test_month_end_clamps(self):
        e = self.ev(date(2026, 1, 31), repeat="month")
        self.assertEqual(agenda.occurrences(e, date(2027, 2, 1), date(2027, 2, 28)), [date(2027, 2, 28)])

    def test_leap_day_each_year(self):
        e = self.ev(date(2024, 2, 29), repeat="year")
        self.assertEqual(agenda.occurrences(e, date(2027, 1, 1), date(2027, 12, 31)), [date(2027, 2, 28)])


class RemindersTest(Base):
    def tick(self, now, person=None, someone=True, can=True, busy=False):
        self.now = now
        return agenda.tick(now, person, someone, can, busy, self.said.append)

    def test_evening_before_then_an_hour_before(self):
        agenda.add("dentysta", date(2026, 11, 12), "15:00", now=NOW)
        self.assertEqual(self.tick(at(2026, 11, 11, 17, 59)), 0)
        self.assertEqual(self.tick(at(2026, 11, 11, 18, 0)), 1)
        self.assertIn("jutro", self.said[-1])
        self.assertEqual(self.tick(at(2026, 11, 11, 18, 1)), 0)      # once
        self.assertEqual(self.tick(at(2026, 11, 12, 14, 0)), 1)
        self.assertIn("dziś o piętnastej", self.said[-1])

    def test_set_too_late_rings_at_the_start(self):
        agenda.add("dentysta", date(2026, 11, 5), "12:30", now=NOW)
        self.assertEqual(self.tick(at(2026, 11, 5, 12, 29)), 0)
        self.assertEqual(self.tick(at(2026, 11, 5, 12, 30)), 1)

    def test_only_the_newest_due_is_said(self):
        agenda.add("dentysta", date(2026, 11, 12), "15:00", remind=[agenda.DAY, agenda.HOUR], now=NOW)
        self.assertEqual(self.tick(at(2026, 11, 12, 14, 5)), 1)      # she was off all evening
        self.assertEqual(len(self.said), 1)
        self.assertEqual(self.tick(at(2026, 11, 12, 14, 6)), 0)

    def test_expired_is_dropped(self):
        agenda.add("dentysta", date(2026, 11, 12), "15:00", now=NOW)
        self.assertEqual(self.tick(at(2026, 11, 12, 15, 11)), 0)

    def test_for_a_person_waits_to_see_them(self):
        agenda.add("trening", date(2026, 11, 12), "15:00", who="Maja", remind=[agenda.HOUR], now=NOW)
        self.assertEqual(self.tick(at(2026, 11, 12, 14, 1), person="Andrzej"), 0)
        self.assertEqual(self.tick(at(2026, 11, 12, 14, 2), person="Maja"), 1)
        self.assertTrue(self.said[-1].startswith("Maju"))

    def test_for_a_person_after_the_hold_to_whoever_is_there(self):
        agenda.add("trening", date(2026, 11, 12), "15:00", who="Maja", remind=[agenda.HOUR], now=NOW)
        self.assertEqual(self.tick(at(2026, 11, 12, 14, 16), person="Andrzej"), 1)
        self.assertIn("Maja", self.said[-1])

    def test_not_at_night_nor_in_front_of_a_guest(self):
        import faces
        agenda.add("pociąg", date(2026, 11, 12), "06:00", remind=[agenda.HOUR], now=NOW)
        self.assertEqual(self.tick(at(2026, 11, 12, 5, 0)), 0)
        agenda.add("kolacja", date(2026, 11, 12), "20:00", remind=[agenda.HOUR], now=NOW)
        with mock.patch.object(faces, "guest_here", lambda: True):
            self.assertEqual(self.tick(at(2026, 11, 12, 19, 0)), 0)
        self.assertEqual(self.tick(at(2026, 11, 12, 19, 1)), 1)

    def test_always_rings_at_night(self):
        agenda.add("pociąg", date(2026, 11, 12), "06:00", remind=[agenda.HOUR], always=True, now=NOW)
        self.assertEqual(self.tick(at(2026, 11, 12, 5, 0)), 1)

    def test_not_over_her_speech(self):
        agenda.add("kolacja", date(2026, 11, 12), "20:00", remind=[agenda.HOUR], now=NOW)
        self.assertEqual(self.tick(at(2026, 11, 12, 19, 0), busy=True), 0)
        self.assertEqual(self.tick(at(2026, 11, 12, 19, 1)), 1)

    def test_all_day_is_said_that_morning(self):
        agenda.add("wycieczka", date(2026, 11, 12), now=NOW)
        self.assertEqual(self.tick(at(2026, 11, 11, 18, 0)), 1)
        self.assertEqual(self.tick(at(2026, 11, 12, 8, 0)), 1)
        self.assertIn("dziś", self.said[-1])

    def test_repeating_rings_each_time(self):
        agenda.add("wywóz", date(2026, 11, 9), repeat="week", remind=[0], now=NOW)
        self.assertEqual(self.tick(at(2026, 11, 9, 8, 0)), 1)
        self.assertEqual(self.tick(at(2026, 11, 16, 8, 0)), 1)

    def test_phrases(self):
        e = agenda.add("dentysta", date(2026, 11, 12), "15:00", who="Maja", now=NOW)
        self.assertEqual(agenda.phrase(e, date(2026, 11, 12), "Maja", at(2026, 11, 11, 18)),
                         "Maju, jutro o piętnastej masz dentystę.")
        self.assertTrue(agenda.phrase(e, date(2026, 11, 12), None, at(2026, 11, 11, 18))
                        .startswith("Przypominam: Maja jutro o piętnastej ma"))
        e2 = agenda.add("do babci", date(2026, 11, 12), now=NOW)
        self.assertIn("— do babci", agenda.phrase(e2, date(2026, 11, 12), None, at(2026, 11, 12, 8)))


class VoiceTest(Base):
    def test_add_with_everything(self):
        self.assertTrue(self.say("Dodaj do kalendarza dentysta 12 listopada o 15"))
        e = self.only()
        self.assertEqual((e["title"], e["date"], e["at"]), ("dentysta", "2026-11-12", "15:00"))
        self.assertEqual(e["remind"], [agenda.DAY, agenda.HOUR])
        self.assertIn("Zapisałam", self.said[-1])
        self.assertEqual(state.overlay[0], "agenda")

    def test_add_said_last(self):
        self.assertTrue(self.say("Maja ma wycieczkę w przyszły piątek, zapisz to w kalendarzu"))
        e = self.only()
        self.assertEqual((e["who"], e["title"], e["date"]), ("Maja", "wycieczka", "2026-11-13"))

    def test_asks_for_the_day(self):
        self.assertTrue(self.say("wpisz do kalendarza dentysta"))
        self.assertEqual(self.said[-1], "Na kiedy?")
        self.assertEqual(agenda.events(), [])
        self.assertTrue(self.say("w środę o 15"))
        e = self.only()
        self.assertEqual((e["title"], e["date"], e["at"]), ("dentysta", "2026-11-11", "15:00"))

    def test_asks_what(self):
        self.assertTrue(self.say("dodaj do kalendarza"))
        self.assertTrue(self.say("urodziny babci 3 grudnia"))
        self.assertEqual(self.only()["date"], "2026-12-03")

    def test_the_question_can_be_cancelled(self):
        self.say("wpisz do kalendarza dentysta")
        self.assertTrue(self.say("nieważne"))
        self.assertEqual(agenda.events(), [])
        self.assertFalse(agenda.expecting())

    def test_a_request_for_something_else_goes_on(self):
        self.say("wpisz do kalendarza dentysta")
        self.assertFalse(self.say("włącz radio"))
        self.assertFalse(agenda.expecting())

    def test_twice_not_understood_gives_up(self):
        self.say("wpisz do kalendarza dentysta")
        self.assertTrue(self.say("bla bla"))
        self.assertFalse(self.say("bla bla"))
        self.assertFalse(agenda.expecting())

    def test_weekly_goes_to_the_plan(self):
        self.assertFalse(self.say("dodaj do kalendarza Maja angielski od poniedziałku do piątku o 17"))

    def test_no_duplicate(self):
        self.say("dodaj do kalendarza dentysta 12 listopada o 15")
        self.say("dodaj do kalendarza dentysta 12 listopada o 15")
        self.assertEqual(len(agenda.events()), 1)
        self.assertIn("już mam", self.said[-1])

    def test_conflict_with_the_week(self):
        schedule.add("Maja", "angielski", [3], "15:00", "16:00")      # Thursdays
        self.say("dodaj do kalendarza Maja dentysta 12 listopada o 15")
        self.assertIn("angielski", self.said[-1])

    def test_follow_up_reminder_time_undo(self):
        self.say("dodaj do kalendarza dentysta 12 listopada")
        self.assertTrue(self.say("o 15"))
        self.assertEqual(self.only()["at"], "15:00")
        self.assertTrue(self.say("przypomnij dzień wcześniej"))
        self.assertEqual(self.only()["remind"], [agenda.DAY])
        self.assertTrue(self.say("nie przypominaj"))
        self.assertEqual(self.only()["remind"], [])
        self.assertTrue(self.say("cofnij"))
        self.assertEqual(agenda.events(), [])

    def test_a_bare_time_later_is_not_ours(self):
        self.say("dodaj do kalendarza dentysta 12 listopada")
        self.now += agenda.LAST_SECS + 1
        self.assertFalse(self.say("o 15"))

    def test_questions(self):
        self.say("dodaj do kalendarza dentysta w sobotę o 15")
        self.said.clear()
        self.assertFalse(self.say("co mamy w sobotę"))      # the model's: it knows her memory too
        self.assertIn("dentysta", agenda.prompt_line(NOW, text="co mamy w sobotę"))
        self.assertTrue(self.say("co mam w kalendarzu w sobotę"))
        self.assertIn("dentysta", self.said[-1])
        self.assertTrue(self.say("czy mamy coś w kalendarzu w sobotę"))
        self.assertTrue(self.say("co w kalendarzu w tym tygodniu"))
        self.assertIn("dentysta", self.said[-1])
        self.assertTrue(self.say("kiedy dentysta"))
        self.assertIn("pojutrze o piętnastej", self.said[-1])
        self.assertTrue(self.say("ile dni do dentysty"))
        self.assertTrue(self.say("co nas czeka"))
        self.assertIn("dentysta", self.said[-1])

    def test_a_stranger_gets_nothing_either(self):
        import faces
        self.say("dodaj do kalendarza dentysta w sobotę o 15")
        self.said.clear()
        with state.lock:
            state.face_detected = True
        with mock.patch.object(faces, "probably_family", lambda: False):
            self.assertTrue(self.say("co macie w kalendarzu"))
            self.assertIn("rodziny", self.said[-1])
            self.assertEqual(agenda.prompt_line(NOW), "")
            self.assertIsNone(agenda.open_from_dock())
            self.assertEqual(state.overlay[0], "card")
            self.assertFalse(agenda.from_note("20 listopada o 18 kino", self.said.append, now=NOW))
        with state.lock:
            state.face_detected = False
        self.assertIsNotNone(agenda.open_from_dock())               # nobody unknown in view

    def test_a_dated_note_is_an_event(self):
        self.assertTrue(agenda.from_note("20 listopada o 18 idziemy do kina", self.said.append, now=NOW))
        self.assertEqual(agenda.events()[0]["at"], "18:00")
        self.assertTrue(self.say("wykreśl to kino, jednak nie idziemy"))
        self.assertEqual(agenda.events(), [])
        for fact in ("klucze są w szufladzie", "Maja ma basen we wtorki",
                     "wczoraj o 18 byłam u lekarza", "20 listopada byliśmy w kinie"):
            self.assertFalse(agenda.from_note(fact, self.said.append, now=NOW), fact)

    def test_my_own_event_without_my_name(self):
        with mock.patch.object(schedule, "_speaker", lambda: "Andrzej"):
            self.say("dodaj do kalendarza dentysta w sobotę o 15")
            self.assertTrue(self.said[-1].startswith("Zapisałam: dentysta"), self.said[-1])
            self.assertEqual(agenda.events()[0]["who"], "Andrzej")
            self.say("kiedy dentysta")
            self.assertTrue(self.said[-1].startswith("Dentysta —"), self.said[-1])

    def test_not_ours(self):
        self.say("dodaj do kalendarza dentysta w sobotę o 15")
        for s in ("co mamy jutro na obiad", "co mamy dzisiaj", "co mam dziś w planie",
                  "kiedy jest wielkanoc", "kiedy przyjedzie babcia", "ile jest dwa razy dwa",
                  "usuń przypomnienie", "usuń pietruszkę", "przesuń przypomnienie na piątą",
                  "kalendarz adwentowy to fajna rzecz", "co masz na sobie w sobotę kochana"):
            self.assertFalse(self.say(s), s)

    def test_show(self):
        self.assertTrue(self.say("pokaż kalendarz"))
        self.assertEqual(state.overlay[0], "agenda")
        self.assertTrue(self.say("otwórz kalendarz na grudzień"))
        self.assertEqual(state.overlay[2]["m"], 12)
        self.assertTrue(self.say("pokaż kalendarz Mai"))
        self.assertEqual(state.overlay[2]["who"], "Maja")

    def test_remove_and_restore(self):
        self.say("dodaj do kalendarza dentysta w sobotę o 15")
        self.assertTrue(self.say("odwołaj dentystę"))
        self.assertEqual(agenda.events(), [])
        self.assertTrue(self.say("przywróć dentystę"))
        self.assertEqual(self.only()["title"], "dentysta")

    def test_remove_which(self):
        agenda.add("dentysta", date(2026, 11, 7), "15:00", now=NOW)
        agenda.add("dentysta", date(2026, 11, 14), "15:00", now=NOW)
        self.assertTrue(self.say("usuń dentystę"))
        self.assertIn("Który", self.said[-1])
        self.assertEqual(len(agenda.events()), 2)
        self.assertTrue(self.say("czternastego listopada"))
        self.assertEqual(self.only()["date"], "2026-11-07")

    def test_remove_only_this_time(self):
        agenda.add("trening", date(2026, 11, 6), "17:00", repeat="week", now=NOW)
        self.assertTrue(self.say("usuń najbliższy trening"))
        e = self.only()
        self.assertEqual(e["skip"], ["2026-11-06"])

    def test_move(self):
        self.say("dodaj do kalendarza dentysta w sobotę o 15")
        self.assertTrue(self.say("przesuń dentystę na czwartek o 16"))
        e = self.only()
        self.assertEqual((e["date"], e["at"]), ("2026-11-12", "16:00"))
        self.assertTrue(self.say("przełóż dentystę na 17"))
        self.assertEqual(self.only()["at"], "17:00")
        self.assertEqual(self.only()["date"], "2026-11-12")

    def test_move_rearms_its_reminders(self):
        agenda.add("dentysta", date(2026, 11, 7), "15:00", now=NOW)
        agenda._mark(agenda.events()[0]["id"], date(2026, 11, 7), [agenda.DAY], NOW)
        self.assertTrue(self.say("przesuń dentystę na 14 listopada"))
        self.assertEqual(self.only()["said"], {})

    def test_named_reminder_and_note(self):
        self.say("dodaj do kalendarza dentysta w sobotę o 15")
        self.now += agenda.LAST_SECS + 1
        self.assertTrue(self.say("przypomnij o dentyście 2 dni wcześniej"))
        self.assertEqual(self.only()["remind"], [2 * agenda.DAY])
        self.assertTrue(self.say("dopisz notatkę do dentysty: weź skierowanie"))
        self.assertEqual(self.only()["note"], "weź skierowanie")

    def test_a_guest_gets_nothing(self):
        import faces
        self.say("dodaj do kalendarza dentysta w sobotę o 15")
        self.said.clear()
        with mock.patch.object(faces, "guest_here", lambda: True):
            self.assertTrue(self.say("pokaż kalendarz"))
            self.assertIn("rodziny", self.said[-1])
            self.assertTrue(self.say("co mamy w kalendarzu w sobotę"))
            self.assertIn("rodziny", self.said[-1])
            self.assertEqual(agenda.prompt_line(NOW, text="co mamy w sobotę"), "")
        self.assertIn("dentysta", agenda.prompt_line(NOW))


class PaperTest(Base):
    def test_rows_filtered(self):
        rows = agenda.from_paper([{"title": "Papier", "date": "2026-11-20"},
                                  {"title": "Stare", "date": "2020-01-01"},
                                  {"title": "Bez daty", "date": "wkrótce"},
                                  {"title": "", "date": "2026-11-21"},
                                  {"title": "Bal", "date": "2026-12-05", "at": "18:00", "note": "strój"}], THU)
        self.assertEqual([r["title"] for r in rows], ["Papier", "Bal"])
        self.assertEqual(rows[1]["at"], "18:00")

    def test_saved_once(self):
        rows = agenda.from_paper([{"title": "Bal", "date": "2026-12-05", "at": "18:00"}], THU)
        self.assertEqual(len(agenda.save_paper(rows, now=NOW)[0]), 1)
        added, kept = agenda.save_paper(rows, now=NOW)
        self.assertEqual((added, kept), ([], 1))

    def test_said_is_ordinary_polish(self):
        rows = agenda.from_paper([{"title": f"Wywóz {k}", "date": f"2026-12-{k:02d}"} for k in range(1, 6)], THU)
        added, _ = agenda.save_paper(rows, now=NOW)
        self.assertIn("5 terminów", agenda.paper_said(added, 0, THU))


class ItemsTest(Base):
    def test_merges_the_week_and_feasts(self):
        schedule.add("Maja", "angielski", [2], "17:00", "18:00")      # Wednesdays
        agenda.add("dentysta", date(2026, 11, 11), "15:00", now=NOW)
        kinds = [(i["kind"], i["title"]) for i in agenda.items_on(date(2026, 11, 11))]
        self.assertIn(("event", "dentysta"), kinds)
        self.assertIn(("plan", "angielski"), kinds)
        self.assertIn(("feast", "Święto Niepodległości"), kinds)
        self.assertLess(kinds.index(("event", "dentysta")), kinds.index(("plan", "angielski")))

    def test_a_person_sees_theirs_and_the_house(self):
        agenda.add("A", date(2026, 11, 11), who="Maja", now=NOW)
        agenda.add("B", date(2026, 11, 11), who="Emilka", now=NOW)
        agenda.add("C", date(2026, 11, 11), now=NOW)
        got = [i["title"] for i in agenda.items_on(date(2026, 11, 11), "Maja") if i["kind"] == "event"]
        self.assertEqual(sorted(got), ["A", "C"])

    def test_marks(self):
        agenda.add("x", date(2026, 11, 12), who="Maja", end_date=date(2026, 11, 13), now=NOW)
        m = agenda.month_marks(2026, 11)
        self.assertEqual(m[12]["who"], ["Maja"])
        self.assertEqual(m[13]["who"], ["Maja"])
        self.assertTrue(m[11]["off"])

    def test_notes_for_the_day(self):
        agenda.add("dentysta", date(2026, 11, 6), "15:00", now=NOW)
        self.assertEqual(agenda.goodnight_note(NOW), "Jutro: dentysta o piętnastej.")
        self.assertIn("dentysta", agenda.morning_note(now=at(2026, 11, 6, 8)))
        self.assertEqual(agenda.today_rows(at(2026, 11, 6, 8)), [("15:00", "dentysta")])


class PageTest(Base):
    W, H = 800, 480

    def tap_at(self, r):
        return agenda.tap(r[0] + r[2] / 2, r[1] + r[3] / 2, self.W, self.H, self.now)

    def card(self):
        e = agenda.add("dentysta", date(2026, 11, 12), "15:00", now=NOW)
        d = agenda.show(date(2026, 11, 12))
        d["sel"] = e["id"]
        return e, d, agenda.layout(self.W, self.H, d)

    def test_opens_on_the_month(self):
        d = agenda.show(date(2026, 12, 3))
        self.assertEqual((d["y"], d["m"]), (2026, 12))

    def test_cells_are_clear_of_the_panel_and_each_other(self):
        for y, m in ((2026, 11), (2026, 2), (2027, 2), (2027, 5)):
            rects = [agenda.cell_rect(y, m, n) for n in range(1, 29)]
            self.assertTrue(all(r[0] + r[2] < agenda.PANEL_X and r[1] + r[3] <= 480 for r in rects))
            d = {"y": y, "m": m, "day": f"{y}-{m:02d}-01"}
            for n, r in zip(range(1, 29), rects):
                self.assertEqual(agenda.hit(r[0] + 10, r[1] + 10, self.W, self.H, d), ("cell", n))

    def test_nothing_under_the_close_zone(self):
        d = agenda.show(date(2026, 11, 12))
        L = agenda.layout(self.W, self.H, d)
        for key in ("who", "view", "add", "type", "paper", "prev", "next"):
            r = L[key]
            self.assertFalse(r[0] + r[2] > 724 and r[1] < 96, key)
        e, d, L = self.card()
        for key in ("title", "back", "w+", "d+", "allday", "repeat"):
            r = L[key]
            self.assertFalse(r[0] + r[2] > 724 and r[1] < 96, key)

    def test_tap_a_day_then_turn_the_month(self):
        d = agenda.show(date(2026, 11, 5))
        self.tap_at(agenda.cell_rect(2026, 11, 20))
        self.assertEqual(d["day"], "2026-11-20")
        self.tap_at(agenda.layout(self.W, self.H, d)["next"])
        self.assertEqual((d["y"], d["m"]), (2026, 12))
        agenda.swipe(100)
        self.assertEqual((d["y"], d["m"]), (2026, 11))

    def test_row_opens_the_card(self):
        e = agenda.add("dentysta", date(2026, 11, 12), "15:00", now=NOW)
        d = agenda.show(date(2026, 11, 12))
        r, _ = agenda.layout(self.W, self.H, d)["rows"][0]
        self.tap_at(r)
        self.assertEqual(d["sel"], e["id"])

    def test_card_changes_the_event(self):
        e, d, L = self.card()
        self.tap_at(L["d+"])
        self.assertEqual(agenda.get(e["id"])["date"], "2026-11-13")
        self.tap_at(L["at+"])
        self.assertEqual(agenda.get(e["id"])["at"], "15:15")
        self.tap_at(L["who"])
        self.assertEqual(agenda.get(e["id"])["who"], "Andrzej")
        self.tap_at(L["repeat"])
        self.assertEqual(agenda.get(e["id"])["repeat"], "week")
        r = next(r for r, lead in L["leads"] if lead == 15)
        self.tap_at(r)
        self.assertIn(15, agenda.get(e["id"])["remind"])
        self.tap_at(r)
        self.assertNotIn(15, agenda.get(e["id"])["remind"])
        self.tap_at(L["always"])
        self.assertTrue(agenda.get(e["id"])["always"])
        self.tap_at(L["allday"])
        self.assertIsNone(agenda.get(e["id"])["at"])

    def test_delete_takes_two_taps(self):
        e, d, L = self.card()
        self.tap_at(L["delete"])
        self.assertIsNotNone(agenda.get(e["id"]))
        self.tap_at(L["delete"])
        self.assertIsNone(agenda.get(e["id"]))
        self.assertIsNone(d["sel"])

    def test_typed_new_event(self):
        d = agenda.show(date(2026, 11, 20))
        self.tap_at(agenda.layout(self.W, self.H, d)["type"])
        self.assertEqual(d["edit"]["field"], "new")
        agenda._press(d, "B", self.now)
        d["edit"]["text"] = "Bal"
        agenda._press(d, "save", self.now)
        e = self.only()
        self.assertEqual((e["title"], e["date"], d["sel"]), ("Bal", "2026-11-20", e["id"]))

    def test_draws_every_state(self):
        try:
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
            import pygame
            import ui_agenda
        except ImportError:
            self.skipTest("no pygame here")
        pygame.init()
        scr = pygame.Surface((self.W, self.H))
        schedule.add("Maja", "angielski", [3], "17:00", "18:00")
        e, d, L = self.card()
        ui_agenda.draw(scr, d, self.now, self.W, self.H)            # the card, with a time
        agenda.update(e["id"], now=self.now, at=None, note="weź skierowanie", who="Maja", repeat="year")
        ui_agenda.draw(scr, d, self.now, self.W, self.H)            # all day
        d["confirm"] = self.now
        ui_agenda.draw(scr, d, self.now, self.W, self.H)
        agenda._start_edit(d, "note", "abc")
        ui_agenda.draw(scr, d, self.now, self.W, self.H)            # the keyboard
        d.update(edit=None, sel=None, toast=("Dodane", self.now + 3))
        ui_agenda.draw(scr, d, self.now, self.W, self.H)            # the month
        d["view"] = "next"
        ui_agenda.draw(scr, d, self.now, self.W, self.H)
        d.update(view="day", day="2026-11-11", who="Maja")
        ui_agenda.draw(scr, d, self.now, self.W, self.H)

    def test_close_steps_back(self):
        e, d, L = self.card()
        agenda._start_edit(d, "note", "")
        self.assertTrue(agenda.on_close())
        self.assertIsNone(d["edit"])
        self.assertTrue(agenda.on_close())
        self.assertIsNone(d["sel"])
        self.assertFalse(agenda.on_close())


if __name__ == "__main__":
    unittest.main()
