# Character Creation

This document defines how players create characters in Tavern. It is a reference for prompt engineering, UI design, and Rules Engine validation — not an architecture decision record. All mechanics described here are based on the SRD 5.2.1.

For the underlying character data model, see ADR-0004. For Rules Engine validation scope, see ADR-0001.

## Two Paths, One Character

Character creation offers two equally supported paths. Both produce the same validated character record. The player chooses their preferred path at the start of creation.

### Path 1: Guided Conversation

Claude leads the player through character creation as an in-world conversation. This is the default for new players and the more immersive experience.

**Flow:**

1. **Concept**: Claude asks what kind of hero the player envisions. Open-ended — "a cunning thief," "someone who protects the weak," "I want to cast fireballs." Claude interprets the concept and suggests 1-3 fitting class/species combinations with brief in-character descriptions of each.

2. **Class**: The player picks from Claude's suggestions or states a different preference. Claude confirms and describes what this choice means narratively — not mechanically. Classes available in the SRD 5.2.1 are: Barbarian, Bard, Cleric, Druid, Fighter, Monk, Paladin, Ranger, Rogue, Sorcerer, Warlock, Wizard.

3. **Species**: Claude suggests species that fit the chosen class and concept, explaining each option in-character. "As a Goliath, you tower over most folk — strength is not something you earned, it's something you were born into." Species available in the SRD 5.2.1 are: Dragonborn, Dwarf, Elf (High Elf, Wood Elf), Gnome (Forest Gnome, Rock Gnome), Goliath, Halfling, Human, Orc, Tiefling. Each species has traits (size, speed, special abilities) that the Rules Engine validates.

4. **Background**: Claude asks about the character's past life before adventuring, then suggests a matching background. Each background provides three ability scores for the player to boost, an Origin feat, two skill proficiencies, and a tool proficiency. SRD 5.2.1 backgrounds are: Acolyte, Criminal, Sage, Soldier.

5. **Ability Scores**: Claude offers the three generation methods narratively:
   - *Standard Array* (15, 14, 13, 12, 10, 8) — "A balanced set of talents, reliable and proven."
   - *Point Buy* (27 points) — "You choose exactly where your strengths lie."
   - *Random Generation* (4d6 drop lowest, six times) — "Leave it to fate."
   
   After generating scores, the player assigns them to the six abilities. Claude may suggest assignments based on the chosen class ("A fighter lives and dies by Strength — or Dexterity, if you prefer finesse"). The background's ability score bonuses (+2/+1 or +1/+1/+1 to the background's three listed abilities) are applied after assignment.

6. **Origin Feat**: The background determines the Origin feat. Claude describes what the feat does in narrative terms. If the feat involves a choice (e.g., Magic Initiate requires choosing spells), Claude walks the player through the options.

7. **Equipment and Spells**: For martial classes, Claude presents the starting equipment options narratively ("Do you prefer a sword and shield, or a heavy two-handed weapon?"). Backgrounds offer a choice between a specific equipment package and 50 GP. For spellcasters, Claude walks through cantrip and prepared spell selection with brief flavour descriptions of each option.

8. **Languages**: The character knows Common plus two languages chosen from the Standard Languages table (Common Sign Language, Draconic, Dwarvish, Elvish, Giant, Gnomish, Goblin, Halfling, Orc). Species and class features may grant additional languages.

9. **Details**: Claude asks about name, alignment, and personality — weaving the answers into a short backstory paragraph. Alignment options follow the SRD's nine alignments (Lawful Good through Chaotic Evil, plus Neutral). Claude may suggest an alignment based on the character concept but never imposes one.

10. **Review**: Claude presents the complete character as a narrative summary ("Here is your hero...") alongside the mechanical character sheet. The player confirms or requests changes. Changes loop back to the relevant step.

11. **Validation**: The Rules Engine validates the final character — ability score totals within method limits, background ability score bonuses correctly applied (no score above 20), class/spell compatibility, equipment legality, Origin feat prerequisites. If validation fails, Claude explains the issue in-character and offers corrections.

**Tone matching**: The conversation adopts the campaign's tone preset (see campaign-design.md). A Heroic Fantasy creation feels epic and aspirational. A Dark & Gritty creation feels grounded and cautious. A Lighthearted creation might include jokes and absurd options.

