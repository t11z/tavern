# The Shattered Coast — Starter World

This is Tavern's default world preset. It ships with the project so that players can start a campaign immediately without configuring world parameters. It also serves as a reference implementation for the community preset format (see campaign-design.md).

This world is original content. It does not use any WotC-protected intellectual property. All names, locations, factions, and lore are created for Tavern and licensed under Apache 2.0 alongside the rest of the project.

## Setting

The Shattered Coast is a stretch of broken coastline where a once-great civilization collapsed two centuries ago. The old empire — the Thalassic Concordance — sank beneath the waves in a single catastrophic night. What remains are the coastal settlements that survived on the empire's periphery: trading towns, fishing villages, and fortress-cities that have spent two hundred years building their own identities from the rubble.

The sea is central to everything. It provides food, trade, and danger in equal measure. The ruins of the Concordance are still visible at low tide — towers jutting from the water, submerged roads leading nowhere, and the occasional artifact washing ashore. What caused the Sinking is debated endlessly. The scholarly consensus is a magical catastrophe. The religious orders call it divine punishment. The truth, if anyone still knows it, has not surfaced.

**Tone**: Adaptable. The Shattered Coast supports all of Tavern's tone presets:
- *Heroic Fantasy*: The ruins hold ancient treasures and the seeds of a restored civilization. Heroes explore, discover, and rebuild.
- *Dark & Gritty*: Resources are scarce, the coastal lords are corrupt, and the sea takes more than it gives. Survival is the daily struggle.
- *Lighthearted*: The fishing villages are full of eccentric characters, the ruins produce absurd artifacts, and the "ancient evil" turns out to be a very confused sea creature.
- *Mystery & Intrigue*: What really caused the Sinking? Who benefits from the current power vacuum? Why are artifacts appearing more frequently?
- *Eldritch Horror*: The Sinking was not natural. Something beneath the waves is waking up. The artifacts are not gifts — they are lures.

## Geography

**Driftmere** — The largest surviving settlement, built on a rocky promontory overlooking a natural harbor. Population ~8,000. Functions as the de facto capital of the Coast, though no one acknowledges it as such. The harbor hosts trading vessels, fishing fleets, and the occasional salvage expedition to the submerged ruins.

**The Tidewalks** — A network of exposed Concordance roads that surface at low tide, connecting small islands and reef formations. Navigable on foot for roughly four hours per tidal cycle. Dangerous — the footing is treacherous, creatures nest in the submerged sections, and being caught when the tide returns is often fatal.

**Salthollow** — A mining town three days inland, built into a canyon system. Produces salt, iron, and a rare blue mineral called tidestone that glows faintly in the presence of Concordance artifacts. The miners are insular and superstitious.

**The Fenwick Reach** — Marshland south of Driftmere, technically claimed by no one. Home to communities of fishers, herbalists, and people who prefer not to be found. Rumored to contain a Concordance archive that survived the Sinking — partially submerged, partially accessible.

**The Drowned Spires** — Visible from Driftmere's harbor on clear days. The tallest structures of the sunken Concordance capital, protruding from the sea like broken fingers. Salvage expeditions go there. Not all return.

## Factions

**The Harbormaster's Council** — Driftmere's governing body. Five elected merchants who control trade, taxation, and port access. Pragmatic, self-interested, and deeply suspicious of anything that might disrupt commerce. They tolerate adventurers because salvage expeditions are profitable — but they regulate them heavily.

**The Tide Wardens** — A loosely organized group of rangers, sailors, and former soldiers who patrol the Tidewalks and the coastal waters. Part coast guard, part monster hunters. Underfunded and overworked. They know more about the ruins than anyone and share less than they should.

**The Ledger** — An information network that operates out of Driftmere's taverns and counting houses. Part thieves' guild, part intelligence service, part rumor mill. They know who is buying Concordance artifacts, who is selling, and who is lying about both. Their leader is known only as the Auditor.

**The Ashen Circle** — A scholarly order dedicated to studying the Concordance and the cause of the Sinking. They maintain a small library in Driftmere and fund expeditions to the ruins. Their research is genuine, but their conclusions are politically inconvenient — they believe the Sinking was caused by the Concordance's own magic, which implies the artifacts are inherently dangerous. The Council does not appreciate this message.

**The Salthollow Compact** — The mining families of Salthollow, organized into a mutual defense and trade pact. They sell minerals to Driftmere but distrust the city. They have their own militia, their own laws, and their own secrets about what tidestone actually does.

## Key NPCs

These NPCs are predefined in the campaign roster (ADR-0013) when a campaign is started
from the Shattered Coast preset. Their names, species, and appearances are fixed at
campaign creation and cannot be changed by the Narrator. Mutable attributes (disposition,
status, current location) evolve through gameplay. The `plot_significant` flag is set to
`true` for all five — they persist in the Narrator's snapshot even after death or flight.

