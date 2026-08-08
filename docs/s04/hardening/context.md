# S0.4 hardening evidence context

Source root: `D:\GitProjects\Jump Terminator`

Target revision: `07a7be25bbbe3ce68778748066c5cdbbd01add6e`

Source drift at analysis start: `none`

Collection SHA-256: `13359cef9d930c9b0691851de3cb981169c82b67df8bf460fe55285e8fa6248b`

The collection digest is SHA-256 over UTF-8 records of `repository-relative path`, NUL, and lowercase artifact SHA-256, joined by LF in the order below.

| Evidence | Artifact | SHA-256 | Purpose |
| --- | --- | --- | --- |
| `E001` | `docs/s03/results/miui14-23078rkd5c-s03-lifecycle-20260803.report.json` | `e0e232910879c632fa7ad0456304264b738a6ef51ebabd91ee23d853cd00eb7c` | v2 force-stop failure baseline |
| `E002` | `docs/s03/results/miui14-23078rkd5c-s03-lifecycle-v003-owner-bound-20260803.report.json` | `0788aa0a3d6779f1bd8bd9f984ba94aeb2d3c169a137589e55d3a691a660f4d7` | v3 owner-bound lifecycle pass |
| `E003` | `s02-shizuku-poc/src/main/aidl/com/jumpterminator/s02/IPrivilegedCompanion.aidl` | `cc124cfbb1ed312a314a648ce88301118a1937b4c2fac02184069d0d7e820aec` | caller-supplied identity and protocol surface |
| `E004` | `s02-shizuku-poc/src/main/java/com/jumpterminator/s02/MainActivity.kt` | `f35f777fb4585ca6ecf7fa08402d8c1af1954e5965267448e8ee8f30ed7e603c` | client ownership and session creation |
| `E005` | `s02-shizuku-poc/src/main/java/com/jumpterminator/s02/OwnerAuthorizationPolicy.kt` | `5e1605b8aef0ff83dec528ac006f36ef0a35c67d7965f225c9efcde125cd6ca6` | current authorization state machine |
| `E006` | `s02-shizuku-poc/src/main/java/com/jumpterminator/s02/PrivilegedCompanionService.kt` | `9fdc52bbfd06f2a4a0315c4ef0d1a741c69c67025909cc0c969ca933eff93562` | privileged action boundary |

Evidence classification:

- `E001` and `E002` are entity-device experiment reports.
- `E003` through `E006` are source observations at the target revision.
- No repository-wide security scan was used; claims are scoped to the S0.2/S0.3 privileged companion.
