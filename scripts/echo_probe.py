"""Record and read the robot's echo cancelling (dev firmware only).

Arms the echo probe on the brain's dev web server, waits while she talks, downloads ten
seconds of what the audio front end was fed (both mics and the speaker reference) and what
it gave back, writes them as four WAV files to listen to, and prints what they show:

- how much of her own voice the echo cancelling removes (ERLE, dB),
- whether the reference leads the echo in the mic, as it must, or lags it,
- whether the mics clip, and how alike reference and echo are (low = distortion),
- the barge-in decisions made on that audio.

    ~/sandy_app_venv/bin/python scripts/echo_probe.py 192.168.8.103 [--out DIR] [--now]

Say the wake word and ask for something long once it says "armed"; stay quiet while she
answers. --now records at once instead of waiting for her to talk.
"""
import argparse
import csv
import io
import sys
import time
import urllib.request
import wave
from pathlib import Path

import numpy as np

RATE = 16000


def fetch(host: str, path: str, timeout: float = 60) -> bytes:
    with urllib.request.urlopen(f"http://{host}{path}", timeout=timeout) as r:
        return r.read()


def status(host: str) -> dict:
    lines = fetch(host, "/echo/status", 10).decode().splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


def write_wav(path: Path, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(samples.astype("<i2").tobytes())


def db(x: float) -> float:
    return 10 * np.log10(max(x, 1e-12))


def power(x: np.ndarray) -> float:
    x = x.astype(np.float64)
    return float(np.mean(x * x)) if x.size else 0.0


def lag_ms(ref: np.ndarray, mic: np.ndarray, max_ms: int = 400) -> tuple[float, float]:
    """Where the reference shows up in the mic (GCC-PHAT), and how sharp that peak is.

    Positive: the echo arrives after the reference, which echo cancelling needs.
    """
    n = 1 << int(np.ceil(np.log2(len(ref) + len(mic))))
    r = np.fft.rfft(ref.astype(np.float64), n)
    m = np.fft.rfft(mic.astype(np.float64), n)
    cross = m * np.conj(r)
    cross /= np.abs(cross) + 1e-9
    cc = np.fft.irfft(cross, n)
    k = int(max_ms * RATE / 1000)
    window = np.concatenate((cc[-k:], cc[:k + 1]))
    peak = int(np.argmax(np.abs(window)))
    sharp = float(np.abs(window[peak]) / (np.mean(np.abs(window)) + 1e-12))
    return (peak - k) * 1000 / RATE, sharp


def coherence(ref: np.ndarray, mic: np.ndarray, lag: int, seg: int = 512) -> float:
    """Mean magnitude-squared coherence over 300–3400 Hz, mic shifted by the lag."""
    if lag > 0:
        ref, mic = ref[:-lag], mic[lag:]
    elif lag < 0:
        ref, mic = ref[-lag:], mic[:lag]
    n = min(len(ref), len(mic)) // seg * seg
    if n < seg * 4:
        return float("nan")
    win = np.hanning(seg)
    r = np.fft.rfft(ref[:n].reshape(-1, seg) * win, axis=1)
    m = np.fft.rfft(mic[:n].reshape(-1, seg) * win, axis=1)
    sxy = np.abs(np.mean(r * np.conj(m), axis=0)) ** 2
    sxx = np.mean(np.abs(r) ** 2, axis=0)
    syy = np.mean(np.abs(m) ** 2, axis=0)
    freqs = np.fft.rfftfreq(seg, 1 / RATE)
    band = (freqs >= 300) & (freqs <= 3400)
    return float(np.mean(sxy[band] / (sxx[band] * syy[band] + 1e-12)))


def analyse(feed: np.ndarray, out: np.ndarray, rows: list[dict], info: dict) -> None:
    left, right, ref = feed[:, 0], feed[:, 1], feed[:, 2]
    playing = np.abs(ref) > 0
    # Where the speaker played (20 ms blocks with any reference), the echo-only stretch.
    block = RATE // 50
    nb = len(ref) // block
    active = np.array([np.any(playing[i * block:(i + 1) * block]) for i in range(nb)])
    idx = np.repeat(active, block)
    print(f"\nfront end fed {len(ref) / RATE:.1f} s, output {len(out) / RATE:.1f} s, "
          f"volume {info.get('volume')}%, reference delay {info.get('ref_delay_ms')} ms")
    print(f"speaker playing in {active.mean() * 100:.0f}% of it")

    for name, ch in (("left mic", left), ("right mic", right)):
        clip = int(np.sum(np.abs(ch.astype(np.int32)) >= 32700))
        print(f"{name}: level {db(power(ch[:len(idx)][idx])):.1f} dB while she talks, "
              f"peak {int(np.max(np.abs(ch.astype(np.int32))))}, clipped samples {clip}")
    print(f"reference: level {db(power(ref[:len(idx)][idx])):.1f} dB, "
          f"peak {int(np.max(np.abs(ref.astype(np.int32))))}")

    if active.sum() < 25:
        print("\nshe barely talked in this recording: nothing to measure the echo on")
        return
    for name, ch in (("left", left), ("right", right)):
        ms, sharp = lag_ms(ref[:len(idx)] * idx, ch[:len(idx)] * idx)
        coh = coherence(ref.astype(np.float64), ch.astype(np.float64), int(ms * RATE / 1000))
        verdict = ("reference leads the echo (good)" if ms >= 0
                   else "reference LAGS the echo: cancelling cannot work")
        print(f"{name} mic: echo {ms:+.1f} ms after the reference (peak sharpness {sharp:.0f}) "
              f"— {verdict}; reference/echo likeness {coh:.2f}")

    # The output trails the feed by the front end's own delay; compare powers over the
    # stretches where she talked, by the rows' talking flag.
    talk_out = np.zeros(len(out), dtype=bool)
    for a, b in zip(rows, rows[1:] + [None]):
        if a["talking"]:
            end = b["out_at"] if b else len(out)
            talk_out[a["out_at"]:end] = True
    if talk_out.any():
        mic_p = power(left[:len(idx)][idx])
        out_p = power(out[talk_out])
        print(f"\necho removed (left mic in → output, while she talks): "
              f"{db(mic_p) - db(out_p):.1f} dB "
              f"(good cancelling is 20 dB or more; under 10 dB means it is barely working)")
        quiet = ~talk_out
        if quiet.sum() > RATE // 2:
            print(f"output while she is quiet: {db(power(out[quiet])):.1f} dB, "
                  f"while she talks: {db(out_p):.1f} dB")

    t = [r for r in rows if r["talking"]]
    if t:
        vad = sum(r["vad"] for r in t) / len(t)
        speech = sum(r["speech"] for r in t) / len(t)
        levels = sorted(r["level"] for r in t)
        print(f"\nwhile she talks: the detector called it speech {vad * 100:.0f}% of the time, "
              f"above the caller's bar {speech * 100:.0f}%; "
              f"level median {levels[len(levels) // 2]}, bar {t[-1]['bar']}")
    barges = [r["at_ms"] for r in rows if r["barge"]]
    print(f"barge-ins in this recording: {len(barges)}"
          + (f" (at {', '.join(f'{b / 1000:.1f}s' for b in barges)})" if barges else ""))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("host")
    ap.add_argument("--out", default="echo_probe_out")
    ap.add_argument("--now", action="store_true", help="record at once")
    ap.add_argument("--wait", type=int, default=180, help="seconds to wait for her to talk")
    a = ap.parse_args()

    print(fetch(a.host, "/echo/arm?now" if a.now else "/echo/arm", 10).decode())
    if not a.now:
        print("armed — say the wake word now and ask her something long, then stay quiet")
    deadline = time.time() + a.wait
    while (s := status(a.host))["state"] != "done":
        if time.time() > deadline:
            print(f"no recording after {a.wait} s (state {s['state']})")
            return 1
        time.sleep(1)

    feed = np.frombuffer(fetch(a.host, "/echo/feed"), dtype="<i2").reshape(-1, 3)
    out = np.frombuffer(fetch(a.host, "/echo/out"), dtype="<i2")
    rows = [{k: int(v) for k, v in r.items()}
            for r in csv.DictReader(io.StringIO(fetch(a.host, "/echo/frames").decode()))]

    d = Path(a.out)
    d.mkdir(parents=True, exist_ok=True)
    write_wav(d / "1_mic_left_raw.wav", feed[:, 0])
    write_wav(d / "2_mic_right_raw.wav", feed[:, 1])
    write_wav(d / "3_reference.wav", feed[:, 2])
    write_wav(d / "4_after_echo_cancel.wav", out)
    (d / "frames.csv").write_bytes(fetch(a.host, "/echo/frames"))
    print(f"files in {d.resolve()}")
    analyse(feed, out, rows, s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
