"""Render one timed narration track for the continuous desktop capture."""

import argparse
import subprocess
import wave
from pathlib import Path
from tempfile import TemporaryDirectory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cues", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cache", type=Path, default=Path.home()/".cache/pm-hackathon")
    args = parser.parse_args()
    cues = []
    for line in args.cues.read_text().splitlines():
        when, text = line.split("|", 1)
        cues.append((float(when), text))
    with TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        with wave.open(str(args.output), "wb") as master:
            rate = 22050
            master.setparams((1, 2, rate, 0, "NONE", "not compressed"))
            timeline = bytearray(180*rate*2)
            for index, (when, text) in enumerate(cues):
                src = tmp / "speech.wav"
                subprocess.run([str(args.cache/"venv/bin/piper"),
                                "-m", str(args.cache/"ru_RU-dmitri-medium.onnx"), "-f", str(src),
                                "--length-scale", "0.94", "--sentence-silence", "0.23",
                                "--volume", "0.82"], input=text+"\n", text=True, check=True,
                               stdout=subprocess.DEVNULL)
                end = cues[index+1][0] - 0.35 if index+1 < len(cues) else 178.7
                with wave.open(str(src), "rb") as segment:
                    assert segment.getframerate() == rate and segment.getnchannels() == 1
                    elapsed = segment.getnframes()/rate
                    raw = segment.readframes(segment.getnframes())
                if elapsed > end-when:
                    tempo = elapsed/(end-when)
                    if tempo > 1.45:
                        raise ValueError(f"Фраза {index+1} слишком длинная: {elapsed:.1f} с на {end-when:.1f} с")
                    raw = subprocess.check_output(["ffmpeg","-hide_banner","-loglevel","error","-i",str(src),
                                                   "-af",f"atempo={tempo+0.02:.3f}","-f","s16le","-"])
                offset = round(when*rate)*2
                timeline[offset:offset+len(raw)] = raw
                print(f"{when:05.1f}  {len(raw)/(2*rate):.1f} s")
            master.writeframes(timeline)


if __name__ == "__main__":
    main()
