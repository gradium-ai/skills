# Pruna designed-avatar examples

Three fictional demonstration clips produced with the `gradium-pruna-designed-avatar` skill. In each, a
portrait was paired with a voice designed in Gradium Voice Design to fit the
character, the script was synthesized with Gradium TTS, and Pruna
`p-video-avatar` animated the portrait from that audio. Every portrait and voice is
AI-generated; no real person is depicted. These are scripted performances, not
real customer accounts. The supplement clip makes no substantiated product or
health claim; its video and poster carry a permanent fictional-performance label.

The files here are 480 px previews re-encoded for the repository; the skill
renders at 720p or 1080p.

| Clip | Character | Length | What to look for |
| --- | --- | --- | --- |
| [support-agent-maya.mp4](support-agent-maya.mp4) | Maya, a support agent at a fictional ISP walking a customer through a router reset | 25 s | Bright, clear customer-support voice matched to a friendly on-camera presence; steady lip-sync on short instructional sentences |
| [insurance-guide-arthur.mp4](insurance-guide-arthur.mp4) | Arthur, an in-app guide for an insurance application | 35 s | Calm, older, reassuring voice designed to fit the portrait; natural pacing over a longer script |
| [supplement-testimonial.mp4](supplement-testimonial.mp4) | A fictional creator performance, visibly labeled as an AI demo | 24 s | Casual British delivery in a handheld, user-generated-content framing; square 1:1 output |

To make your own, install the skill and ask:

```text
Use $gradium-pruna-designed-avatar to create a talking-avatar video from
portrait.png. The character is a calm, older guide for an insurance app.
Script: "Hi, I'm Arthur ..."
```

The skill will audition one voice candidate, ask you to approve it, then submit
a single Pruna render and grade the result before showing it to you.
