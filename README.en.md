<!-- README decision pending 2 (English name): default = "Call Locate", taken from the repository folder name call-locate. Pending 3 (what the top leads with): default = the service as the title, the scored engine in the second paragraph under the image and the "Ordinance engine (scored API)" section. The service name is not decided yet either (11-21): when it is, change the h1 in both versions. -->
<h1 align="center">Call Locate (통화로 위치 좁히기)</h1>

<h3 align="center">Even when the caller cannot give an address, we narrow down the place through the call, find the basis in the ordinance text, and turn it into one intake case.</h3>

<!-- Demo place (PM decision, 11-21): the street near Lotte World Tower → Jamsil Station Exit 1. The two images below were taken in saved-answers mode from main 08bd360 (second batch #157, Korean option names; step 2 question "who rescues it and where is it cared for?"). If the place or script changes again, retake them with the README image tool in `_orch-tools` and update the place, radius, lot number, and handoff office in both captions -->
<p align="center">
  <img src="docs/img/readme/call-narrowing.png" alt="The light agent screen during a call. The live transcript is on the left, the next question and the ordinance answer are at the top center, the map shows a blue candidate area with a radius of about 200 m and landmarks to ask about, and the intake card is on the right." width="80%">
  <br>
  <sub>The agent screen during a call (in Korean). It replays a made-up call the team wrote, in "saved answers" mode (see <a href="#how-one-call-goes">How one call goes</a>).</sub>
</p>

<p align="center">General complaint lines such as 120 cannot get the caller's location, so the call agent hears the place in words. This screen reads location clues from what the caller says, shrinks the area on the map, and shows one next question to ask. When the place is fixed, the intake card gets the lot number and the office in charge, and if the case falls under one of the six Seoul ordinances, the screen adds an answer based on the ordinance.</p>

<p align="center">
  <b>Try it</b> — the address of the demo screen for judges is in the LMS submission. To run it on your own computer without an API key, follow <a href="#getting-started">Getting started</a>.<br>
  This is Team GG's repository for the Upstage track, "Public law Q&A AI with Upstage AI Studio", of the 2026 AI Bootcamp Competition. It holds the <b>ordinance Q&A engine</b> (<code>engine/</code>, the API the contest scores) and the <b>demo screen</b> built on it (<code>demo/call/</code>).
</p>

<p align="center">
  <a href="README.md">한국어</a> · <b>English</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10--3.13-3776AB?logo=python&logoColor=white" alt="Python 3.10 to 3.13">
  <img src="https://img.shields.io/badge/FastAPI-0.162-009688?logo=fastapi&logoColor=white" alt="FastAPI 0.162">
  <img src="https://img.shields.io/badge/Upstage-solar--pro4%20%C2%B7%20solar--embedding--2%20%C2%B7%20Document%20Parse-5B4CF5" alt="Upstage solar-pro4 · solar-embedding-2 · Document Parse">
  <img src="https://img.shields.io/badge/MapLibre%20GL-5.6-396CB2" alt="MapLibre GL 5.6">
</p>

<p align="center">
  <a href="#getting-started"><b>Run it on your computer</b></a> •
  <a href="#how-one-call-goes">How one call goes</a> •
  <a href="#features">Features</a> •
  <a href="#architecture-and-models">Architecture and models</a> •
  <a href="#measurements">Measurements</a> •
  <a href="#what-you-should-know">What you should know</a> •
  <a href="#license">License</a>
</p>

---

## How one call goes

> [!NOTE]
> The service and these screenshots are in Korean. The call is a made-up call the team wrote. It is not a real complaint or a real person, the agent's name tag is "상담사 A" (Agent A), and the caller's phone number ("민원인 연락처") is made up with the middle digits hidden. The scripted scene was played in "saved answers" mode: the team ran the script once with real calls, saved the Upstage model responses, and replays them for the same words.

Four steps at the top of the screen show where the call is.

1. **Hear the situation.** The caller's words come in one line at a time. In the demo, they come from a script or are typed in.
2. **Narrow down the place.** For each line, code reads names and relations and shows the area and the next question right away. Then solar-pro4 reads the same line once more and corrects the place name, relation, and what happened. If the case is one to ask the ordinances about, the screen asks the engine once the case type and place type are known.
3. **Confirm.** When the area is within a 50 m radius (a 200 m stretch on a road), the screen reads the narrowed place back ("…is that right?"). The pin drops only after the caller says yes. If the caller says no, it lowers the chance of that place and keeps narrowing.
4. **Hand off.** From the fixed place it decides the lot number and the office, fills the intake card, and saves the case to the records. The agent sets the status to "handed to the office" (the scripted scene shows it as already chosen). When the call ends, "다음 전화 받기" (Take next call) and "상담 기록 보기" (View records) buttons appear. The demo does not file or send anything for real; the status changes only inside the screen.

<p align="center">
  <img src="docs/img/readme/call-handoff.png" alt="The light agent screen after the call. The map has a fixed pin, the next-question box shows the closing words, the bottom left has Take next call and View records buttons, and the intake card on the right shows the lot number, the office in charge, past records nearby, the status, and a reference table." width="100%">
</p>

- **During the call (the image at the top).** "It's by the street near Lotte World Tower, on the way out from Jamsil Station. I don't know the lot number." shrinks the area from all of Seoul to a radius of about 200 m, and the next question ("What do you see right in front of you?") appears in "지금 물을 말" (What to ask now) with landmark names to pick from (the options read aloud are Korean names; the landmark chips also show English names as written in the map data). For "If I report an injured cat, who rescues it and where is it cared for?", the "조례 근거 답" (Ordinance answer) box shows a draft and the cited articles (Animal Protection Ordinance, Article 10(1) and 10(3)). Even before the place is fixed, the intake card already shows "민원인이 한 말" (what the caller said).
- **After the call (this image).** "Right in front of Jamsil Station Exit 1" shrinks the area to a radius of about 40 m. The caller says yes to "Songpa-gu, Jamsil 6-dong, right in front of Jamsil Station Exit 1, is that right?", so the place is fixed. The intake card shows the lot number "near 8 Sincheon-dong, Songpa-gu (nearest building, about 90 m)" and the office "Songpa-gu Office animal protection team · the animal shelter the district office designated". At the bottom, a reference table shows how the handoff changes with "alive or dead, and where it is".

## Why we built it

Some complaints depend on the location (an injured animal, a dead animal on the road, a broken road), because someone has to go to the spot. But a place heard over the phone may not be exact.

| What we checked | Source |
| --- | --- |
| The law lets only the special numbers 119, 122, and 112 get the caller's location from the call. 120 is not one of them. To get a location, 120 needs the caller's separate consent | Act on the Protection, Use, etc. of Location Information, Article 15(1) and Article 29, and its Enforcement Decree, Article 29 |
| In 2025, 120 handled 6,443,378 consultations. Phone calls were the largest channel at 3,310,889 (51.4%) | Seoul 120 Dasan Call Foundation, reply to an information disclosure request (2026-11-17) |
| Field workers find places by lot number, but callers describe them like "from the ○○ intersection toward ○○", so the field worker has to guess. If they cannot find it, they call the caller back | One phone call with a road complaint officer at a district office (2026-11-17). This is one person's account, and "they call back" was an answer to a question we asked first |

So we narrow down the place during the call. Each source and how to use it carefully is in the [evidence notes](docs/call-locate/근거.md) (Korean).

## Features

- 🗣️ **Reads location clues from speech.** It finds names in a place list (143,988 OpenStreetMap places and 348,712 small-business records) and uses the words right after a name to tell "right in front of", "near", "past", and "before reaching". It also handles real speech and speech-to-text mistakes (see the folded section below).
- ❓ **Shows only one next question.** It computes which question splits the remaining candidates most evenly. Questions that change the handoff office (is the animal alive, is it inside a park or on the street) come first.
- 🗂️ **Fills the intake card.** It writes a line for finding the spot, the lot number of the nearest building with its distance, map coordinates, and the office in charge. The office line also says whether it was "confirmed in official guidance" or is "not yet confirmed (a guess)".
- 📜 **Adds the ordinance answer.** If the case falls under the six ordinances, a draft the engine made from the ordinance and the cited articles stay in the same box during the whole call. Clicking an article number shows the article text, effective date, and source link in that box.
- 🏫 **Knows large places and intersection names.** For schools, stations, large stores and similar places bigger than 60 m, it adds their size to the area, and it reads lakes, park trails, and the edges of plazas as their perimeter. It understands 994 names of major intersections in Seoul.
- 🗒️ **Keeps consultation records.** Calls with a confirmed place are saved, and past records nearby (within 400 m) appear on the intake card and the map. Each record can open "그때 나눈 대화" (the conversation at the time).
- 🏙️ **Draws buildings at their real height.** 68,197 Seoul buildings that are taller in reality than in the map tiles are redrawn with heights from Seoul's building data. Add `?heights=off` to the address to turn this off.
- 📱 **Works on a phone.** Upright or sideways, nothing is hidden: the boxes stack in one column.
- 🙅 **Says when it does not know.** The engine answers "확인 불가" (cannot confirm) when it finds no basis, and the screen writes what is missing as it is, for example "not yet confirmed (a guess)" or "no lot number (inside a park)".

<details>
<summary><b>Features in more detail (speech fixes · intake card · ordinance answer · calls you turn on with a switch)</b></summary>

- **Real speech (on by default, `SPEECH_ON` in `demo/call/locate.py`).** "A few minutes' walk", saying where you are now apart from where you saw it, "not X but Y", "across from", "from A toward B", giving only an exit number, naming a brand and its branch separately, giving an address, and more. A name the caller takes back ("oh, no, wait") is dropped.
- **Speech-to-text mistakes (`STT_ON`).** Station names split or off by one letter, numbers written out in Korean words, particles after a name, and "no" (아니에요) to the inside-or-outside-the-park question.
- **Fixes for the failures from the 11/19 field test (on by default).** Common words such as "spot", "here", and "near" (자리 · 여기 · 근처) are not read as shop names. An area that is already narrow cannot jump several kilometers on one line. "Yes, but not right in front, a bit to the side" is not read as "no" when the screen reads the place back.
- **When the Upstage model reads a line again.** It can no longer move the area or the case to something the caller did not say. If the caller answers the read-back with a question ("Sorry? What?") or sounds unsure, the screen asks once more instead of fixing the place.
- **Questions.** A case question that has been answered is not asked again later in the call.
- **Large places.** It does not drop a pin in their center. An example of an intersection name is "강남역사거리".
- **Intake card.** If the agent picks a different case type in "일" (Case), the screen keeps the call text and the area and decides the office and whether the six ordinances apply again. The status has five steps: received, handed to the office, in progress, not found on site / call back, and done.
- **Ordinance answer.** The screen tells the agent not to read the draft as is but to judge and explain in their own words, and the answer and cited articles can be copied. For smoking on the street, smoke-free areas are set as places rather than "the street", so once the place is narrowed, the question to the engine includes the nearest bus stop or subway exit. A kick scooter left at a Ttareungyi (Seoul public bike) station or rack is handled as a bicycle ordinance case. What the ordinances do not cover is written as it is, for example "the six Seoul ordinances have no article on handling animal carcasses".
- **Building heights.** The buildings in the script get a roof outline. The heights in Seoul's data are not measured; they are floors × 3.5 m.
- **Phone.** Upright (width under 600 px) or sideways (height under 500 px), the boxes stack in this order: the chat (with the input box), what to ask now, the ordinance answer, the location area, and the intake card.
- **Records.** Each record keeps what was said in the call, and "the conversation at the time" starts folded.
- **Second batch on 11-21 (on by default).** A bridge or overpass longer than 120 m is read as the whole bridge when the caller gives only its name, not as its center point, and "the ○○ end" is read as that end of the bridge. When the same kind of location question would come twice in a row, the screen acknowledges what it heard and asks in different words. Options read aloud are swapped for Korean names (for example "Possibilites" → "롯데콘서트홀"). If the caller only says "I can see ○○", it is taken as the distance at which it can be seen, not "right in front".
- **Handoff fixes (11-21).** Road damage and streetlights on Han River bridges go to the Seoul Metropolitan Government, cases inside Olympic Park to the Korea Sports Promotion Foundation, Cheonggyecheon to the Seoul Facilities Corporation, and cases the caller says are inside a subway station to the operator of that station.
- **Calls you turn on with a switch (off by default).** `CALL_DIRECT=1` is the direct call: a visitor plays the caller and types, and the next line the screen picked and the ordinance answer appear in the chat as the agent's words (an access code and usage limits can be set). `CALL_VOICE=1` is a voice call placed and answered from a phone browser, turned on only on the presentation server (see "What you should know" 4). Details are in [`demo/call/voice/README.md`](demo/call/voice/README.md) (Korean).

</details>

## Architecture and models

Every model call is a single call that returns set items (JSON), and code decides what happens next. Things that must not be made up, such as place names, article names, source links, and effective dates, come only from tables and the ordinance text.

```mermaid
flowchart LR
  Say["Caller's words (text)"] --> Find["Find names · read relations<br>code + place list"]
  Find --> Read["Read again<br>solar-pro4"]
  Read --> Narrow["Compute area · pick next question<br>code"]
  Narrow -.->|next question| Say
  Narrow -->|when narrow enough| Confirm["Read back to confirm<br>code + caller's yes"]
  Confirm --> Route["Handoff office · lot number<br>handoff table · address list"]
  Narrow -->|when case and place type are known| Ask["Write the question<br>solar-pro4"]
  Ask --> Engine["Ordinance engine<br>solar-embedding-2-query · solar-pro4"]
  Engine --> Card["Intake card"]
  Route --> Card

  classDef model fill:#ede9fe,stroke:#6d28d9,color:#2e1065
  classDef code fill:#e0f2fe,stroke:#0369a1,color:#0c4a6e
  classDef data fill:#dcfce7,stroke:#15803d,color:#14532d
  class Read,Ask,Engine model
  class Narrow,Confirm,Card code
  class Find,Route data
```

Purple is an Upstage model call, blue is code, and green is a table or data lookup (code does the lookup in green boxes too).

### Upstage models by stage

The table follows the five stages the contest notice asked teams to describe. We checked the model names in `engine/config.py` and in the calls in each file.

| Stage | What we do | Upstage model |
| --- | --- | --- |
| Collection | The original text of the six Seoul ordinances is kept as a data file (`engine/data/ordinances.json`), with the source link and effective date for each | None |
| Document parsing | The tables in the annexes (fee tables and so on) were read with Document Parse and saved. On top of the starter kit's results, we re-read them in a mode that keeps table cells, and code turns each row into "header: value" lines. It is not called per question | Document Parse (`document-parse`) |
| Search | The 528 ordinance chunks are turned into vectors in advance. The question is turned into a vector to find close chunks, mixed with a keyword score | `solar-embedding-2-passage` (chunks) · `solar-embedding-2-query` (questions) |
| Answer generation | Pick out the ordinance name, region, and what is asked from the question (no answer yet), read the full text of the chosen ordinance and write the answer, then rewrite it in plain words | `solar-pro4` |
| Verification | Judge whether the remaining evidence really covers what the question asks. Three code checks add to this: choosing which ordinance to read, checking that the quoted phrase appears word for word in the article, and checking the output format | `solar-pro4` + code |
| (Demo screen) read again · write the question · shorten for reading aloud | The purple boxes above. Only when the engine answer is longer than two sentences or 160 characters is it shortened to one or two sentences. The short version is dropped if it adds a number or changes the conclusion | `solar-pro4` |
| (Presentation server only, voice switch `CALL_VOICE`) speech-to-text · reading aloud | Only turns sound into text and text into sound. Not used for narrowing the place, picking questions, or the ordinance answer (see "What you should know" 4) | Not an Upstage model: ElevenLabs `scribe_v2_realtime` (speech-to-text) · `eleven_multilingual_v2` (reading aloud) |

<details>
<summary><b>Stages in more detail (files and functions)</b></summary>

**For each line** (`demo/call/server.py` · `locate.py` · `gaz.py`)

| Stage | Who | What it does | File · function |
| --- | --- | --- | --- |
| Remove fillers | code | Removes fillers such as "um" and "so" | `server.py` `FILLER` |
| Find names | code + place list | Finds names in the place list, longest first, and also links names that sound alike | `server.py` `shortlist`, `gaz.py` |
| Read relations | code | Uses the words right after a name to tell the relation, and reads words such as the animal and whether it is alive | `server.py` `code_read` |
| Read again | solar-pro4, once | Gets the name candidates code found and the options of the last question, and has it answer only in set items. Names not on the list are dropped. If the format is wrong, only the code reading is used | `server.py` `model_read`, `READ_PROMPT` |
| Compute area | code | Places candidate points every 20 m where the clues point, and multiplies for each point "how likely the caller would say this if it were here". The area is where 90% of the likelihood sits | `locate.py` `infer` |
| Pick next question | code | Questions that change the handoff come first, then the one location question that splits the area best. At most 10 location questions | `locate.py` `questions`, `LOCCAP` |
| Narrow enough · confirm | code | Within a 50 m radius (a 200 m stretch on a road), it reads the place back | `locate.py` `is_done` |

**After the place is fixed**

| Stage | Who | What it does | File · function |
| --- | --- | --- | --- |
| Place type | code + data | Street, city park, Han River park, neighborhood park, or motorway | `locate.py` `place_class` |
| Handoff office | table | Picks one row by case type × place type × animal, and fills in the district name | `server.py` `route_of`, `data/routes.json` |
| Write the question | solar-pro4, once | Turns the call into a one- or two-sentence question that starts with "[place] …" | `server.py` `_run_engine`, `ASK_PROMPT` |
| Ordinance engine | table below | Calls the same code as the scored API | `engine.pipeline.answer` |
| Attach articles | code + data | Adds the ordinance name, article text, link, and effective date for each cited article from the ordinance data | `server.py` `engine_card` |
| Lot number | address list | The lot number of the address point closest to the pin (162,442 addresses from the small-business data) and its distance. If it is more than 100 m away, "no lot number" comes first | `server.py` `nearest_addr` · `bunji_of` |

**Inside the ordinance engine** (`engine/flow2/flow.py`, submitted settings `eval/configs/release.json`)

| Stage | Who | What it does |
| --- | --- | --- |
| Search | solar-embedding-2-query, once + code | Picks 20 candidates from the chunks of the six ordinances |
| Analyze the question | solar-pro4, once | Picks out only the subject, what is asked, the type, any ordinance named, and the region. It does not write an answer yet |
| Choose the ordinance | code | Picks at most two ordinances to read. If the question is about another ordinance, a district, or another city, it ends here with "cannot confirm" |
| Read the ordinance · write the answer | solar-pro4, once | Reads the full text of the chosen ordinance (annexes included) and returns an answer and evidence (article name + a phrase copied from it) |
| Phrase check | code | Keeps a citation only if the copied phrase appears word for word in that article |
| Check against the question | solar-pro4, 0 or 1 time | Judges whether the remaining evidence really covers what the question asks |
| Plain words · opening word | solar-pro4, once + code | Rewrites the answer in plain words and drops the rewrite if a number or the conclusion changes. It also keeps the draft if the rewrite drops a value from a correct draft or adds "it is not set" (정해져 있지 않다) that the draft did not say (the plain-words check). Adds "yes" or "no" to the front of answers to yes/no questions |
| Output | code | Keeps only articles that are in the index, and code adds the source link and effective date. With no citation left, the answer becomes "cannot confirm" |

</details>

### Servers

All three servers run on AWS. Their code, servers, and addresses are frozen with the 11/22 submission and not changed after it.

| Server | What it does | Sound | Submitted |
| --- | --- | --- | --- |
| Scoring API | Answers the contest's scoring questions at `POST /ask`. On during the 11/25 to 11/27 scoring period | None | Yes |
| Demo | The agent screen judges try themselves. Open from 11/22 to 11/27 | None (text only) | Yes |
| Presentation | Used only by the team for the live demo during the presentation | Speech-to-text · reading aloud (ElevenLabs) | No |

<!-- Place for the submitted addresses (scoring API · demo): their form is for the PM to decide (11-21). Do not write addresses or IPs until then -->

### Ordinance engine (scored API)

Send a question to `POST /ask` and it answers in the contest's four-field JSON. This is a real response from the version then on the scoring server (2026-11-18). The submitted version only adds the plain-words check to it, so the citations and "cannot confirm" are the same. The answer is in Korean; in English it says: "Yes, parking fees are reduced for people with disabilities. With the disabled vehicle sign attached, a person with a disability on board, and the disability card shown, the fee is 80% off. At subway transfer parking lots, the first 3 hours per day are free and 80% off after that."

```json
POST /ask  {"question": "장애인 주차요금 감면되나요?"}

{"answer": "네, 장애인 주차요금은 감면됩니다. 장애인자동차표지를 부착하고 장애인이 탑승해 장애인등록증을 제시하면 주차요금의 80%가 할인됩니다. 지하철 환승주차장에서는 1일 1회당 최초 3시간까지 주차요금이 면제되고 이후 80%가 할인됩니다.",
 "citation": ["서울특별시 주차장 설치 및 관리 조례 제7조 제1항"],
 "source_url": "https://www.law.go.kr/ordinInfoP.do?ordinSeq=2171833",
 "effective_date": "2026-10-01"}
```

- When it finds no basis, `answer` starts with "확인 불가" (cannot confirm) and `citation` is empty.
- Each question has a 75-second deadline, and any error still returns HTTP 200 with the four-field JSON.
- `GET /health` returns the fingerprint of the loaded settings (`settings`). The submitted version is `7327ca7e355b`.

<details>
<summary><b>The six ordinances and their effective dates</b></summary>

The ordinances are the versions in force on 2026-10-01, as the contest set. Each ordinance has its own effective date, and `effective_date` in the response is the effective date of the cited ordinance.

| Ordinance | Effective date |
| --- | --- |
| 서울특별시 주차장 설치 및 관리 조례 (parking lots) | 2026-10-01 |
| 서울특별시 동물보호 조례 (animal protection) | 2026-10-01 |
| 서울특별시 자전거이용 활성화에 관한 조례 (bicycle use) | 2026-10-01 |
| 서울특별시 도시공원 조례 (city parks) | 2026-07-13 |
| 서울특별시 청년 기본 조례 (youth) | 2025-07-14 |
| 서울특별시 금연환경 조성 및 간접흡연 피해방지조례 (smoke-free areas) | 2026-10-01 |

</details>

## Measurements

### Ordinance engine

Scores of the submitted version (settings fingerprint `7327ca7e355b`), measured on 2026-11-20 on questions never used in development (unseen questions) and on development questions. These are the team's own measurements, not the contest's hidden scoring.

| | 174 unseen questions, 12 runs | 693 development questions, 2 runs |
| --- | --- | --- |
| **Weighted score** | **93.1** (90.5 to 95.9) | **95.2** (95.3 · 95.1) |
| Simple lookup | 95.0 | 94.8 |
| Conditional | 94.3 | 96.3 |
| Combining several articles | 91.6 | 92.0 |
| No basis (trap) | 90.9 (11 questions) | 98.7 |
| Over-abstaining ("cannot confirm" when an answer exists) | 2.8% | 2.9% |
| Errors | 0 | 0 |

<details>
<summary><b>How we measured</b></summary>

- The answer labels follow the 11/19 scoring notice. The weighted score averages the scores by type with the starter kit's example ratio (simple 3, conditional 3, combined 3, trap 2).
- Unseen questions: measured on 2026-11-20, side by side with other candidate versions at the same time, three runs each on four occasions, 12 runs in all (simple 71, conditional 63, combined 29, trap 11). The scores by type are the average of the 12 runs. Development questions: the record made when the submitted version was built (2026-11-20, two runs, four questions at a time). On the development questions there were also no format errors and no answers over 90 s.
- The same version scores differently from run to run (90.5 to 95.9 on the unseen questions). Most of the 2.1-point gap between the two sets comes from trap questions. The unseen set has only 11 trap questions, so one question moves the trap score by 9.1 points.
- Two runs of the 693 development questions made 5,873 Upstage calls (about 4.2 per question, embeddings included). The logged cost (tokens × list price) was $3.06.

</details>

<details>
<summary><b>What we changed from the starter kit (improvement history)</b></summary>

| Version (date measured) | Weighted score on development questions | Over-abstaining | Questions · scoring rule |
| --- | --- | --- | --- |
| Start, the starter kit moved over (11-07) | 67.0 | 28.4% | 661 questions, rule before 11-11 |
| 11-10 | 76.9 | 18.8% | 661 questions, rule before 11-11 |
| 11-13 | 92.5 | 7.2% | 693 questions, 11-11 rule |
| 11-15, first put on the scoring server | 94.8 | 2.0% | 693 questions, 11-11 rule |
| 11-20, submitted (the 11-15 version + plain-words check) | 95.2 | 2.9% | 693 questions, labels matched to the 11-19 notice |

The question set and the scoring rule changed in the middle, so the numbers up to 11-10 should not be compared directly with the numbers from 11-13 on. The record for each version is in [`docs/engine/releases.md`](docs/engine/releases.md) (Korean).

| | Start | Submitted |
| --- | --- | --- |
| Flow | search → pick evidence · write answer → judge → output | search → analyze the question → choose the ordinance (code) → read the full ordinance and write the answer → phrase check (code) → check against the question → plain words (keep the draft if the rewrite spoils a correct one) → output check (code) |
| What it reads | A few chunks from search | The full text of the chosen ordinance |
| Annexes | The table text the kit read | Re-read keeping table cells, turned into "header: value" lines |
| Questions outside the six ordinances | Left to search scores and a model judgment | Code ends them before reading |
| Citations | Names of the chunks the model picked | Only phrases that appear word for word in the article. Code adds the link and effective date |

The stages and switches of the new flow are in [`docs/engine/flow2.md`](docs/engine/flow2.md) (Korean).

</details>

### Narrowing the location

<!-- The 600-call values in this section were measured on the 11-21 baseline (location code the same as main 5000e28), run r75-c2m (report 78, "바탕" row: 421 · 397 · 416 / 0 · 0 · 5). The ten location fixes (#149, main 16d57be) and the second batch (#157, main 08bd360) did not change these 600 calls either (#149 · #157 descriptions: same). The 93-case values are the "new yardstick" row of the #157 description (sum of three seeds, circle 110/7 → 110/0 · boundary 136/10 → 136/3). "우리 측정" in docs/call-locate/README.md still has the 11-18 values -->

These come from simulated calls, 600 per condition, measured with the defaults of main 08bd360 (all location-reading fixes on, 2026-11-21). Code picks a true location in Seoul, and a simulated caller answers the screen's questions with what can be seen from that spot. No call with a real person speaking has been measured by distance yet.

| Caller (600 calls each) | Calls narrowed to one point | Calls fixed at a wrong place |
| --- | --- | --- |
| Answers what they see | **421 (70.2%)** | **0** |
| 10% wrong answers and 10% "I don't know" | 397 (66.2%) | 0 |
| 10% wrong answers and easily says yes to a wrong place | 416 (69.3%) | 5 |

We also ran a separate set of 93 cases, built without looking at the code being fixed (the kinds of places that failed in the field: behind or beside large buildings, event sites, bridges, nicknames), with three seeds (279 calls in all). The simulated caller judges distance to a large building either by approximating it as a circle or by its real boundary.

| 93 cases × 3 seeds | Calls narrowed to one point | Calls fixed at a wrong place (before → after the second batch) |
| --- | --- | --- |
| Building approximated as a circle | 110 | 7 → **0** |
| Building's real boundary | 136 | 10 → **3** |

- "One point" means the area was narrowed within a 50 m radius (a 200 m stretch on a road), the caller confirmed it, and the point is within 60 m (120 m on a road) of the true location. A "wrong fix" means the confirmed point is farther than that.
- Distance to the lot number (from the true location to the nearest lot number): median 18 m in alleys and shopping streets, 25 m around station exits, 39 m on main roads. Share more than 100 m away: 48% on motorways, 80% inside parks.

<details>
<summary><b>How we measured</b></summary>

- Measured on 2026-11-21 with the current defaults (all location-reading fixes on). The 600 calls are four runs of 150. Two of the four random seeds that pick true locations were never used in development. When the caller answers what they see, a call has 6.4 exchanges on average.
- The simulated caller never says speech-to-text mistakes or intersection names, and names a large place like a school only when standing near its point. So the fixes turned on on 11-19 (speech-to-text mistakes, large places, intersection names) did not change the one-point or wrong-fix counts of these 600 calls; their effect was checked with separate sets of made-up phrases. The 11-20 fixes (fixes for the field test failures, reading perimeters, and more) also barely changed these 600 calls (398 → 397, 417 → 416); their effect was checked by feeding the words of real calls back in and with a separate set of cases. The second batch on 11-21 (long bridges, "I can see …", Korean option names, and more) did not change these 600 calls either; its effect shows in the wrong fixes of the 93-case set above.
- Measurements up to 11-18 and how we fixed things are in "우리 측정" (Our measurements) in [`docs/call-locate/README.md`](docs/call-locate/README.md) (Korean).
- On 11-18, before we found and fixed four causes of wrong fixes, the same 600 calls gave 414 (69.0%) and 4 wrong fixes when the caller answers what they see.

</details>

## Getting started

You need Python 3.10 to 3.13 (3.12 is recommended). Run every command from the repository root.

### 1. Run the demo without an API key

You only need numpy. The saved-answers mode calls neither the Upstage API nor the engine.

```bash
OPENBLAS_NUM_THREADS=1 CALL_MODE=saved python3 demo/call/server.py
```

Open <http://127.0.0.1:8772> and press "받기" (Answer) or Enter to play the main scene (an injured cat by the street near Lotte World Tower). Change the port with `CALL_PORT`.

| Address | Scene |
| --- | --- |
| `/?auto=cat_street` | Plays the main scene right away. Add `&speed=3` to play it faster |
| `/?auto=cat_park` | An injured cat inside Seoul Forest park (a place with no lot number) |
| `/?auto=roadkill` | A dead cat seen while driving (a motorway stretch, outside the six ordinances) |
| `/?view=records` | The consultation records screen |

In "직접 통화" (Live call, keyboard `0`) you can type any place in Seoul. For example: "마포구인데요, 스타벅스 앞 가로등이 꺼져 있어요" (It's Mapo-gu, the streetlight in front of Starbucks is out) → "합정역 근처예요" (It's near Hapjeong Station). In saved-answers mode, words that are not in the script are read by code only, without a model.

The browser loads map tiles (OpenFreeMap) and the map library (MapLibre GL, from unpkg) from the internet. The font (IBM Plex Sans KR) is in the repository at `demo/call/web/fonts/`. The server fetches nothing from outside. The screen is light by default; add `?tone=dark` to the address for a dark screen.

### 2. With an Upstage API key

Create the engine's virtual environment and add the key. Keep the key only in `.env` and never commit it (`.gitignore` blocks it).

```bash
python3 -m venv .venv
.venv/bin/pip install -r engine/requirements.txt
cp .env.example .env          # put your key after UPSTAGE_API_KEY=
```

Run the demo with real calls. solar-pro4 reads each line again, and the ordinance answer calls the engine directly.

```bash
OPENBLAS_NUM_THREADS=1 ENGINE_CONFIG=eval/configs/release.json .venv/bin/python demo/call/server.py
```

Ask the engine one question (about 4 Upstage calls).

```bash
.venv/bin/python -m engine.pipeline "장애인 주차요금 감면되나요?" eval/configs/release.json
```

Run the scoring API server (the submitted version). Run a single worker (do not pass `--workers`).

```bash
ENGINE_CONFIG=eval/configs/release.json .venv/bin/uvicorn engine.server:app --host 0.0.0.0 --port 8000
curl -s -X POST http://localhost:8000/ask -H 'Content-Type: application/json' -d '{"question": "장애인 주차요금 감면되나요?"}'
```

> [!NOTE]
> Without a key, the engine answers every question with "확인 불가" (cannot confirm), still as HTTP 200 and four-field JSON. On Windows, use `.venv\Scripts\python`. Other differences are in "윈도우에서 다른 것" (On Windows) in [`engine/README.md`](engine/README.md) (Korean).

### 3. Checks

| What it checks | Command | Key |
| --- | --- | --- |
| Runs the demo server in saved-answers mode and plays the scripted scenes, buttons only, places outside the script, saving a nickname, consultation records (with the conversation at the time), and reference values to the end. Exit code 1 on failure | `OPENBLAS_NUM_THREADS=1 python3 demo/call/check.py` (port 8779, change with `CALL_CHECK_PORT`) | No |
| Self-test of the location math | `python3 demo/call/locate.py` | No |
| 30 simulated calls: number of exchanges, error of the fixed point, handoff office (code only, about 30 s) | `OPENBLAS_NUM_THREADS=1 python3 demo/call/tools/sim_calls.py` | No |
| Server side of the voice call and direct call switches (off by default). Speech-to-text is fake, and outside services are replaced by fake servers on this computer | `OPENBLAS_NUM_THREADS=1 python3 demo/call/voice/check_voice.py`, `OPENBLAS_NUM_THREADS=1 python3 demo/call/voice/check_direct.py` | No |
| Self-tests of the engine's response format and flow | `.venv/bin/python -m engine.contract --selftest`, `.venv/bin/python -m engine.flow2.flow --selftest` | No |
| Score the 693 development questions (two runs) | `.venv/bin/python eval/run.py --config eval/configs/release.json --split dev --repeat 2` | Yes |

<details>
<summary><b>Environment variables</b></summary>

| Name | Used by | If missing |
| --- | --- | --- |
| `UPSTAGE_API_KEY` | The engine and real calls in the demo | The engine only answers "cannot confirm" |
| `ENGINE_CONFIG` | Engine settings file (submitted: `eval/configs/release.json`) | The start version (defaults in `engine/config.py`) |
| `ENGINE_LOG_DIR` | Folder for per-question logs from the scoring server | `logs/` (an empty value turns logging off) |
| `LAW_OC` | Only for downloading the ordinance text again (`eval/fetch_source.py`) | Not needed to run (the text is in the repository) |
| `CALL_MODE` | Demo: `saved` for saved answers, `code` for code only without a model, anything else for real calls | Real calls |
| `CALL_PORT` | Demo port | 8772 |
| `CALL_MODEL` | Model the demo uses to read lines and write the question | solar-pro4 |
| `CALL_DIRECT` | `1` turns on the direct call (text) | Off |
| `CALL_VOICE` | `1` turns on the voice call (speech-to-text and reading aloud with ElevenLabs, on only on the presentation server) | Off |

The demo's other environment variables are in [`demo/call/README.md`](demo/call/README.md) (Korean).

</details>

<!-- README decision pending 4 (standard consultation database sentence): default = the same words as the screen text (the "가상 흐름" row in docs/content/A-05). Change both together -->
## What you should know

1. **The demo calls are made up.** This call and question flow is a made-up flow the team built from public material and the ordinance text, and it is not connected to the 120 standard consultation database (the bottom left of the screen says the same). The team wrote the call scripts and question wording, and chose the complaint types from Seoul's field complaint handling standard. The line "표준 답변 자료와 맞춰 본 뒤 안내하세요" (check against the standard answers before you tell the caller) leaves that check to the agent. The 14 past records on the records screen are also examples the team made.
2. **The call accuracy numbers come from simulated calls.** No call with a real person speaking has been measured by distance yet.
3. **The handoff table mixes "confirmed" and "guessed" rows.** Of 32 rows across 12 case types, 31 were confirmed in official guidance or the ordinance text, and 1 is a guess (handoff table `demo/call/data/routes.json`, main 08bd360 · as of 2026-11-21). The screen shows them as "확인 전(추측)" (not yet confirmed, a guess), and team names may differ by district.
4. **Every model that makes an answer is an Upstage model.**
   - Narrowing the place, picking questions, and the ordinance answer use only Upstage models.
   - Only speech-to-text (sound to text) and reading aloud (text to sound) use another company's models (ElevenLabs: `scribe_v2_realtime` for speech-to-text, `eleven_multilingual_v2` for reading aloud), because Upstage offers no speech-to-text or speech synthesis model.
   - These two run only on the presentation server with the voice switch (`CALL_VOICE`, off by default) turned on. The scoring API server and the demo server work with text only and do not use them ([`docs/decisions.md`](docs/decisions.md), 11-21, Korean).
   - With the default settings, the only outside model API that the engine and the demo server call is Upstage's, and the browser loads only map tiles and the map library from outside. The voice switch code can also choose other speech-to-text options (Whisper running on this computer, Return Zero), but the presentation server uses ElevenLabs.

<!-- README decision pending 5 (name and shape of the "Limitations" section): the presentation uses "next directions" instead of "limitations" (11-20). The README keeps the content under the current name. Once decided, change only this section's title and shape -->
## Limitations

- It cannot understand shop or building names that are not in the map data (OpenStreetMap and the small-business data). It also has no motorway signs or exit numbers.
- The lot number is not the lot number of the spot itself. It is the lot number of the nearest building with a shop, so the distance is always shown with it.
- The values that read "right in front" as about 18 m and "near" as about 100 m, and the rule for when to move on to confirming, were not tuned with real calls.
- The first question assumes the caller is at the spot. If someone reports something they saw while passing by from another place, the screen may narrow down the wrong place (only the motorway scene asks separately which bridge the driver passed).
- Roads, stations, or bridges that share a name are not fixed until another clue tells them apart.
- The screen assumes it receives text from the call center's speech-to-text tool. It has never been connected to that tool. The demo uses script playback and typed input.
- It does not actually file or send a case.
- Engine: on unseen questions, the trap score (questions where "cannot confirm" is correct because there is no basis) is lower than on development questions (90.9 vs 98.7). For cases under the six ordinances, the engine sometimes gives different answers to the same question.
- Engine: it is weak on questions about details that an ordinance leaves to someone else, such as the mayor (the delegation case in the 11/19 scoring notice). Candidate versions that fixed this did not pass the criteria set in advance (they had to pass on every set), so they were not put into the submitted version ([`docs/decisions.md`](docs/decisions.md), 11-21, Korean).

Some evidence is still missing. We filed an information disclosure request for the number of call-backs caused by unclear locations and have not received it. A test where real people describe their own location in their own words is prepared but has 0 calls so far (section 7 of the [evidence notes](docs/call-locate/근거.md), Korean).

## Data sources and terms

Map, shop, traffic, and building height data and the font follow their own terms: © OpenStreetMap contributors (ODbL 1.0) · Public Data Portal (no restriction on use) · Seoul Open Data Plaza (KOGL Type 1) · National Transport Information Center · Wikidata (CC0) · Korean Wikipedia (CC BY-SA 4.0) · © OpenFreeMap · © OpenMapTiles · IBM Plex Sans KR (SIL Open Font License 1.1). The source of each file is in the table below.

<details>
<summary><b>Source and terms of each file</b></summary>

| Data | Source · terms |
| --- | --- |
| Text of the six Seoul ordinances (`engine/data/ordinances.json`) | National Law Information Center (law.go.kr). The version as of 2026-10-01 that the contest starter kit downloaded |
| Annex reading results (`engine/data/annex/`, `engine/flow2/annex/`) | Results of reading the annexes with Upstage Document Parse |
| 528 ordinance chunks and embeddings (`engine/data/`) | Made by the starter kit and used as is (solar-embedding-2-passage, 1024 dimensions) |
| Places · roads · parks (`places.tsv.gz` · `roads.json.gz` · `areas.json` · `park_things.tsv.gz` · `park_names.tsv.gz` · `ramps.tsv.gz` in `demo/call/data/seoul/`) | © OpenStreetMap contributors, ODbL 1.0 (BBBike Seoul extract, 2026-11-08). The reduced tables also follow ODbL (attribution, share-alike) |
| Shops · addresses (`shops.tsv.gz` · `addrs.tsv.gz`) | Public Data Portal 15083033, "소상공인시장진흥공단_상가(상권)정보_20260930" (small-business commercial data). No restriction on use |
| Streetlight numbers (`lamps.tsv.gz`) | Public Data Portal streetlight locations (15107934 Seoul, 15070592 Gwangjin-gu, 15107876 Yeongdeungpo-gu, 15062578 Seodaemun-gu). No restriction on use |
| Park restrooms (`park_toilets.tsv.gz`) | Seoul Open Data Plaza OA-22586, Seoul public restroom locations. KOGL Type 1 (attribution) |
| Motorway interchange and tunnel names (`road_nodes.tsv.gz`) · major intersection names (`cross_nodes.tsv.gz`) | National Transport Information Center standard node-link data (2026-11-11) |
| Sizes of large places (`extents.tsv.gz`) | © OpenStreetMap contributors, ODbL 1.0 (areas from the Seoul extract above) + station exits from the same place list |
| Bridge areas (`bridges.json.gz`) | © OpenStreetMap contributors, ODbL 1.0 (bridge areas from the Seoul extract above) |
| Other names of places (`wiki_alias.tsv.gz`, read only by a switch that is off by default) | Korean aliases from Wikidata (CC0) and Korean Wikipedia redirect titles (CC BY-SA 4.0, source ko.wikipedia.org), downloaded 2026-11-20 |
| A few demo places (`demo/call/data/extra_places.json`) | Added by hand by the team because the map data had no name for them |
| Saved answers (`demo/call/data/saved.json`) | Upstage model and engine responses saved from running the scripted scenes with real calls |
| Building heights (`demo/call/web/heights/`) | Seoul Metropolitan Government, "서울시 건물 태양에너지 등급도(2018년)" (Seoul building solar energy grade map, 2018), Seoul Open Data Plaza OA-15944, KOGL Type 1 (attribution). Heights are not measured; they are floors × 3.5 m. Footprints: © OpenStreetMap contributors · OpenFreeMap tiles |
| Map tiles (screen) | © OpenFreeMap · © OpenMapTiles · © OpenStreetMap contributors (shown at the bottom of the screen) |
| Font (`demo/call/web/fonts/`) | IBM Plex Sans KR 1.1.0, © 2017 IBM Corp., SIL Open Font License 1.1 (`demo/call/web/fonts/OFL.txt`) |

The original data is not in the repository; only the reduced tables are. The scripts that rebuild them are `demo/call/tools/osm_fetch.py` and `build_*.py`.

</details>

## Documentation map

All of these documents are in Korean.

| What you want to know | Document |
| --- | --- |
| How to run and click through the demo, scene addresses, environment variables | [`demo/call/README.md`](demo/call/README.md) |
| An introduction to the service and its measurements | [`docs/call-locate/README.md`](docs/call-locate/README.md) |
| A 30-minute study guide to the whole system | [`docs/공부-자료-1120.md`](docs/공부-자료-1120.md) |
| Evidence that the problem is real, with sources | [`docs/call-locate/근거.md`](docs/call-locate/근거.md) |
| The words on the screen and the call scripts (the source of all screen text) | [`docs/content/A-05_통화위치좁히기.md`](docs/content/A-05_통화위치좁히기.md) |
| How to run the engine, its files, and its logs | [`engine/README.md`](engine/README.md) |
| The engine's new flow | [`docs/engine/flow2.md`](docs/engine/flow2.md) |
| The scoring rules we received | [`docs/engine/scoring-rules.md`](docs/engine/scoring-rules.md) |
| How to measure scores and keep records | [`docs/engine/reproducibility.md`](docs/engine/reproducibility.md) |
| Engine scores by version | [`docs/engine/releases.md`](docs/engine/releases.md) |
| Contest judging criteria | [`docs/evaluation.md`](docs/evaluation.md) |
| What the team decided and why | [`docs/decisions.md`](docs/decisions.md) |
| How we work | [`AGENTS.md`](AGENTS.md) · [`CONTRIBUTING.md`](CONTRIBUTING.md) |

<details>
<summary><b>Folders</b></summary>

```text
engine/              # Ordinance Q&A engine (scoring API: engine/server.py)
├── flow2/           # Flow of the submitted version
└── data/            # Ordinance text, annex results, chunks, embeddings
eval/                # Evaluation questions, scoring tools, experiment settings (eval/configs/)
demo/call/           # Demo screen "Call Locate"
├── server.py        # Call server (reading lines, handoff office, intake card)
├── locate.py        # Area math and next-question choice
├── gaz.py           # Place list
├── data/            # Handoff table, place and address tables, saved answers, example records
├── web/             # Screen
└── tools/           # Data builders, simulated-call measurement
docs/                # Introduction, evidence, screen text, engine docs, decisions, meetings
```

</details>

## License

Team GG holds the rights to the code and documents the team wrote in this repository (Copyright © 2026 Team GG. All rights reserved.). The full terms are in [`LICENSE`](LICENSE).

- **No need to ask**: viewing, downloading, and running it for the contest's operation, judging, and reproducibility checks, and reading it and running it on your own device to learn as an individual.
- **Please ask first**: any other use (redistributing, modifying and using, running it as a service, applying it to your work) needs the team's prior written permission. This applies to commercial and non-commercial use alike, including use by national or local governments and public institutions in their work. Leave a note in [Issues](https://github.com/team-gg-aibc/aibc2026-gg/issues) and we will be glad to talk.
- **Follows its own terms**: code and data from the starter kit (the team claims no rights to them), the data in the [Data sources and terms](#data-sources-and-terms) table (tables extracted from OpenStreetMap are under ODbL 1.0, so anyone may use them under those terms), and the font and outside libraries.
