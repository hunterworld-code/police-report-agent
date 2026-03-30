# Scam Call Police Reporting Agent

This project creates a small AI-powered service that turns scam-call details into a police-ready, non-emergency report.

It does three things:

1. Accepts scam-call intake details through an API.
2. Uses the OpenAI Responses API to produce a strict JSON incident report.
3. Saves both JSON and Markdown copies locally, and can optionally forward the report to a configured webhook.
4. Can email the report automatically in professional Arabic to a configured recipient.

It also includes a browser UI on `/` so you can submit reports without using `curl`.
It now also includes Twilio-compatible voice webhook endpoints so a phone number can host a live AI phone conversation, answer caller questions, ask follow-up questions, and then save the final incident bundle after the call.

## Safety note

This service is designed for non-emergency reporting workflows. It does not call emergency services and should not be used when someone is in immediate danger.

## Requirements

- Python 3.9+
- An OpenAI API key

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set your `.env` values:

```env
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-5.4-mini
POLICE_REPORT_WEBHOOK_URL=
AUTO_FORWARD_REPORTS=false
WEBHOOK_AUTH_HEADER_NAME=Authorization
WEBHOOK_AUTH_HEADER_VALUE=Bearer replace-me
REPORT_STORAGE_DIR=reports
REPORT_LANGUAGE=ar
AUTO_EMAIL_REPORTS=true
EMAIL_TO_ADDRESS=hunterworld@gmail.com
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=
SMTP_USE_TLS=true
PUBLIC_BASE_URL=
TWILIO_AGENT_PHONE_NUMBER=
TWILIO_REPORTING_PHONE_NUMBER=
TWILIO_AUTH_TOKEN=
TWILIO_DEFAULT_COUNTRY=
TWILIO_DEFAULT_CITY=
TWILIO_GATHER_LANGUAGE=ar-SA
TWILIO_AUTO_FORWARD_REPORTS=false
TWILIO_VOICE_MODE=conversation
TWILIO_REALTIME_MODEL=gpt-realtime-mini
TWILIO_TRANSCRIPTION_MODEL=gpt-4o-mini-transcribe
TWILIO_AGENT_VOICE=marin
TWILIO_AGENT_LANGUAGE=ar
TWILIO_AGENT_SPEED=1.0
WHATSAPP_CHAT_MODEL=gpt-5.4-mini
```

## Run

```bash
uvicorn app.main:app --reload
```

Open the docs at `http://127.0.0.1:8000/docs`.
Open the browser form at `http://127.0.0.1:8000/`.

## Deploy on Render

This repo now includes a Render blueprint at `render.yaml`.

Quick deploy steps:

1. Push this project to GitHub.
2. In Render, create a new Blueprint and point it at the repo.
3. Render will detect `render.yaml` and create one Python web service.
4. Fill in the secret environment variables Render prompts for, especially:
   - `OPENAI_API_KEY`
   - `SMTP_HOST`
   - `SMTP_USERNAME`
   - `SMTP_PASSWORD`
   - `SMTP_FROM_EMAIL`
   - `TWILIO_REPORTING_PHONE_NUMBER`
   - `TWILIO_AUTH_TOKEN`
   - `TWILIO_DEFAULT_COUNTRY`
   - `TWILIO_DEFAULT_CITY`
5. Deploy the service.

Render automatically provides a public URL for the service, and the app now uses Render's `RENDER_EXTERNAL_URL` automatically. That means `PUBLIC_BASE_URL` is optional on Render unless you later move to a custom domain.

After deploy, point Twilio to:

```text
https://your-service-name.onrender.com/twilio/voice/incoming
https://your-service-name.onrender.com/twilio/whatsapp/incoming
```

Important notes for Render:

- The included `render.yaml` uses the `free` plan by default so it does not surprise you with charges.
- For real Twilio voice and WhatsApp use, Render `starter` or higher is strongly recommended because free services can sleep when idle.
- Report files saved to the local filesystem are ephemeral unless you attach a persistent disk.
- If you add a persistent disk on Render, set `REPORT_STORAGE_DIR=/opt/render/project/src/reports` so saved PDF, JSON, and Markdown files persist across restarts.

## Example request

```bash
curl -X POST http://127.0.0.1:8000/reports \
  -H "Content-Type: application/json" \
  -d @sample_report_request.json
```

## Browser workflow

1. Open `http://127.0.0.1:8000/`.
2. Fill out the intake form.
3. Submit the transcript or detailed call summary.
4. Review the generated report, saved file paths, and forwarding status in the result panel.

## Phone call workflow

This app can now run in two phone modes:

- `conversation` mode, which is the default, for a live AI phone conversation over Twilio Media Streams
- `gather` mode, which uses the older one-shot speech capture and then writes the report

