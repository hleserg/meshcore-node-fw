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
python scripts/build.py v4       # -> dist/v4-factory.bin + dist/manifest.json
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

| env | плата | база апстрима |
|---|---|---|
| `t114_companion_serial` | Heltec T114 (nRF52840) | `[Heltec_t114]` |
| `v4_companion_serial` | Heltec WiFi LoRa 32 V4 (ESP32-S3) | `[heltec_v4_oled]` |

Собрать напрямую, без обёртки:

```bash
cd external/MeshCore
pio run -e t114_companion_serial
pio run -e v4_companion_serial
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

**WiFi и BLE выключены тем, что соответствующие define'ы не заданы.** Порядок
выбора интерфейса в `examples/companion_radio/main.cpp` — препроцессорный:

```
#ifdef WIFI_SSID          -> SerialWifiInterface
#elif defined(BLE_PIN_CODE) -> SerialBLEInterface
#elif defined(SERIAL_RX)    -> ArduinoSerialInterface на аппаратном UART   <- мы здесь
#else                       -> ArduinoSerialInterface на Serial (USB-CDC)
```

Дополнительно `helpers/nrf52/SerialBLEInterface.cpp` и `helpers/esp32/*.cpp`
не входят в `build_src_filter`, поэтому BLE/WiFi-код не линкуется вообще.

### T114 (nRF52840)

```
-D SERIAL_RX=9
-D SERIAL_TX=10
-D CONFIG_NFCT_PINS_AS_GPIOS
-D DISPLAY_CLASS=NullDisplayDriver
board_build.ldscript = boards/nrf52840_s140_v6_extrafs.ld
board_upload.maximum_size = 712704
```

### V4 (ESP32-S3)

```
-D SERIAL_RX=47
-D SERIAL_TX=48
-D COMPANION_SERIAL_NUM=2
-D DISPLAY_CLASS=SSD1306Display
```

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

## Распиновка UART и почему именно такие пины

3.3 В, 115200 8N1. RX платы идёт на TX адаптера и наоборот.

### T114 — `Serial2` (NRF_UARTE1), P0.09 / P0.10

Хедер P1, силк `GPIO9` / `GPIO10`.

Это маркировка Heltec, а не номер Arduino-пина, поэтому идентификаторы взяты из
дерева платы, а не подставлены вслепую:

- `variants/heltec_t114/variant.h` объявляет
  `PIN_SERIAL2_RX (9)` и `PIN_SERIAL2_TX (10)`;
- `variants/heltec_t114/variant.cpp` задаёт `g_ADigitalPinMap[]`, который для
  индексов ≥ 2 является тождественным: Arduino-пин `N` → порт-пин `P0.N`.

Значит Arduino-пины 9 и 10 — это ровно `P0.09` и `P0.10`, то есть те самые
площадки на хедере.

**Почему `Serial2`, а не `Serial1`.** `Serial1` (NRF_UARTE0) на этой плате занят
GPS: `variants/heltec_t114/target.cpp` создаёт на нём `MicroNMEALocationProvider`,
а `EnvironmentSensorManager` делает `Serial1.setPins(PIN_GPS_TX, PIN_GPS_RX)`.
Перевесить `Serial1` на 9/10 значило бы отобрать порт у GPS-драйвера, который тут
же вернул бы его обратно. У nRF52840 есть второй UARTE, `Serial2` объявляется
ядром при наличии `PIN_SERIAL2_RX`/`TX` — его и используем. Переопределяется через
`-D COMPANION_SERIAL=SerialX`.

**NFC.** `P0.09`/`P0.10` после сброса принадлежат NFC-антенне и как GPIO не
работают. Освобождает их `-D CONFIG_NFCT_PINS_AS_GPIOS`: флаг доходит до
`cores/nRF5/nordic/nrfx/mdk/system_nrf52840.c` в составе фреймворка, тот при
первом старте однократно переписывает `UICR->NFCPINS` и перезагружает чип.

### V4 — UART2, GPIO47 / GPIO48

Хедер J3. Здесь `Serial1` тоже занят GPS (тот же `EnvironmentSensorManager`),
поэтому companion переехал на UART2 через `-D COMPANION_SERIAL_NUM=2`.
Пины назначаются в рантайме через `companion_serial.setPins(SERIAL_RX, SERIAL_TX)`,
так что дефолтная распиновка UART2 роли не играет.

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

## Сборка сайта (полевой хаб)

```bash
pip install markdown pymdown-extensions
python scripts/build_site.py           # собрать docs/ и проверить
python scripts/build_site.py --verify  # только проверить уже собранное
python scripts/build_site.py --offline # не ходить в сеть за meshlog.py
```

### Логгер берётся из другого репозитория

`meshlog.py` живёт в [flipperMeshCoreConfig](https://github.com/hleserg/flipperMeshCoreConfig)
и продолжает меняться, поэтому он **скачивается на этапе сборки**, а не лежит копией
здесь — копия молча устарела бы. Если файл недоступен, билд падает: лучше красный
CI, чем хаб с мёртвой кнопкой. Локально можно собрать без сети через `--offline`,
тогда берётся `meshlog.py` из корня репозитория, если он там есть.

На карточке логгера показан короткий sha содержимого — по нему видно, какая версия
сейчас отдаётся.

### Гайд, которого ещё нет

Если исходника нет в репозитории, страница не генерируется вовсе, а карточка на хабе
показывается неактивной. Битых ссылок не появляется, и проверка это отдельно
контролирует.

`docs/` почти целиком генерируется и в git не коммитится. Руками там живёт только
`flash.html` — страница-флешер.

| Файл в `docs/` | Откуда берётся |
|---|---|
| `index.html` | `scripts/hub_template.html` + карточки |
| `guide-sergey.html` | `MESHCORE_TESTING.md` через `scripts/render_guide.py` |
| `MESHCORE_*.md` | копия исходника рядом с отрендеренной страницей |
| `guide-mark.html` | `MESHCORE_MARK.md` через `scripts/render_guide.py` |
| `meshlog.py` | скачивается из [flipperMeshCoreConfig](https://github.com/hleserg/flipperMeshCoreConfig) на билде, байт в байт |
| `app.webmanifest`, `icon.svg`, `sw.js` | генерируются `build_site.py` |
| `flash.html` | лежит в репозитории |
| `*.uf2`, `*.bin`, `manifest.json` | кладёт CI из артефактов сборки |

Правка `.md` в корне → push → страница пересобралась. Ничего вручную конвертировать
не надо.

### Что делает рендер гайдов

- Конвертация **фактическая**: ничего не переписывается и не сокращается.
  `build_site.py` сверяет число заголовков, таблиц и блоков кода в исходнике и в
  результате и падает, если что-то потерялось.
- **Copy-кнопка генерируется в HTML на этапе сборки**, а не навешивается скриптом —
  поэтому «у каждого блока кода есть кнопка» проверяется статически. Кнопка стоит
  в обычном потоке **над** блоком: наложенная поверх кода, она прятала хвост длинных
  команд — ровно тех, которые и хочется скопировать.
- Первый `# Заголовок` документа становится заголовком страницы, а `#`-заголовки
  ниже — это части инструкции («ЧАСТЬ 1», «ГРАБЛИ»), поэтому TOC собирается из
  `h1`/`h2`/`h3`. Оглавление только по `h2`/`h3` потеряло бы весь верхний уровень.
- Блок-цитаты с эмодзи-маркером становятся callout-карточками:
  ⚠️ warning, 🚨 danger, 💡 tip, ✅ success. Любой другой эмодзи в начале цитаты
  тоже даёт карточку — нейтральную «заметку», чтобы незнакомый маркер не превращался
  молча в серую цитату.

  Тонкость: markdown склеивает идущие подряд блок-цитаты в одну. Наивный рендер взял
  бы маркер только у первой, и красное «плата сгорит» превратилось бы в жёлтую
  заметку. Поэтому `convert_callouts()` режет по каждому абзацу, который начинается
  с маркера.
- Авто-TOC с якорями (кириллица в slug сохраняется), липкая навигация, «наверх».
- Весь CSS и JS **инлайн** — гайд обязан открываться без сети.

### Оффлайн и PWA

`sw.js` кэширует хаб, гайды, `meshlog.py`, манифест и иконку — **только те файлы,
которые реально собрались**: `cache.addAll()` атомарен, и один 404 отменил бы всю
установку, тихо выключив оффлайн.

Документы отдаются по стратегии **network-first**: если сеть есть, всегда показывается
свежая версия, а кэш подхватывается только когда сети нет. Cache-first показывал бы
старую редакцию инструкции человеку, который онлайн — а устаревшая полевая инструкция
это ровно тот провал, ради которого всё это и делается. Статика (иконка, манифест,
логгер) идёт cache-first.

 Флешер, прошивки и
`manifest.json` в кэш **не** попадают: им нужны Web Serial и CDN, и притворяться, что
они работают оффлайн, — врать в поле. `build_site.py --verify` это проверяет.

Имя кэша — sha256 от содержимого кэшируемых файлов, поэтому меняется ровно тогда,
когда меняется контент.

### Фикстура

`tests/fixture_guide.md` на сайт не попадает. Это файл, на котором гоняется рендер:
в нём есть все конструкции из боевых инструкций — таблицы, чек-листы, вложенные
списки, все четыре типа callout подряд, блоки кода с языком и без.

```bash
python scripts/render_guide.py tests/fixture_guide.md /tmp/fixture.html --title Фикстура
```
