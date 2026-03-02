import picoscroll
import uasyncio as asyncio

import font

WIDTH = 17
HEIGHT = 7
DIGIT_WIDTH = 3
DIGIT_HEIGHT = 5
DIGIT_SPACING = 1
MAX_DIGITS = 4
LEFT_MARGIN = WIDTH - (DIGIT_WIDTH * MAX_DIGITS + DIGIT_SPACING * (MAX_DIGITS - 1))
TOP_MARGIN = (HEIGHT - DIGIT_HEIGHT) // 2

ANIMATION_STEP_DELAY_MS = 40
WARNING_RATIO = 0.75
WATT_PER_AMP = 100


def init():
    picoscroll.init()
    clear()


def clear():
    picoscroll.clear()
    picoscroll.show()


def _set_pixel_safe(x, y, brightness):
    if 0 <= x < WIDTH and 0 <= y < HEIGHT:
        picoscroll.set_pixel(x, y, brightness)


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


def draw_text(text, brightness=255):
    text = str(text)
    if len(text) > MAX_DIGITS:
        text = text[-MAX_DIGITS:]
    text = text.rjust(MAX_DIGITS)

    picoscroll.clear()
    for idx, ch in enumerate(text):
        x = LEFT_MARGIN + idx * (DIGIT_WIDTH + DIGIT_SPACING)
        _draw_digit_at(x, ch, TOP_MARGIN, brightness)
    picoscroll.show()


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


def draw_number(number, brightness=255):
    value = _normalize_value(number)
    if value is None:
        draw_error()
        return

    draw_text(str(value), brightness)


def draw_error():
    draw_text("---")


def is_warning(power, contract_amperage):
    try:
        return int(power) >= int(contract_amperage) * WATT_PER_AMP * WARNING_RATIO
    except (TypeError, ValueError):
        return False


async def animate_digit(x, old_digit, new_digit, brightness=255):
    if old_digit == new_digit:
        draw_digit(x, new_digit, brightness)
        picoscroll.show()
        return

    for step in range(DIGIT_HEIGHT + 1):
        _clear_digit_area(x)
        _draw_digit_at(x, old_digit, TOP_MARGIN - step, brightness)
        _draw_digit_at(x, new_digit, TOP_MARGIN + DIGIT_HEIGHT - step, brightness)
        picoscroll.show()
        await asyncio.sleep_ms(ANIMATION_STEP_DELAY_MS)


async def update_display(old_value, new_value, brightness=255):
    new_value = _normalize_value(new_value)
    if new_value is None:
        draw_error()
        return

    if old_value is None:
        draw_number(new_value, brightness)
        return

    old_value = _normalize_value(old_value)
    if old_value is None:
        old_value = 0

    old_text = str(old_value).rjust(MAX_DIGITS)
    new_text = str(new_value).rjust(MAX_DIGITS)

    for step in range(DIGIT_HEIGHT + 1):
        picoscroll.clear()
        for idx in range(MAX_DIGITS):
            x = LEFT_MARGIN + idx * (DIGIT_WIDTH + DIGIT_SPACING)
            old_digit = old_text[idx]
            new_digit = new_text[idx]
            if old_digit == new_digit:
                _draw_digit_at(x, new_digit, TOP_MARGIN, brightness)
            else:
                _draw_digit_at(x, old_digit, TOP_MARGIN - step, brightness)
                _draw_digit_at(x, new_digit, TOP_MARGIN + DIGIT_HEIGHT - step, brightness)
        picoscroll.show()
        await asyncio.sleep_ms(ANIMATION_STEP_DELAY_MS)