**Maren Voss** — Harbormaster and Council chair. Mid-50s, sharp, patient, ruthless when necessary. She built Driftmere's trade network from nothing after the previous Harbormaster died in a storm. She genuinely believes commerce is the only thing holding the Coast together, and she will sacrifice anything — including the truth — to protect it.
*Secret*: She possesses a Concordance artifact that she has never reported to the Council. It showed her something about the Sinking that she has told no one.

**Callum Dray** — Captain of the Tide Wardens. Late 30s, scarred, quiet. A former sailor who lost his ship to something in the Drowned Spires and has never spoken about what he saw. He is competent, respected, and visibly haunted.
*Secret*: He knows the Drowned Spires are not empty ruins. Something lives there. He has been managing this knowledge alone for three years because telling anyone would cause panic.

**Sable** — The Auditor of the Ledger. Age unknown, gender ambiguous, appearance changes between encounters (or so people claim). Sable trades in information the way merchants trade in fish — everything has a price, and the price is always another piece of information.
*Secret*: Sable is not one person. The Auditor is a role shared by three individuals who coordinate to maintain the illusion of omniscience.

**Perin Ashgrove** — Senior researcher of the Ashen Circle. Early 60s, absent-minded in conversation, razor-sharp in analysis. She has spent thirty years studying the Concordance and is closer to understanding the Sinking than anyone alive. She is also terminally ill and increasingly willing to take risks with her research.
*Secret*: She has partially translated a Concordance text that suggests the Sinking was not an accident but a deliberate act — someone or something chose to destroy the empire. She does not know who, or why.

**Torren Gale** — Spokesperson for the Salthollow Compact. Late 40s, blunt, suspicious of outsiders. He represents the miners' interests in trade negotiations with Driftmere and has a talent for making simple demands sound like threats.
*Secret*: The miners have found a sealed Concordance chamber deep in the canyon. They have not opened it. Torren is terrified of what might be inside, but he is more terrified of what Driftmere would do if they knew it existed.

## World Rules

These constraints shape Claude's narrative decisions throughout any campaign set in the Shattered Coast:

- **The Concordance is dead.** No surviving Concordance citizens, no hidden enclaves, no time-displaced survivors. The empire is gone. Only its ruins, artifacts, and unanswered questions remain.
- **Magic is uncommon but not feared.** Spellcasters exist and are not persecuted, but they are unusual enough to attract attention. A wizard walking through Driftmere draws curious looks, not angry mobs.
- **The sea is dangerous.** Travel by sea is risky. Storms are frequent, creatures inhabit the shallows near the ruins, and the Drowned Spires are actively hazardous. The sea is not evil — it is indifferent and powerful.
- **No gods walk the earth.** Divine magic works (clerics and paladins function mechanically as per SRD), but the gods do not manifest, speak directly, or intervene visibly. Faith is a matter of belief, not evidence.
- **Artifacts are valuable and dangerous.** Concordance artifacts wash ashore or are salvaged from the ruins. They are worth enormous sums to collectors and scholars. Some function. Some do not. Some do things their users did not expect. The Harbormaster's Council regulates their trade — officially.
- **There is no single villain.** The Shattered Coast is a setting of competing interests, not a setting of good versus evil. Every faction has legitimate goals and questionable methods. The players' choices determine who becomes an ally and who becomes an obstacle.

## Campaign Hooks

Claude uses these as starting points, adapting based on the campaign's tone and the players' actions:

**The Salvage Job**: The players are hired for a routine salvage expedition to a newly exposed Concordance structure. The job goes sideways — they find something that multiple factions want, and returning to Driftmere with it makes them either valuable or dangerous.

**The Missing Warden**: A Tide Warden patrol has not returned from the Tidewalks. Captain Dray asks the players to investigate. What they find forces a decision: report truthfully and cause panic, or keep the secret and manage it themselves.

**The Auditor's Price**: Sable offers the players information they need — but the price is a job that puts them on the wrong side of the Harbormaster's Council. The deeper they go into the Ledger's world, the more they learn about who really controls Driftmere.

**The Ashgrove Translation**: Perin Ashgrove needs help retrieving a text from the Fenwick Reach — one that might explain the Sinking. The Ashen Circle cannot fund the expedition officially because their findings embarrass the Council. The players must decide whom to trust with what they discover.

**The Sealed Chamber**: Word reaches Driftmere that the Salthollow miners have found something underground. Torren Gale wants help from outsiders he can trust — which means outsiders who have no loyalty to Driftmere. What is behind the sealed door, and what happens when it opens?

## Attribution

This world is original content created for the Tavern project. Licensed under Apache 2.0.

Game mechanics are compatible with the System Reference Document 5.2 by Wizards of the Coast, used under Creative Commons Attribution 4.0 International License.

## Preset Format Reference

This file follows the community preset format defined in campaign-design.md. Community contributors can use this structure as a template for their own world presets. The required sections are Setting, Factions, Key NPCs, World Rules, and Attribution.

If a preset defines NPCs with mechanical roles (guards, named combatants), include a
`stat_block_ref` field referencing a valid SRD monster index (e.g. `"veteran"`,
`"bandit-captain"`). This allows the Rules Engine to populate mechanical attributes at
campaign start without Narrator-provided values.