**Duration**: Guided creation takes approximately 5-10 minutes. Claude keeps the conversation moving — it does not monologue, it asks one question at a time and responds concisely.

### Path 2: Direct Form

An interactive form that lets the player build a character by selecting options directly. This is the path for experienced players who know what they want and do not need narrative guidance.

**Flow:**

1. **Class**: Select from the 12 SRD classes. The form shows hit dice, primary abilities, armor training, and a brief description.
2. **Species**: Select from SRD species, including subspecies where applicable (High Elf / Wood Elf, Forest Gnome / Rock Gnome). The form shows traits, size, and speed.
3. **Background**: Select from SRD backgrounds. The form shows the three associated ability scores, the Origin feat, skill proficiencies, and tool proficiency.
4. **Ability Scores**: Choose generation method (Standard Array, Point Buy, or Random). Assign scores to abilities. Apply background bonuses (+2/+1 or +1/+1/+1 to the background's listed abilities). The form enforces the point buy budget, prevents scores above 20, and shows modifier calculations in real time.
5. **Origin Feat**: Displayed based on background selection. If the feat involves choices (e.g., spell selection for Magic Initiate), the form presents those options.
6. **Spells** (if applicable): Select cantrips and prepared spells from the class spell list. The form enforces known/prepared limits per class at level 1.
7. **Equipment**: Choose between the class starting equipment package and the background equipment package (or 50 GP alternative for each). The form shows item details.
8. **Languages**: Common is automatic. Select two from the Standard Languages table. Species and class features may grant additional languages.
9. **Name and Details**: Name, alignment, personality traits (optional freeform text).
10. **Review and Confirm**: Full character sheet view. Submit to create.

**Validation**: Identical to Path 1 — the Rules Engine validates the complete character before creation. Invalid selections are blocked in the form (e.g., wizard spells are not selectable for a fighter, ability scores cannot exceed 20 after bonuses).

### What Both Paths Produce

Regardless of path, the result is a `Character` record (ADR-0004) with all fields populated:

- Name, species (including subspecies), class, level (1)
- Ability scores (base + background bonuses) and modifiers
- HP (max for level 1 per class: Barbarian 12, Fighter/Paladin/Ranger 10, Bard/Cleric/Druid/Monk/Rogue/Warlock 8, Sorcerer/Wizard 6 — plus Constitution modifier)
- AC (based on starting armor and Dexterity modifier)
- Proficiencies (skills from background + class, saves from class, tools from background, armor from class, weapons from class)
- Origin feat (from background)
- Starting equipment (from class + background choices)
- Languages (Common + 2 chosen + any from species/class)
- Spells known/prepared and cantrips (if applicable, per class at level 1)
- Spell slots (per class at level 1)
- Background, alignment, personality traits, backstory

The character is immediately playable at level 1. No further setup required.

### Client Rendering

**Web client**: Path 1 is a chat interface (same as gameplay). Path 2 is a form with dropdowns, point-buy sliders, and spell selection checkboxes. A toggle at the top switches between paths.

**Discord bot**: Path 1 is a conversation in the text channel — Claude asks, the player responds. Path 2 is a series of slash commands or a multi-step modal form using Discord's interaction components.

Both clients produce the same API call to create the character. The server does not know which path was used.

## Subclasses

Subclasses are not selected at character creation. Per SRD 5.2.1, subclass selection happens at **level 3**. This is handled as part of the level-up flow, not the creation flow.

If a campaign starts at level 3 or higher (see "Starting at Higher Levels" below), subclass selection is included in the creation process — the player chooses their subclass as part of the initial build.

**SRD 5.2.1 subclasses (one per class):**

| Class | Subclass | Level |
|---|---|---|
| Barbarian | Path of the Berserker | 3 |
| Bard | College of Lore | 3 |
| Cleric | Life Domain | 3 |
| Druid | Circle of the Land | 3 |
| Fighter | Champion | 3 |
| Monk | Warrior of the Open Hand | 3 |
| Paladin | Oath of Devotion | 3 |
| Ranger | Hunter | 3 |
| Rogue | Thief | 3 |
| Sorcerer | Draconic Sorcerer | 3 |
| Warlock | Fiend Patron | 3 |
| Wizard | Evoker | 3 |

The SRD provides exactly one subclass per class. Community-contributed subclasses can extend these options via the import pipeline (ADR-0001) — they are data, not code.

## Level-Up

Level-up follows the same dual-path pattern as creation.

**Guided**: Claude narrates the level-up ("After weeks of battle, you feel a new strength within you...") and walks the player through choices. At the appropriate levels, this includes subclass selection (level 3), Ability Score Improvements or feats (levels 4, 8, 12, 16, 19), and new class features.

**Direct**: The form presents the mechanical choices. Select subclass, select spells, assign ASI or feat. All choices are validated by the Rules Engine.

**Level-up steps (per SRD 5.2.1):**

1. **Choose class** (relevant only for multiclassing — otherwise the character advances in their existing class).
2. **Gain HP**: Roll the class hit die + Constitution modifier (or use fixed value: Barbarian 7, Fighter/Paladin/Ranger 6, Bard/Cleric/Druid/Monk/Rogue/Warlock 5, Sorcerer/Wizard 4 — plus Con modifier). Add to HP maximum.
3. **Gain Hit Die**: Add one hit die to the pool.
4. **Record new class features**: Including subclass features at the appropriate levels.
5. **Adjust Proficiency Bonus**: Increases at levels 5 (+3), 9 (+4), 13 (+5), and 17 (+6).
6. **Ability Score Improvement / Feat** (at class-specific levels): Increase one ability score by 2 or two scores by 1 (no score above 20), or select a feat.
7. **Update spells** (if applicable): New cantrips, new prepared spells, new spell slot levels per class progression.

The Rules Engine validates every level-up choice against the SRD progression tables.

## Starting at Higher Levels

Campaigns may start at a level higher than 1. The SRD 5.2.1 recommends starting at level 3 for experienced groups.

When starting at a higher level:
- The character is created with the minimum XP for that level (per the Character Advancement table).
- All level-up choices from level 1 through the starting level must be made during creation — including subclass selection at level 3.
- Starting equipment scales with level (per SRD 5.2.1 table): levels 2-4 get normal equipment plus a Common magic item; levels 5-10 add 500 GP + 1d10×25 GP plus an Uncommon magic item; higher levels scale further.

Both creation paths handle higher-level starts: the guided conversation includes subclass and feat choices naturally in the flow; the direct form expands to show level-up options for each level.

## Multiclassing

Multiclassing is supported but not surfaced prominently. In the guided path, Claude does not suggest multiclassing unless the player's concept clearly calls for it ("I want to be a fighter who dabbles in magic" → Fighter/Wizard). In the direct path, multiclassing is an option at level-up.

**Prerequisites (per SRD 5.2.1)**: To multiclass, the character must have a score of at least 13 in the primary ability of both their current class and the new class.

**Multiclass validation is strict**: Ability score prerequisites, correct multiclass spell slot calculation (per the SRD's Multiclass Spellcaster table), correct proficiency grants (multiclassing into a class grants fewer proficiencies than starting in it), and Extra Attack non-stacking. This is one of the Rules Engine's most complex validation tasks and requires thorough test coverage (ADR-0001).

## SRD 5.2.1 Content Scope

Character creation is limited to SRD 5.2.1 content. This section is the authoritative list — if something is not listed here, it is not in the SRD and must not be offered as a default option.

**Species** (9): Dragonborn, Dwarf, Elf (High Elf, Wood Elf), Gnome (Forest Gnome, Rock Gnome), Goliath, Halfling, Human, Orc, Tiefling.

**Classes** (12): Barbarian, Bard, Cleric, Druid, Fighter, Monk, Paladin, Ranger, Rogue, Sorcerer, Warlock, Wizard.

**Subclasses** (12, one per class): Path of the Berserker, College of Lore, Life Domain, Circle of the Land, Champion, Warrior of the Open Hand, Oath of Devotion, Hunter, Thief, Draconic Sorcerer, Fiend Patron, Evoker.

**Backgrounds** (4): Acolyte, Criminal, Sage, Soldier.

**Ability Score Methods**: Standard Array (15, 14, 13, 12, 10, 8), Point Buy (27 points), Random (4d6 drop lowest × 6).

Community-contributed content (homebrew species, classes, subclasses, backgrounds) can extend all of these lists via the import pipeline (ADR-0001) without code changes — they are data, not code.