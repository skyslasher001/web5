# The neural universe: a proposal

Status: **proposal for the owner, 2026-10-14.** Nothing here changes SPEC.md until you approve it. Each item
says which SPEC phase it belongs to and whether SPEC already asks for it.

You asked for the universe to work like a brain, a neural network in the shape of a universe: agents act as
neurons, subjects (galaxies) act as synapses, zoom is smooth and scalable, and voice is ready to receive
transmissions. This document thinks that through, says where the metaphor needs adjusting to hold up, and
proposes what to add.

## 1. Making the metaphor hold up

A brain doesn't store memories *in* neurons. It stores them in the **pattern and strength of the
connections** between neurons. A connection used often gets stronger ("cells that fire together wire
together"), and an unused one fades. That is what makes a brain feel alive, and it's the part UNIVERSE
doesn't have yet: today every link is equally bright, forever.

So I recommend this mapping. It keeps your two ideas and adds the missing piece.

| Brain | UNIVERSE | Today | Proposed |
| --- | --- | --- | --- |
| Memories (engrams) | Items: notes, songs, photos… (stars, planets, pulsars) | ✓ dim when forgotten | flare when recalled |
| **Synapses** (connections whose strength changes with use) | Links between items (light filaments) | all equal, static | **strengthen with use, fade without** |
| **Synaptic hubs / brain regions** | Galaxies (subjects, projects) | ✓ sized by item count, brightened by activity | glow as signals pass through them |
| **Neurons firing** (signal carriers) | Agents (probes) | fly in straight lines to what they work on | **travel along the filaments**, as pulses |
| Brainstem / thalamus (relays every signal) | The Core | ✓ home, pulses with activity | the hub every signal enters and leaves |
| Senses | Voice (ears and speech), Vision (eyes), Research (news from outside) | Phases 7, 8, 6 | transmissions arrive at the Core |
| Sleep | Nightly consolidation ("dreaming", SPEC §10) | Phase 9 | replays the day's pathways |
| Immune system | Sentinel and Forge | Phase 5 | errors are "pain" signals routed to Forge |

Your "galaxies as synapses" idea fits best as **synaptic hubs**: a galaxy is where many connections meet,
and where a signal crosses from one subject to another. The individual synapses are the filaments between
items. That's the one change I'd make to how you described it, because it gives the strength-with-use idea
somewhere to live.

## 2. What to add, ranked by value for effort

1. **Pathways that strengthen with use** (Hebbian links). *SPEC §7 already says "filament brightness =
   strength" and §10 says "strengthen or weaken links based on use"; nothing builds it yet.*
   - Links fire when:
     - you follow a `[[link]]` or open B shortly after A;
     - an agent uses both items in one task;
     - you pick two items from the same search.
   - Each firing raises the strength; it decays with a half-life (about 30 days).
   - Filament width and brightness show the strength, so the paths you actually think along become
     visibly brighter.
   - Two items that keep firing together *without* a link get a dashed suggested filament: auto-linking
     learned from your behaviour, not just from embeddings.
   - Weak links fade but are never deleted (the vault rule).
   - The `links.strength` column already exists.
   - Belongs to: Phase 9 (brain layer). The data collection could start earlier, so there's history to
     learn from.
2. **Signal pulses along filaments.** When an agent reads or links items, or you move from one item to a
   linked one, a light pulse travels the filament. This is the single most "neural" visual, and it costs
   one extra draw call. It uses the agent step events and links that exist today.
   - Belongs to: Phase 4 polish. I can build it in this patch if you want it.
3. **Agents fly the pathways.** A probe travels along the shortest strong path through the link graph to
   its target, instead of in a straight line, and leaves a fading trail. You literally watch a thought move.
   - Belongs to: Phase 4 polish (with 2).
4. **Spreading activation.** When you select or search something, activation spreads one or two hops along
   strong links. Related items glow faintly ("priming"), and search ranking gets a small boost from them.
   This is how a brain brings back the thing next to the thing you asked for.
   - Belongs to: Phase 9 (recall); the glow could come with 2.
5. **A Cluster zoom level.** Between Galaxy and System: topics inside a galaxy (k-means on the item vectors,
   like the Semantic layout), named by the local model. The zoom becomes Universe → Galaxy → Cluster →
   System → Item, so the smooth zoom always has something meaningful at every distance.
   - Belongs to: Phase 9, or Phase 4 polish without the names.
6. **Dream replay.** The morning brief can replay yesterday's strongest new pathways at high speed, using the
   time slider that exists.
   - Belongs to: Phase 9 (with consolidation).
7. **Working memory you can see.** The current task's context (what Core and the agents hold right now) as a
   small lit constellation in the HUD. You can drop things into it or take them out.
   - Belongs to: Phase 9 (memory UI).
8. **System state as body signals.** These are already measured; this only changes how they're shown:
   - Budget and compute load: "energy".
   - Errors: pain signals that fly to Forge (Phase 5).
   - Sentinel: the immune response.

My recommendation: approve **1** into SPEC, so it's planned and its data collection starts. Let me build
**2 and 3** now as Phase 4 polish (small and visual, and they make the brain idea visible today). Park **4–8**
for their phases.

## 3. Smooth, scalable zoom (built in this patch)

- **Log-scale zoom:** each scroll notch multiplies the distance by the same factor, so going from the whole
  universe to one star takes the same effort per order of magnitude, and it never feels too fast up close or
  too slow far away.
- **Easing:** the camera glides to the zoom goal, at the same speed at any frame rate.
- **Zooms toward the cursor:** the star or point under the cursor stays under it, like a map.
- **Clip planes follow the distance:** depth stays precise from 1 unit to the whole universe.
- **No popping:** stars fade in and out at the detail threshold.
- **Zooming in is enough to arrive:** zooming into a galaxy puts you at Galaxy level in the breadcrumb, no
  click needed.
- **Keyboard and screen readers:** `+` and `−` keys, and a zoom slider in the navigator.
- **Lite mode** uses the same log-scale zoom instead of sigma's fixed ×1.7 jumps.

## 4. Voice: the receive chain ("transmissions")

SPEC §11 and Phase 7 cover this. Nothing of the voice pipeline is built yet, and it starts only when Phase 7
does. This is the chain to build, so nothing is forgotten. Every model and version gets checked online at
build time, as always.

| Step | What it does | Default (verify at build time) | Budget |
| --- | --- | --- | --- |
| 1. Consent | The mic is off until you turn it on, with an indicator that's impossible to miss (exists: `ConsentIndicators`). Audio lives in memory only; nothing is stored unless it's a voice memo or you say so. | — | — |
| 2. Capture | 16 kHz mono from the chosen mic, in a separate process so the UI never stutters. | Electron/Chromium audio, or a Python capture service | — |
| 3. Clean-up | Echo cancellation (so it can hear you while it speaks), noise suppression. | WebRTC AEC3, or headset mode | ~10 ms |
| 4. Voice detection | Is someone speaking? | Silero VAD class | ~30 ms |
| 5. Trigger | Push-to-talk hotkey, wake word ("Hey Universe", customizable), or continuous mode with a timeout. | openWakeWord class | — |
| 6. Speech to text | Streaming transcription with end-of-speech detection. | faster-whisper (a turbo/distil model on a GPU) | ~300–500 ms after you stop |
| 7. Route | Fast path: Navigator commands ("take me to Ember Wolf") run directly. Everything else goes to Core. | the Phase 3 router | < 300 ms fast path |
| 8. Answer | Short spoken answer in the agent's own voice; full detail on screen. Barge-in stops it the moment you speak. | Kokoro-82M (licence checked per voice) | first audio < 1.5 s total |

**In the universe:** a transmission arrives as a wave from the edge into the Core (the "ear"), fires along
the pathway to the agent that handles it, and the answer travels back. The voice orb shows idle, listening
(live waveform), thinking and speaking. **Also in Phase 7:** dictation into any editor, voice memos
transcribed into the vault automatically, and per-agent voices.

**Hardware flag:** the 1.5 s target assumes a GPU for speech-to-text. On a CPU-only machine I'll measure it
and propose the closest target, as SPEC §24 says.

## 5. Decisions I need from you

1. Approve **pathways that strengthen with use** (item 1) into SPEC, as part of Phase 9, with data collection
   starting now?
2. Build **signal pulses and agents flying the pathways** (items 2 and 3) now, as part of the Phase 4 patch?
3. Anything in items 4–8 you want moved earlier, or dropped?
