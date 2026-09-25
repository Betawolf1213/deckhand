# Third-party notices

Deckhand's own code is MIT licensed (see `LICENSE`). The release zip also bundles the components below,
each under its own licence. `start.bat` downloads the same components when you run from source.

| Component | Where it lives in the zip | Licence |
|---|---|---|
| [Vosk API](https://github.com/alphacep/vosk-api) runtime, `libvosk.dll` (c) Alpha Cephei Inc | `zig-out/bin/` | Apache 2.0, text in `licenses/Apache-2.0.txt` |
| [vosk-model-small-en-us-0.15](https://alphacephei.com/vosk/models) speech model (c) 2020 Alpha Cephei Inc | `models/vosk-model-small-en-us/` | Apache 2.0, text in `licenses/Apache-2.0.txt` |
| GCC runtime, `libstdc++-6.dll` and `libgcc_s_seh-1.dll` (shipped with Vosk) | `zig-out/bin/` | GPL-3.0 with the [GCC Runtime Library Exception](https://www.gnu.org/licenses/gcc-exception-3.1.html), which permits distribution with any program |
| mingw-w64 winpthreads, `libwinpthread-1.dll` (shipped with Vosk) | `zig-out/bin/` | MIT-style licence of the [mingw-w64 project](https://www.mingw-w64.org/) |
| [Zig](https://ziglang.org/) standard library, compiled into `deckhand.exe` | `zig-out/bin/deckhand.exe` | MIT |

Python packages (`requests`, `pywin32`) are not bundled; `pip` installs them from PyPI under their own licences.

Deckhand is an independent rewrite of [Kabutopz Voice Protocol](https://github.com/Kabutopzzz/Kabutopz-Voice-Protocol)
by Kabutopzzz. Its default voice phrases (`config/commands.default.json`) and mining tables come from that project,
which has no licence file. That content is credited to its author, is not covered by Deckhand's MIT licence,
and reuse of it depends on its author's permission.

Star Citizen is a trademark of Cloud Imperium Rights LLC. Deckhand is a fan project and is not affiliated with
or endorsed by Cloud Imperium Games.
