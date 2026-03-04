import uasyncio as asyncio

from is31fl3731 import PicoScroll
import font

_scroll = None

WIDTH = 17
HEIGHT = 7
DIGIT_WIDTH = 3
DIGIT_HEIGHT = 5
DIGIT_SPACING = 1
MAX_DIGITS = 4
LEFT_MARGIN = 1
TOP_MARGIN = (HEIGHT - DIGIT_HEIGHT) // 2

ANIMATION_STEP_DELAY_MS = 40


def init():
    global _scroll
    _scroll = PicoScroll()
    _scroll.init()
    clear()


def clear():
    _scroll.clear()
    _scroll.show()


def toggle_flip():
    _scroll.flipped = not _scroll.flipped


def _draw_warning_corners(brightness):
    for x, y in ((0, 0), (0, HEIGHT - 1), (WIDTH - 1, 0), (WIDTH - 1, HEIGHT - 1)):
        _scroll.set_pixel(x, y, brightness)


def _set_pixel_safe(x, y, brightness):
    if 0 <= x < WIDTH and 0 <= y < HEIGHT:
        _scroll.set_pixel(x, y, brightness)


def _clear_digit_area(x):
    for dx in range(DIGIT_WIDTH):
        for dy in range(HEIGHT):
            _set_pixel_safe(x + dx, dy, 0)


def _draw_digit_at(x, digit, y_offset, brightness):
    bitmap = font.FONT.get(digit, font.FONT[" "])
    for row in range(DIGIT_HEIGHT):
        row_bits = bitmap[row]
        for col in range(DIGIT_WIDTH):
            if row_bits & (1 << (DIGIT_WIDTH - 1 - col)):
                _set_pixel_safe(x + col, y_offset + row, brightness)


def draw_digit(x, digit, brightness=255):
    _clear_digit_area(x)
    _draw_digit_at(x, digit, TOP_MARGIN, brightness)


def draw_digit_partial(x, digit, offset, brightness=255):
    _clear_digit_area(x)
    _draw_digit_at(x, digit, TOP_MARGIN + offset, brightness)


def draw_text(text, brightness=255, warning_brightness=0):
    text = str(text)
    if len(text) > MAX_DIGITS:
        text = text[-MAX_DIGITS:]
    text = (" " * (MAX_DIGITS - len(text)) + text)

    _scroll.clear()
    for idx, ch in enumerate(text):
        x = LEFT_MARGIN + idx * (DIGIT_WIDTH + DIGIT_SPACING)
        _draw_digit_at(x, ch, TOP_MARGIN, brightness)
    if warning_brightness:
        _draw_warning_corners(warning_brightness)
    _scroll.show()


def _normalize_value(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None

    if value < 0:
        value = 0
    if value > 9999:
        value = 9999

    return value


def draw_number(number, brightness=255, warning_brightness=0):
    value = _normalize_value(number)
    if value is None:
        draw_error()
        return

    draw_text(str(value), brightness, warning_brightness)


def draw_error():
    draw_text("---")


def is_warning(power, threshold):
    try:
        return int(power) >= int(threshold)
    except (TypeError, ValueError):
        return False


async def animate_digit(x, old_digit, new_digit, brightness=255):
    if old_digit == new_digit:
        draw_digit(x, new_digit, brightness)
        _scroll.show()
        return

    total = DIGIT_HEIGHT + TOP_MARGIN
    for step in range(total + 1):
        _clear_digit_area(x)
        _draw_digit_at(x, old_digit, TOP_MARGIN - step, brightness)
        new_y = TOP_MARGIN + total - step
        _draw_digit_at(x, new_digit, new_y, brightness)
        _scroll.show()
        await asyncio.sleep_ms(ANIMATION_STEP_DELAY_MS)


async def update_display(old_value, new_value, brightness=255, warning_brightness=0):
    new_value = _normalize_value(new_value)
    if new_value is None:
        draw_error()
        return

    if old_value is None:
        draw_number(new_value, brightness, warning_brightness)
        return

    old_value = _normalize_value(old_value)
    if old_value is None:
        old_value = 0

    old_s = str(old_value)
    old_text = " " * (MAX_DIGITS - len(old_s)) + old_s
    new_s = str(new_value)
    new_text = " " * (MAX_DIGITS - len(new_s)) + new_s

    # 桁ごとにスクロール方向を決定（数字が増えたら上へ、減ったら下へ）
    directions = []
    for idx in range(MAX_DIGITS):
        o = old_text[idx]
        n = new_text[idx]
        if o == n:
            directions.append(1)
        else:
            ov = -1 if o == " " else int(o)
            nv = -1 if n == " " else int(n)
            directions.append(1 if nv >= ov else -1)

    total = DIGIT_HEIGHT + TOP_MARGIN
    for step in range(total + 1):
        _scroll.clear()
        for idx in range(MAX_DIGITS):
            x = LEFT_MARGIN + idx * (DIGIT_WIDTH + DIGIT_SPACING)
            old_digit = old_text[idx]
            new_digit = new_text[idx]
            d = directions[idx]
            if old_digit == new_digit:
                _draw_digit_at(x, new_digit, TOP_MARGIN, brightness)
            else:
                _draw_digit_at(x, old_digit, TOP_MARGIN - step * d, brightness)
                new_y = TOP_MARGIN + (total - step) * d
                _draw_digit_at(x, new_digit, new_y, brightness)
        if warning_brightness:
            _draw_warning_corners(warning_brightness)
        _scroll.show()
        await asyncio.sleep_ms(ANIMATION_STEP_DELAY_MS)
