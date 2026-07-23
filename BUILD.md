# BUILD

Сборка обеих прошивок локально. В облаке ровно то же самое делает
`.github/workflows/build.yml`, вызывая те же скрипты.

## Что нужно

- Python 3.9+
- `pip install platformio`
- git с сабмодулями

```bash
git clone --recurse-submodules https://github.com/hleserg/meshcore-node-fw.git
cd meshcore-node-fw
# если клонировали без --recurse-submodules:
git submodule update --init --recursive
```

Первая сборка тянет тулчейны (nRF52 ~200 МБ, ESP32-S3 ~500 МБ) — это долго,
дальше всё из кэша.

## Собрать

```bash
python scripts/build.py t114     # -> dist/t114-companion.uf2
python scripts/build.py v4       # -> dist/v4-companion-factory.bin + manifest.json
python scripts/build.py t114rep  # -> dist/t114-repeater.uf2
python scripts/build.py all
```

Версия прошивки берётся из `$FIRMWARE_VERSION` (по умолчанию `dev`) и к ней
приписывается короткий SHA сабмодуля. Она попадает в ответ self-info, так что по
ней видно, что именно залито в плату:

```bash
FIRMWARE_VERSION=v0.1.0 python scripts/build.py all
```

`build.py` сам вызывает `prepare.py`, который:

1. накатывает всё из `patches/` на `external/MeshCore` (идемпотентно — уже
   применённые патчи пропускаются);
2. копирует `pio/meshcore-node-fw.ini` в `external/MeshCore/platformio.local.ini`.

Корневой `platformio.ini` MeshCore уже содержит `extra_configs = ... platformio.local.ini`,
поэтому наши окружения подхватываются без правки апстримных файлов. Файл в
`.gitignore` апстрима, так что дерево сабмодуля остаётся чистым (кроме патча).

Обновить MeshCore на новую версию:

```bash
cd external/MeshCore && git fetch --tags && git checkout <новый-тег> && cd ../..
python scripts/prepare.py --reset      # скажет, если патч перестал накатываться
```

## Окружения PlatformIO

Определены в [`pio/meshcore-node-fw.ini`](pio/meshcore-node-fw.ini).

| env | плата | что собирает |
|---|---|---|
| `t114_companion` | Heltec T114 (nRF52840) | companion + автодетект UART/BLE |
| `v4_companion` | Heltec WiFi LoRa 32 V4 (ESP32-S3) | companion + автодетект UART/WiFi-AP |
| `t114_repeater` | Heltec T114 (nRF52840) | стоковый repeater, без патчей |

Собрать напрямую, без обёртки:

```bash
cd external/MeshCore
pio run -e t114_companion
pio run -e v4_companion
pio run -e t114_repeater
```

Обратите внимание: голый `pio run` **не** создаёт ни `.uf2`, ни объединённый
`.bin` — апстрим вешает их на отдельные таргеты (`create_uf2`, `mergebin`).
`scripts/build.py` делает этот шаг за вас.

## Ключевые флаги

Общее для обоих окружений:

```
-D SERIAL_RX=<пин>      ; включает ветку hardware-serial в companion
-D SERIAL_TX=<пин>
-D MAX_CONTACTS=350
-D MAX_GROUP_CHANNELS=40
-D OFFLINE_QUEUE_SIZE=256
```

**В стоке транспорт выбирается препроцессором**, один на сборку:

```
#ifdef WIFI_SSID            -> SerialWifiInterface
#elif defined(BLE_PIN_CODE) -> SerialBLEInterface
#elif defined(SERIAL_RX)    -> ArduinoSerialInterface на аппаратном UART
#else                       -> ArduinoSerialInterface на Serial (USB-CDC)
```

**У нас компилируются обе половины**, и выбор делается в рантайме. Проверено по
символам в собранных образах:

