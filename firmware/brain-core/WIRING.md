# Sandy Brain — wiring map

Board: **ESP32-S3-DevKitC-1 / N16R8**. Every GPIO below comes from
`main/include/config.h` — that file is the source of truth, this is the
human-readable copy for when the robot gets taken apart.

Only the parts whose `ENABLE_*` flag is `1` are actually wired right now.

## Currently enabled

| Part | Pin on the part | GPIO | Power |
|---|---|---|---|
| ST7789 display | MOSI / SDA | 40 | 3V3 |
| | SCLK / SCL | 41 | |
| | CS | 39 | |
| | DC | 42 | |
| | RST | 2 | |
| | BLK (backlight) | 1 | |
| INMP441 mic ×2 | SCK | 5 | 3V3 |
| | WS / LRCL | 6 | |
| | SD (data out) | 7 | |
| | L/R — **left mic** | tie to GND | |
| | L/R — **right mic** | tie to 3V3 | |
| MAX98357A amp | BCLK | 9 | **5V** |
| | LRC / WS | 10 | |
| | DIN | 11 | |
| | SD (shutdown) | leave floating / pull to VIN | |
| SG90 servo (neck) | signal | 16 | **5V** |
| Buzzer | signal | 17 | 3V3 |
| HC-SR04 distance | TRIG | 15 | **5V** |
| | ECHO | 13 | see warning |
| WS2812 RGB LED | — | 48 | on-board, nothing to wire |

Both INMP441s share SCK/WS/SD on one I2S bus. The **only** difference between
them is the L/R pin: grounded = left slot, tied to 3V3 = right slot. Get this
wrong and both mics land in the same slot — the other slot reads a constant
noise floor, and sound-direction stops working.

> **HC-SR04 ECHO warning:** the sensor is a 5V part and its ECHO line drives 5V
> into a 3.3V-only GPIO. Put a divider on it (1kΩ from ECHO to GPIO13, 2kΩ from
> GPIO13 to GND) or use a 3.3V-tolerant module.

## Disabled — nothing wired

`ENABLE_MOTORS`, `ENABLE_TOUCH`, `ENABLE_MIC` (MAX9814 clap mic), `ENABLE_EARS`,
`ENABLE_OTA`, `ENABLE_SPK_TEST` are all `0`. Their pins are reserved in
`config.h` but no part hangs off them:

| Part | GPIO |
|---|---|
| L298N motor driver | 18, 8, 12, 47 |
| MAX9814 clap mic | 4 (ADC1 CH3) |
| TTP223 touch | 14 |

## Do not use

| GPIO | Why |
|---|---|
| 33–37 | Octal PSRAM on the N16R8 |
| 0, 3, 45, 46 | Strapping pins |
| 43, 44 | UART0 console (TX/RX) |
| 19, 20 | Native USB D− / D+ |

## Power

Feed the board through the **UART** USB-C port with a **USB-A to USB-C** cable.
The board has no USB-C CC resistors, so a C-to-C cable from a laptop or a C
charger negotiates nothing and delivers no usable current — it measures a few
hundred millivolts and nothing boots.

The servo and the amp are the two current spikes on the 5V rail. If boots get
flaky, a 1000µF electrolytic across 5V/GND (stripe leg to GND) absorbs them.
