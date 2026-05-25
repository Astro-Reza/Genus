import re

replacements = [
    (r'f"Target: Az {target\[\'azimuth\'\]:\.1f} El {target\[\'elevation\'\]:\.1f}"',
     r'"Target: Az {:.1f} El {:.1f}".format(target[\'azimuth\'], target[\'elevation\'])'),
    (r'f"Seeking\.\.\. Err Az:{az_err:\.1f} El:{el_err:\.1f}"',
     r'"Seeking... Err Az:{:.1f} El:{:.1f}".format(az_err, el_err)'),
    (r'f"Step 1: Sweep Right 10 -> {tgt_az:\.1f}"',
     r'"Step 1: Sweep Right 10 -> {:.1f}".format(tgt_az)'),
    (r'f"Step 2: Sweep Left 20 -> {tgt_az:\.1f}"',
     r'"Step 2: Sweep Left 20 -> {:.1f}".format(tgt_az)'),
    (r'f"Step 3: Up 5 -> {tgt_el:\.1f}"',
     r'"Step 3: Up 5 -> {:.1f}".format(tgt_el)'),
    (r'f"Step 4: Sweep Right 20 -> {tgt_az:\.1f}"',
     r'"Step 4: Sweep Right 20 -> {:.1f}".format(tgt_az)'),
    (r'f"Step 5: Down 10 -> {tgt_el:\.1f}"',
     r'"Step 5: Down 10 -> {:.1f}".format(tgt_el)'),
    (r'f"Step 6: Wipe Left 20 -> {tgt_az:\.1f}"',
     r'"Step 6: Wipe Left 20 -> {:.1f}".format(tgt_az)'),
    (r'f"\[GPS\] Starting on {self\.port}\.\.\."',
     r'"[GPS] Starting on {}...".format(self.port)'),
    (r'f"\[GPS\] Connected"',
     r'"[GPS] Connected"'),
    (r'f"\[AHRS\] Starting on {self\.port}\.\.\."',
     r'"[AHRS] Starting on {}...".format(self.port)'),
    (r'f"\[AHRS\] Connected"',
     r'"[AHRS] Connected"'),
    (r'f"\[Control/SPI\] Starting on /dev/spidev{self\.spi_bus}\.{self\.spi_device}\.\.\."',
     r'"[Control/SPI] Starting on /dev/spidev{}.{}...".format(self.spi_bus, self.spi_device)'),
    (r'f"\[Control/SPI\] Connected"',
     r'"[Control/SPI] Connected"'),
    (r'f"\[Control/SPI\] Write Error: {e}"',
     r'"[Control/SPI] Write Error: {}".format(e)'),
    (r'f"\[Control/SPI\] ERROR: /dev/spidev{self\.spi_bus}\.{self\.spi_device} not found\. Enable SPI in armbian-config\."',
     r'"[Control/SPI] ERROR: /dev/spidev{}.{} not found. Enable SPI in armbian-config.".format(self.spi_bus, self.spi_device)'),
    (r'f"\[Control/SPI\] Error: {e}"',
     r'"[Control/SPI] Error: {}".format(e)'),
    (r'f"\[AMIP\] {msg}"',
     r'"[AMIP] {}".format(msg)')
]

with open("backend_orangepi.py", "r", encoding="utf-8") as f:
    content = f.read()

for pattern, repl in replacements:
    content = re.sub(pattern, repl, content)

with open("backend_orangepi.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Done")
