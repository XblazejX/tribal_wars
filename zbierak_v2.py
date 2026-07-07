from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoAlertPresentException
import time
import keyboard
from datetime import datetime
import sys

# =====================
# KONFIG
# =====================
LEVELS = [1, 2, 3, 4]

VILLAGES = [
    {"name": "001_blocnix", "url": "https://pl230.plemiona.pl/game.php?village=6603&screen=place&mode=scavenge"},
    {"name": "002_blocnix", "url": "https://pl230.plemiona.pl/game.php?village=6437&screen=place&mode=scavenge"},
    {"name": "003_blocnix", "url": "https://pl230.plemiona.pl/game.php?village=3416&screen=place&mode=scavenge"}
]

BASE = "/html/body/table/tbody/tr[2]/td[2]/table[3]/tbody/tr/td/table/tbody/tr/td/table/tbody/tr/td/div/div/div[2]"

TIMER_XPATH = BASE + "/div[{lvl}]/div[3]/div/ul/li[4]/span[2]"
START_XPATH = BASE + "/div[{lvl}]/div[3]/div/div[2]/a[1]"

ZERO_WAIT_SECONDS = 5
POST_START_COOLDOWN = 15
NEAR_FINISH_THRESHOLD = 307

LOOP_SLEEP_RUNNING = 17
LOOP_SLEEP_STOPPED = 0.2
VILLAGE_SWITCH_DELAY = 1.0
PERIODIC_CHECK_INTERVAL = 1800  # 30 minut

# =====================
# AUTO START
# =====================
SCHEDULED_START = True
START_DELAY = "00:02"

# =====================
# DRIVER7
# =====================
driver = webdriver.Chrome()
driver.get(VILLAGES[0]["url"])
time.sleep(3)

# =====================
# STATE
# =====================
running = False
auto_started = False
start_time_ts = None

village_states = []
for _ in VILLAGES:
    village_states.append({
        "pending_restart": {},
        "cooldown_until": {},
        "started_levels": set(),
        "blocked_levels": {},
    })

current_village_idx = 0
next_periodic_check = time.time() + PERIODIC_CHECK_INTERVAL

t_was_down = False
y_was_down = False

# =====================
# HELPERS
# =====================
def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    print(msg, flush=True)
    with open("zbierak.txt", "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def log_start(lvl, village_name):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log(f"[{now_str}] WIOSKA: {village_name} | LVL: {lvl} | START")


def log_finish(lvl, village_name):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log(f"[{now_str}] WIOSKA: {village_name} | LVL: {lvl} | ZAKOŃCZONO")


def close_alert_if_present():
    try:
        alert = driver.switch_to.alert
        alert.accept()
        log("ALERT CLOSED")
    except NoAlertPresentException:
        pass
    except Exception:
        pass


def delay_seconds():
    h, m = map(int, START_DELAY.split(":"))
    return h * 3600 + m * 60


def wait_for_element(xpath, timeout=10):
    try:
        return WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((By.XPATH, xpath)))
    except Exception:
        return None


def open_village(village):
    try:
        if driver.current_url != village["url"]:
            driver.get(village["url"])
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    except Exception:
        pass


def get_text(xpath):
    try:
        return driver.find_element(By.XPATH, xpath).text.strip()
    except:
        return "0:00:00"


def get_timer(lvl):
    return get_text(TIMER_XPATH.format(lvl=lvl))


def is_zero(t):
    return t in ["0:00:00", "00:00:00"]


def parse_time(t):
    try:
        h, m, s = map(int, t.split("." if "." in t else ":"))
        return h * 3600 + m * 60 + s
    except:
        return 999999


def format_seconds(secs):
    if secs >= 999999:
        return "--:--:--"
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def get_button_text(lvl):
    try:
        el = driver.find_element(By.XPATH, START_XPATH.format(lvl=lvl))
        return el.text.strip()
    except:
        return ""


def is_button_unlocked(lvl):
    return "Odblokowanie" in get_button_text(lvl)


def click_start(lvl):
    for attempt in range(2):
        el = wait_for_element(START_XPATH.format(lvl=lvl), timeout=4)
        if el is not None:
            try:
                driver.execute_script("arguments[0].click();", el)
            except Exception:
                pass

        time.sleep(0.8)

        if not is_zero(get_timer(lvl)):
            time.sleep(2)
            return True

    return False


def press_zero():
    try:
        driver.find_element(By.TAG_NAME, "body").send_keys("0")
    except:
        pass


def press_v():
    keyboard.press_and_release("v")


# =====================
# LOOP
# =====================
print("BOT STARTED")

