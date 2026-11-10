# Android build components

CashMiner source remains MIT (see the root LICENSE). This preview adds:

| Component | Version | Upstream | License |
|---|---|---|---|
| Chaquopy | 17.2.0 | https://github.com/chaquo/chaquopy | MIT |
| CPython | 3.11 runtime supplied by Chaquopy | https://github.com/python/cpython | PSF and included notices |
| cryptography | 42.0.8 | https://github.com/pyca/cryptography | Apache-2.0 OR BSD-3-Clause |
| cffi | 1.17.1 | https://foss.heptapod.net/pypy/cffi | MIT |
| pycparser | 3.12 | https://github.com/eliben/pycparser | BSD-3-Clause |
| chaquopy-libffi | 3.3 | https://github.com/libffi/libffi | MIT and included notices |

The cryptography wheel incorporates OpenSSL: retain its bundled license notices.
The Python runtime incorporates additional components with their own notices.
The Android WebView is supplied and maintained by the device, not bundled as a
separate browser distribution by CashMiner. Android SDK/NDK, CMake, Gradle, JDK
and AGP are build tools; their complete installations are not shipped in the APK.

Dependency versions here describe the preview build, not the Windows release.
The root THIRD_PARTY_NOTICES.md also applies to shared wallet/UI/miner sources.
