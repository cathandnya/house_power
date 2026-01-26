import network
import uasyncio as asyncio
import ujson

from uwebsockets.client import connect

import config
import display


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


async def blink_loop(state, display_lock):
    while True:
        if state["warning"] and state["current"] is not None:
            state["blink_on"] = not state["blink_on"]
            brightness = config.BRIGHTNESS if state["blink_on"] else 0
            async with display_lock:
                display.draw_number(state["current"], brightness)
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
            ws = await connect(config.SERVER_URL)
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
                state["warning"] = display.is_warning(power, config.CONTRACT_AMPERAGE)

                async with display_lock:
                    await display.update_display(old_value, power, config.BRIGHTNESS)
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

    state = {
        "current": None,
        "warning": False,
        "blink_on": True,
        "ws": None,
    }
    display_lock = asyncio.Lock()

    asyncio.create_task(blink_loop(state, display_lock))
    asyncio.create_task(keepalive_loop(state))

    await websocket_loop(state, display_lock)


asyncio.run(main())
