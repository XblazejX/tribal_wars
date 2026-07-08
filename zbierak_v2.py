"""
Bot do automatycznego zbieractwa w Plemionach (Tribal Wars).
Obsługuje wiele wiosek — skanuje timery, czeka aż wszystkie poziomy będą gotowe,
potem startuje je od najwyższego (4) do najniższego (1).
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoAlertPresentException
import time
import keyboard
from datetime import datetime
import sys


# =============================================================================
#  KONFIGURACJA — JEDYNE MIEJSCE DO EDYCJI
# =============================================================================
#  Tutaj ustawiasz wioski i auto-start. Reszty pliku nie trzeba ruszać.
# =============================================================================

# Lista wiosek do obsługi.
# URL: wejdź w grze na Zbieractwo w danej wiosce i skopiuj adres z paska przeglądarki.
# name: dowolna etykieta do logów (np. numer_wioski_nick)
VILLAGES = [
    {"name": "001_blocnix", "url": "https://pl230.plemiona.pl/game.php?village=6603&screen=place&mode=scavenge"},
    {"name": "002_blocnix", "url": "https://pl230.plemiona.pl/game.php?village=6437&screen=place&mode=scavenge"},
    {"name": "003_blocnix", "url": "https://pl230.plemiona.pl/game.php?village=3416&screen=place&mode=scavenge"},
]

# Auto-start bota po uruchomieniu skryptu
SCHEDULED_START = True   # True = bot włączy się sam po START_DELAY | False = tylko klawisz T
START_DELAY = "00:01"    # Opóźnienie przed auto-startem, format HH:MM (np. "00:02" = 2 minuty)

# Sterowanie klawiszem Y
STOP_ON_Y = False         # True = Y zatrzymuje bota | False = Y ignorowany (start tylko klawiszem T)



# =============================================================================
#  USTAWIENIA WEWNĘTRZNE — nie edytuj bez potrzeby
# =============================================================================

LEVELS = [1, 2, 3, 4]  # Poziomy zbieractwa w grze

# Ścieżki XPath do elementów na stronie zbieractwa (struktura HTML gry)
BASE = "/html/body/table/tbody/tr[2]/td[2]/table[3]/tbody/tr/td/table/tbody/tr/td/table/tbody/tr/td/div/div/div[2]"
TIMER_XPATH = BASE + "/div[{lvl}]/div[3]/div/ul/li[4]/span[2]"
START_XPATH = BASE + "/div[{lvl}]/div[3]/div/div[2]/a[1]"

# Czas oczekiwania po timerze 0:00:00 zanim poziom uznany za gotowy
ZERO_WAIT_SECONDS = 3
# Cooldown po udanym starcie poziomu (ochrona przed podwójnym kliknięciem)
POST_START_COOLDOWN = 5
# Bufor dodawany do najdłuższego timera wioski przed planowanym startem
READY_BUFFER_SECONDS = 5
# Przerwa między kolejnymi kliknięciami START w tej samej wiosce
INTER_START_DELAY_SECONDS = 1

# Odstępy pętli głównej
LOOP_SLEEP_RUNNING = 17   # Gdy brak harmonogramu — jak długo spać
LOOP_SLEEP_STOPPED = 0.2  # Gdy bot zatrzymany (klawisz Y)
PERIODIC_CHECK_INTERVAL = 1800  # Watchdog: pełny skan co 30 min (czy bot nie utknął)

LOG_FILE = "zbierak.txt"


# =============================================================================
#  INICJALIZACJA
# =============================================================================

# Uruchom Chrome i otwórz pierwszą wioskę (musisz być zalogowany w tej sesji)
driver = webdriver.Chrome()
driver.get(VILLAGES[0]["url"])
time.sleep(3)

# Stan bota
running = False          # Czy pętla pracy jest aktywna
auto_started = False     # Czy auto-start już się wykonał
start_time_ts = None     # Timestamp planowanego auto-startu

# Osobny stan dla każdej wioski (timery, blokady, harmonogram)
village_states = []
for _ in VILLAGES:
    village_states.append({
        "pending_restart": {},   # Kiedy poziom po raz pierwszy pokazał 0:00:00
        "cooldown_until": {},      # Do kiedy nie próbować ponownie startu poziomu
        "started_levels": set(),   # Poziomy uruchomione w tej sesji
        "blocked_levels": {},      # Poziomy zablokowane (np. przycisk „odblokuj”)
        "last_attempt_ts": {},     # Ostatnia próba kliknięcia START
        "next_start_ts": None,     # Kiedy wioska ma być gotowa do startu (max timer + bufor)
        "last_max_secs": 999999,   # Ostatnio odczytany najdłuższy aktywny timer
    })

next_periodic_check = 0       # Kiedy następny watchdog (pełny skan)
last_schedule_key = None        # Ostatni zalogowany harmonogram (anty-spam logów)
last_wait_all_key = None        # Ostatni stan „czekam na wszystkie” (anty-spam logów)

# Klawisze T/Y — wykrywanie pojedynczego naciśnięcia (nie przytrzymania)
t_was_down = False
y_was_down = False


# =============================================================================
#  LOGOWANIE I CZAS
# =============================================================================

def now():
    """Aktualny czas jako string do logów."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    """Wypisz na konsolę i dopisz do pliku logu."""
    print(msg, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def log_start(lvl, village_name):
    log(f"[{now()}] WIOSKA: {village_name} | LVL: {lvl} | START")


def log_finish(lvl, village_name):
    log(f"[{now()}] WIOSKA: {village_name} | LVL: {lvl} | ZAKOŃCZONO")


def delay_seconds():
    """Zamień START_DELAY (HH:MM) na sekundy."""
    h, m = map(int, START_DELAY.split(":"))
    return h * 3600 + m * 60


def format_seconds(secs):
    """Sekundy → HH:MM:SS."""
    if secs >= 999999:
        return "--:--:--"
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_countdown(secs):
    """Odliczanie w dół, minimum 0."""
    if secs < 0:
        secs = 0
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def parse_time(t):
    """Timer z gry (H:M:S lub H.M.S) → sekundy. Błąd → bardzo duża liczba."""
    try:
        h, m, s = map(int, t.split("." if "." in t else ":"))
        return h * 3600 + m * 60 + s
    except Exception:
        return 999999


def is_zero(t):
    """Czy timer pokazuje zero (poziom skończył / gotowy do restartu)."""
    return t is not None and t in ["0:00:00", "00:00:00"]


# =============================================================================
#  PRZEGLĄDARKA I ELEMENTY GRY
# =============================================================================

def close_alert_if_present():
    """Zamknij popup JS (np. potwierdzenie), żeby bot nie utknął."""
    try:
        alert = driver.switch_to.alert
        alert.accept()
        log("ALERT CLOSED")
    except NoAlertPresentException:
        pass
    except Exception:
        pass


def wait_for_element(xpath, timeout=10):
    """Poczekaj aż element będzie klikalny; None jeśli timeout."""
    try:
        return WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.XPATH, xpath))
        )
    except Exception:
        return None


def open_village(village):
    """Przejdź na stronę zbieractwa danej wioski."""
    try:
        if driver.current_url != village["url"]:
            driver.get(village["url"])
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
    except Exception:
        pass


def get_text(xpath):
    """Odczytaj tekst elementu; przy błędzie zwróć 0:00:00."""
    try:
        return driver.find_element(By.XPATH, xpath).text.strip()
    except Exception:
        return "0:00:00"


def get_timer(lvl):
    """Timer poziomu zbieractwa."""
    return get_text(TIMER_XPATH.format(lvl=lvl))


def get_button_text(lvl):
    """Tekst przycisku startu / odblokowania."""
    try:
        el = driver.find_element(By.XPATH, START_XPATH.format(lvl=lvl))
        return el.text.strip()
    except Exception:
        return ""


def is_button_unlocked(lvl):
    """Poziom wymaga odblokowania (np. brak punktów) — pomijamy na stałe."""
    text = get_button_text(lvl).lower()
    return "odblok" in text or "unlock" in text


def press_zero():
    """Skrót gry: wypełnij wszystkie dostępne jednostki przed startem."""
    try:
        driver.find_element(By.TAG_NAME, "body").send_keys("0")
    except Exception:
        pass


def full_boot_scan(trigger):
    """Zachowuj się jak przy starcie: pełny skan wszystkich wiosek."""
    log(f"[{now()}] RECOVER | PELNY_SKAN_START | TRIGGER: {trigger}")
    for village_idx in range(len(VILLAGES)):
        close_alert_if_present()
        scan_village(village_idx, verbose=True)
        time.sleep(0.5)



def click_start(lvl):
    """
    Kliknij START dla poziomu. Sukces = timer zmienił się z zera na wartość > 0.
    Dwie próby z krótką przerwą.
    """
    before_timer = get_timer(lvl)
    for _ in range(2):
        el = wait_for_element(START_XPATH.format(lvl=lvl), timeout=4)
        if el is not None:
            try:
                driver.execute_script("arguments[0].click();", el)
            except Exception:
                pass

        time.sleep(1.2)
        after_timer = get_timer(lvl)
        if after_timer is not None and after_timer != before_timer and not is_zero(after_timer):
            time.sleep(2)
            return True

    return False


# =============================================================================
#  SKANOWANIE WIOSKI
# =============================================================================

def scan_village(village_idx, verbose=False):
    """
    Odczytaj stan wszystkich poziomów w wiosce.
    Ustawia next_start_ts = teraz + max(aktywne timery) + READY_BUFFER_SECONDS.
    Zwraca: gotowe poziomy, max sekund, czy są zera w oczekiwaniu,
            oczekiwane poziomy (bez blokad), czy WSZYSTKIE oczekiwane są gotowe.
    """
    village = VILLAGES[village_idx]
    state = village_states[village_idx]
    open_village(village)
    now_ts = time.time()

    timers = {lvl: get_timer(lvl) for lvl in LEVELS}
    active_secs = []       # Timery jeszcze lecące (wyprawa w toku)
    ready_levels = []      # Poziomy gotowe do START
    level_debug = []       # Szczegóły do logu
    blocked_now = []
    has_pending_zero = False  # Zera, które jeszcze nie przeszły ZERO_WAIT_SECONDS

    for lvl in LEVELS:
        t = timers[lvl]

        # Jeśli przycisk mówi "odblokuj" => poziom aktualnie zablokowany.
        # W watchdog'u sprawdzamy to zawsze, żeby wykryć moment odblokowania.
        if is_button_unlocked(lvl):
            # Czyści flagi związane z „0” żeby po odblokowaniu nie odpalić od razu.
            state["pending_restart"].pop(lvl, None)

            if lvl not in state["blocked_levels"]:
                level_debug.append(f"LVL {lvl}: ZABLOKOWANY(przycisk odblokuj)")
            else:
                level_debug.append(f"LVL {lvl}: PONOWNIE_ZABLOKOWANY(przycisk odblokuj)")

            state["blocked_levels"][lvl] = now_ts
            blocked_now.append(lvl)
            continue

        # Jeśli wcześniej był zablokowany, a teraz przycisk nie ma "odblokuj" => odblokowany.
        if lvl in state["blocked_levels"]:
            state["blocked_levels"].pop(lvl, None)
            level_debug.append(f"LVL {lvl}: ODBLOKOWANY(wcześniej blokada)")

        if is_zero(t):
            # Pierwsze zobaczenie zera — zacznij odliczać ZERO_WAIT_SECONDS
            if lvl not in state["pending_restart"]:
                state["pending_restart"][lvl] = now_ts
                has_pending_zero = True
                level_debug.append(f"LVL {lvl}: 0:00:00 -> OCZEKIWANIE_ZERO({ZERO_WAIT_SECONDS}s)")
                continue

            if now_ts - state["pending_restart"][lvl] < ZERO_WAIT_SECONDS:
                has_pending_zero = True
                remaining = int(ZERO_WAIT_SECONDS - (now_ts - state["pending_restart"][lvl]))
                level_debug.append(f"LVL {lvl}: 0:00:00 -> OCZEKIWANIE_ZERO({max(0, remaining)}s)")
                continue

            if time.time() < state["cooldown_until"].get(lvl, 0):
                remaining_cd = int(state["cooldown_until"].get(lvl, 0) - time.time())
                level_debug.append(f"LVL {lvl}: 0:00:00 -> COOLDOWN({max(0, remaining_cd)}s)")
                continue

            if now_ts - state["last_attempt_ts"].get(lvl, 0) < 2:
                level_debug.append(f"LVL {lvl}: 0:00:00 -> ANTY_SPAM_2S")
                continue

            ready_levels.append(lvl)
            level_debug.append(f"LVL {lvl}: GOTOWY_DO_STARTU")
            continue

        # Aktywna wyprawa — timer leci
        state["pending_restart"].pop(lvl, None)
        secs = parse_time(t)
        if secs < 999999:
            active_secs.append(secs)
            level_debug.append(f"LVL {lvl}: AKTYWNY({format_seconds(secs)})")
        else:
            level_debug.append(f"LVL {lvl}: TIMER_NIECZYTELNY({t})")

    # Poziomy, które bot ma obsłużyć (bez trwale zablokowanych)
    expected_levels = [lvl for lvl in LEVELS if lvl not in state["blocked_levels"]]
    missing_levels = sorted(set(expected_levels) - set(ready_levels), reverse=True)

    # Start dopiero gdy każdy oczekiwany poziom jest gotowy i nic nie leci
    all_ready = (
        len(expected_levels) > 0
        and set(ready_levels) == set(expected_levels)
        and not has_pending_zero
        and not active_secs
    )

    if active_secs:
        max_secs = max(active_secs)
    elif ready_levels:
        max_secs = 0
    else:
        max_secs = LOOP_SLEEP_RUNNING

    state["last_max_secs"] = max_secs
    state["next_start_ts"] = now_ts + max_secs + READY_BUFFER_SECONDS

    if blocked_now:
        for lvl in blocked_now:
            log(f"[{now()}] WIOSKA: {village['name']} | LVL: {lvl} | ZABLOKOWANY (pomijam)")

    if verbose:
        next_in = int(state["next_start_ts"] - time.time())
        log(
            f"[{now()}] SKAN | WIOSKA: {village['name']} | ALL_READY: {all_ready} "
            f"| EXPECTED: {sorted(expected_levels, reverse=True)} "
            f"| GOTOWE: {sorted(ready_levels, reverse=True)} "
            f"| BRAKUJE: {missing_levels} "
            f"| MAX_TIMER: {format_seconds(max_secs)} | START_ZA: {format_countdown(next_in)}"
        )
        for msg in level_debug:
            log(f"[{now()}] SKAN_DETAIL | WIOSKA: {village['name']} | {msg}")

    return ready_levels, max_secs, has_pending_zero, expected_levels, all_ready


# =============================================================================
#  START POZIOMÓW W WIOSCE
# =============================================================================

def start_ready_levels_in_village(village_idx):
    """
    Uruchom zbieractwo we wszystkich gotowych poziomach wiosce.
    Warunek: all_ready — inaczej START_ABORT (nic nie klika).
    Kolejność: od LVL 4 w dół do 1.
    """
    village = VILLAGES[village_idx]
    state = village_states[village_idx]
    open_village(village)

    ready_levels, _, has_pending_zero, expected_levels, all_ready = scan_village(
        village_idx, verbose=True
    )

    if not all_ready:
        missing = sorted(set(expected_levels) - set(ready_levels), reverse=True)
        log(
            f"[{now()}] START_ABORT | WIOSKA: {village['name']} | POWOD: NIE_WSZYSTKIE_GOTOWE "
            f"| GOTOWE: {sorted(ready_levels, reverse=True)} | BRAKUJE: {missing} "
            f"| PENDING_ZERO: {has_pending_zero}"
        )
        return False

    levels_to_start = sorted(expected_levels, reverse=True)
    log(f"[{now()}] START_SEKWENCJA | WIOSKA: {village['name']} | KOLEJNOSC_LVL: {levels_to_start}")

    started_count = 0
    for lvl in levels_to_start:
        if lvl in state["blocked_levels"]:
            log(f"[{now()}] START_SKIP | WIOSKA: {village['name']} | LVL: {lvl} | POWOD: BLOKADA")
            continue

        if time.time() < state["cooldown_until"].get(lvl, 0):
            wait_cd = int(state["cooldown_until"].get(lvl, 0) - time.time())
            log(
                f"[{now()}] START_SKIP | WIOSKA: {village['name']} | LVL: {lvl} "
                f"| POWOD: COOLDOWN {max(0, wait_cd)}s"
            )
            continue

        log(f"[{now()}] START_PROBA | WIOSKA: {village['name']} | LVL: {lvl}")
        press_zero()
        time.sleep(1)
        state["last_attempt_ts"][lvl] = time.time()
        started = click_start(lvl)

        if started:
            started_count += 1
            log_start(lvl, village["name"])
            state["cooldown_until"][lvl] = time.time() + POST_START_COOLDOWN
            state["started_levels"].add(lvl)
            log_finish(lvl, village["name"])
        else:
            after = get_timer(lvl)
            log(
                f"[{now()}] START_FAILED | WIOSKA: {village['name']} | LVL: {lvl} "
                f"| TIMER_PO_PROBIE: {after}"
            )

        time.sleep(INTER_START_DELAY_SECONDS)

    scan_village(village_idx, verbose=True)

    if started_count == len(levels_to_start):
        log(
            f"[{now()}] START_WYNIK | WIOSKA: {village['name']} | STATUS: WSZYSTKIE_URUCHOMIONE "
            f"| COUNT: {started_count}/{len(levels_to_start)}"
        )
        return True

    log(
        f"[{now()}] START_WYNIK | WIOSKA: {village['name']} | STATUS: CZESCIOWY_LUB_BRAK "
        f"| COUNT: {started_count}/{len(levels_to_start)}"
    )
    state["next_start_ts"] = time.time() + LOOP_SLEEP_RUNNING
    return False


# =============================================================================
#  GŁÓWNA PĘTLA
# =============================================================================
#  Sterowanie: T = start bota | Y = stop bota (jeśli STOP_ON_Y = True)
#  Terminal na żywo: START ZA / CEKAM NA WSZYSTKIE
# =============================================================================

print("BOT STARTED")

while True:
    close_alert_if_present()

    # --- Auto-start po START_DELAY (tylko raz po uruchomieniu skryptu) ---
    if SCHEDULED_START and not auto_started:
        if start_time_ts is None:
            start_time_ts = time.time() + delay_seconds()

        remaining = int(start_time_ts - time.time())
        if remaining > 0:
            sys.stdout.write(f"\rWAITING AUTO START: {format_countdown(remaining)}")
            sys.stdout.flush()
            time.sleep(1)
            continue

        print("\nAUTO START TRIGGERED")
        running = True
        auto_started = True    

    # --- Ręczne włączenie (T) / wyłączenie (Y, jeśli STOP_ON_Y) ---
    t_down = keyboard.is_pressed("t")
    y_down = keyboard.is_pressed("y") if STOP_ON_Y else False

    if t_down and not t_was_down:
        running = True
        log(f"[{now()}] BOT | START")

    if STOP_ON_Y and y_down and not y_was_down:
        running = False
        log(f"[{now()}] BOT | STOP")

    t_was_down = t_down
    y_was_down = y_down

    if not running:
        time.sleep(LOOP_SLEEP_STOPPED)
        continue

    now_ts = time.time()

    # --- Pełny skan wszystkich wiosek: start, watchdog 30 min, brak harmonogramu ---
    need_full_scan = False
    full_scan_reason = ""
    if next_periodic_check == 0:
        next_periodic_check = now_ts + PERIODIC_CHECK_INTERVAL
        need_full_scan = True
        full_scan_reason = "INIT"
    elif now_ts >= next_periodic_check:
        print("\nPERIODICZNE SPRAWDZENIE (watchdog) - pełny skan")
        next_periodic_check = now_ts + PERIODIC_CHECK_INTERVAL
        need_full_scan = True
        full_scan_reason = "WATCHDOG_30M"
    elif any(village_states[idx]["next_start_ts"] is None for idx in range(len(VILLAGES))):
        need_full_scan = True
        full_scan_reason = "BRAK_HARMONOGRAMU"

    if need_full_scan:
        log(f"[{now()}] PETLA | PELNY_SKAN_START | POWOD: {full_scan_reason}")
        for village_idx in range(len(VILLAGES)):
            close_alert_if_present()
            scan_village(village_idx, verbose=True)
            time.sleep(0.5)

    # --- Wybierz wioskę z najwcześniejszym planowanym startem ---
    schedule = []
    for village_idx in range(len(VILLAGES)):
        state = village_states[village_idx]
        if state["next_start_ts"] is not None:
            schedule.append((state["next_start_ts"], village_idx))

    if not schedule:
        log(f"[{now()}] HARMONOGRAM | BRAK_WIOSEK_DO_PLANU -> SLEEP {LOOP_SLEEP_RUNNING}s")
        time.sleep(LOOP_SLEEP_RUNNING)
        continue

    schedule.sort(key=lambda x: x[0])
    target_ts, target_village_idx = schedule[0]
    target_village = VILLAGES[target_village_idx]
    target_state = village_states[target_village_idx]
    schedule_key = (target_village_idx, int(target_ts))

    wait_time = int(target_ts - time.time())

    # --- Jeszcze za wcześnie — odliczanie do planowanego czasu (max timer + bufor) ---
    if wait_time > 0:
        sys.stdout.write(
            f"\rSTART ZA: {wait_time}s | WIOSKA: {target_village['name']}                     "
        )
        sys.stdout.flush()
        if schedule_key != last_schedule_key:
            log(
                f"[{now()}] HARMONOGRAM | CEL: {target_village['name']} "
                f"| START_ZA: {format_countdown(wait_time)} "
                f"| MAX_TIMER: {format_seconds(target_state['last_max_secs'])} + {READY_BUFFER_SECONDS}s"
            )
            last_schedule_key = schedule_key
        time.sleep(1)
        continue

    # --- Czas minął — czekaj aż WSZYSTKIE poziomy w wiosce będą gotowe ---
    last_schedule_key = None
    ready_levels, _, _, expected_levels, all_ready = scan_village(target_village_idx, verbose=False)

    if not all_ready:
        missing_levels = sorted(set(expected_levels) - set(ready_levels), reverse=True)
        wait_all_key = (target_village_idx, tuple(missing_levels), len(ready_levels))

        sys.stdout.write(
            f"\rCEKAM NA WSZYSTKIE {len(ready_levels)}/{len(expected_levels)} | "
            f"WIOSKA: {target_village['name']} | BRAKUJE: {missing_levels}                     "
        )
        sys.stdout.flush()

        if wait_all_key != last_wait_all_key:
            log(
                f"[{now()}] CZEKAM_NA_WSZYSTKIE | WIOSKA: {target_village['name']} "
                f"| GOTOWE: {sorted(ready_levels, reverse=True)} | BRAKUJE: {missing_levels} "
                f"| MAX_TIMER+{READY_BUFFER_SECONDS}s JUZ MINAL"
            )
            last_wait_all_key = wait_all_key

        time.sleep(1)
        continue

    # --- Wszystkie gotowe — start sekwencji 4 → 3 → 2 → 1 ---
    last_wait_all_key = None
    log(
        f"[{now()}] CZAS_STARTU | WIOSKA: {target_village['name']} "
        f"| WARUNEK: WSZYSTKIE_POZIOMY_GOTOWE ({len(expected_levels)}/{len(expected_levels)})"
    )
    start_ready_levels_in_village(target_village_idx)
