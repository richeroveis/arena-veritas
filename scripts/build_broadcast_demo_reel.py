#!/usr/bin/env python3
"""Build the ArenaVeritas broadcast demo reel with audio and burned subtitles.

Pure local synthesis: frames are drawn with Pillow and piped into the bundled
ffmpeg (imageio-ffmpeg), the stereo bed is generated with numpy, and captions
come from a generated ASS file plus an SRT sidecar. No stock assets.

Outputs (identical bytes in both locations):
  docs/demo-video-subtitled.mp4
  frontend/public/demo-video-subtitled.mp4
Runtime is fixed at 50.0 s, 1280x720, 30 fps, libx264 + aac, under 15 MB.
"""
from __future__ import annotations

import hashlib
import math
import os
import shutil
import subprocess
import sys
import wave

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "video-build")
AUDIO_WAV = os.path.join(BUILD, "broadcast_bed.wav")
ASS_PATH = os.path.join(BUILD, "captions.ass")
SRT_PATH = os.path.join(ROOT, "docs", "demo-video-subtitles.srt")
TARGETS = [
    os.path.join(ROOT, "docs", "demo-video-subtitled.mp4"),
    os.path.join(ROOT, "frontend", "public", "demo-video-subtitled.mp4"),
]

W, H = 1280, 720
FPS = 30
DURATION = 50.0
SR = 44100
SIZE_CEILING = 15 * 1000 * 1000

OBSIDIAN = (7, 9, 14)
PANEL = (16, 21, 32)
PANEL_2 = (22, 29, 44)
LIME = (163, 230, 53)
ROSE = (244, 63, 94)
STEEL = (94, 110, 140)
FOG = (178, 192, 214)
WHITE = (232, 240, 238)
AMBER = (251, 191, 36)

CONTRACT = "0x1eC61228C0311150cAe42Af4d1C6C0bF847fc058"
EXPLORER = "explorer-studio.genlayer.com"

FONTS = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")


def font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    name = "arialbd.ttf" if bold else "consolab.ttf"
    path = os.path.join(FONTS, name)
    if not os.path.exists(path):
        path = os.path.join(FONTS, "arial.ttf")
    return ImageFont.truetype(path, size)


SCENES = [
    (0.0, 6.0, "OPEN"),
    (6.0, 18.0, "BRACKET"),
    (18.0, 28.0, "ANALYZER"),
    (28.0, 40.0, "DOCKET"),
    (40.0, 46.0, "SETTLEMENT"),
    (46.0, 50.0, "CLOSE"),
]

CAPTIONS = [
    (0.3, 5.6, "ArenaVeritas  the AI verified integrity desk for esports and speedruns"),
    (6.2, 9.4, "Live bracket view: four finals  ten AVT held in the prize custody vault"),
    (9.7, 13.6, "Every bracket escrows its prize pool before a single competitor bond lands"),
    (13.9, 17.6, "Anti-cheat bonds arrive from separate signer wallets in native value"),
    (18.3, 21.8, "Frame tick analyzer maps telemetry onto the 500 bps integrity grid"),
    (22.1, 25.4, "Anomaly index and integrity baseline snap to the discrete quantized ladder"),
    (25.7, 27.7, "Verdict band derives from the quantized pair  not from a raw float"),
    (28.3, 32.0, "Protest docket console  a filed challenge locks its own protest bond"),
    (32.3, 36.2, "Validators re render telemetry and rulebook independently on chain"),
    (36.5, 39.7, "Prompt comparative settlement demands exact equality on all seven fields"),
    (40.3, 43.4, "Settlement unlocks only after the protest deadline has passed"),
    (43.7, 45.7, "Custody invariants assert in the same transaction that pays out"),
    (46.2, 49.6, "ArenaVeritas on studionet  contract " + CONTRACT),
]

BRACKETS = [
    ("CS2 Major Grand Final", "CS2", "2.00 AVT", "ACTIVE"),
    ("Valorant Sovereign Cup", "VAL", "2.00 AVT", "ACTIVE"),
    ("Elden Ring Any% WR Check", "ELDN", "2.00 AVT", "PROTESTED"),
    ("Dota 2 Saigon Invitational", "DOTA", "2.00 AVT", "VOID"),
]


def tstamp_ass(t: float) -> str:
    cs = int(round(t * 100))
    return f"{cs // 360000}:{(cs // 6000) % 60:02d}:{(cs // 100) % 60:02d}.{cs % 100:02d}"


