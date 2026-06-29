from selenium import webdriver
from selenium.webdriver.common.by import By
import time
import keyboard
from datetime import datetime

# =====================
# KONFIG
# =====================
LEVELS = [1, 2, 3, 4]

BASE = "/html/body/table/tbody/tr[2]/td[2]/table[3]/tbody/tr/td/table/tbody/tr/td/table/tbody/tr/td/div/div/div[2]"

TIMER_XPATH = BASE + "/div[{lvl}]/div[3]/div/ul/li[4]/span[2]"
START_XPATH = BASE + "/div[{lvl}]/div[3]/div/div[2]/a[1]"

LOG_FILE = "zbierak.txt"

ZERO_WAIT_SECONDS = 5
POST_START_COOLDOWN = 15

NEAR_FINISH_THRESHOLD = 10  # <= 10s = czekamy
V7_INTERVAL = 30 * 60
LOOP_SLEEP_RUNNING = 1
LOOP_SLEEP_STOPPED = 0.2

# =====================
# DRIVER
# =====================
driver = webdriver.Chrome()
driver.get("https://pl230.plemiona.pl/game.php?village=6603&screen=place&mode=scavenge")
time.sleep(3)

running = False

pending_restart = {}
cooldown_until = {}

last_v7 = time.time()

t_was_down = False
y_was_down = False


# =====================
# HELPERS
# =====================
def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(text):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(text + "\n")


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
        parts = t.split(":")
        if len(parts) != 3:
            return 999999
        h, m, s = map(int, parts)
        return h * 3600 + m * 60 + s
    except:
        return 999999


def click_start(lvl):
    try:
        el = driver.find_element(By.XPATH, START_XPATH.format(lvl=lvl))
        driver.execute_script("arguments[0].click();", el)
    except:
        pass


def press_zero():
    try:
        driver.find_element(By.TAG_NAME, "body").send_keys("0")
    except:
        pass


def press_v():
    keyboard.press_and_release("v")


def press_seven():
    keyboard.press_and_release("7")


def reset_state():
    global last_v7
    pending_restart.clear()
    cooldown_until.clear()
    last_v7 = time.time()


def bot_ok():
    print("BOT OK", flush=True)
    log(f"[{now()}] BOT OK")


# =====================
# START
# =====================
print("BOT STARTED", flush=True)
log(f"[{now()}] BOT STARTED")


# =====================
# LOOP
# =====================
while True:
    t_down = keyboard.is_pressed("t")
    y_down = keyboard.is_pressed("y")

    if t_down and not t_was_down:
        running = True
        reset_state()
        print("START BOT", flush=True)
        log(f"[{now()}] START BOT")
        time.sleep(0.5)

    if y_down and not y_was_down:
        running = False
        print("STOP BOT", flush=True)
        log(f"[{now()}] STOP BOT")
        time.sleep(0.5)

    t_was_down = t_down
    y_was_down = y_down

    if not running:
        time.sleep(LOOP_SLEEP_STOPPED)
        continue

    now_ts = time.time()

    # V + 7
    if now_ts - last_v7 >= V7_INTERVAL:
        press_v()
        time.sleep(3)
        press_seven()
        last_v7 = now_ts

    # =====================
    # zbierz timery
    # =====================
    timers = {lvl: get_timer(lvl) for lvl in LEVELS}

    # =====================
    # znajdź gotowe + bliskie
    # =====================
    ready = []
    near_finish_exists = False

    for lvl in LEVELS:
        t = timers[lvl]
        secs = parse_time(t)

        if is_zero(t):
            if lvl not in pending_restart:
                pending_restart[lvl] = now_ts
            elif now_ts - pending_restart[lvl] >= ZERO_WAIT_SECONDS:
                ready.append(lvl)
        else:
            pending_restart.pop(lvl, None)

        if 0 < secs <= NEAR_FINISH_THRESHOLD:
            near_finish_exists = True

    # =====================
    # logika czekania
    # =====================
    if near_finish_exists and not ready:
        time.sleep(0.5)
        continue

    # =====================
    # start (NAJWYŻSZY PIERWSZY)
    # =====================
    while ready:
        lvl = max(ready)

        # re-check przed kliknięciem
        if not is_zero(get_timer(lvl)):
            ready.remove(lvl)
            continue

        press_zero()
        time.sleep(0.2)
        click_start(lvl)

        log(f"[{now()}] START LVL {lvl}")

        cooldown_until[lvl] = time.time() + POST_START_COOLDOWN
        ready.remove(lvl)

        time.sleep(0.4)

    time.sleep(LOOP_SLEEP_RUNNING)