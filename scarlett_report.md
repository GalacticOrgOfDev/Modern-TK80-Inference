# Modern-TK80 Scarlett hardware check

Run at 2026-10-28T22:03:31-04:00.

Every value below was returned by the audio library or measured from captured samples on this run. Nothing is filled in from a spec sheet. A SKIPPED step says why it did not run.

## Environment

- Python: 3.12.1
- Platform: Windows-10-10.0.19045-SP0
- SD_ENABLE_ASIO requested: yes
- sounddevice: 0.5.6
- PortAudio: PortAudio V19.7.0-devel, revision unknown

## Steps

| Step | Result | Detail |
|---|---|---|
| Load sounddevice | PASS | 0.5.6 |
| List host APIs and devices | PASS | 5 host APIs (ASIO present), 22 devices, 7 named Scarlett/Focusrite |
| Pick device | SKIPPED | --list-only |
| Rate x buffer matrix | SKIPPED | --list-only |
| Record 16-bit (int16) | SKIPPED | --list-only |
| Record 24-bit (int24) | SKIPPED | --list-only |
| Record 32-bit (int32) | SKIPPED | --list-only |
| Play test tone | SKIPPED | --list-only |
| Loopback tone | SKIPPED | --list-only |

## Host APIs

| Index | Name | Devices | ASIO |
|---|---|---|---|
| 0 | MME | 6 |  |
| 1 | Windows DirectSound | 6 |  |
| 2 | ASIO | 2 | yes |
| 3 | Windows WASAPI | 4 |  |
| 4 | Windows WDM-KS | 4 |  |

## Devices

| Index | Name | Host API | Inputs | Outputs | Default rate | ASIO | Scarlett/Focusrite |
|---|---|---|---|---|---|---|---|
| 0 | Microsoft Sound Mapper - Input | MME | 2 | 0 | 44100.0 |  |  |
| 1 | Analogue 1 + 2 (Focusrite USB A | MME | 2 | 0 | 44100.0 |  | yes |
| 2 | Microsoft Sound Mapper - Output | MME | 0 | 2 | 44100.0 |  |  |
| 3 | 3 - ASUS PB278 (AMD High Defini | MME | 0 | 2 | 44100.0 |  |  |
| 4 | Digital Audio (S/PDIF) (High De | MME | 0 | 2 | 44100.0 |  |  |
| 5 | Speakers (Focusrite USB Audio) | MME | 0 | 2 | 44100.0 |  | yes |
| 6 | Primary Sound Capture Driver | Windows DirectSound | 2 | 0 | 44100.0 |  |  |
| 7 | Analogue 1 + 2 (Focusrite USB Audio) | Windows DirectSound | 2 | 0 | 44100.0 |  | yes |
| 8 | Primary Sound Driver | Windows DirectSound | 0 | 2 | 44100.0 |  |  |
| 9 | 3 - ASUS PB278 (AMD High Definition Audio Device) | Windows DirectSound | 0 | 2 | 44100.0 |  |  |
| 10 | Digital Audio (S/PDIF) (High Definition Audio Device) | Windows DirectSound | 0 | 2 | 44100.0 |  |  |
| 11 | Speakers (Focusrite USB Audio) | Windows DirectSound | 0 | 2 | 44100.0 |  | yes |
| 12 | ASIO4ALL v2 | ASIO | 2 | 6 | 44100.0 | yes |  |
| 13 | Focusrite USB ASIO | ASIO | 2 | 2 | 44100.0 | yes | yes |
| 14 | Digital Audio (S/PDIF) (High Definition Audio Device) | Windows WASAPI | 0 | 2 | 48000.0 |  |  |
| 15 | 3 - ASUS PB278 (AMD High Definition Audio Device) | Windows WASAPI | 0 | 2 | 48000.0 |  |  |
| 16 | Speakers (Focusrite USB Audio) | Windows WASAPI | 0 | 2 | 48000.0 |  | yes |
| 17 | Analogue 1 + 2 (Focusrite USB Audio) | Windows WASAPI | 2 | 0 | 48000.0 |  | yes |
| 18 | SPDIF Out (HD Audio SPDIF out) | Windows WDM-KS | 0 | 2 | 44100.0 |  |  |
| 19 | Analogue 1 + 2 (wc4800_8006) | Windows WDM-KS | 2 | 0 | 48000.0 |  |  |
| 20 | Speakers (wr4800_8006) | Windows WDM-KS | 0 | 2 | 48000.0 |  |  |
| 21 | Output (AMD HD Audio DP out #2) | Windows WDM-KS | 0 | 2 | 44100.0 |  |  |
