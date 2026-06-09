"""ESP32-S3 MicroPython 4-servo mechanical min/max tester.

Upload as main.py with Thonny. Use the Thonny Shell directly.

This is ONLY for mechanical testing before connecting the laptop app.
It uses the hardware-tested wiring:
    horizontal servos: GPIO42, GPIO39
    vertical servos:   GPIO41, GPIO38
"""

from machine import Pin, PWM
from time import sleep_ms


SERVO_FREQ_HZ = 50

# Hardware-tested pins.
PIN_BY_SLOT = {
    "h1": 42,
    "h2": 39,
    "v1": 41,
    "v2": 38,
}

HORIZ_SLOTS = ("h1", "h2")
VERT_SLOTS = ("v1", "v2")

PAN_NEUTRAL = 90
PAN_MIN = 50
PAN_MAX = 130
TILT_NEUTRAL = 0
TILT_MIN = 0
TILT_MAX = 50

# Never sweep all unknown servos at once.
SAFE_TEST_ANGLES = (90, 75, 105, 90)
FULL_180_TEST_ANGLES = (90, 60, 120, 90, 30, 150, 90)

CLASSIFY_STEPS = (
    (90, "CENTER / STOP check"),
    (75, "LOW angle check"),
    (90, "BACK TO CENTER check"),
    (105, "HIGH angle check"),
    (90, "FINAL CENTER check"),
)

_pwms = {}


def clamp(value, low, high):
    return max(low, min(high, int(value)))


def angle_to_duty(angle):
    # Matches the previously working hardware script.
    angle = clamp(angle, 0, 180)
    return int((angle / 180) * 102 + 26)


def is_horizontal(slot):
    return slot in HORIZ_SLOTS


def get_pwm(slot):
    slot = slot.lower().strip()
    if slot not in PIN_BY_SLOT:
        raise ValueError("unknown slot: {}".format(slot))
    if slot not in _pwms:
        _pwms[slot] = PWM(Pin(PIN_BY_SLOT[slot]), freq=SERVO_FREQ_HZ)
    return _pwms[slot]


def write_angle(slot, angle):
    slot = slot.lower().strip()
    pwm = get_pwm(slot)
    hardware_angle = 180 - angle if is_horizontal(slot) else angle
    duty = angle_to_duty(hardware_angle)
    pwm.duty(duty)
    print(
        "{} GPIO{} logical_angle={} hardware_angle={} duty={}".format(
            slot, PIN_BY_SLOT[slot], angle, hardware_angle, duty
        )
    )


def set_horizontal(angle):
    angle = clamp(angle, PAN_MIN, PAN_MAX)
    for slot in HORIZ_SLOTS:
        write_angle(slot, angle)


def set_vertical(angle):
    angle = clamp(angle, TILT_MIN, TILT_MAX)
    for slot in VERT_SLOTS:
        write_angle(slot, angle)


def set_pose(pan, tilt):
    set_horizontal(pan)
    set_vertical(tilt)


def release(slot):
    slot = slot.lower().strip()
    pwm = _pwms.pop(slot, None)
    if pwm is not None:
        pwm.deinit()
    print("released", slot)


def release_all():
    for slot in list(_pwms.keys()):
        release(slot)


def pause_for_observation():
    input("Press Enter after observing... ")


def classify_servo(slot):
    print("\n=== CLASSIFY {} ===".format(slot))
    print("Watch ONE servo only. If it holds positions, it is 180 positional.")
    print("If it buzzes/hits end-stop, unplug servo power immediately.\n")
    for angle, label in CLASSIFY_STEPS:
        print("STEP: {} | command logical angle {}".format(label, angle))
        write_angle(slot, angle)
        sleep_ms(350)
        pause_for_observation()


def test_servo(slot, full=False, delay_ms=1200):
    angles = FULL_180_TEST_ANGLES if full else SAFE_TEST_ANGLES
    print("Testing {} with logical angles {}".format(slot, angles))
    for angle in angles:
        write_angle(slot, angle)
        sleep_ms(delay_ms)
    write_angle(slot, 90 if is_horizontal(slot) else 0)


def classify_hint():
    print("Classification hints:")
    print("- 180 positional: logical angle command moves then holds position.")
    print("- For this project, all 4 servos are expected to be 180 positional.")
    print("- If any servo spins continuously, buzzes, or hits an end-stop, stop testing.")
    print("- Use external 5V servo power and common GND with ESP32.")


