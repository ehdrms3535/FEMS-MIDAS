# RPi4 펠티어 제어 배선 문서

이 문서는 아래 구성 기준입니다.

- Raspberry Pi 4
- TEC1-12706 40mm 펠티어 / JK-A-CH1 냉각 모듈
- BTS7960 43A 듀얼 H-브리지 모터 드라이버
- Adafruit AO3406 MOSFET Driver - 팬 2개 ON/OFF용
- SMPS 12V 250W
- 14AWG 실리콘 케이블

중요: BTS7960은 릴레이가 아니라 H-브리지 드라이버입니다. 펠티어 본품 전류는 BTS7960으로 제어하고, AO3406 보드는 팬 2개를 켜고 끄는 용도로만 씁니다. AO3406은 펠티어 전류를 직접 감당하는 용도가 아닙니다.

## 전체 구조

```text
Raspberry Pi 4
  GPIO18 -------------- BTS7960 RPWM
  GPIO19 -------------- BTS7960 LPWM
  GPIO20 -------------- BTS7960 R_EN
  GPIO21 -------------- BTS7960 L_EN
  GPIO23 -------------- AO3406 In
  5V ------------------ BTS7960 VCC
  GND ----------------- BTS7960 GND / AO3406 GND / SMPS -V

SMPS 12V
  +V -- 인라인 퓨즈 --+-- BTS7960 B+
                     |
                     +-- AO3406 V+

  -V ----------------+-- BTS7960 B-
                     |
                     +-- AO3406 GND
                     |
                     +-- Raspberry Pi GND

BTS7960 출력
  M+ ---------------- 펠티어 +
  M- ---------------- 펠티어 -

AO3406 출력
  + 출력 ------------ 팬1 + / 팬2 +
  - 또는 Out -------- 팬1 - / 팬2 -
```

## GPIO 핀 매핑

코드 기본값은 BCM GPIO 번호 기준입니다.

| RPi BCM GPIO | 물리 핀 | 연결 대상 | 역할 |
|---:|---:|---|---|
| GPIO18 | Pin 12 | BTS7960 RPWM | 펠티어 forward PWM |
| GPIO19 | Pin 35 | BTS7960 LPWM | 펠티어 reverse PWM |
| GPIO20 | Pin 38 | BTS7960 R_EN | BTS7960 오른쪽 enable |
| GPIO21 | Pin 40 | BTS7960 L_EN | BTS7960 왼쪽 enable |
| GPIO23 | Pin 16 | AO3406 In | 팬 2개 ON/OFF |
| 5V | Pin 2 또는 4 | BTS7960 VCC | BTS7960 로직 전원 |
| GND | Pin 6 등 | 공통 GND | SMPS -V와 공통 접지 |

BTS7960 모듈에 `R_IS`, `L_IS` 핀이 있으면 현재 코드는 사용하지 않으므로 연결하지 않아도 됩니다.

## BTS7960 배선

### 로직 쪽

```text
RPi GPIO18 -> BTS7960 RPWM
RPi GPIO19 -> BTS7960 LPWM
RPi GPIO20 -> BTS7960 R_EN
RPi GPIO21 -> BTS7960 L_EN
RPi 5V     -> BTS7960 VCC
RPi GND    -> BTS7960 GND
```

### 전원/펠티어 쪽

```text
SMPS +V -> 인라인 퓨즈 -> BTS7960 B+
SMPS -V ---------------- BTS7960 B-

BTS7960 M+ -> 펠티어 빨간선 또는 +
BTS7960 M- -> 펠티어 검정선 또는 -
```

펠티어의 차가운 면과 뜨거운 면이 반대로 나오면 두 가지 중 하나로 해결할 수 있습니다.

```bash
python3 -u ~/edge/peltier_bts7960_manual.py --duty 20 --seconds 30 --direction reverse
```

또는 펠티어의 `M+`, `M-` 연결을 서로 바꿉니다. 냉각 방향을 확인한 뒤에는 한 방향으로 고정해서 쓰는 편이 좋습니다.

## AO3406 팬 배선

Adafruit AO3406 보드는 low-side 스위치입니다. 보드의 `In`이 HIGH가 되면 출력 `-` 또는 `Out`이 GND로 연결됩니다.

```text
RPi GPIO23 -> AO3406 In
RPi GND    -> AO3406 GND
SMPS +V    -> AO3406 V+

AO3406 출력 +      -> 팬1 +, 팬2 +
AO3406 출력 -/Out  -> 팬1 -, 팬2 -
```

팬 2개는 병렬로 연결합니다.