| Образ | UART | Беспроводной |
|---|---|---|
| `t114_companion` | `ArduinoSerialInterface` ✓ | `SerialBLEInterface` ✓ |
| `v4_companion` | `ArduinoSerialInterface` ✓ | `SerialWifiInterface` + `softAP` ✓ |

### T114 companion (nRF52840)

```
-D TRANSPORT_DETECT_PIN=13   ; P0.13, хедер P1
-D SERIAL_RX=9               ; P0.09
-D SERIAL_TX=10              ; P0.10
-D CONFIG_NFCT_PINS_AS_GPIOS ; освободить NFC-пины
-D BLE_PIN_CODE=123456       ; BLE — беспроводная половина автодетекта
-D DISPLAY_CLASS=NullDisplayDriver
board_build.ldscript = boards/nrf52840_s140_v6_extrafs.ld
board_upload.maximum_size = 712704
```

### V4 companion (ESP32-S3)

```
-D TRANSPORT_DETECT_PIN=33
-D SERIAL_RX=47
-D SERIAL_TX=48
-D COMPANION_SERIAL_NUM=2    ; UART1 занят GPS
-D TCP_PORT=5000
-D DISPLAY_CLASS=SSD1306Display
```

### T114 repeater

Стоковый `simple_repeater`, никаких наших флагов. Патч на него не действует —
он трогает только `examples/companion_radio/`.

## Патч

Единственный файл: [`patches/0001-companion-radio-hardware-uart.patch`](patches/0001-companion-radio-hardware-uart.patch),
трогает только `examples/companion_radio/main.cpp`.

**Зачем он нужен.** У апстрима ветка hardware-serial реализована для ESP32 и
RP2040, но для nRF52 её нет: там либо BLE, либо `serial_interface.begin(Serial)`,
то есть USB-CDC. Патч добавляет nRF52-ветку и заодно делает выбор UART-периферии
на ESP32 настраиваемым.

```diff
 #elif defined(NRF52_PLATFORM)
   #ifdef BLE_PIN_CODE
     SerialBLEInterface serial_interface;
+  #elif defined(SERIAL_RX)
+    ArduinoSerialInterface serial_interface;
+    #ifndef COMPANION_SERIAL
+      #define COMPANION_SERIAL Serial2
+    #endif
   #else
     ArduinoSerialInterface serial_interface;
   #endif
```

```diff
 #ifdef BLE_PIN_CODE
   serial_interface.begin(BLE_NAME_PREFIX, ...);
+#elif defined(NRF52_PLATFORM) && defined(SERIAL_RX)
+  COMPANION_SERIAL.setPins(SERIAL_RX, SERIAL_TX);
+  COMPANION_SERIAL.begin(115200);
+  serial_interface.begin(COMPANION_SERIAL);
 #else
   serial_interface.begin(Serial);
 #endif
```

Для ESP32 `HardwareSerial companion_serial(1)` заменён на
`HardwareSerial companion_serial(COMPANION_SERIAL_NUM)` с дефолтом `1`
(поведение апстрима не меняется).

## Распиновка — ЗАФИКСИРОВАНА

Паяется ровно по этим номерам. Всё на одном хедере на каждой плате.

**T114 (nRF52840) — хедер P1**

| Сигнал | Позиция | GPIO | nRF |
|---|---|---|---|
| GND | P1 пин 4 | — | — |
| **DETECT** | P1 пин 8 | `GPIO33` | P1.01 |
| RX (плата ← TX адаптера) | P1 пин 12 | `GPIO9` | P0.09, UART1_RX |
| TX (плата → RX адаптера) | P1 пин 13 | `GPIO10` | P0.10, UART1_TX |

**V4 (ESP32-S3) — хедер J2**

| Сигнал | Позиция | GPIO |
|---|---|---|
| GND | J2 пин 1 | — |
| **DETECT** | J2 пин 12 | `GPIO33` |
| RX (плата ← TX адаптера) | J2 пин 13 | `GPIO47` |
| TX (плата → RX адаптера) | J2 пин 14 | `GPIO48` |