In `conversation` mode, the AI speaks with the caller naturally, asks follow-up questions, answers practical questions, and prepares the written report after the call ends.
It is tuned for suspected scam calls and tries to keep the caller talking in a calm, wandering, human-sounding conversation while collecting details for the final report.

1. Run the app locally or deploy it somewhere Twilio can reach over HTTPS.
2. Set `PUBLIC_BASE_URL` to that public HTTPS base URL.
3. Buy or assign one Twilio voice number for the scammer-facing bait line and, if you want a separate victim reporting line, buy or assign a second voice number.
4. Put the scammer-facing number in `TWILIO_AGENT_PHONE_NUMBER`.
5. Put the victim reporting number in `TWILIO_REPORTING_PHONE_NUMBER`.
6. Add your Twilio Auth Token to `TWILIO_AUTH_TOKEN` if you want request signature validation enabled.
7. In the Twilio settings for each phone number, point the incoming voice webhook to:

```text
https://your-public-host/twilio/voice/incoming
```

8. Calls to `TWILIO_AGENT_PHONE_NUMBER` use the neutral scammer-facing opener and try to keep the caller talking.
9. Calls to `TWILIO_REPORTING_PHONE_NUMBER` use the transparent reporting opener and help the caller document the scam.
10. When the call ends, the app will save the generated report in `reports/`, optionally email it, and optionally forward it if enabled.

Recommended practice:

- Use a separate Twilio number for this agent instead of your personal line.
- Use two separate Twilio numbers if you want one line for suspected scammers and one line for victims reporting scams.
- Do not let the agent provide real passwords, OTP codes, banking details, or remote access.
- Review local laws and provider rules before recording or retaining call content.

In `conversation` mode, the incoming webhook returns TwiML with `<Connect><Stream>` and Twilio opens a bidirectional WebSocket stream to `/twilio/voice/media-stream`.
If you set `TWILIO_VOICE_MODE=gather`, the app uses the older speech-capture route and posts to `/twilio/voice/process-speech`.

## Local testing for phone calls

Twilio needs a public URL for live webhooks. For local development, use any HTTPS tunnel or deploy the app to a reachable server, then set that public address as `PUBLIC_BASE_URL`.

You can still test the legacy gather route locally without Twilio by posting form data:

```bash
curl -X POST http://127.0.0.1:8000/twilio/voice/process-speech \
  -d "From=%2B971500000000" \
  -d "SpeechResult=The caller pretended to be from my bank and asked for my OTP code." \
  -d "CallSid=CA1234567890"
```

The live conversation route needs a real Twilio Media Stream because it runs over a WebSocket and relays bidirectional `audio/x-mulaw` audio between Twilio and the OpenAI Realtime API.

## WhatsApp workflow

The app can also run as a conversational Arabic assistant over Twilio WhatsApp webhooks.

1. In Twilio, configure your WhatsApp sender or sandbox inbound webhook to:

```text
https://your-public-host/twilio/whatsapp/incoming
```

2. Send a WhatsApp message describing the scam.
3. The AI will reply in Arabic, ask follow-up questions, and continue the conversation across multiple messages.
4. When the user is done, they can send `تم` or `أرسل التقرير`.
5. The app will then generate the Arabic police-style report, save it locally, and optionally email it.
6. If `PUBLIC_BASE_URL` is configured and reachable, the WhatsApp reply will also attach a PDF copy of the report.

Expected Twilio webhook fields include:

- `Body`
- `From`
- `MessageSid`
- `NumMedia`
- `MediaUrl0`

Conversation memory is stored locally per WhatsApp sender under the report storage directory so the AI can continue the chat between messages.

## Output

Each report is saved under `reports/` as:

- A PDF report suitable for email and WhatsApp sharing
- A JSON bundle with the intake and generated report
- A Markdown file you can review or submit manually

The generated report content and Markdown layout are now written in professional Arabic by default.

## Email delivery

If SMTP is configured, the app will automatically email each generated report to `hunterworld@gmail.com` by default.

Required `.env` fields for email:

```env
AUTO_EMAIL_REPORTS=true
EMAIL_TO_ADDRESS=hunterworld@gmail.com
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=your_smtp_username
SMTP_PASSWORD=your_smtp_password
SMTP_FROM_EMAIL=your_sender@example.com
SMTP_USE_TLS=true
```

The email includes:

- A professional Arabic summary in the email body
- The generated PDF report as an attachment
- The generated Markdown report as an attachment
- The JSON report bundle as an attachment

## Forwarding behavior

External forwarding only happens when all of these are true:

- The request sets `"wants_forwarding": true`
- `AUTO_FORWARD_REPORTS=true`
- `POLICE_REPORT_WEBHOOK_URL` is configured

That default makes the app safer by keeping a human in the loop unless you intentionally enable automation.
