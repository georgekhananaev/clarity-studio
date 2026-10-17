"""Create an explicitly labeled local sample. No network or speech API calls."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw, ImageFont
from clarity.media import probe, run
from clarity.models import Cue
from clarity.store import Store


def main():
    store = Store()
    existing = next((p for p in store.list() if p.title == "A clearer walkthrough · Sample"), None)
    if existing:
        print(existing.id)
        return
    directory = store.root / "_sample"
    directory.mkdir(exist_ok=True)
    font_path = "/System/Library/Fonts/Helvetica.ttc"
    large = ImageFont.truetype(font_path, 45)
    medium = ImageFont.truetype(font_path, 23)
    small = ImageFont.truetype(font_path, 17)
    states = [
        ("01", "Make room for a clear explanation.", "Start with the action you want to show.", 0),
        ("02", "Give each moment a few words.", "A short sentence can make a big difference.", 1),
        ("03", "Keep the story in sync.", "Review your captions, then share the recording.", 2),
    ]
    for index, (step, title, subtitle, active) in enumerate(states):
        image = Image.new("RGB", (1280, 720), "#e9ede3")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((24, 24, 1256, 696), 18, fill="#f7f8f3", outline="#c6cfc0", width=2)
        draw.rounded_rectangle((24, 24, 1256, 86), 18, fill="#dce4d4")
        draw.rectangle((25, 58, 1255, 86), fill="#dce4d4")
        for x, color in [(53, "#aa927c"), (77, "#b4b77e"), (101, "#8fa478")]:
            draw.ellipse((x, 48, x + 11, 59), fill=color)
        draw.text((530, 43), "CLARITY / SAMPLE", fill="#687b5d", font=small)
        draw.rounded_rectangle((63, 125, 1217, 624), 14, fill="#edf1e8", outline="#d4ddcb", width=2)
        draw.rounded_rectangle((100, 164, 181, 245), 20, fill="#c8dcb5")
        draw.text((115, 180), step, fill="#49613c", font=large)
        draw.text((103, 287), title, fill="#2c4227", font=large)
        draw.text((105, 359), subtitle, fill="#7b8f6e", font=medium)
        for item in range(3):
            x = 105 + item * 335
            draw.rounded_rectangle((x, 443, x + 300, 543), 12, fill="#d7e6cb" if item == active else "#e2e8dc", outline="#91aa7c" if item == active else "#ccd7c3", width=2)
            draw.text((x + 22, 465), ["Add a recording", "Write the explanation", "Preview & export"][item], fill="#4c6640" if item == active else "#91a086", font=medium)
            draw.text((x + 23, 505), ["Your original stays yours", "One moment at a time", "Words and actions, together"][item], fill="#7e9271", font=small)
        draw.text((65, 655), "SAMPLE RECORDING  /  This is a demonstration, not your video.", fill="#94a388", font=small)
        image.save(directory / f"state-{index}.png")
    video = directory / "sample-walkthrough.mp4"
    playlist = directory / "scenes.txt"
    playlist.write_text("".join(f"file 'state-{i}.png'\nduration 4\n" for i in range(3)) + "file 'state-2.png'\n")
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(playlist), "-vf", "fps=24", "-t", "12", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(video)])
    project = store.create(probe(video), "A clearer walkthrough · Sample")
    project = store.update(project.id, [
        Cue(start=0.4, end=3.7, text="Start by adding your screen recording."),
        Cue(start=4.2, end=7.7, text="Add a short explanation for each action."),
        Cue(start=8.2, end=11.8, text="Review the timing, then export your subtitles."),
    ], 0)
    print(project.id)


if __name__ == "__main__":
    main()
