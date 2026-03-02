from machine import Pin, I2C

I2C_ADDR = 0x74
WIDTH = 17
HEIGHT = 7

# レジスタ
REG_BANK = 0xFD
BANK_CONFIG = 0x0B

# Config bank レジスタ
REG_SHUTDOWN = 0x0A
REG_MODE = 0x00
REG_PICTURE_FRAME = 0x01

# Frame bank オフセット
ENABLE_OFFSET = 0x00
COLOR_OFFSET = 0x24


class PicoScroll:
    def __init__(self, sda=4, scl=5):
        self.i2c = I2C(0, sda=Pin(sda), scl=Pin(scl), freq=400_000)
        self._buf = bytearray(WIDTH * HEIGHT)
        self.flipped = False

    def init(self):
        self._bank(BANK_CONFIG)
        self._write_reg(REG_SHUTDOWN, 0)

        for frame in range(8):
            self._bank(frame)
            for i in range(18):
                self._write_reg(ENABLE_OFFSET + i, 0xFF)
            for i in range(144):
                self._write_reg(COLOR_OFFSET + i, 0)

        self._bank(BANK_CONFIG)
        self._write_reg(REG_MODE, 0x00)
        self._write_reg(REG_PICTURE_FRAME, 0x00)
        self._write_reg(REG_SHUTDOWN, 0x01)

    def set_pixel(self, x, y, brightness):
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            self._buf[y * WIDTH + x] = brightness

    def clear(self):
        for i in range(len(self._buf)):
            self._buf[i] = 0

    def show(self):
        self._bank(0)
        hw = bytearray(144)
        for y in range(HEIGHT):
            for x in range(WIDTH):
                offset = self._pixel_addr(x, y)
                if 0 <= offset < 144:
                    hw[offset] = self._buf[y * WIDTH + x]
        self.i2c.writeto_mem(I2C_ADDR, COLOR_OFFSET, hw)

    def _pixel_addr(self, x, y):
        """Pimoroniのマッピングアルゴリズム（C実装から移植）"""
        if self.flipped:
            x = (WIDTH - 1) - x
            y = (HEIGHT - 1) - y
        x = (WIDTH - 1) - x
        if x > 8:
            x = x - 8
            y = (HEIGHT - 1) - (y + 8)
        else:
            x = 8 - x
        return x * (WIDTH - 1) + y

    def _bank(self, bank):
        self._write_reg(REG_BANK, bank)

    def _write_reg(self, reg, value):
        self.i2c.writeto_mem(I2C_ADDR, reg, bytes([value]))
