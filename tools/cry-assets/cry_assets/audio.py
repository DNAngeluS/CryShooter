"""Self-authored audio fixture (ported from the P0(i) spike make_audio_fixture.py).

write_audio(out_dir) writes two files under out_dir and returns their paths, wav first:
  <out_dir>/sdlmixer/assets/snl_beep.wav   2 s, 440 Hz, 22.05 kHz mono s16
  <out_dir>/sdlmixer/ace/snl_test.xml      ATL control file with one trigger, Play_snl_beep
The SDL_mixer module opens samples with a plain OS path relative to the working directory, so a caller that
wants to play the samples from a project root must make `audio` -> `<out_dir>` there. This module does not create
that link; the caller does it (see README).
"""

import math
import os
import struct
import wave

ATL_XML = '''<AudioSystemData name="snl_test" version="5" triggers="1">
 <ImplData events="1"/>
 <Triggers>
  <Trigger name="Play_snl_beep">
   <Event name="snl_beep.wav" path="" loop_count="1"/>
  </Trigger>
 </Triggers>
</AudioSystemData>
'''


def write_audio(out_dir):
    """Write the wav and the ATL xml under out_dir; return [wav_path, xml_path]."""
    d = os.path.join(out_dir, "sdlmixer", "assets")
    os.makedirs(d, exist_ok=True)
    wav_path = os.path.join(d, "snl_beep.wav")
    n, rate = 22050 * 2, 22050
    with wave.open(wav_path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * i / rate) * min(1, i / 500, (n - i) / 500))) for i in range(n)))
    a = os.path.join(out_dir, "sdlmixer", "ace")
    os.makedirs(a, exist_ok=True)
    xml_path = os.path.join(a, "snl_test.xml")
    with open(xml_path, "w") as f:
        f.write(ATL_XML)
    return [wav_path, xml_path]
