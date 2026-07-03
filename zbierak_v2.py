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
]

BASE = "/html/body/table/tbody/tr[2]/td[2]/table[3]/tbody/tr/td/table/tbody/tr/td/table/tbody/tr/td/div/div/div[2]"

TIMER_XPATH = BASE + "/div[{lvl}]/div[3]/div/ul/li[4]/span[2]"
START_XPATH = BASE + "/div[{lvl}]/div[3]/div/div[2]/a[1]"

ZERO_WAIT_SECONDS = 5
POST_START_COOLDOWN = 15
NEAR_FINISH_THRESHOLD = 30

V7_INTERVAL = 30 * 60

LOOP_SLEEP_RUNNING = 1
LOOP_SLEEP_STOPPED = 0.2
VILLAGE_SWITCH_DELAY = 1.0

# =====================
# AUTO START
# =====================
SCHEDULED_START = True
START_DELAY = "00:05"

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
        "last_v7": time.time(),
    })

current_village_idx = 0

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
        h, m, s = map(int, t.split(":"))
        return h * 3600 + m * 60 + s
    except:
        return 999999


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

        if attempt == 0:
            press_seven()
            time.sleep(0.5)

    return False


def press_zero():
    try:
        driver.find_element(By.TAG_NAME, "body").send_keys("0")
    except:
        pass


def press_v():
    keyboard.press_and_release("v")


def press_seven():
    keyboard.press_and_release("7")


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

    now_ts = time.time()

    village = VILLAGES[current_village_idx]
    state = village_states[current_village_idx]
    open_village(village)

    # =====================
    # V7
    # =====================
    if now_ts - state["last_v7"] >= V7_INTERVAL:
        time.sleep(3)
        press_seven()
        state["last_v7"] = now_ts

    # =====================
    # TIMERS
    # =====================
    timers = {lvl: get_timer(lvl) for lvl in LEVELS}

    ready = []
    near_finish = False

    for lvl in LEVELS:
        t = timers[lvl]
        secs = parse_time(t)

        if is_zero(t):
            if lvl not in state["pending_restart"]:
                state["pending_restart"][lvl] = now_ts
            elif now_ts - state["pending_restart"][lvl] >= ZERO_WAIT_SECONDS:
                ready.append(lvl)
        else:
            state["pending_restart"].pop(lvl, None)

        if 0 < secs <= NEAR_FINISH_THRESHOLD:
            near_finish = True

    if near_finish and not ready:
        current_village_idx = (current_village_idx + 1) % len(VILLAGES)
        time.sleep(VILLAGE_SWITCH_DELAY)
        continue

    # =====================
    # EXECUTION
    # =====================
    while ready:
        lvl = max(ready)

        if time.time() < state["cooldown_until"].get(lvl, 0):
            ready.remove(lvl)
            continue

        if not is_zero(get_timer(lvl)):
            ready.remove(lvl)
            continue

        press_zero()
        time.sleep(1)
        started = click_start(lvl)

        if started:
            log_start(lvl, village["name"])
            state["cooldown_until"][lvl] = time.time() + POST_START_COOLDOWN
            log_finish(lvl, village["name"])
        else:
            log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] WIOSKA: {village['name']} | LVL: {lvl} | FAILED")

        ready.remove(lvl)
        time.sleep(2)

    current_village_idx = (current_village_idx + 1) % len(VILLAGES)
    time.sleep(LOOP_SLEEP_RUNNING)