3.3 В, UART 115200 8N1.

Источники: [датасheet T114](https://resource.heltec.cn/download/Mesh_Node_T114/Datasheet.pdf)
§2.2 и [датасheet V4](https://resource.heltec.cn/download/WiFi_LoRa_32_V4/datasheet/WiFi_LoRa_32_V4.2.0.pdf)
§2.2.1 (J2). Сверено с `variants/heltec_t114/variant.h`: `g_ADigitalPinMap` — тождественное
отображение, поэтому Arduino 33 → P1.01, Arduino 9/10 → P0.09/P0.10, ровно как в датасheet.
Heltec-овский «UART1» — это `NRF_UARTE1`, который ядро Adafruit отдаёт как `Serial2`
(`Serial1` = `NRF_UARTE0` занят GPS).

На V4 сознательно не используются: `GPIO26` (J2 пин 15) — SPICS1 на линии флеша,
`GPIO19`/`GPIO20` — нативный USB D−/D+, `GPIO0` — strapping/PRG.


## NFC-пины — обязательная проверка

`P0.09`/`P0.10` на nRF52840 после сброса сконфигурированы как выводы NFC-антенны, а не
как GPIO. Без флага UART на них не заработает — **молча, без единой ошибки при сборке**.

Что найдено в дереве:

| Где искал | Есть `CONFIG_NFCT_PINS_AS_GPIOS`? |
|---|---|
| `variants/heltec_t114/variant.h` | нет |
| `boards/heltec_t114.json` | нет |
| апстримный `platformio.ini` | нет |
| фреймворк `framework-arduinoadafruitnrf52` | только *потребитель* — `cores/nRF5/nordic/nrfx/mdk/system_nrf52840.c`, определения по умолчанию нет |

**Вывод: флаг нигде не выставлен, его обязаны добавить мы.** Он стоит в
`[env:t114_companion]`. Проверено, что он реально доходит до нужного файла:

```bash
pio run -e t114_companion -v | grep system_nrf52840
# в команде компиляции присутствует -DCONFIG_NFCT_PINS_AS_GPIOS
```

При первом старте `system_nrf52840.c` однократно перепишет `UICR->NFCPINS` и перезагрузит
чип — плата на пару секунд «задумается», это нормально и происходит один раз.

## Проверка self-info по UART

```bash
pip install meshcore
python scripts/selftest.py COM5          # Windows
python scripts/selftest.py /dev/ttyUSB0  # Linux / macOS
python scripts/selftest.py COM5 -d       # + сырой дамп кадров
```

Скрипт открывает порт на 115200, поднимает companion-сессию и печатает self-info.
Обмен идёт кадрами: запрос от хоста начинается с `<`, ответ ноды — с `>`, дальше
двухбайтовая длина (LSB, MSB) и тело (см. `src/helpers/ArduinoSerialInterface.cpp`).
Флаг `-d` показывает эти кадры целиком.

Если ответа нет:

- перепутаны RX/TX — поменяйте местами;
- нет общей земли;
- для T114: первый старт после прошивки уходит на перезапись UICR и ребут —
  дайте плате пару секунд;
- убедитесь, что залита именно эта прошивка, а не апстримная `..._companion_radio_usb`
  (в ней протокол уходит в USB-CDC).

Радио-параметры в ответе — это runtime-настройки ноды. Менять их можно тем же
companion-протоколом; в прошивку они не зашиты.

## Артефакты

| Файл | Что это |
|---|---|
| `dist/t114-companion.uf2` | Образ для UF2-бутлоадера, старт `0x26000` (после SoftDevice S140 v6) |
| `dist/v4-factory.bin` | bootloader + partitions + boot_app0 + приложение одним куском, пишется с offset `0` |
| `dist/manifest.json` | Манифест ESP Web Tools для страницы-флешера |

`v4-factory.bin` собирается апстримным `merge-bin.py` (`pio run -t mergebin`) —
именно он нужен ESP Web Tools, потому что тот пишет один файл по нулевому смещению.

## CI

`.github/workflows/build.yml`:

- **триггеры** — push тега `v*`, push в `main`, ручной `workflow_dispatch`;
- **матрица** — два независимых job'а (nRF52 и ESP32), кэш `~/.platformio`;
- на теге — job `release`: создаёт Release и прикладывает `t114-companion.uf2`,
  `v4-factory.bin`, `manifest.json`;
- всегда — job `pages`: кладёт свежие бинари рядом с `docs/index.html` и
  деплоит GitHub Pages, чтобы страница отдавала актуальные образы.

## Патч автодетекта

Единственный файл: [`patches/0001-companion-radio-transport-autodetect.patch`](patches/0001-companion-radio-transport-autodetect.patch).
Трогает `examples/companion_radio/main.cpp`, `AbstractUITask.h` и `ui-new/UITask.cpp`.

**Как устроено.** При `-D TRANSPORT_DETECT_PIN=n` компилируются оба транспорта, а
`serial_interface` становится макросом над указателем:

```cpp
#if defined(TRANSPORT_DETECT_PIN)
  static bool transport_is_wired = false;
  #define serial_interface (*serial_interface_ptr)
#endif
```

Благодаря этому весь остальной файл — а он ссылается на `serial_interface` в
нескольких местах — остаётся ровно таким, как его написал апстрим, и диффа получается
мало. В `setup()`, до всего остального:

```cpp
pinMode(TRANSPORT_DETECT_PIN, INPUT_PULLDOWN);
delayMicroseconds(200);
transport_is_wired = (digitalRead(TRANSPORT_DETECT_PIN) == HIGH);
serial_interface_ptr = transport_is_wired ? &serial_wired : &serial_wireless;
```

Ещё два места, которые иначе тихо сломались бы:

- `UITask` конструируется глобально, до того как решение принято, поэтому в
  `AbstractUITask` добавлен `setSerialInterface()` — иначе кнопки экрана дёргали бы не
  тот интерфейс.
- `UITask` показывает `WiFi.localIP()`, а в режиме точки доступа это `0.0.0.0`. Адрес,
  на который смотрит логгер, — `WiFi.softAPIP()`. Патч показывает именно его.

**WiFi у нас — точка доступа, а не станция.** В стоке `WIFI_SSID`-сборка делает
`WiFi.begin(SSID, PWD)`, то есть подключается к чужой сети и адреса `192.168.4.1` дать
не может; `softAP` в MeshCore есть только в OTA-хелпере и к companion отношения не
имеет. На фесте роутера нет, подключаться некуда, а полевой процесс завязан на
`192.168.4.1:5000`. Поэтому здесь поднимается `WiFi.softAP()` с SSID вида
`MeshCore-<имя-ноды>`. Это осознанное отступление от стока.

## Как проверить, что всё сошлось

**Стартовый лог.** Воткни USB, открой порт **платы** терминалом на 115200, нажми `RST`:

```
=== MeshCore companion :: transport auto-detect ===
firmware  : v0.2.0-… (…)
detect    : arduino 13  -> P0.13
detect    : LOW (nothing wired)
transport : BLE
note      : pull the detect pin HIGH and reboot to use the wire
==================================================
```

С подключённым проводом строки станут `HIGH (something wired)` и `HARDWARE UART`, плюс
появятся назначенные пины UART. На nRF52 печатается **порт-пин**, разрешённый через
`g_ADigitalPinMap`, а не тот номер, что передали в сборку — иначе это была бы не
проверка, а повтор предположения.

**Self-info по проводу:**

```bash
pip install meshcore
python scripts/selftest.py COM5          # порт АДАПТЕРА, не платы
```
