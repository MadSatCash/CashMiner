# CashMiner Android

Experimental Android port of the shared CashMiner 2.17.1 sources. This is a
separate APK build; the Windows release and its native DLLs are unchanged.

## Scope / Alcance

- Android 7.0/API 24 or later. APK includes ARM32 (`armeabi-v7a`), ARM64
  (`arm64-v8a`) and x86-64. Hardware compatibility still requires device testing.
- The existing local HTML UI runs in a WebView. Python wallet, P2P, RPC, Stratum,
  peer storage and ranking policy come from the shared source tree.
- CPU only: the original `native/source/bch_hashscan.c` is compiled with the
  Android NDK and uses its existing internal-thread interface. No CUDA/OpenCL.
- Initial Android version: 25% CPU by default, maximum 50%, one mining session at once.
  Leaving the app, locking the screen or opening another application stops
  mining. Returning does not automatically restart it. Network operations can
  take several seconds to stop; an isolated miner process is terminated if it
  does not exit within six seconds. A foreground notification also offers Stop.
- App data is private Android storage, separate from Windows wallets. Seed
  material is wrapped with Android Keystore AES-256-GCM and wallet-bound AAD.
  Recovery phrases/keys remain necessary: uninstalling or clearing app storage
  can destroy the vault and its wrapping key. Never treat copying an encrypted
  Android vault to another device as a recovery method.
- Explorer automation starts disabled in a new Android installation. Ranking
  runs in an app worker thread, separately from the miner service process, using
  the existing scoring policy and SQLite fallback.
- The desktop log file download uses browser Blob URLs; native file export is
  not implemented in this Android version. Copying logs and displaying recovery material
  remain available. This is not a claim of full desktop feature parity.
- Python 3.11 is required for Chaquopy's ARM32 support. Android uses the available
  prebuilt `cryptography==42.0.8`, not the Windows dependency version. This older
  mobile dependency must be reviewed before promoting the Android port to a stable
  wallet release. Start with test networks and recovery backups.

No Google Play distribution is planned for an app which mines on the device.
The project owner reported successful Testnet3 native P2P mining on a phone,
around 2 MH/s, with the resulting reward also visible in the matching PC wallet.
This does not establish equivalent coverage of every device or network.

## Build / Compilación

Use a Windows host with Python 3.11 (a complete installation with `venv`),
JDK 21, Gradle 8.11.1, Android platform/build tools 35, NDK 28.2.13676358 and
CMake 3.22.1. The pinned Gradle plugins are AGP 8.9.2 and Chaquopy 17.2.0.
Download tools from their official providers. `sdkmanager` package names:

```
platform-tools
platforms;android-35
build-tools;35.0.0
ndk;28.2.13676358
cmake;3.22.1
```

Choose a work directory outside the checkout and write its `tools.json`:

```json
{
  "java": "C:/build-tools/jdk-21",
  "gradle": "C:/build-tools/gradle-8.11.1",
  "sdk": "C:/build-tools/sdk",
  "python": "C:/build-tools/python311/python.exe"
}
```

From the repository root:

```powershell
python packaging/android/build.py --work C:/CashMiner-Android/.work --output C:/CashMiner-Android
```

The script redirects Gradle caches, Android user files, temporary files, assets,
native staging and build outputs into the work directory. It creates the APK,
SHA256SUMS.txt and `Signing/` in the output directory. **Preserve the signing key
and its password privately** to sign future updates. They are not app data or
disposable build files and must never be uploaded to GitHub or shared with users.
The APK is signed by that preview key; it is not signed by an app store.

Build verification should include `apksigner verify`, the APK manifest/ABIs,
an emulator startup, a real native hashing vector and a controlled mining run.
`MainActivity` accepts `--ez selftest true` through adb for local developer tests:
it checks native genesis PoW, Keystore authentication and temporary wallet
recovery, logging only boolean results under `CashMinerSelfTest`.

Portable controller checks:

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -p test_android_preview.py -v
```

After verification, stop the emulator/build tools and delete the disposable
work directory. Keep the APK, its checksum, instructions and the private signing
material. Do not publish emulator data, SDKs, build caches or real wallet data.

## Third-party components

Chaquopy (MIT), CPython (PSF), cryptography (Apache-2.0 OR BSD-3-Clause), cffi
(MIT), pycparser (BSD), libffi and OpenSSL notices accompany the embedded runtime
and Python distributions. Existing project credits and notices remain in the
source payload. See `ANDROID_NOTICES.md` for upstream references.
