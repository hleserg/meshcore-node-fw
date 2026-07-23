# meshcore-node-fw

Кастомные companion-прошивки [MeshCore](https://github.com/meshcore-dev/MeshCore)
для двух плат Heltec, у которых **companion-протокол выведен на аппаратный UART**,
а не на USB-CDC или BLE. Нода подключается по проводу — например, к Flipper Zero,
который пишет лог.

- **WiFi и BLE отключены.** В `examples/companion_radio/main.cpp` интерфейс
  выбирается по приоритету `WIFI_SSID` → `BLE_PIN_CODE` → `SERIAL_RX` → `Serial` (USB).
  Ни `WIFI_SSID`, ни `BLE_PIN_CODE` в этих сборках не определены, поэтому побеждает
  аппаратный serial.
- **Параметры радио не захардкожены.** Частота, BW, SF, CR задаются в рантайме через
  companion-протокол; значения в сборке — только заводские дефолты MeshCore.
- **Собирается в облаке.** GitHub Actions делает оба образа, кладёт их в Releases
  и публикует страницу-флешер. PlatformIO на своей машине ставить не нужно.

## Прошить

**→ [Открыть страницу-флешера](https://hleserg.github.io/meshcore-node-fw/)**

| Плата | Чип | Как шьётся |
|---|---|---|
| Heltec WiFi LoRa 32 **V4** | ESP32-S3 | **Кликом в браузере** (Chrome/Edge, Web Serial) |
| Heltec Mesh Node **T114** | nRF52840 | **Скачать `.uf2`** → двойной тап `RST` → перетащить на диск |

Готовые файлы также лежат в [Releases](../../releases): `v4-factory.bin` и
`t114-companion.uf2`.

## Подключение по UART

3.3 В, 115200 8N1.

| T114 (хедер P1) | | V4 (хедер J3) | |
|---|---|---|---|
| `GPIO9` (P0.09) — RX | ← TX адаптера | `GPIO47` — RX | ← TX адаптера |
| `GPIO10` (P0.10) — TX | → RX адаптера | `GPIO48` — TX | → RX адаптера |
| `GND` | ↔ GND | `GND` | ↔ GND |

Проверить, что нода отвечает:

```bash
pip install meshcore
python scripts/selftest.py COM5        # или /dev/ttyUSB0
```

## Ограничения

- **V4 из браузера — только Chrome или Edge на десктопе.** Прошивка использует
  Web Serial API; в Firefox и Safari его нет. Страница должна открываться по HTTPS
  (или с `localhost`) — иначе браузер не даст доступ к порту.
- **T114 из браузера не шьётся вообще.** nRF52840 не отдаёт себя по Web Serial —
  единственный путь — UF2-перетаскивание. Это ограничение платформы, а не страницы.
- **Странное поведение T114 после смены прошивки** (не поднимается файловая система,
  сбрасываются настройки) лечится разовым прогоном erase-прошивки `.uf2` из
  [`MeshCore/bin`](https://github.com/meshcore-dev/MeshCore/tree/main/bin),
  после чего можно шить обычный образ.
- **`GPIO9`/`GPIO10` на nRF52840 — это NFC-пины.** Прошивка собирается с
  `-D CONFIG_NFCT_PINS_AS_GPIOS`, поэтому при первом старте она однократно
  перепишет UICR и перезагрузит плату. Это нормально.

## Как это собрано

- `external/MeshCore` — сабмодуль апстрима, зафиксированный на теге.
- `patches/` — минимальный патч на `examples/companion_radio/main.cpp`, добавляющий
  ветку hardware-serial для nRF52 и выбор UART-периферии для ESP32.
- `pio/meshcore-node-fw.ini` — два PlatformIO-окружения; копируется в
  `external/MeshCore/platformio.local.ini`, который апстрим уже подхватывает через
  `extra_configs`.
- `scripts/` — `prepare.py` (накатить патчи), `build.py` (собрать и разложить
  артефакты), `selftest.py` (проверить UART).

Подробности сборки, флаги и обоснование выбора пинов — в [BUILD.md](BUILD.md).