def tstamp_srt(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{(ms // 60000) % 60:02d}:{(ms // 1000) % 60:02d},{ms % 1000:03d}"


def write_caption_files() -> None:
    header = (
        "[Script Info]\n"
        "Title: ArenaVeritas broadcast reel\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1280\n"
        "PlayResY: 720\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,30,&H00E8F0F0,&H00FFFFFF,&H000E0907,&H96000000,-1,0,0,0,100,100,0.5,0,3,2,1,2,40,40,44,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = [
        f"Dialogue: 0,{tstamp_ass(a)},{tstamp_ass(b)},Default,,0,0,0,,{text}"
        for a, b, text in CAPTIONS
    ]
    with open(ASS_PATH, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(header + "\n".join(lines) + "\n")
    srt = []
    for i, (a, b, text) in enumerate(CAPTIONS, start=1):
        srt.append(f"{i}\n{tstamp_srt(a)} --> {tstamp_srt(b)}\n{text}\n")
    with open(SRT_PATH, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(srt))


# --------------------------------------------------------------------------- audio
def env(length: int, attack: float, decay: float) -> np.ndarray:
    e = np.ones(length)
    a = max(1, int(length * attack))
    d = max(1, int(length * decay))
    ramp = np.linspace(0, 1, a)
    e[:a] *= ramp
    e[-d:] *= np.linspace(1, 0, d)
    return e


def kick(rng: np.ndarray, at: int, gain: float) -> np.ndarray:
    n = int(0.22 * SR)
    if at + n >= len(rng):
        return rng
    t = np.arange(n) / SR
    body = np.sin(2 * np.pi * (52 - 18 * t * 6) * t) * env(n, 0.01, 0.55) * np.exp(-t * 14)
    click = rng[:n] * np.exp(-t * 190) * 0.35
    rng[at:at + n] += (body + click) * gain
    return rng


def noise_hit(rng: np.ndarray, at: int, dur: float, gain: float, decay_rate: float, hp: bool) -> np.ndarray:
    n = int(dur * SR)
    if at + n >= len(rng):
        return rng
    x = rng[at:at + n]
    if hp:
        x = np.diff(x, prepend=0.0)
        x = np.diff(x, prepend=0.0)
    t = np.arange(n) / SR
    out = x * np.exp(-t * decay_rate)
    out -= out.mean()
    peak = np.max(np.abs(out)) or 1.0
    rng[at:at + n] += out / peak * gain
    return rng


def saw(freq: float, dur: float, detune: float) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    phase = 2 * np.pi * freq * t
    wave_ = np.zeros_like(t)
    for harm in range(1, 14):
        wave_ += np.sin(phase * harm + detune * harm) / harm
    return wave_ / 6.5


def lowpass(x: np.ndarray, alpha: float) -> np.ndarray:
    """One-pole IIR approximation by truncated exponential kernel (vectorized)."""
    tail = max(8, int(4.0 / alpha))
    kernel = alpha * np.exp(-np.arange(tail) * alpha)
    kernel /= kernel.sum()
    return np.convolve(x, kernel, mode="same")


def build_audio() -> None:
    rng = np.random.default_rng(7)
    mono = np.zeros(int(DURATION * SR) + SR)
    beat = 60.0 / 128.0
    roots = {"OPEN": 55.0, "BRACKET": 55.0, "ANALYZER": 73.42, "DOCKET": 65.41, "SETTLEMENT": 82.41, "CLOSE": 55.0}
    scene_of = lambda t: next(name for a, b, name in SCENES if a <= t < b)

    # percussion grid
    b = 0
    while b * beat < DURATION:
        at = int(b * beat * SR)
        mono = kick(mono, at, 0.85)
        if b % 2 == 1:
            mono = noise_hit(mono, at, 0.09, 0.16, 60, hp=True)
        if b % 4 in (1, 3):
            mono = noise_hit(mono, at, 0.16, 0.30, 26, hp=True)
        b += 1

    # sub bass eighths
    t = 0.0
    step = beat / 2
    i = 0
    while t < DURATION:
        at = int(t * SR)
        root = roots[scene_of(min(t, DURATION - 0.01))]
        f = root * (1.5 if i % 4 == 3 else 1.0)
        n = int(step * 0.9 * SR)
        tt = np.arange(n) / SR
        tone = np.sin(2 * np.pi * f * tt) * 0.55 + np.sin(2 * np.pi * f * 2 * tt) * 0.18
        tone *= env(n, 0.02, 0.4)
        if at + n < len(mono):
            mono[at:at + n] += tone * 0.34
        t += step
        i += 1

    # harmonic pad per scene
    for a, b_end, name in SCENES:
        root = roots[name]
        n = int((b_end - a) * SR)
        dur = n / SR
        pad = np.zeros(n)
        for mult, det in ((1.0, 0.0), (1.5, 0.4), (2.0, 1.1)):
            s = saw(root * mult * 2, dur, det)
            s = lowpass(s, 0.06)
            pad += s
        pad *= env(n, 0.25, 0.3) * 0.075
        mono[int(a * SR):int(a * SR) + n] += pad

    # risers into each scene change and impacts on scene starts
    for a, _b, _name in SCENES[1:]:
        n = int(1.4 * SR)
        at = max(0, int(a * SR) - n)
        tt = np.arange(n) / SR
        sweep = np.sin(2 * np.pi * (220 + 900 * (tt / 1.4) ** 2) * tt) * (tt / 1.4) ** 2
        mono[at:at + n] += sweep * 0.10
        mono = noise_hit(mono, int(a * SR), 0.5, 0.5, 14, hp=False)

    # sidechain duck from the kick grid
    duck = np.ones(len(mono))
    b = 0
    while b * beat < DURATION:
        at = int(b * beat * SR)
        n = int(0.19 * SR)
        if at + n < len(duck):
            duck[at:at + n] *= np.linspace(0.55, 1.0, n)
        b += 1
    mono *= duck

    # stereo width via short Haas offset on a duplicated bed
    shift = int(0.008 * SR)
    left = mono[: int(DURATION * SR)]
    right = np.concatenate([np.zeros(shift), mono[: int(DURATION * SR) - shift]])
    stereo = np.stack([left, right], axis=1)
    stereo = stereo / (np.max(np.abs(stereo)) or 1.0) * 0.86
    fade = int(1.2 * SR)
    stereo[:fade] *= np.linspace(0, 1, fade)[:, None]
    stereo[-fade:] *= np.linspace(1, 0, fade)[:, None]

    pcm = (stereo * 32767).astype(np.int16)
    with wave.open(AUDIO_WAV, "wb") as fh:
        fh.setnchannels(2)
        fh.setsampwidth(2)
        fh.setframerate(SR)
        fh.writeframes(pcm.tobytes())
    print(f"audio {AUDIO_WAV} {os.path.getsize(AUDIO_WAV)} bytes  {DURATION}s stereo")


# --------------------------------------------------------------------------- frames
class Reel:
    def __init__(self) -> None:
        self.f_h1 = font(True, 54)
        self.f_h2 = font(True, 34)
        self.f_h3 = font(True, 22)
        self.f_mono = font(False, 20)
        self.f_mono_s = font(False, 15)
        self.f_big = font(True, 88)
        logo_path = os.path.join(ROOT, "frontend", "public", "logo.png")
        self.logo = Image.open(logo_path).convert("RGBA").resize((150, 150), Image.Resampling.LANCZOS) if os.path.exists(logo_path) else None

    def base(self) -> Image.Image:
        img = Image.new("RGB", (W, H), OBSIDIAN)
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, W, 74], fill=PANEL)
        d.line([(0, 74), (W, 74)], fill=LIME, width=2)
        d.text((28, 22), "ARENA VERITAS", font=self.f_h2, fill=LIME)
        d.text((372, 34), "BROADCAST CONTROL ROOM  MATCH INTEGRITY DESK", font=self.f_mono_s, fill=STEEL)
        if self.logo:
            img.paste(self.logo, (W - 186, 4), self.logo)
        d.text((28, H - 30), "studionet  chain 61999", font=self.f_mono_s, fill=STEEL)
        return img

    def panel(self, d: ImageDraw.ImageDraw, box, title: str) -> None:
        d.rounded_rectangle(box, radius=10, fill=PANEL_2, outline=STEEL, width=1)
        d.text((box[0] + 18, box[1] + 12), title, font=self.f_h3, fill=FOG)

    def bar(self, d, x, y, w, h, frac, color) -> None:
        d.rectangle([x, y, x + w, y + h], fill=PANEL, outline=STEEL)
        d.rectangle([x + 1, y + 1, x + 1 + int(max(0.0, min(1.0, frac)) * (w - 2)), y + h - 1], fill=color)

    def frame(self, t: float) -> Image.Image:
        img = self.base()
        d = ImageDraw.Draw(img)
        scene = next(name for a, b, name in SCENES if a <= t < b)
        local = t - next(a for a, b, name in SCENES if a <= t < b)
        handler = getattr(self, f"scene_{scene.lower()}")
        handler(d, local)
        return img

    # scene renderers
    def scene_open(self, d, local) -> None:
        cx = W // 2
        pulse = 0.5 + 0.5 * math.sin(local * 3.4)
        d.text((cx, 210), "AI VERIFIED SETTLEMENT", font=self.f_big, fill=WHITE, anchor="mm")
        d.text((cx, 292), "esports  speedrun  anti-cheat integrity", font=self.f_h2, fill=LIME, anchor="mm")
        d.rectangle([cx - 300, 340, cx + 300, 346], fill=PANEL)
        d.rectangle([cx - 300, 340, cx - 300 + int(600 * min(1.0, local / 5.0)), 346], fill=LIME)
        for i, label in enumerate(["CONSENSUS VERIFIED EVIDENCE", "QUANTIZED VERDICT BANDS", "NON TRAPPING PAYABLES"]):
            d.text((cx, 392 + i * 40), label, font=self.f_mono, fill=STEEL if i else FOG, anchor="mm")
        d.ellipse([cx - 6, 566 - 6, cx + 6, 566 + 6], fill=(int(ROSE[0]), int(ROSE[1] * pulse + 40), int(ROSE[2])))
        d.text((cx + 22, 566), "LIVE", font=self.f_h3, fill=ROSE, anchor="lm")

    def scene_bracket(self, d, local) -> None:
        self.panel(d, [24, 92, 760, 560], "LIVE TOURNAMENT BRACKET")
        for i, (title, game, prize, status) in enumerate(BRACKETS):
            y = 150 + i * 96
            reveal = min(1.0, max(0.0, (local - i * 1.6) / 1.2))
            col = ROSE if status in ("VOID", "PROTESTED") else LIME if status == "ACTIVE" else STEEL
            d.rounded_rectangle([44, y, 740, y + 76], radius=8, fill=PANEL, outline=col, width=int(1 + 2 * reveal))
            d.text((60, y + 10), title, font=self.f_h3, fill=WHITE)
            d.text((60, y + 42), f"{game}   prize {prize} escrowed   bond 0.01 GEN per slot", font=self.f_mono_s, fill=STEEL)
            d.text((724, y + 12), status, font=self.f_h3, fill=col, anchor="ra")
            d.rectangle([44, y + 70, 44 + int(696 * reveal), y + 73], fill=col)
        self.panel(d, [780, 92, 1256, 300], "PRIZE CUSTODY TICKER")
        vault = 10.0 * min(1.0, local / 6.0)
        d.text((800, 148), f"{vault:5.2f} AVT", font=self.f_h1, fill=LIME, anchor="lm")
        d.text((800, 208), "vault custody balance", font=self.f_mono_s, fill=STEEL)
        escrow = 8.0 * min(1.0, local / 8.0)
        d.text((800, 236), f"escrowed prize {escrow:4.2f} AVT", font=self.f_mono_s, fill=FOG)
        d.text((800, 262), "invariant balanced", font=self.f_mono_s, fill=LIME)
        self.panel(d, [780, 320, 1256, 560], "SIGNER DEPOSITS")
        signers = [("finalist A", "0.01 GEN bond x3"), ("finalist B", "0.01 GEN bond x3"), ("bystander", "soft failed  refundable")]
        for i, (who, what) in enumerate(signers):
            if local < 3 + i * 2:
                break
            col = ROSE if i == 2 else LIME
            d.text((800, 372 + i * 52), who, font=self.f_h3, fill=col)
            d.text((800, 396 + i * 52), what, font=self.f_mono_s, fill=STEEL)

    def scene_analyzer(self, d, local) -> None:
        self.panel(d, [24, 92, 620, 560], "FRAME TICK  REPLAY INTEGRITY ANALYZER")
        frame_ticks = int(local * 30)
        d.rectangle([44, 150, 600, 154], fill=PANEL)
        for x in range(0, 556, 6):
            v = abs(math.sin((x + frame_ticks) * 0.05)) * 0.8 + 0.1
            d.rectangle([44 + x, 260 - int(v * 100), 44 + x + 3, 260], fill=LIME if v < 0.75 else ROSE)
        raw_integrity = 10000 - int(600 * abs(math.sin(local * 0.5)))
        raw_anomaly = 3800 + int(400 * math.sin(local * 0.9))
        qi = (raw_integrity // 500) * 500
        qa = (raw_anomaly // 500) * 500 + (500 if raw_anomaly % 500 >= 250 else 0)
        d.text((44, 300), f"raw integrity {raw_integrity} bps   quantized {qi} bps", font=self.f_mono, fill=FOG)
        d.text((44, 330), f"raw anomaly    {raw_anomaly} bps   quantized {qa} bps", font=self.f_mono, fill=FOG)
        d.text((44, 366), "grid step 500 bps  champion floor 8500  cheat ceiling 3000", font=self.f_mono_s, fill=STEEL)
        self.bar(d, 44, 400, 556, 26, qi / 10000, LIME)
        self.bar(d, 44, 440, 556, 26, qa / 10000, ROSE)
        band = "CHEAT_DISQUALIFICATION_SLASH" if qa >= 3000 else "VERIFIED_CHAMPION_PAYOUT" if qi >= 8500 and qa <= 1000 else "RULE_VIOLATION_PENALTY"
        d.text((44, 500), "derived band", font=self.f_mono_s, fill=STEEL)
        d.text((44, 522), band, font=self.f_h3, fill=ROSE if "CHEAT" in band else AMBER)
        self.panel(d, [640, 92, 1256, 560], "TELEMETRY SOURCES")
        for i, u in enumerate([
            "docs/evidence/cs2-major-telemetry.html",
            "docs/evidence/valorant-sovereign-telemetry.html",
            "docs/evidence/elden-ring-anypercent-telemetry.html",
            "docs/evidence/av-rulebook.html",
        ]):
            on = local > 1.2 * i
            d.text((660, 152 + i * 46), ("fetched  " if on else "pending  ") + u, font=self.f_mono_s, fill=LIME if on else STEEL)
        d.text((660, 340), "leader and every validator render each URL", font=self.f_mono, fill=FOG)
        d.text((660, 368), "independently on chain. A self reported claim", font=self.f_mono, fill=FOG)
        d.text((660, 396), "is never trusted. Missing evidence fails closed.", font=self.f_mono, fill=FOG)

    def scene_docket(self, d, local) -> None:
        self.panel(d, [24, 92, 640, 560], "REFEREE EQUIVALENCE CONSOLE")
        fields = ["verdict_band", "verified_winner_slot", "integrity_baseline_bps", "anomaly_bps", "champion_payout", "runner_up_payout", "bond_slash"]
        for i, f in enumerate(fields):
            done = local > 0.9 * i
            d.text((44, 150 + i * 42), f, font=self.f_mono, fill=FOG)
            d.text((470, 150 + i * 42), "exact match" if done else "waiting", font=self.f_mono_s, fill=LIME if done else STEEL)
        d.text((44, 470), "prompt_comparative requires 100 percent equality", font=self.f_mono, fill=WHITE)
        d.text((44, 498), "on all seven decision fields. No numeric tolerance.", font=self.f_mono, fill=WHITE)
        self.panel(d, [660, 92, 1256, 330], "PROTEST DOCKET")
        d.text((680, 150), "elden ring any percent WR", font=self.f_h3, fill=WHITE)
        d.text((680, 182), "filed by FINALIST_B against FINALIST_A", font=self.f_mono_s, fill=ROSE)
        d.text((680, 206), "protest bond locked 0.01 GEN native", font=self.f_mono_s, fill=STEEL)
        progress = min(1.0, local / 6.0)
        d.rectangle([680, 250, 1236, 254], fill=PANEL)
        d.rectangle([680, 250, 680 + int(556 * progress), 254], fill=ROSE)
        d.text((680, 270), "challenge window   match close  ->  protest deadline", font=self.f_mono_s, fill=STEEL)
        self.panel(d, [660, 350, 1256, 560], "VALIDATOR VOTES")
        for i in range(5):
            x = 690 + i * 116
            on = local > 1.4 + i * 0.8
            d.ellipse([x, 420, x + 78, 498], fill=PANEL, outline=LIME if on else STEEL, width=3)
            d.text((x + 39, 459), "AGREE" if on else "idle", font=self.f_mono_s, fill=LIME if on else STEEL, anchor="mm")

    def scene_settlement(self, d, local) -> None:
        self.panel(d, [24, 92, 1256, 300], "SETTLEMENT AFTER THE PROTEST DEADLINE")
        rows = [
            ("CS2 Major Grand Final", "VERIFIED_CHAMPION_PAYOUT", "2.00 AVT to champion"),
            ("Valorant Sovereign Cup", "SPLIT_DRAW_SETTLEMENT", "1.00 AVT each side"),
            ("Elden Ring Any% WR Check", "CHEAT_DISQUALIFICATION_SLASH", "bond slashed  prize to clean slot"),
            ("Dota 2 Saigon Invitational", "VOID_NO_CONTEST_REFUND", "escrow returned to organizer"),
        ]
        for i, (who, band, effect) in enumerate(rows):
            if local < i * 1.1:
                break
            col = ROSE if "CHEAT" in band or "VOID" in band else LIME
            d.text((52, 140 + i * 38), who, font=self.f_mono, fill=WHITE)
            d.text((560, 140 + i * 38), band, font=self.f_mono, fill=col)
            d.text((980, 140 + i * 38), effect, font=self.f_mono_s, fill=STEEL)
        self.panel(d, [24, 320, 1256, 560], "CUSTODY ACCOUNTING INVARIANT")
        vault = 10.0
        escrow = 8.0 * max(0.0, 1 - local / 5.0)
        ledger = vault - escrow
        d.text((52, 372), f"vault {vault:.2f} AVT  =  escrow {escrow:.2f}  +  paid out {ledger:.2f}", font=self.f_mono, fill=FOG)
        d.text((52, 404), f"native custody = bonds + protest + refundable credit", font=self.f_mono, fill=FOG)
        ok = local > 4.0
        d.text((52, 452), "asserted inside claim_tournament_settlement", font=self.f_mono_s, fill=STEEL)
        d.text((52, 478), "INVARIANT " + ("BALANCED" if ok else "CHECKING"), font=self.f_h2, fill=LIME if ok else AMBER)

    def scene_close(self, d, local) -> None:
        cx = W // 2
        d.text((cx, 250), "ARENA VERITAS", font=self.f_h1, fill=LIME, anchor="mm")
        d.text((cx, 322), CONTRACT, font=self.f_mono, fill=WHITE, anchor="mm")
        d.text((cx, 360), EXPLORER, font=self.f_mono_s, fill=STEEL, anchor="mm")
        d.text((cx, 430), "deploy verified on studionet  4 way source identity", font=self.f_mono_s, fill=FOG, anchor="mm")
        d.rectangle([cx - 260, 470, cx + 260, 474], fill=PANEL)
        d.rectangle([cx - 260, 470, cx - 260 + int(520 * min(1.0, local / 3.6)), 474], fill=LIME)


def encode(crf: int, preset: str) -> int:
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    out = os.path.join(BUILD, "demo-video-subtitled.mp4")
    reel = Reel()
    cmd = [
        ff, "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "pipe:",
        "-i", os.path.abspath(AUDIO_WAV),
        "-vf", "subtitles=captions.ass",
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-movflags", "+faststart", "-shortest", "-t", f"{DURATION}",
        out,
    ]
    err_path = os.path.join(BUILD, "ffmpeg-stderr.log")
    with open(err_path, "wb") as err_file:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=err_file, cwd=BUILD)
        assert proc.stdin is not None
        total = int(DURATION * FPS)
        for n in range(total):
            img = reel.frame(n / FPS)
            proc.stdin.write(img.tobytes())
            if n % 150 == 0:
                print(f"frame {n}/{total}", flush=True)
        proc.stdin.close()
        code = proc.wait()
    if code != 0:
        print(open(err_path, "rb").read().decode("utf-8", "replace")[-2000:], file=sys.stderr)
        raise SystemExit(f"ffmpeg failed with exit {code}")
    return os.path.getsize(out)


def main() -> None:
    os.makedirs(BUILD, exist_ok=True)
    write_caption_files()
    print("captions written", flush=True)
    build_audio()
    crf, preset = 23, "medium"
    size = encode(crf, preset)
    while size > SIZE_CEILING and crf < 34:
        crf += 3
        preset = "veryfast"
        print(f"re-encode at crf {crf} to fit the size ceiling")
        size = encode(crf, preset)
    if size > SIZE_CEILING:
        raise SystemExit(f"video is {size} bytes which still exceeds 15 MB")
    for target in TARGETS:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(os.path.join(BUILD, "demo-video-subtitled.mp4"), target)
    digest = hashlib.sha256(open(TARGETS[0], "rb").read()).hexdigest()
    print(f"video {size} bytes  crf {crf}  {W}x{H} {DURATION}s  sha256 {digest[:16]}")
    for target in TARGETS:
        print("  wrote", os.path.relpath(target, ROOT))


if __name__ == "__main__":
    main()
