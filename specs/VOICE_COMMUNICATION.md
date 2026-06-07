# Product Split:
### 1. Direct Conversation
```
Every agent should be reachable like a person:
text them, call them, email them, or summon them from Pidgin.
```
### 2. Meeting Participation
```
Agents are invited to meetings like coworkers.
```

Both modes are needed for the MVP. However, to simplify, we'll focus on only one option for each.

1. Web Voice Button for immediate conversation
2. Recall.ai or equivalent for meeting joining





# Reference
Part of what makes an agent useful is that you could talk to it. This is a must for the MVP phase


Our options are these:
| Option                       |    Simplicity | Good for                       | Notes                                                                                                                                                                                                                      |
| ---------------------------- | ------------: | ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Phone call**               |   **Easiest** | Real voice conversation        | Twilio has bidirectional media streams: your server receives call audio and sends generated audio back into the call. Good fit for AI voice agents. ([Twilio][1])                                                          |
| **Web voice button**         | **Very easy** | “Talk to Jane” inside your app | Browser mic → STT → agent → TTS. No telecom, no Zoom, no install.                                                                                                                                                          |
| **Slack text / audio clips** |          Easy | Workplace agent UX             | Slack is great for text, but live Huddles are not cleanly programmable as a voice-agent surface; Slack Huddles are designed for human real-time coworking. ([Slack][2])                                                    |
| **WhatsApp voice**           |        Medium | Consumer-like UX               | WhatsApp Business Calling API exists, but platform policy and availability are moving targets. ([WhatsApp for Business][3])                                                                                                |
| **Google Meet / Zoom**       |        Harder | Formal meetings                | Better when the agent joins scheduled meetings, not for quick “talk to my agent.” Google Meet now has a Media API for real-time meeting media, but it’s still a meeting-platform integration. ([Google for Developers][4]) |

[1]: https://www.twilio.com/docs/voice/media-streams?utm_source=chatgpt.com "Media Streams Overview"
[2]: https://slack.com/help/articles/4402059015315-Use-huddles-in-Slack?utm_source=chatgpt.com "Use huddles in Slack"
[3]: https://business.whatsapp.com/blog/whatsapp-business-calling-api?utm_source=chatgpt.com "Announcing Launch of the WhatsApp Business Calling API"
[4]: https://developers.google.com/workspace/meet/media-api/guides/overview?utm_source=chatgpt.com "Meet Media API overview"


Options:
Deepgram - Not great on quality
ElevenLabs - actually great! Saw some post regarding latency when scaling up
OpenAI voice - 