```text
AO3406 + ----+---- 팬1 +
             |
             +---- 팬2 +

AO3406 - ----+---- 팬1 -
             |
             +---- 팬2 -
```

AO3406은 1.5A 연속급으로 보는 게 안전합니다. 팬 2개의 합산 전류가 1.5A를 넘으면 AO3406 대신 더 큰 MOSFET 드라이버를 쓰거나 팬을 SMPS 12V에 직접 연결하세요. 팬을 직접 연결하면 코드 실행 시 `--fan-pin -1` 옵션을 씁니다.

## 퓨즈 위치

퓨즈는 SMPS `+V` 바로 다음에 직렬로 넣습니다.

```text
SMPS +V -> 10A 인라인 퓨즈 -> BTS7960 B+
                             -> AO3406 V+
```

처음 추천값은 10A입니다. 더 보수적으로 시작하려면 7.5A도 가능합니다. TEC1-12706 1개와 팬 2개 구성에서 정상 동작 중 자주 끊기면 배선/전류를 먼저 확인한 뒤 10A를 사용하세요.

## 케이블 권장

14AWG 실리콘 케이블을 우선 쓰면 좋은 구간:

```text
SMPS +V -> 퓨즈 -> BTS7960 B+
SMPS -V -> BTS7960 B-
BTS7960 M+ / M- -> 펠티어
```

팬과 GPIO 신호선은 더 얇은 선을 써도 됩니다. 단, 모든 나사 단자는 헐겁지 않게 고정해야 합니다.

## 실행 명령

하드웨어 없이 콘솔 시뮬레이션:

```bash
python3 -u ~/edge/simulate_bts7960_peltier.py --demo --duty 25
```

실제 GPIO 저출력 테스트:

```bash
python3 -u ~/edge/peltier_bts7960_manual.py --duty 20 --seconds 10
```

펠티어 방향 반전 테스트:

```bash
python3 -u ~/edge/peltier_bts7960_manual.py --duty 20 --seconds 10 --direction reverse
```

팬을 AO3406으로 제어하지 않을 때:

```bash
python3 -u ~/edge/peltier_bts7960_manual.py --duty 20 --seconds 10 --fan-pin -1
```

## 처음 전원 넣는 순서

1. AC 전원과 SMPS를 분리한 상태에서 배선을 끝냅니다.
2. 멀티미터로 SMPS `+V`와 `-V`가 쇼트가 아닌지 확인합니다.
3. Raspberry Pi만 켜고 시뮬레이션 명령을 먼저 실행합니다.
4. SMPS 12V 없이 RPi와 BTS7960/AO3406 신호선만 연결해 GPIO 테스트를 합니다.
5. AO3406에 팬만 연결하고 팬 ON/OFF를 확인합니다.
6. BTS7960에 SMPS 12V와 펠티어를 연결합니다.
7. 처음은 `--duty 20 --seconds 30` 정도로 짧게 테스트합니다.
8. 핫사이드 방열판과 팬이 제대로 열을 빼는지 확인한 뒤 duty를 천천히 올립니다.

## 안전 체크

- SMPS 12V를 Raspberry Pi GPIO, 3.3V, 5V 핀에 연결하지 마세요.
- Raspberry Pi GND와 SMPS `-V`는 공통으로 묶어야 GPIO 신호 기준이 맞습니다.
- 펠티어는 방열판과 팬 없이 켜지 마세요.
- BTS7960 방열판도 발열을 확인하세요.
- SMPS AC 입력 단자 `L`, `N`, `FG`는 감전 위험이 있으니 전원 플러그를 뽑은 상태에서만 만지세요.
- `FG` 또는 접지 단자는 가능한 보호접지에 연결하세요.
- 팬이 멈춘 상태로 펠티어를 계속 켜두지 마세요.

## 코드 동작 순서

`edge/peltier_bts7960_manual.py`는 다음 순서로 동작합니다.

```text
시작:
  1. AO3406 팬 ON
  2. fan_spinup 시간 대기, 기본 2초
  3. BTS7960 R_EN / L_EN HIGH
  4. RPWM 또는 LPWM에 PWM duty 적용

종료:
  1. RPWM / LPWM duty 0
  2. BTS7960 R_EN / L_EN LOW
  3. fan_cooldown 시간 대기, 기본 30초
  4. AO3406 팬 OFF
```

기본 `forward`는 RPWM만 PWM을 넣고 LPWM은 0으로 둡니다. `reverse`는 반대로 LPWM만 PWM을 넣고 RPWM은 0으로 둡니다.
