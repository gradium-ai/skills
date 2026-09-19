# MiniMax designed-avatar example

One demonstration clip produced with the `gradium-minimax-designed-avatar`
skill, end to end from the skill's own script: a voice was designed in Gradium
Voice Design to fit the portrait (two candidates were auditioned and rejected
before the third was promoted), the script was synthesized with Gradium TTS,
and MiniMax H3 Max lip-sync on fal.ai animated the portrait from that audio in
a single generation. The portrait is a synthetic image; no real person is
depicted, and "Callum" is a fictional character in a scripted performance.

The file here is a 480 px preview re-encoded for the repository; the skill
rendered at 768P (768x1024).

| Clip | Character | Length | What to look for |
| --- | --- | --- | --- |
| [highland-guide-callum.mp4](highland-guide-callum.mp4) | Callum, a Highlands tour guide welcoming the week's group | 12.8 s | A warm Scottish voice in his early 40s designed from a one-paragraph description; a 34-word script fitted inside MiniMax's 14.8 s window; steady lip-sync on a relaxed pace with a natural blink as the model leaves the still image |

Voice description used:

```text
A warm, resonant male voice in his early 40s: a mature adult voice with youthful
vitality, clearly not an older man. Medium-low pitch, natural Scottish accent.
Smooth and rich with only a faint touch of texture, gently tapped r sounds,
rounded vowels, and an easy melodic lilt. Relaxed, conversational pace with clear
articulation and unhurried pauses. Grounded, friendly, energetic, quietly
confident, with a hint of dry humour. Authentic and easy to understand, without
exaggeration.
```

Script (34 words, 12.7 s of speech):

```text
Welcome to the Highlands. I'm Callum, and I'll be your guide this week. Bring
good boots, an open mind, and a healthy appetite. The weather does what it
likes, but the whisky never disappoints.
```

To make your own, install the skill and ask:

```text
Use $gradium-minimax-designed-avatar to make a short clip of portrait.png
introducing our Highlands tour. Voice: warm Scottish male, early 40s, dry humour.
```

The skill auditions one voice candidate at a time, asks you to approve it,
checks that the script fits 14.8 seconds, submits one fal generation, and
grades the result before showing it to you.