while True:
    close_alert_if_present()

    # =====================
    # AUTO START
    # =====================
    if SCHEDULED_START and not auto_started:
        if start_time_ts is None:
            start_time_ts = time.time() + delay_seconds()

        remaining = int(start_time_ts - time.time())

        if remaining > 0:
            sys.stdout.write(f"\rWAITING AUTO START: {remaining}s")
            sys.stdout.flush()
            time.sleep(1)
            continue

        print("\nAUTO START TRIGGERED")
        running = True
        auto_started = True

    # =====================
    # MANUAL CONTROL
    # =====================
    t_down = keyboard.is_pressed("t")
    y_down = keyboard.is_pressed("y")

    if t_down and not t_was_down:
        running = True
        log("START BOT")

    if y_down and not y_was_down:
        running = False
        log("STOP BOT")

    t_was_down = t_down
    y_was_down = y_down

    if not running:
        time.sleep(LOOP_SLEEP_STOPPED)
        continue

    # =====================
    # ZBIERANIE DANYCH Z WIOSEK
    # =====================
    village_timers = {}
    active_timer_entries = []
    zero_timer_entries = []
    ready_candidates = []
    any_zero_ready_or_blocked_global = False
    
    for village_idx in range(len(VILLAGES)):
        close_alert_if_present()
        
        village = VILLAGES[village_idx]
        state = village_states[village_idx]
        open_village(village)
        
        now_ts = time.time()
        timers = {lvl: get_timer(lvl) for lvl in LEVELS}
        min_time = 999999
        
        active_times = []
        any_zero_ready_or_blocked = False
        
        for lvl in LEVELS:
            t = timers[lvl]
            secs = parse_time(t)

            if lvl in state["blocked_levels"]:
                continue

            if is_zero(t):
                zero_timer_entries.append({
                    "secs": secs,
                    "village_name": village["name"],
                    "lvl": lvl,
                })
                
                if lvl not in state["pending_restart"]:
                    state["pending_restart"][lvl] = now_ts
                    continue

                if now_ts - state["pending_restart"][lvl] < ZERO_WAIT_SECONDS:
                    continue

                if time.time() < state["cooldown_until"].get(lvl, 0):
                    continue

                if is_button_unlocked(lvl):
                    state["blocked_levels"][lvl] = now_ts
                    log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] WIOSKA: {village['name']} | LVL: {lvl} | ZABLOKOWANY (pomijam)")
                    continue

                any_zero_ready_or_blocked = True
                ready_candidates.append({
                    "village_idx": village_idx,
                    "village": village,
                    "lvl": lvl,
                })
                continue

            state["pending_restart"].pop(lvl, None)
            active_timer_entries.append({
                "secs": secs,
                "village_name": village["name"],
                "lvl": lvl,
            })
            active_times.append(secs)

        if active_times:
            min_time = min(active_times)
        elif any_zero_ready_or_blocked:
            min_time = min(LOOP_SLEEP_RUNNING, 5)
        
        village_timers[village_idx] = min_time
        any_zero_ready_or_blocked_global |= any_zero_ready_or_blocked
        time.sleep(0.5)

    # =====================
    # ZNALEZIENIE NAJMNIEJSZEGO CZASU
    # =====================
    min_global_time = min(village_timers.values())
    wait_target = None
    wait_on_max = False
    if active_timer_entries:
        min_entry = min(active_timer_entries, key=lambda e: e["secs"])
        max_entry = max(active_timer_entries, key=lambda e: e["secs"])
        if max_entry["secs"] - min_entry["secs"] < 300:
            wait_target = {
                "entry": max_entry,
                "label": "NAJDŁUŻSZY"
            }
            min_global_time = max_entry["secs"]
            wait_on_max = True
        else:
            wait_target = {
                "entry": min_entry,
                "label": "NAJKRÓTSZY"
            }
            min_global_time = min_entry["secs"]
    elif zero_timer_entries and any_zero_ready_or_blocked_global:
        wait_target = {
            "entry": min(zero_timer_entries, key=lambda e: e["secs"]),
            "label": "NAJKRÓTSZY"
        }
        min_global_time = min(LOOP_SLEEP_RUNNING, 5)

    if min_global_time == 999999:
        time.sleep(LOOP_SLEEP_RUNNING)
        continue

    if ready_candidates and not wait_on_max:
        for candidate in ready_candidates:
            village = candidate["village"]
            lvl = candidate["lvl"]
            open_village(village)
            press_zero()
            time.sleep(1)
            started = click_start(lvl)

            if started:
                log_start(lvl, village["name"])
                state = village_states[candidate["village_idx"]]
                state["cooldown_until"][lvl] = time.time() + POST_START_COOLDOWN
                state["started_levels"].add(lvl)
                actual_timer = get_timer(lvl)
                actual_secs = parse_time(actual_timer)
                if actual_secs < min_time:
                    min_time = actual_secs
            else:
                log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] WIOSKA: {village['name']} | LVL: {lvl} | FAILED")

    # =====================
    # CZEKANIE NA NAJMNIEJSZY CZAS + BUFFER
    # =====================
    wait_time = min_global_time + 3
    while wait_time > 0:
        close_alert_if_present()

        now_ts = time.time()
        if now_ts >= next_periodic_check:
            print("\nPERIODICZNY SPRAWDZANIE TIMERA - PONOWNY SKAN")
            next_periodic_check = now_ts + PERIODIC_CHECK_INTERVAL
            break

        if wait_target is not None:
            target = wait_target["entry"]
            target_time = format_seconds(target["secs"])
            sys.stdout.write(
                f"\rCZEKAJE: {wait_time}s na {wait_target['label']} {target_time} - {target['village_name']} LVL {target['lvl']}"
            )
        else:
            sys.stdout.write(f"\rCZEKAJE: {wait_time}s (timer + buffer)")
        sys.stdout.flush()
        time.sleep(1)
        wait_time -= 1

    print("\nCZAS OSIĄGNIĘTY - PONOWNE SKANOWANIE")