def test_mechanical_limits():
    print("\n=== MECHANICAL LIMITS: BOTH EYES SYNCED ===")
    print("Horizontal pins {} | Vertical pins {}".format(HORIZ_SLOTS, VERT_SLOTS))
    print("PAN {}..{} neutral {} | TILT {}..{} neutral {}".format(
        PAN_MIN, PAN_MAX, PAN_NEUTRAL, TILT_MIN, TILT_MAX, TILT_NEUTRAL
    ))
    steps = (
        ("neutral", PAN_NEUTRAL, TILT_NEUTRAL),
        ("hmin", PAN_MIN, TILT_NEUTRAL),
        ("neutral", PAN_NEUTRAL, TILT_NEUTRAL),
        ("hmax", PAN_MAX, TILT_NEUTRAL),
        ("neutral", PAN_NEUTRAL, TILT_NEUTRAL),
        ("vmax", PAN_NEUTRAL, TILT_MAX),
        ("neutral", PAN_NEUTRAL, TILT_NEUTRAL),
        ("diag hmin+vmax", PAN_MIN, TILT_MAX),
        ("neutral", PAN_NEUTRAL, TILT_NEUTRAL),
        ("diag hmax+vmax", PAN_MAX, TILT_MAX),
        ("neutral", PAN_NEUTRAL, TILT_NEUTRAL),
    )
    for name, pan, tilt in steps:
        print("STEP {} -> pan={} tilt={}".format(name, pan, tilt))
        print("If any servo buzzes/hits end-stop, unplug power immediately.")
        pause_for_observation()
        set_pose(pan, tilt)
        sleep_ms(700)


def help_text():
    print("Commands:")
    print("  pins              print configured pins")
    print("  limits            guided min/max test for horizontal+vertical axes")
    print("  hmid              horizontal neutral pan=90")
    print("  hmin              horizontal min pan=50")
    print("  hmax              horizontal max pan=130")
    print("  vmid              vertical neutral tilt=0")
    print("  vmin              vertical min tilt=0")
    print("  vmax              vertical max tilt=50")
    print("  pose 90 0         set synced pan/tilt")
    print("  classify h1       test one servo only: h1/h2/v1/v2")
    print("  test h1           quick one-servo test")
    print("  full h1           wider one-servo test")
    print("  angle h1 90       write one servo logical angle")
    print("  release h1        deinit one PWM")
    print("  release all       deinit all PWM")
    print("  help              show this help")


def handle_command(line):
    parts = line.strip().lower().split()
    if not parts:
        return
    cmd = parts[0]
    try:
        if cmd == "help":
            help_text()
        elif cmd == "hint":
            classify_hint()
        elif cmd == "pins":
            print(PIN_BY_SLOT)
        elif cmd == "limits":
            test_mechanical_limits()
        elif cmd == "hmid":
            set_horizontal(PAN_NEUTRAL)
        elif cmd == "hmin":
            set_horizontal(PAN_MIN)
        elif cmd == "hmax":
            set_horizontal(PAN_MAX)
        elif cmd == "vmid":
            set_vertical(TILT_NEUTRAL)
        elif cmd == "vmin":
            set_vertical(TILT_MIN)
        elif cmd == "vmax":
            set_vertical(TILT_MAX)
        elif cmd == "pose" and len(parts) == 3:
            set_pose(int(parts[1]), int(parts[2]))
        elif cmd == "classify" and len(parts) == 2:
            classify_servo(parts[1])
        elif cmd == "test" and len(parts) == 2:
            test_servo(parts[1], full=False)
        elif cmd == "full" and len(parts) == 2:
            test_servo(parts[1], full=True)
        elif cmd == "angle" and len(parts) == 3:
            write_angle(parts[1], int(parts[2]))
        elif cmd == "release" and len(parts) == 2 and parts[1] == "all":
            release_all()
        elif cmd == "release" and len(parts) == 2:
            release(parts[1])
        else:
            print("Unknown command or wrong args. Type help.")
    except Exception as exc:
        print("ERROR:", exc)


def repl():
    help_text()
    classify_hint()
    while True:
        try:
            handle_command(input("servo> "))
        except KeyboardInterrupt:
            release_all()
            print("Stopped")
            break


repl()
