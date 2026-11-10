# Release artifacts / Artefactos de distribución — 2.17.1

The release retains the tested packages; it does not rebuild them while editing
documentation. A single repository holds shared source and platform build recipes.
Each binary has its own build provenance; do not assume a documentation commit
was the input of an older binary. / Se conservan los paquetes probados y se
registra por separado la procedencia de cada uno.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `CashMiner-Windows.zip` | 18852449 | `903aef8ab81de5e34796ebd6e6e392ddf5b6991c4efbccae617d57f7c4e6f10f` |
| `CashMiner-Android-v2.17.1.apk` | 30359215 | `75596df8e37af42a395b41172094c103980cb1b4a5a0a3fe8783169b80df617f` |

## Windows

The retained Windows candidate's 58 packaged application source files were
compared with desktop commit
[`dce3b1543afc2de86ae3642172dda87ee35fb02f`](https://github.com/MadSatCash/CashMiner/tree/dce3b1543afc2de86ae3642172dda87ee35fb02f);
all matched after line-ending normalization. Its `BUILD_MANIFEST.json` records
byte hashes for delivered files and runtime/toolchain inputs. The ZIP predates
the later shared C-MT CPU duty fix in commit
`a43334c53c2593c4f45818151f9d076929390508`; it is not rebuilt by this release task.
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
