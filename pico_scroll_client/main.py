import network
import uasyncio as asyncio
import ujson
from machine import Pin

from uwebsockets.client import connect

import config
import display
import mdns_resolve

BRIGHTNESS_LEVELS = [8, 16, 32, 64, 128, 255]

BTN_A = Pin(12, Pin.IN, Pin.PULL_UP)
BTN_B = Pin(13, Pin.IN, Pin.PULL_UP)
BTN_X = Pin(14, Pin.IN, Pin.PULL_UP)
BTN_Y = Pin(15, Pin.IN, Pin.PULL_UP)


async def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if not wlan.isconnected():
        wlan.connect(config.SSID, config.PASSWORD)

    for _ in range(60):
        if wlan.isconnected():
            return wlan
        await asyncio.sleep_ms(500)

    raise OSError("Wi-Fi connection failed")


async def button_loop(state, display_lock):
    while True:
        changed = False
        flipped = state.get("flipped", False)
        btn_up = BTN_A if flipped else BTN_B
        btn_down = BTN_B if flipped else BTN_A
        if btn_up.value() == 0:
            if state["bright_idx"] < len(BRIGHTNESS_LEVELS) - 1:
                state["bright_idx"] += 1
                changed = True
        if btn_down.value() == 0:
            if state["bright_idx"] > 0:
                state["bright_idx"] -= 1
                changed = True
        if changed:
            state["brightness"] = BRIGHTNESS_LEVELS[state["bright_idx"]]
            if state["current"] is not None:
                async with display_lock:
                    display.draw_number(state["current"], state["brightness"], 255 if state["warning"] else 0)
            while BTN_A.value() == 0 or BTN_B.value() == 0:
                await asyncio.sleep_ms(50)
        if BTN_X.value() == 0 or BTN_Y.value() == 0:
            state["flipped"] = not state.get("flipped", False)
            display.toggle_flip()
            if state["current"] is not None:
                async with display_lock:
                    display.draw_number(state["current"], state["brightness"], 255 if state["warning"] else 0)
            else:
                async with display_lock:
                    display.draw_error()
            while BTN_X.value() == 0 or BTN_Y.value() == 0:
                await asyncio.sleep_ms(50)
        await asyncio.sleep_ms(100)


async def blink_loop(state, display_lock):
    while True:
        if state["warning"] and state["current"] is not None:
            state["blink_on"] = not state["blink_on"]
            brightness = state["brightness"] if state["blink_on"] else 0
            async with display_lock:
                display.draw_number(state["current"], brightness, 255)
            await asyncio.sleep_ms(config.BLINK_INTERVAL_MS)
        else:
            state["blink_on"] = True
            await asyncio.sleep_ms(200)


async def keepalive_loop(state):
    while True:
        if state.get("ws"):
            try:
                await state["ws"].send("ping")
            except Exception:
                pass
        await asyncio.sleep(10)


async def websocket_loop(state, display_lock):
    while True:
        try:
            ws = await connect(state["server_url"])
            state["ws"] = ws

            while True:
                message = await ws.recv()
                data = ujson.loads(message)
                power = data.get("instant_power")
                if power is None:
                    continue

                try:
                    power = int(power)
                except (TypeError, ValueError):
                    continue

                old_value = state["current"]
                state["current"] = power
                state["warning"] = display.is_warning(power, config.WARNING_THRESHOLD)

                async with display_lock:
                    await display.update_display(old_value, power, state["brightness"], 255 if state["warning"] else 0)
        except Exception:
            state["ws"] = None
            state["current"] = None
            state["warning"] = False

            async with display_lock:
                display.draw_error()

            await asyncio.sleep(config.RECONNECT_INTERVAL)


async def main():
    display.init()
    display.draw_error()

    await connect_wifi()

    server_ip = mdns_resolve.resolve(config.SERVER_HOST)
    if server_ip is None:
        server_ip = mdns_resolve.resolve(config.SERVER_HOST)
    server_url = "ws://{}:{}{}".format(
        server_ip or config.SERVER_HOST,
        config.SERVER_PORT,
        config.SERVER_PATH,
    )

    bright_idx = BRIGHTNESS_LEVELS.index(config.BRIGHTNESS) if config.BRIGHTNESS in BRIGHTNESS_LEVELS else len(BRIGHTNESS_LEVELS) - 1
    state = {
        "current": None,
        "warning": False,
        "blink_on": True,
        "ws": None,
        "server_url": server_url,
        "brightness": BRIGHTNESS_LEVELS[bright_idx],
        "bright_idx": bright_idx,
    }
    display_lock = asyncio.Lock()

    asyncio.create_task(button_loop(state, display_lock))
    asyncio.create_task(blink_loop(state, display_lock))
    asyncio.create_task(keepalive_loop(state))

    await websocket_loop(state, display_lock)


asyncio.run(main())
