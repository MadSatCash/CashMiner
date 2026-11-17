# Release artifacts — 2.18.2

| Artifact | SHA-256 |
| --- | --- |
| `CashMiner-Windows.zip` | `0c7aae3fb5898913546027f5f58dcb0046fee88284b5cc656f3e7770b92bf103` |
| `CashMiner-Android-v2.18.2.apk` | `710b59a92ffeb59cf60b30b296b0d01b2efe0d6c14c29d26471adb9d8e0bb7a6` |

Windows is generated from the shared 2.18.2 source with the pinned build recipe.
Android updates the 2.18.1 Python/UI payload and manifest: versionName 2.18.2,
versionCode 2180200. All 32 DEX/native/resource entries and the signing certificate
are retained. Signature, payload and manifest are verified. This is not a
Java/native rebuild or a phone/emulator test.

The Windows EXE started and closed normally with isolated data; all 321 manifest
files stayed unchanged. The owner confirmed WIF import during Windows testing.
Native hashing DLLs are unchanged from 2.18. The release distributes these two
files and SHA256SUMS.txt. Signing material and wallet data are excluded.

---

## Unpublished local candidate 2.18.1 — provenance only

| Artifact | SHA-256 |
| --- | --- |
| `CashMiner-Windows.zip` | `6a11b3143ea729e80fd8b29b4eaccc32b0d59fa9accb59dc920521935a12379c` |
| `CashMiner-Android-v2.18.1.apk` | `1edee277422a274f465a06d04e9283afa4c3ba09160f9aa56aa4708c3621ed18` |

Windows is built from the shared 2.18.1 source using the pinned Windows recipe.
BUILD_MANIFEST.json records every delivered file. The extracted EXE started,
served API 2.18.1 and closed normally with isolated data; all manifest hashes
remained unchanged. Ten wallet/WIF HTTP and storage tests passed using the
bundled Python and the delivered application sources.

Android updates the 2.18 Python/UI payload and manifest to versionName 2.18.1,
versionCode 2180100. All 32 DEX/native/resource entries are unchanged. Google
zipalign/apksigner 35.0.0 align and verify the package; the existing signing
certificate is retained. This is not a Java/native rebuild or a phone test.

This candidate was not published separately. Its changes are included in 2.18.2.
Signing material and test data remain outside public artifacts.

---

# Release artifacts / Artefactos de distribución — 2.18

| Artifact | SHA-256 |
| --- | --- |
| `CashMiner-Windows.zip` | `9bef263f6beaf5036db5c01afd08bffbfb33af98c6e160468957ab76c5f982a3` |
| `CashMiner-Android-v2.18.apk` | `a295e1ad7d83fa02485b8eb3a292325880dd6f159c3f3d1a57bdf27286e53c2d` |

The Windows package is built from the shared 2.18 runtime source tree using
`packaging/windows/build.py`. Its manifest records hashes of all 322 delivered
files and the pinned Python/wheel/compiler inputs; native hashing DLLs are
retained. Source changes for 2.17.2 and 2.18 are included in this release.

Android updates the Python/UI payload and manifest of the 2.17.2 APK. The latter
was an incremental update of tested 2170105 described below. DEX, resources and
native libraries remain byte-identical (32 entries). VersionName: `2.18`;
versionCode: `2180000`; package: `org.cashminer.android`. Google zipalign and
apksigner 35.0.0 verified alignment/signatures with the same certificate:
`5cbdd31329f6e1a7e3bc15751c921f9ac1deeaf7764edbccf1f92f6f3d200091`.
This is not a fresh Java/native compilation or a phone/emulator test of this APK.

[Detailed 2.18 changes and checks](releases/NOTAS_V2.18.md).
Private signing keys/passwords, wallet data and build tools are excluded.
Checksums cover the exact files attached to the experimental v2.18 release.

---

## Historical release artifacts / Artefactos históricos — 2.17.1

The Android APK is retained exactly as tested. The Windows ZIP refreshes only
MIT/vendor license documents and its manifest; executable, native DLLs and
application sources are unchanged from the tested package. A single repository holds shared source and platform build recipes.
Each binary has its own build provenance; do not assume a documentation commit
was the input of an older binary. / Se conservan los paquetes probados y se
registra por separado la procedencia de cada uno.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `CashMiner-Windows.zip` | 18868759 | `f3d724029be852e89c4af225771e6bf6987a5d04c6e9aa7d7f5944bfd43bbcd3` |
| `CashMiner-Android-v2.17.1.apk` | 30359215 | `75596df8e37af42a395b41172094c103980cb1b4a5a0a3fe8783169b80df617f` |

## Windows

The retained Windows candidate's 58 packaged application source files were
compared with desktop commit
[`dce3b1543afc2de86ae3642172dda87ee35fb02f`](https://github.com/MadSatCash/CashMiner/tree/dce3b1543afc2de86ae3642172dda87ee35fb02f);
all matched after line-ending normalization. Its `BUILD_MANIFEST.json` records
byte hashes for delivered files and runtime/toolchain inputs. The ZIP predates
the later shared C-MT CPU duty fix in commit
`a43334c53c2593c4f45818151f9d076929390508`; its executable and runtime are not rebuilt by this release task. The ZIP now
includes the project MIT license and CUDA 12.8 runtime license, with an updated
manifest. The earlier candidate ZIP SHA-256 was `903aef8ab81de5e34796ebd6e6e392ddf5b6991c4efbccae617d57f7c4e6f10f`.
The tracked Windows DLLs are unchanged. Existing pending notice/provenance work
is described in [third-party notices](../THIRD_PARTY_NOTICES.md).

## Android

APK source:
[`b5b487332006bb2d7f764de6e07795608ff05cfc`](https://github.com/MadSatCash/CashMiner/tree/b5b487332006bb2d7f764de6e07795608ff05cfc).
Build recipe: [packaging/android](../packaging/android/README.md).

- Application ID: `org.cashminer.android`; versionName `2.17.1`; versionCode `2170105`.
- Label: `CashMiner`; CPU library for ARM32, ARM64 and x86-64.
- Signing certificate SHA-256:
  `5cbdd31329f6e1a7e3bc15751c921f9ac1deeaf7764edbccf1f92f6f3d200091`.
- Same certificate as the installed test APK; install as an update, not by
  uninstalling. The old certificate's internal common name remains unchanged
  to retain update compatibility; the displayed app name is CashMiner.
- Final APK executable components/manifest and inner source payload were compared
  with the emulator-tested package. Native libraries were unchanged. The owner
  subsequently reported a checked Testnet3 block on their phone.

Signing keys/passwords, wallet data, SDKs, emulator images and build caches are
not source or release assets and must remain private. / Las claves de firma,
billeteras y herramientas/cachés no se suben al repositorio ni a la release.

The checksum file is also attached to the release: [SHA256SUMS.txt](SHA256SUMS.txt).
